"""Tests for HTML report generator."""

import json
from pathlib import Path
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
from logdetective.report_html import generate_html_report, get_chart_js_path, get_template_path


def test_asset_paths_exist():
    assert get_template_path().is_file()
    assert get_chart_js_path().is_file()


def test_generate_html_report_from_mock_dict(tmp_path: Path):
    mock_file = Path(__file__).parent / "mock_result.json"
    with open(mock_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    out_file = tmp_path / "test_report.html"
    html = generate_html_report(data, output_path=out_file)

    assert out_file.is_file()
    assert len(html) > 50000

    # Verify self-contained offline Chart.js
    assert "Chart" in html
    assert "chart.umd" in html or "Chart.js" in html

    # Verify summary header components
    assert "File Size" in html
    assert "Processed Lines" in html
    assert "Analysis Duration" in html
    assert "Unique Clusters" in html
    assert "sample_crash.log" in html

    # Verify error timeline chart
    assert "timelineChartCanvas" in html
    assert "Error Rate Over Time" in html
    assert "First Crash Trigger at" in html or "First crash detected at" in html

    # Verify cluster bar chart
    assert "clusterBarChartCanvas" in html
    assert "Top Patterns by Count" in html

    # Verify first-occurrence cards and search/filter bar
    assert "First-Occurrence Failure Patterns" in html
    assert "clusterSearchInput" in html
    assert "severityFilters" in html
    assert "data-filter=\"WARN\"" in html
    assert "data-filter=\"ERROR\"" in html
    assert "data-filter=\"FATAL\"" in html
    assert "c1" in html
    assert "Connection to database" in html
    assert "org.postgresql.core.v3.ConnectionFactoryImpl.openConnectionImpl" in html

    # Verify crash sequence timeline with trigger
    assert "Crash Sequence Reconstruction" in html
    assert "CRASH TRIGGER" in html
    assert "OutOfMemoryError in worker thread pool" in html
    assert "repeated x45 times" in html


def test_generate_html_report_from_result_dataclass(tmp_path: Path):
    result = Result(
        meta=Meta(
            file="test.log",
            size_bytes=2048,
            lines=100,
            events=95,
            malformed_lines=0,
            duration_s=0.05,
            peak_mem_mb=12.5,
            time_range=["2026-11-21T12:00:00Z", "2026-11-21T12:05:00Z"],
            level_counts={"ERROR": 5, "FATAL": 1, "INFO": 89},
        ),
        clusters=[
            Cluster(
                id="c1",
                template="Null pointer in <PATH>",
                count=5,
                level="ERROR",
                first_seen=FirstSeen(ts="2026-11-21T12:01:00Z", line_no=12),
                last_seen=LastSeen(ts="2026-11-21T12:04:00Z", line_no=90),
                sample="Null pointer in /app/main.py",
                stack_top=["File 'main.py', line 42, in process"],
                services=["backend"],
                buckets=[1, 2, 2],
            )
        ],
        timeline=Timeline(
            bucket_edges=["2026-11-21T12:00:00Z", "2026-11-21T12:02:00Z", "2026-11-21T12:05:00Z"],
            errors_per_bucket=[2, 3],
        ),
        crashes=[
            CrashSnapshot(
                trigger=CrashTrigger(
                    ts="2026-11-21T12:05:00Z",
                    line_no=95,
                    message="Fatal crash: Segmentation fault",
                ),
                sequence=[
                    CrashEvent(
                        ts="2026-11-21T12:01:00Z",
                        level="ERROR",
                        message="Null pointer in /app/main.py",
                        cluster_id="c1",
                        is_first_occurrence=True,
                        is_trigger=False,
                    ),
                    CrashEvent(
                        ts="2026-11-21T12:05:00Z",
                        level="FATAL",
                        message="Fatal crash: Segmentation fault",
                        cluster_id=None,
                        is_first_occurrence=True,
                        is_trigger=True,
                    ),
                ],
            )
        ],
        ai_summary="Segmentation fault caused by unhandled null reference.",
    )

    out_file = tmp_path / "dataclass_report.html"
    html = generate_html_report(result, output_path=out_file)

    assert out_file.is_file()
    assert "test.log" in html
    assert "Null pointer in" in html
    assert "Segmentation fault" in html
    assert "Segmentation fault caused by unhandled null reference." in html
