"""Unit tests for stack trace detection and joining."""

from logdetective.contract import Event
from logdetective.stacktrace import is_stack_trace_line, join_events


def test_is_stack_trace_line_python():
    assert is_stack_trace_line("Traceback (most recent call last):")
    assert is_stack_trace_line('  File "/app/server.py", line 124, in handle')
    assert is_stack_trace_line("ZeroDivisionError: division by zero")


def test_is_stack_trace_line_java():
    assert is_stack_trace_line("\tat com.zaxxer.hikari.pool.HikariPool.throwException(HikariPool.java:595)")
    assert is_stack_trace_line("Caused by: java.sql.SQLException: Connection refused")
    assert is_stack_trace_line("\t... 32 more")


def test_join_events_with_python_traceback():
    lines = [
        (1, '2026-11-21 10:00:00,000 [INFO] [app] Starting application'),
        (2, '2026-11-21 10:00:01,000 [ERROR] [app] Unhandled exception occurred'),
        (3, 'Traceback (most recent call last):'),
        (4, '  File "/app/services.py", line 45, in execute'),
        (5, '    result = 1 / 0'),
        (6, 'ZeroDivisionError: division by zero'),
        (7, '2026-11-21 10:00:02,000 [INFO] [app] Shutting down')
    ]

    events = list(join_events(lines))
    assert len(events) == 3

    assert events[0].level == "INFO"
    assert len(events[0].stack) == 0

    assert events[1].level == "ERROR"
    assert events[1].fmt == "trace"
    assert len(events[1].stack) == 4
    assert "Traceback" in events[1].stack[0]
    assert "ZeroDivisionError" in events[1].stack[3]

    assert events[2].level == "INFO"
    assert len(events[2].stack) == 0


def test_join_events_with_java_traceback():
    lines = [
        (1, '2026-11-21 10:00:00,000 [ERROR] [db-pool] Failed to initialize pool'),
        (2, '\tat com.zaxxer.hikari.pool.HikariPool.<init>(HikariPool.java:115)'),
        (3, 'Caused by: java.sql.SQLTransientConnectionException: Connection is not available'),
        (4, '\tat com.zaxxer.hikari.util.ConcurrentBag.borrow(ConcurrentBag.java:125)'),
        (5, '\t... 32 more')
    ]

    events = list(join_events(lines))
    assert len(events) == 1
    assert events[0].level == "ERROR"
    assert events[0].fmt == "trace"
    assert len(events[0].stack) == 4
