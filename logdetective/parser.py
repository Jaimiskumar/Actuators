"""Log line parser: High-performance parsing for JSON, timestamped text, and syslog."""

import json
import re
from datetime import datetime
from typing import Any, Optional, Tuple

from logdetective.contract import Event

# Pre-compiled regular expressions for timestamp matching (cheapest first)
# ISO 8601 / RFC 3339: 2026-11-21T10:00:00.000Z or 2026-11-21 10:00:00,123
RE_ISO_TIMESTAMP = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)

# Standard date-time format: 2026-11-21 10:00:00
RE_STD_TIMESTAMP = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)"
)

# Syslog format: Nov 21 03:01:02 or Nov  5 12:00:00
RE_SYSLOG_TIMESTAMP = re.compile(
    r"^([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})"
)

# Level matcher in text logs
RE_LEVEL = re.compile(
    r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL|PANIC|SEVERE)\b",
    re.IGNORECASE,
)

# Bracketed tokens like [service] or [req-1234]
RE_BRACKET_TOKENS = re.compile(r"\[([a-zA-Z0-9_\-.:]+)\]")

# Syslog header pattern: Nov 21 03:01:02 hostname service[pid]: message
RE_SYSLOG_HEADER = re.compile(
    r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+([a-zA-Z0-9_\-.]+)(?:\[\d+\])?:\s*(.*)$"
)

LEVEL_NORMALIZATION = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARN": "WARN",
    "WARNING": "WARN",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "FATAL": "FATAL",
    "CRITICAL": "FATAL",
    "PANIC": "FATAL",
    "SEVERE": "FATAL",
}

# Known JSON field keys
TS_KEYS = ("timestamp", "ts", "time", "@timestamp", "datetime")
LEVEL_KEYS = ("level", "severity", "lvl", "levelname")
MSG_KEYS = ("message", "msg", "log", "error")
REQ_KEYS = ("request_id", "trace_id", "req_id", "correlation_id")
THREAD_KEYS = ("thread", "thread_id")
SERVICE_KEYS = ("service", "logger", "app")


def normalize_level(level_str: Optional[str]) -> str:
    """Normalize arbitrary level strings into standard canonical levels."""
    if not level_str:
        return "UNKNOWN"
    clean = level_str.strip().upper()
    return LEVEL_NORMALIZATION.get(clean, "UNKNOWN")


def parse_timestamp(ts_raw: Any) -> Optional[datetime]:
    """Parse various timestamp representations into a Python datetime."""
    if not ts_raw:
        return None
    if isinstance(ts_raw, (int, float)):
        # Epoch seconds or milliseconds
        if ts_raw > 1e11:  # ms epoch
            return datetime.fromtimestamp(ts_raw / 1000.0)
        return datetime.fromtimestamp(ts_raw)
    
    if not isinstance(ts_raw, str):
        return None

    s = ts_raw.strip()
    if not s:
        return None

    # Try ISO 8601 (Python 3.11+ handles Z and offsets cleanly)
    iso_clean = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_clean)
    except ValueError:
        pass

    # Try standard YYYY-MM-DD HH:MM:SS,ms or .ms
    if len(s) >= 19:
        try:
            s_std = s[:23].replace(",", ".")
            return datetime.fromisoformat(s_std)
        except ValueError:
            pass

    # Try Syslog: Nov 21 03:01:02
    try:
        now_year = datetime.now().year
        dt = datetime.strptime(s[:15], "%b %d %H:%M:%S")
        return dt.replace(year=now_year)
    except ValueError:
        pass

    return None


def parse_line(line_no: int, raw_line: str) -> Tuple[Optional[Event], bool]:
    """Parse a single raw log line into an Event or identify as continuation.
    
    Returns:
        (event, is_continuation)
        - If (event, False): Base event created.
        - If (None, True): Continuation line (e.g. stack trace frame).
    """
    stripped = raw_line.strip()
    if not stripped:
        return None, True

    # Check 1: JSON line (cheapest check: starts with '{')
    if raw_line.startswith("{"):
        try:
            data = json.loads(raw_line)
            if isinstance(data, dict):
                # Extract timestamp
                ts = None
                for k in TS_KEYS:
                    if k in data:
                        ts = parse_timestamp(data[k])
                        if ts:
                            break

                # Extract level
                raw_level = None
                for k in LEVEL_KEYS:
                    if k in data:
                        raw_level = str(data[k])
                        break

                # Extract message
                msg = ""
                for k in MSG_KEYS:
                    if k in data:
                        msg = str(data[k])
                        break
                if not msg and "error" in data and isinstance(data["error"], dict):
                    msg = str(data["error"].get("message", ""))

                # Extract request / correlation ID
                req_id = None
                for k in REQ_KEYS:
                    if k in data:
                        req_id = str(data[k])
                        break

                # Extract service / logger
                svc = None
                for k in SERVICE_KEYS:
                    if k in data:
                        svc = str(data[k])
                        break

                event = Event(
                    line_no=line_no,
                    ts=ts,
                    level=normalize_level(raw_level),
                    message=msg or stripped,
                    stack=[],
                    fmt="json",
                    request_id=req_id,
                    service=svc,
                )
                return event, False
        except (json.JSONDecodeError, ValueError):
            # Not valid JSON, fall through to text parsing
            pass

    # Check 2: Matches timestamp at line start (Plain text / Syslog)
    ts_match = (
        RE_ISO_TIMESTAMP.match(raw_line)
        or RE_STD_TIMESTAMP.match(raw_line)
        or RE_SYSLOG_TIMESTAMP.match(raw_line)
    )

    if ts_match:
        ts_str = ts_match.group(1)
        ts = parse_timestamp(ts_str)
        rest_of_line = raw_line[ts_match.end():].strip()

        # Check for syslog style: Nov 21 03:01:02 host app[pid]: message
        svc = None
        syslog_hdr = RE_SYSLOG_HEADER.match(raw_line)
        if syslog_hdr:
            svc = syslog_hdr.group(1)
            rest_of_line = syslog_hdr.group(2)

        # Extract bracketed tokens e.g. [INFO] [order-service] [req-1234]
        level = "UNKNOWN"
        req_id = None
        bracket_tokens = RE_BRACKET_TOKENS.findall(rest_of_line)
        for token in bracket_tokens:
            norm_lvl = normalize_level(token)
            if norm_lvl != "UNKNOWN" and level == "UNKNOWN":
                level = norm_lvl
            elif "req" in token.lower() or "trace" in token.lower() or "id" in token.lower():
                if not req_id:
                    req_id = token
            elif not svc and not token.isdigit():
                svc = token

        # If level wasn't found in brackets, search in the line
        if level == "UNKNOWN":
            lvl_match = RE_LEVEL.search(rest_of_line)
            if lvl_match:
                level = normalize_level(lvl_match.group(1))

        # Clean message: strip leading bracket tokens from message if message starts with them
        msg = rest_of_line
        # Clean prefix markers like "[INFO] [service] [req-1] "
        msg = re.sub(r"^(?:\[[a-zA-Z0-9_\-.: ]+\]\s*)+", "", msg)
        # Clean inline level if at start: e.g. "ERROR: Connection failed" or "WARN Connection"
        msg = re.sub(r"^(?:DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL)[:\s]+", "", msg, flags=re.IGNORECASE)

        event = Event(
            line_no=line_no,
            ts=ts,
            level=level,
            message=msg.strip() or rest_of_line,
            stack=[],
            fmt="text",
            request_id=req_id,
            service=svc,
        )
        return event, False

    # Check 3: Neither JSON nor timestamped line -> continuation line
    return None, True
