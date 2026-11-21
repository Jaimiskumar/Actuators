"""Single-pass streaming analysis engine."""

import os
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Union

try:
    import psutil
except ImportError:
    psutil = None

from logdetective.cluster import ClusterStore
from logdetective.contract import (
    CrashEvent,
    CrashSnapshot,
    CrashTrigger,
    Event,
    Meta,
    Result,
    Timeline,
)
from logdetective.reader import stream_lines
from logdetective.stacktrace import join_events

# Crash trigger keywords per Section 6.6
CRASH_TRIGGER_KEYWORDS = (
    "panic",
    "segfault",
    "sigsegv",
    "outofmemoryerror",
    "core dumped",
    "fatal error",
    "unhandled exception",
    "killed",
    "exit code",
)


class Engine:
    """Orchestrates single-pass log processing."""

    def __init__(self, buffer_size: int = 300):
        self.buffer_size = buffer_size

    def analyze(
        self,
        source: Union[str, Path],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        callback_interval: int = 10000,
    ) -> Result:
        """Run single-pass ingestion, clustering, and crash timeline capture."""
        start_time = time.perf_counter()
        process = psutil.Process() if psutil else None

        line_count = 0
        event_count = 0
        malformed_count = 0
        level_counts: dict[str, int] = {
            "DEBUG": 0,
            "INFO": 0,
            "WARN": 0,
            "ERROR": 0,
            "FATAL": 0,
            "UNKNOWN": 0,
        }

        min_ts: Optional[datetime] = None
        max_ts: Optional[datetime] = None

        cluster_store = ClusterStore()
        recent_events: deque[tuple[Event, Optional[str], bool]] = deque(maxlen=self.buffer_size)
        crashes: list[CrashSnapshot] = []

        file_size = 0
        file_name = str(source)
        if source != "-" and sys.stdin is not source:
            p = Path(source)
            if p.exists():
                file_size = p.stat().st_size
                file_name = p.name

        raw_stream = stream_lines(source)

        for event in join_events(raw_stream):
            event_count += 1
            line_count = max(line_count, event.line_no)

            # Update level counts
            lvl = event.level if event.level in level_counts else "UNKNOWN"
            level_counts[lvl] = level_counts.get(lvl, 0) + 1

            # Update timestamp bounds
            if event.ts:
                if min_ts is None or event.ts < min_ts:
                    min_ts = event.ts
                if max_ts is None or event.ts > max_ts:
                    max_ts = event.ts

            cluster_id = None
            is_first_occurrence = False

            # Cluster only WARN, ERROR, FATAL events (brief section 6.5)
            if lvl in ("WARN", "ERROR", "FATAL"):
                cluster_id, is_first_occurrence = cluster_store.add(event)

            # Check for crash triggers
            is_trigger = False
            lower_msg = event.message.lower()
            if lvl == "FATAL" or any(k in lower_msg for k in CRASH_TRIGGER_KEYWORDS):
                is_trigger = True

            recent_events.append((event, cluster_id, is_first_occurrence))

            if is_trigger and len(crashes) < 10:
                # Capture crash snapshot
                trigger_ts = event.ts.isoformat() + "Z" if event.ts else None
                trigger_obj = CrashTrigger(
                    ts=trigger_ts,
                    line_no=event.line_no,
                    message=event.message,
                )

                sequence: list[CrashEvent] = []
                for hist_ev, cid, first_occ in list(recent_events)[-15:]:
                    h_ts = hist_ev.ts.isoformat() + "Z" if hist_ev.ts else None
                    sequence.append(
                        CrashEvent(
                            ts=h_ts,
                            level=hist_ev.level,
                            message=hist_ev.message,
                            cluster_id=cid,
                            is_first_occurrence=first_occ,
                            is_trigger=(hist_ev.line_no == event.line_no),
                        )
                    )

                crashes.append(CrashSnapshot(trigger=trigger_obj, sequence=sequence))

            if progress_callback and event_count % callback_interval == 0:
                progress_callback(line_count, event_count)

        duration = time.perf_counter() - start_time
        peak_mem_mb = (
            process.memory_info().rss / (1024 * 1024) if process else 0.0
        )

        clusters, bucket_edges, errors_per_bucket = cluster_store.build_clusters(
            min_ts, max_ts, num_buckets=100
        )

        meta = Meta(
            file=file_name,
            size_bytes=file_size,
            lines=line_count,
            events=event_count,
            malformed_lines=malformed_count,
            duration_s=round(duration, 3),
            peak_mem_mb=round(peak_mem_mb, 2),
            time_range=[
                min_ts.isoformat() + "Z" if min_ts else None,
                max_ts.isoformat() + "Z" if max_ts else None,
            ],
            level_counts=level_counts,
        )

        timeline = Timeline(
            bucket_edges=bucket_edges,
            errors_per_bucket=errors_per_bucket,
        )

        return Result(
            meta=meta,
            clusters=clusters,
            timeline=timeline,
            crashes=crashes,
            ai_summary=None,
        )
