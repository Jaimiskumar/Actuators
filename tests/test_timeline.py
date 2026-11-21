"""Unit tests for crash detection and timeline reconstruction."""

from datetime import datetime, timedelta
from logdetective.contract import Event
from logdetective.timeline import TimelineTracker, is_crash_trigger


def test_is_crash_trigger():
    # Fatal level
    assert is_crash_trigger(Event(line_no=1, level="FATAL", message="Normal message"))

    # Keywords
    assert is_crash_trigger(Event(line_no=2, level="ERROR", message="fatal error: connection dropped"))
    assert is_crash_trigger(Event(line_no=3, level="ERROR", message="Kernel panic: unable to mount root fs"))
    assert is_crash_trigger(Event(line_no=4, level="ERROR", message="SIGSEGV caught in worker"))
    assert is_crash_trigger(Event(line_no=5, level="ERROR", message="java.lang.OutOfMemoryError: Java heap space"))
    assert is_crash_trigger(Event(line_no=6, level="ERROR", message="process killed by oom-killer"))
    assert is_crash_trigger(Event(line_no=7, level="ERROR", message="Process finished with exit code 137"))

    # Non-crash
    assert not is_crash_trigger(Event(line_no=8, level="ERROR", message="Connection timeout"))
    assert not is_crash_trigger(Event(line_no=9, level="INFO", message="Server started"))


def test_timeline_tracker_refinement():
    tracker = TimelineTracker(max_buffer_size=100)
    base_time = datetime(2026, 11, 21, 10, 0, 0)

    # 1. Old event outside 120s window (should be filtered)
    ev_old = Event(
        line_no=10,
        ts=base_time - timedelta(seconds=200),
        level="INFO",
        message="Old info event",
    )
    tracker.record(ev_old, cluster_id=None, is_first_occurrence=False)

    # 2. Patient-zero first occurrence inside window (must be kept)
    ev_fo = Event(
        line_no=20,
        ts=base_time - timedelta(seconds=90),
        level="WARN",
        message="Connection pool usage above 80%",
    )
    tracker.record(ev_fo, cluster_id="c1", is_first_occurrence=True)

    # 3. Repeated error events (should be collapsed)
    for i in range(5):
        ev_rep = Event(
            line_no=30 + i,
            ts=base_time - timedelta(seconds=60 - i * 2),
            level="ERROR",
            message="Database connection timed out",
            request_id="req-999",
            service="order-service",
        )
        tracker.record(ev_rep, cluster_id="c2", is_first_occurrence=(i == 0))

    # 4. Irrelevant plain INFO noise (should be dropped)
    for i in range(10):
        ev_noise = Event(
            line_no=50 + i,
            ts=base_time - timedelta(seconds=30 - i),
            level="INFO",
            message=f"HTTP GET /healthz 200 {i}",
            request_id="health-probe",
            service="gateway",
        )
        tracker.record(ev_noise, cluster_id=None, is_first_occurrence=False)

    # 5. Matching correlation INFO event (should be boosted/kept)
    ev_correl = Event(
        line_no=70,
        ts=base_time - timedelta(seconds=10),
        level="INFO",
        message="Payment processing initiated for order #1234",
        request_id="req-999",
        service="order-service",
    )
    tracker.record(ev_correl, cluster_id=None, is_first_occurrence=False)

    # 6. Crash Trigger
    ev_crash = Event(
        line_no=80,
        ts=base_time,
        level="FATAL",
        message="fatal error: OutOfMemoryError in order worker thread",
        request_id="req-999",
        service="order-service",
    )
    tracker.record(ev_crash, cluster_id="c3", is_first_occurrence=True)

    snapshots = tracker.get_snapshots()
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap.trigger.line_no == 80
    assert "OutOfMemoryError" in snap.trigger.message

    seq_messages = [item.message for item in snap.sequence]

    # Verify: Old event (200s ago) was dropped
    assert "Old info event" not in seq_messages

    # Verify: First occurrence event was preserved
    assert any("Connection pool usage" in m for m in seq_messages)

    # Verify: Repeated database timeout events were collapsed
    assert any("Database connection timed out (... repeated x5)" in m for m in seq_messages)

    # Verify: Correlated INFO event was preserved
    assert any("Payment processing initiated" in m for m in seq_messages)

    # Verify: Irrelevant health probe INFO noise was dropped
    assert not any("healthz" in m for m in seq_messages)

    # Verify: Trigger event is last in sequence and marked as trigger
    assert snap.sequence[-1].is_trigger is True
    assert snap.sequence[-1].message == ev_crash.message
