"""Pattern normalization, fingerprinting, and error clustering."""

import hashlib
import re
from datetime import datetime
from typing import Dict, List, Optional, Set

from logdetective.contract import Cluster, Event, FirstSeen, LastSeen

# High-performance pre-compiled regexes for token normalization
# Order of normalization is critical
RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
RE_URL = re.compile(r"https?://[^\s/$.?#].[^\s]*")
RE_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
RE_IPV4_PORT = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b")
RE_IPV6 = re.compile(r"\b[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){7}\b")
RE_FILE_PATH = re.compile(r"(?:/[a-zA-Z0-9_\.\-]+){2,}|(?:[a-zA-Z]:\\[a-zA-Z0-9_\.\-\\]+)")
RE_QUOTED_STR = re.compile(r"(['\"])(?:(?=(\\?))\2.)*?\1")
RE_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-fA-F]{16,}\b")
RE_NUMBER = re.compile(r"\d+(?:\.\d+)?")

# Line number remover in stack trace frames for stable fingerprinting
RE_STACK_LINE_NO = re.compile(r"(?:line \d+|:\d+\b)")

LEVEL_SEVERITY = {
    "FATAL": 4,
    "ERROR": 3,
    "WARN": 2,
    "INFO": 1,
    "DEBUG": 0,
    "UNKNOWN": 0,
}


def normalize_message(msg: str) -> str:
    """Normalize dynamic tokens in log messages to stable pattern templates."""
    if not msg:
        return ""

    # Replace complex tokens first
    s = RE_EMAIL.sub("<EMAIL>", msg)
    s = RE_URL.sub("<URL>", s)
    s = RE_UUID.sub("<ID>", s)
    s = RE_IPV4_PORT.sub("<IP>", s)
    s = RE_IPV6.sub("<IP>", s)
    s = RE_FILE_PATH.sub("<PATH>", s)
    s = RE_QUOTED_STR.sub("<STR>", s)
    s = RE_HEX.sub("<HEX>", s)
    s = RE_NUMBER.sub("<NUM>", s)

    return s.strip()


def normalize_stack_frame(frame: str) -> str:
    """Strip line numbers from stack trace frames for consistent hashing."""
    return RE_STACK_LINE_NO.sub(":<NUM>", frame.strip())


def compute_fingerprint(template: str, stack: List[str]) -> str:
    """Compute a deterministic hash from the message template and top 3 stack frames."""
    key = template
    if stack:
        top_frames = [normalize_stack_frame(f) for f in stack[:3]]
        key = f"{template}|{'|'.join(top_frames)}"

    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


class ClusterEntry:
    """Internal cluster accumulator with low memory overhead."""
    __slots__ = (
        "id",
        "template",
        "count",
        "level",
        "first_seen_ts",
        "first_seen_line",
        "last_seen_ts",
        "last_seen_line",
        "sample",
        "stack_top",
        "services",
        "ts_list",
    )

    def __init__(self, cluster_id: str, template: str, event: Event):
        self.id = cluster_id
        self.template = template
        self.count = 1
        self.level = event.level
        iso_ts = event.ts.isoformat() + "Z" if event.ts else None
        self.first_seen_ts = iso_ts
        self.first_seen_line = event.line_no
        self.last_seen_ts = iso_ts
        self.last_seen_line = event.line_no
        self.sample = event.message
        self.stack_top = [f.strip() for f in event.stack[:3]] if event.stack else []
        self.services: Set[str] = {event.service} if event.service else set()
        # Keep relative timestamps or epoch seconds for adaptive histogram
        self.ts_list: List[float] = [event.ts.timestamp()] if event.ts else []

    def update(self, event: Event):
        self.count += 1
        iso_ts = event.ts.isoformat() + "Z" if event.ts else None
        self.last_seen_ts = iso_ts
        self.last_seen_line = event.line_no
        if event.service:
            self.services.add(event.service)
        if event.ts:
            self.ts_list.append(event.ts.timestamp())
        # Escalate level if higher severity observed
        if LEVEL_SEVERITY.get(event.level, 0) > LEVEL_SEVERITY.get(self.level, 0):
            self.level = event.level
        if not self.stack_top and event.stack:
            self.stack_top = [f.strip() for f in event.stack[:3]]


class ClusterStore:
    """Stores and aggregates error clusters with bounded memory."""

    def __init__(self):
        self.clusters: Dict[str, ClusterEntry] = {}
        self._next_id = 1

    def add(self, event: Event) -> tuple[str, bool]:
        """Add an event to the cluster store.
        
        Returns:
            (cluster_id, is_first_occurrence)
        """
        template = normalize_message(event.message)
        fp = compute_fingerprint(template, event.stack)

        if fp in self.clusters:
            entry = self.clusters[fp]
            entry.update(event)
            return entry.id, False

        cluster_id = f"c{self._next_id}"
        self._next_id += 1
        entry = ClusterEntry(cluster_id, template, event)
        self.clusters[fp] = entry
        return cluster_id, True

    def build_clusters(
        self,
        min_ts: Optional[datetime],
        max_ts: Optional[datetime],
        num_buckets: int = 100,
    ) -> tuple[List[Cluster], List[str], List[int]]:
        """Materialize contract Cluster models and adaptive timeline buckets."""
        cluster_list: List[Cluster] = []

        # Sort clusters by frequency descending
        sorted_entries = sorted(
            self.clusters.values(), key=lambda c: c.count, reverse=True
        )

        has_time_range = min_ts and max_ts and max_ts > min_ts
        bucket_edges: List[str] = []
        global_errors_per_bucket = [0] * num_buckets if has_time_range else []

        if has_time_range:
            start_epoch = min_ts.timestamp()
            end_epoch = max_ts.timestamp()
            total_span = end_epoch - start_epoch
            bucket_duration = total_span / num_buckets

            for b in range(num_buckets + 1):
                edge_dt = datetime.fromtimestamp(start_epoch + b * bucket_duration)
                bucket_edges.append(edge_dt.isoformat() + "Z")

        for entry in sorted_entries:
            # Calculate per-cluster adaptive bucket counts
            cluster_buckets = [0] * num_buckets if has_time_range else []
            if has_time_range and entry.ts_list:
                start_epoch = min_ts.timestamp()
                end_epoch = max_ts.timestamp()
                span = end_epoch - start_epoch
                for t in entry.ts_list:
                    if start_epoch <= t <= end_epoch:
                        idx = min(int((t - start_epoch) / span * num_buckets), num_buckets - 1)
                        cluster_buckets[idx] += 1
                        global_errors_per_bucket[idx] += 1

            c = Cluster(
                id=entry.id,
                template=entry.template,
                count=entry.count,
                level=entry.level,
                first_seen=FirstSeen(ts=entry.first_seen_ts, line_no=entry.first_seen_line),
                last_seen=LastSeen(ts=entry.last_seen_ts, line_no=entry.last_seen_line),
                sample=entry.sample,
                stack_top=entry.stack_top,
                services=sorted(list(entry.services)),
                buckets=cluster_buckets,
            )
            cluster_list.append(c)

        return cluster_list, bucket_edges, global_errors_per_bucket
