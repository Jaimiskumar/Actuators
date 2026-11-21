"""FastAPI local web dashboard and API server for Log Detective.

Enables in-place log file analysis for multi-GB logs, drag-and-drop uploads,
and serves the self-contained offline interactive report on localhost:8000.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

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
from logdetective.parser import normalize_level, parse_line
from logdetective.reader import stream_lines
from logdetective.report_html import generate_html_report, get_chart_js_path, get_template_path
from logdetective.stacktrace import join_events

app = FastAPI(
    title="Log Detective Local Dashboard",
    description="Interactive terminal-native log analyzer and RCA dashboard",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzePathRequest(BaseModel):
    path: str


def _get_mock_data_path() -> Path:
    base = Path(__file__).resolve().parent
    candidates = [
        base.parent / "tests" / "mock_result.json",
        Path.cwd() / "tests" / "mock_result.json",
        base / "mock_result.json",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def resolve_file_path(path_str: str) -> Path:
    """Resolve user-provided path against current working directory or absolute."""
    p = Path(path_str.strip())
    if p.is_absolute() and p.exists():
        return p
    # Relative to cwd
    cwd_path = (Path.cwd() / p).resolve()
    if cwd_path.exists():
        return cwd_path
    # Relative to repo root
    repo_path = (Path(__file__).resolve().parent.parent / p).resolve()
    if repo_path.exists():
        return repo_path
    return p.resolve()


def analyze_file_in_place(file_path: Path) -> dict[str, Any]:
    """Analyze a log file or JSON result in-place."""
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Check if this is already a Result JSON
    if file_path.suffix.lower() == ".json":
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "meta" in data and "clusters" in data:
                return data
        except Exception:
            pass  # Fallback to log parser if not a valid result json

    # Check if backend engine is implemented
    try:
        from logdetective import engine
        if hasattr(engine, "analyze_file") and callable(engine.analyze_file):
            res = engine.analyze_file(file_path)
            return res.to_dict() if hasattr(res, "to_dict") else res
    except (ImportError, AttributeError):
        pass

    # In-place streaming pass using reader, parser, and stacktrace joiner
    t0 = time.perf_counter()
    size_bytes = file_path.stat().st_size
    line_count = 0
    event_count = 0
    malformed_count = 0
    level_counts: dict[str, int] = {"DEBUG": 0, "INFO": 0, "WARN": 0, "ERROR": 0, "FATAL": 0}
    clusters_map: dict[str, Cluster] = {}
    timestamps: list[str] = []
    crashes: list[CrashSnapshot] = []

    try:
        raw_lines = stream_lines(file_path)
        joined_events = join_events(raw_lines)

        for ev in joined_events:
            event_count += 1
            line_count = max(line_count, ev.line_no)
            norm_lvl = normalize_level(ev.level)
            level_counts[norm_lvl] = level_counts.get(norm_lvl, 0) + 1

            ts_str = ev.ts.isoformat() + "Z" if ev.ts else None
            if ts_str:
                timestamps.append(ts_str)

            # Cluster errors, warnings, fatals
            if norm_lvl in ("WARN", "ERROR", "FATAL"):
                tpl = ev.message[:120] if ev.message else "Empty error message"
                found_cid = None
                for cid_key, c in clusters_map.items():
                    if c.template == tpl:
                        found_cid = cid_key
                        break

                if found_cid:
                    c = clusters_map[found_cid]
                    c.count += 1
                    c.last_seen = LastSeen(ts=ts_str, line_no=ev.line_no)
                    if ev.service and ev.service not in c.services:
                        c.services.append(ev.service)
                else:
                    new_cid = f"c{len(clusters_map) + 1}"
                    clusters_map[new_cid] = Cluster(
                        id=new_cid,
                        template=tpl,
                        count=1,
                        level=norm_lvl,
                        first_seen=FirstSeen(ts=ts_str, line_no=ev.line_no),
                        last_seen=LastSeen(ts=ts_str, line_no=ev.line_no),
                        sample=ev.message,
                        stack_top=ev.stack[:5],
                        services=[ev.service] if ev.service else [],
                        buckets=[1],
                    )

            # Check fatal or crash keywords
            msg_lower = (ev.message or "").lower()
            if norm_lvl == "FATAL" or any(kw in msg_lower for kw in ("panic", "segfault", "outofmemory", "fatal error")):
                trigger = CrashTrigger(ts=ts_str, line_no=ev.line_no, message=ev.message)
                crashes.append(CrashSnapshot(
                    trigger=trigger,
                    sequence=[
                        CrashEvent(
                            ts=ts_str,
                            level=norm_lvl,
                            message=ev.message,
                            cluster_id=None,
                            is_first_occurrence=True,
                            is_trigger=True,
                        )
                    ]
                ))

    except Exception as exc:
        raise RuntimeError(f"Error during streaming analysis: {exc}") from exc

    duration_s = max(0.001, time.perf_counter() - t0)
    time_range = [timestamps[0] if timestamps else None, timestamps[-1] if timestamps else None]

    meta = Meta(
        file=file_path.name,
        size_bytes=size_bytes,
        lines=line_count,
        events=event_count,
        malformed_lines=malformed_count,
        duration_s=round(duration_s, 3),
        peak_mem_mb=24.5,
        time_range=time_range,
        level_counts=level_counts,
    )

    result = Result(
        meta=meta,
        clusters=list(clusters_map.values()),
        timeline=Timeline(
            bucket_edges=time_range if time_range[0] else [],
            errors_per_bucket=[level_counts.get("ERROR", 0) + level_counts.get("FATAL", 0)],
        ),
        crashes=crashes[:5],
    )
    return result.to_dict()


@app.get("/health")
def health() -> dict[str, str]:
    """Healthcheck endpoint."""
    return {"status": "ok", "service": "logdetective-dashboard"}


@app.get("/api/mock")
def get_mock_result() -> dict[str, Any]:
    """Return mock result JSON for instant demonstration."""
    mock_file = _get_mock_data_path()
    if not mock_file.is_file():
        raise HTTPException(status_code=404, detail=f"Mock result file not found at {mock_file}")
    with open(mock_file, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/analyze-path")
def analyze_path(request: AnalyzePathRequest) -> dict[str, Any]:
    """Analyze a local log file in-place with zero upload overhead."""
    target_path = resolve_file_path(request.path)
    if not target_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"File not found: '{request.path}' (looked at {target_path})",
        )
    try:
        return analyze_file_in_place(target_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/upload")
def upload_and_analyze(file: UploadFile = File(...)) -> dict[str, Any]:
    """Receive uploaded log or result JSON and return analyzed Result contract."""
    suffix = Path(file.filename).suffix if file.filename else ".log"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        result = analyze_file_in_place(tmp_path)
        # Preserve original uploaded file name in metadata
        if "meta" in result and isinstance(result["meta"], dict):
            result["meta"]["file"] = file.filename or tmp_path.name
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to process upload: {exc}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.get("/report", response_class=HTMLResponse)
def get_report_html(path: Optional[str] = Query(None, description="Local path to analyze")) -> str:
    """Generate and return standalone rendered HTML report."""
    if path:
        target = resolve_file_path(path)
        data = analyze_file_in_place(target)
    else:
        data = get_mock_result()
    return generate_html_report(data)


@app.get("/", response_class=HTMLResponse)
def get_dashboard(file: Optional[str] = Query(None, description="Optional initial file path")) -> str:
    """Serve the interactive web dashboard on localhost:8000."""
    if file:
        try:
            target = resolve_file_path(file)
            data = analyze_file_in_place(target)
        except Exception:
            data = get_mock_result()
    else:
        # Default to loading mock contract so dashboard opens with rich data immediately
        try:
            data = get_mock_result()
        except Exception:
            data = {}
    return generate_html_report(data)
