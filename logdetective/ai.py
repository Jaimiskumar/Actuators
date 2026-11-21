"""Optional AI-assisted root cause summary (opt-in via --ai flag)."""

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional

from logdetective.contract import Result


def build_compact_prompt(result: Result) -> str:
    """Build a compact incident prompt (few KB) from aggregated patterns.
    
    Privacy guarantee: Raw logs NEVER leave the machine. Only top templates
    and pre-crash event summaries are sent.
    """
    meta = result.meta
    prompt_lines = [
        "You are an expert site reliability engineer (SRE) and software debugger.",
        "Analyze this aggregated production crash report and summarize the likely root cause in 2-3 concise sentences.",
        "",
        "### Incident Metadata",
        f"- File: {meta.file}",
        f"- Processed: {meta.lines:,} lines across {meta.events:,} events",
        f"- Time Span: {meta.time_range[0] or 'N/A'} to {meta.time_range[1] or 'N/A'}",
        f"- Errors/Fatals: {meta.level_counts.get('ERROR', 0)} errors, {meta.level_counts.get('FATAL', 0)} fatal triggers",
        "",
        "### Top Error Clusters (Patient-Zero First Occurrences)",
    ]

    for c in result.clusters[:5]:
        fo_line = f"Line {c.first_seen.line_no}"
        fo_ts = c.first_seen.ts or "unknown time"
        prompt_lines.append(
            f"- [{c.level}] Cluster {c.id} ({c.count:,} occurrences, first seen {fo_line} at {fo_ts}):"
        )
        prompt_lines.append(f"  Template: {c.template}")
        if c.sample:
            prompt_lines.append(f"  Sample: {c.sample}")
        if c.stack_top:
            prompt_lines.append(f"  Top stack: {' -> '.join(c.stack_top[:2])}")

    if result.crashes:
        primary_crash = result.crashes[0]
        prompt_lines.extend([
            "",
            "### Primary Crash Trigger & Cascade",
            f"Trigger at Line {primary_crash.trigger.line_no}: {primary_crash.trigger.message}",
            "Sequence of leading events:",
        ])
        for step in primary_crash.sequence[-8:]:
            prefix = "[TRIGGER] " if step.is_trigger else ("[ROOT FO] " if step.is_first_occurrence else "")
            prompt_lines.append(f"  - {prefix}[{step.level}] {step.message}")

    prompt_lines.extend([
        "",
        "Provide your analysis in this exact format:",
        "Root Cause: <one sentence identifying what started the incident>",
        "Failure Cascade: <one sentence explaining the chain reaction leading to the crash>",
        "Recommended Fix: <one sentence actionable remediation>",
    ])

    return "\n".join(prompt_lines)


def generate_ai_summary(result: Result, model: str = "gemini-2.5-flash") -> Optional[str]:
    """Generate an AI summary using the Gemini API.
    
    Reads GEMINI_API_KEY (or GOOGLE_API_KEY) from environment.
    Fails safely with a clear warning without halting the application.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print(
            "\n[Log Detective AI] GEMINI_API_KEY not set in environment. "
            "To enable AI root cause analysis, set export GEMINI_API_KEY='your-key'.",
            file=sys.stderr,
        )
        return None

    prompt = build_compact_prompt(result)

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 300,
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts and "text" in parts[0]:
                    return parts[0]["text"].strip()
    except urllib.error.HTTPError as exc:
        print(f"\n[Log Detective AI] Gemini API HTTP Error ({exc.code}): {exc.reason}", file=sys.stderr)
    except Exception as exc:
        print(f"\n[Log Detective AI] Failed to generate AI summary: {exc}", file=sys.stderr)

    return None
