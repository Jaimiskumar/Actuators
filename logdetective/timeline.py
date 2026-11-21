"""Crash timeline reconstruction with sliding context window and heuristic refinement."""

import re
from collections import deque
from datetime import datetime
from typing import List, Optional, Tuple

from logdetective.contract import CrashEvent, CrashSnapshot, CrashTrigger, Event

# Pre-compiled regex for crash triggers per brief Section 6.6
RE_CRASH_TRIGGER = re.compile(
    r"\b(?:"
    r"panic|segfault|sigsegv|outofmemoryerror|core\s+dumped"
    r"|fatal\s+error|unhandled\s+exception|killed|segmentation\s+fault"
    r"|exit\s+code\s+[1-9]\d*"
    r")\b",
    re.IGNORECASE,
)

# Uncaught traceback patterns
RE_UNCAUGHT_TRACE = re.compile(
    r"(?:uncaught\s+exception|traceback\s+\(most\s+recent\s+call\s+last\))",
    re.IGNORECASE,
)


def is_crash_trigger(event: Event) -> bool:
    """Detect if an event represents an unhandled failure or crash."""
    if event.level == "FATAL":
        return True

    msg = event.message or ""
    if RE_CRASH_TRIGGER.search(msg):
        return True

    # Check for uncaught exception in stack trace
    if event.stack:
        for frame in event.stack:
            if RE_UNCAUGHT_TRACE.search(frame):
                return True

    return False


class TimelineTracker:
    """Maintains a rolling buffer of recent events and generates refined crash sequences."""

    def __init__(self, max_buffer_size: int = 300, max_snapshots: int = 10):
        self.max_buffer_size = max_buffer_size
        self.max_snapshots = max_snapshots
        # Stores (Event, cluster_id, is_first_occurrence)
        self.buffer: deque[Tuple[Event, Optional[str], bool]] = deque(maxlen=max_buffer_size)
        self.snapshots: List[CrashSnapshot] = []

    def record(self, event: Event, cluster_id: Optional[str], is_first_occurrence: bool):
        """Append an event to the rolling buffer and check for crash triggers."""
        is_trigger = is_crash_trigger(event)
        self.buffer.append((event, cluster_id, is_first_occurrence))

        if is_trigger:
            snapshot = self._refine_crash_sequence(event)
            self._add_snapshot(snapshot)

    def _add_snapshot(self, snapshot: CrashSnapshot):
        """Cap snapshots at max_snapshots while always preserving the first and the last."""
        if len(self.snapshots) < self.max_snapshots:
            self.snapshots.append(snapshot)
        else:
            # Keep first snapshot (patient zero crash) and update the last one
            self.snapshots[-1] = snapshot

    def _refine_crash_sequence(
        self,
        trigger_event: Event,
        window_seconds: float = 120.0,
    ) -> CrashSnapshot:
        """Refines the buffer leading up to a crash trigger into a concise narrative.
        
        Rules:
        1. Keep events within the last T seconds (default 120s).
        2. Boost events sharing the crash's request/trace/thread/service id.
        3. Always include the first-seen event of any new error cluster inside the window.
        4. Collapse repeated identical events into '... repeated xN'.
        5. Drop low-value INFO/DEBUG noise.
        """
        trigger_ts = trigger_event.ts
        trigger_req_id = trigger_event.request_id
        trigger_service = trigger_event.service

        # Step 1: Filter events within time window T seconds
        window_events: List[Tuple[Event, Optional[str], bool]] = []
        for ev, cid, is_fo in self.buffer:
            if trigger_ts and ev.ts:
                delta = (trigger_ts - ev.ts).total_seconds()
                if 0 <= delta <= window_seconds:
                    window_events.append((ev, cid, is_fo))
            else:
                # If timestamp is missing, retain recent context
                window_events.append((ev, cid, is_fo))

        # If window is small or empty, fall back to last 20 events
        if len(window_events) < 5:
            window_events = list(self.buffer)[-20:]

        # Step 2: Score and filter events
        scored_events: List[Tuple[Event, Optional[str], bool, bool]] = []
        # (Event, cluster_id, is_fo, is_trigger)

        for ev, cid, is_fo in window_events:
            is_trig = (ev.line_no == trigger_event.line_no)
            if is_trig:
                scored_events.append((ev, cid, is_fo, True))
                continue

            # Always keep first occurrence of an error cluster
            if is_fo:
                scored_events.append((ev, cid, is_fo, False))
                continue

            # Keep all WARN, ERROR, FATAL
            if ev.level in ("FATAL", "ERROR", "WARN"):
                scored_events.append((ev, cid, is_fo, False))
                continue

            # Boost events matching request_id or service of the crash
            has_req_match = trigger_req_id and ev.request_id and (ev.request_id == trigger_req_id)
            has_svc_match = trigger_service and ev.service and (ev.service == trigger_service)

            if has_req_match or has_svc_match:
                scored_events.append((ev, cid, is_fo, False))
                continue

            # Drop plain INFO/DEBUG noise

        # Step 3: Collapse repeated identical consecutive messages into '... repeated xN'
        collapsed: List[Tuple[Event, Optional[str], bool, bool, int]] = []
        # (Event, cluster_id, is_fo, is_trigger, repeat_count)

        for ev, cid, is_fo, is_trig in scored_events:
            if not collapsed:
                collapsed.append((ev, cid, is_fo, is_trig, 1))
                continue

            prev_ev, prev_cid, prev_fo, prev_trig, prev_count = collapsed[-1]
            if not is_trig and not prev_trig and (ev.message == prev_ev.message) and (ev.level == prev_ev.level):
                # Increment repeat count
                collapsed[-1] = (prev_ev, prev_cid, prev_fo or is_fo, prev_trig, prev_count + 1)
            else:
                collapsed.append((ev, cid, is_fo, is_trig, 1))

        # Step 4: Build CrashEvent sequence
        sequence: List[CrashEvent] = []
        for ev, cid, is_fo, is_trig, repeat_count in collapsed:
            msg = ev.message
            if repeat_count > 1:
                msg = f"{msg} (... repeated x{repeat_count})"

            ts_str = ev.ts.isoformat() + "Z" if ev.ts else None
            sequence.append(
                CrashEvent(
                    ts=ts_str,
                    level=ev.level,
                    message=msg,
                    cluster_id=cid,
                    is_first_occurrence=is_fo,
                    is_trigger=is_trig,
                )
            )

        trigger_snapshot_ts = trigger_event.ts.isoformat() + "Z" if trigger_event.ts else None
        return CrashSnapshot(
            trigger=CrashTrigger(
                ts=trigger_snapshot_ts,
                line_no=trigger_event.line_no,
                message=trigger_event.message,
            ),
            sequence=sequence,
        )

    def get_snapshots(self) -> List[CrashSnapshot]:
        """Return the collected and refined crash snapshots."""
        return self.snapshots
