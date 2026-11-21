"""Unit tests for the FastAPI local dashboard server."""

import json
from pathlib import Path
from fastapi.testclient import TestClient
from logdetective.server import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_get_mock_endpoint():
    response = client.get("/api/mock")
    assert response.status_code == 200
    data = response.json()
    assert "meta" in data
    assert "clusters" in data
    assert len(data["clusters"]) > 0


def test_analyze_path_with_mock_json():
    mock_path = str(Path("tests/mock_result.json"))
    response = client.post("/api/analyze-path", json={"path": mock_path})
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["file"] == "sample_crash.log"
    assert len(data["clusters"]) == 4


def test_analyze_path_with_sample_log():
    sample_log = str(Path("tests/sample_logs/sample.log"))
    response = client.post("/api/analyze-path", json={"path": sample_log})
    assert response.status_code == 200
    data = response.json()
    assert "meta" in data
    assert data["meta"]["file"] == "sample.log"
    assert data["meta"]["lines"] >= 1000
    assert "level_counts" in data["meta"]


def test_analyze_path_nonexistent():
    response = client.post("/api/analyze-path", json={"path": "nonexistent_file.log"})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_upload_endpoint(tmp_path: Path):
    mock_data = {
        "meta": {
            "file": "uploaded_test.log",
            "size_bytes": 1024,
            "lines": 50,
            "events": 48,
            "malformed_lines": 0,
            "duration_s": 0.02,
            "peak_mem_mb": 10.0,
            "time_range": ["2026-11-21T10:00:00Z", "2026-11-21T10:05:00Z"],
            "level_counts": {"ERROR": 2, "INFO": 46},
        },
        "clusters": [
            {
                "id": "c1",
                "template": "Timeout reaching <IP>",
                "count": 2,
                "level": "ERROR",
                "first_seen": {"ts": "2026-11-21T10:01:00Z", "line_no": 10},
                "last_seen": {"ts": "2026-11-21T10:04:00Z", "line_no": 40},
                "sample": "Timeout reaching 10.0.0.1",
                "stack_top": [],
                "services": ["service-a"],
                "buckets": [1, 1],
            }
        ],
        "timeline": {
            "bucket_edges": ["2026-11-21T10:00:00Z", "2026-11-21T10:05:00Z"],
            "errors_per_bucket": [2],
        },
        "crashes": [],
        "ai_summary": None,
    }

    test_file = tmp_path / "test_upload.json"
    test_file.write_text(json.dumps(mock_data), encoding="utf-8")

    with open(test_file, "rb") as f:
        response = client.post("/api/upload", files={"file": ("custom_crash.json", f, "application/json")})

    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["file"] == "custom_crash.json"
    assert len(data["clusters"]) == 1


def test_dashboard_homepage_serves_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text

    # Verify drag & drop upload exists
    assert "dropZone" in html
    assert "Upload Log or Result JSON" in html

    # Verify in-place path input exists
    assert "localPathInput" in html
    assert "Local File Path (In-Place Streaming)" in html
    assert "btnAnalyzePath" in html

    # Verify search/filter bar exists
    assert "clusterSearchInput" in html
    assert "severityFilters" in html
    assert "data-filter=\"FATAL\"" in html
    assert "data-filter=\"ERROR\"" in html
    assert "data-filter=\"WARN\"" in html

    # Verify charts and summary exist
    assert "timelineChartCanvas" in html
    assert "clusterBarChartCanvas" in html
    assert "File Size" in html
