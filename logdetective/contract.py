"""Contract definitions and schema models for Log Detective."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass(slots=True)
class Event:
    """Internal log event representation."""
    line_no: int
    ts: Optional[datetime] = None
    level: str = "UNKNOWN"  # DEBUG/INFO/WARN/ERROR/FATAL/UNKNOWN
    message: str = ""
    stack: list[str] = field(default_factory=list)
    fmt: str = "text"  # json | text | trace
    request_id: Optional[str] = None
    service: Optional[str] = None


@dataclass(slots=True)
class FirstSeen:
    ts: Optional[str]
    line_no: int


@dataclass(slots=True)
class LastSeen:
    ts: Optional[str]
    line_no: int


@dataclass(slots=True)
class Cluster:
    id: str
    template: str
    count: int
    level: str
    first_seen: FirstSeen
    last_seen: LastSeen
    sample: str
    stack_top: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    buckets: list[int] = field(default_factory=list)


@dataclass(slots=True)
class CrashEvent:
    ts: Optional[str]
    level: str
    message: str
    cluster_id: Optional[str]
    is_first_occurrence: bool
    is_trigger: bool


@dataclass(slots=True)
class CrashTrigger:
    ts: Optional[str]
    line_no: int
    message: str


@dataclass(slots=True)
class CrashSnapshot:
    trigger: CrashTrigger
    sequence: list[CrashEvent]


@dataclass(slots=True)
class Timeline:
    bucket_edges: list[str] = field(default_factory=list)
    errors_per_bucket: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Meta:
    file: str
    size_bytes: int
    lines: int
    events: int
    malformed_lines: int
    duration_s: float
    peak_mem_mb: float
    time_range: list[Optional[str]] = field(default_factory=lambda: [None, None])
    level_counts: dict[str, int] = field(default_factory=dict)
    memory_threshold_mb: Optional[float] = None
    budget_exceeded: Optional[bool] = None


@dataclass(slots=True)
class Result:
    """Root contract for Log Detective output.
    
    Shared between core engine, terminal report, HTML report, and dashboard.
    """
    meta: Meta
    clusters: list[Cluster] = field(default_factory=list)
    timeline: Timeline = field(default_factory=Timeline)
    crashes: list[CrashSnapshot] = field(default_factory=list)
    ai_summary: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
