"""Unit tests for log parser."""

from datetime import datetime
from logdetective.parser import parse_line, parse_timestamp, normalize_level


def test_normalize_level():
    assert normalize_level("info") == "INFO"
    assert normalize_level("WARNING") == "WARN"
    assert normalize_level("warn") == "WARN"
    assert normalize_level("error") == "ERROR"
    assert normalize_level("critical") == "FATAL"
    assert normalize_level("panic") == "FATAL"
    assert normalize_level("unknown_val") == "UNKNOWN"
    assert normalize_level(None) == "UNKNOWN"


def test_parse_json_log():
    raw = '{"ts": "2026-11-21T10:15:30Z", "level": "ERROR", "service": "order-service", "request_id": "req-101", "message": "Failed to connect to db"}'
    event, is_continuation = parse_line(1, raw)

    assert not is_continuation
    assert event is not None
    assert event.line_no == 1
    assert event.level == "ERROR"
    assert event.service == "order-service"
    assert event.request_id == "req-101"
    assert event.message == "Failed to connect to db"
    assert event.fmt == "json"
    assert event.ts is not None
    assert event.ts.year == 2026


def test_parse_json_with_alternate_keys():
    raw = '{"timestamp": "2026-11-21T10:15:30Z", "severity": "WARN", "app": "billing", "correlation_id": "corr-42", "msg": "High memory consumption"}'
    event, is_continuation = parse_line(2, raw)

    assert not is_continuation
    assert event is not None
    assert event.level == "WARN"
    assert event.service == "billing"
    assert event.request_id == "corr-42"
    assert event.message == "High memory consumption"


def test_parse_text_standard_log():
    raw = "2026-11-21 10:04:12,102 [ERROR] [order-service] [req-9801] Connection to database timed out"
    event, is_continuation = parse_line(3, raw)

    assert not is_continuation
    assert event is not None
    assert event.level == "ERROR"
    assert event.service == "order-service"
    assert event.request_id == "req-9801"
    assert "Connection to database timed out" in event.message
    assert event.fmt == "text"


def test_parse_syslog():
    raw = "Nov 21 03:01:02 myhost web-01[102]: WARN Connection dropped by peer"
    event, is_continuation = parse_line(4, raw)

    assert not is_continuation
    assert event is not None
    assert event.level == "WARN"
    assert event.service == "web-01"
    assert "Connection dropped by peer" in event.message


def test_continuation_detection():
    raw = '  File "/app/main.py", line 42, in run'
    event, is_continuation = parse_line(5, raw)

    assert is_continuation
    assert event is None
