"""Unit tests for AI root cause summary generator."""

import io
import json
from unittest.mock import MagicMock, patch

from logdetective.ai import build_compact_prompt, generate_ai_summary
from logdetective.contract import (
    Cluster,
    CrashEvent,
    CrashSnapshot,
    CrashTrigger,
    FirstSeen,
    LastSeen,
    Meta,
    Result,
    Timeline,
)


def _make_dummy_result() -> Result:
    meta = Meta(
        file="crash.log",
        size_bytes=1048576,
        lines=10000,
        events=9980,
        malformed_lines=0,
        duration_s=0.08,
        peak_mem_mb=45.0,
        time_range=["2026-11-21T10:00:00Z", "2026-11-21T10:05:00Z"],
        level_counts={"ERROR": 50, "FATAL": 1},
    )

    clusters = [
        Cluster(
            id="c1",
            template="Connection to database <IP> timed out after <NUM>ms",
            count=50,
            level="ERROR",
            first_seen=FirstSeen(ts="2026-11-21T10:01:00Z", line_no=120),
            last_seen=LastSeen(ts="2026-11-21T10:04:00Z", line_no=9500),
            sample="Connection to database 10.0.1.5:5432 timed out after 5000ms",
            stack_top=["org.postgresql.Driver.connect"],
            services=["order-service"],
            buckets=[10, 20, 20],
        )
    ]

    crashes = [
        CrashSnapshot(
            trigger=CrashTrigger(
                ts="2026-11-21T10:05:00Z",
                line_no=9999,
                message="fatal error: OutOfMemoryError in worker thread pool",
            ),
            sequence=[
                CrashEvent(
                    ts="2026-11-21T10:04:55Z",
                    level="ERROR",
                    message="Connection to database 10.0.1.5:5432 timed out after 5000ms",
                    cluster_id="c1",
                    is_first_occurrence=False,
                    is_trigger=False,
                ),
                CrashEvent(
                    ts="2026-11-21T10:05:00Z",
                    level="FATAL",
                    message="fatal error: OutOfMemoryError in worker thread pool",
                    cluster_id=None,
                    is_first_occurrence=False,
                    is_trigger=True,
                ),
            ],
        )
    ]

    return Result(
        meta=meta,
        clusters=clusters,
        timeline=Timeline(),
        crashes=crashes,
        ai_summary=None,
    )


def test_build_compact_prompt():
    result = _make_dummy_result()
    prompt = build_compact_prompt(result)

    # Must contain essential incident anchors
    assert "crash.log" in prompt
    assert "Connection to database <IP> timed out after <NUM>ms" in prompt
    assert "OutOfMemoryError" in prompt
    assert "Root Cause:" in prompt

    # Privacy guarantee: size is compact (under 5 KB)
    assert len(prompt.encode("utf-8")) < 5120


def test_generate_ai_summary_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    result = _make_dummy_result()
    summary = generate_ai_summary(result)
    assert summary is not None
    assert "Root Cause:" in summary
    assert "Failure Cascade:" in summary


def test_generate_ai_summary_mock_success(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-fake-key")

    mock_resp_data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                "Root Cause: Database connection timeouts to 10.0.1.5:5432.\n"
                                "Failure Cascade: Thread exhaustion from repeated retries led to OutOfMemoryError.\n"
                                "Recommended Fix: Increase database connection pool size and configure backoff."
                            )
                        }
                    ]
                }
            }
        ]
    }

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = io.BytesIO(json.dumps(mock_resp_data).encode("utf-8"))

    with patch("urllib.request.urlopen", return_value=mock_cm):
        result = _make_dummy_result()
        summary = generate_ai_summary(result)
        assert summary is not None
        assert "Database connection timeouts" in summary
        assert "Recommended Fix:" in summary
