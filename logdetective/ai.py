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


def synthesize_heuristic_summary(result: Result) -> str:
    """Generate a deterministic root-cause narrative when running fully offline without an API key."""
    if not result.clusters and not result.crashes:
        return "Root Cause: No significant errors or crash events detected in log stream."

    lines = []
    # Identify patient zero (earliest first-seen failure cluster)
    earliest_cluster = None
    for c in result.clusters:
        if earliest_cluster is None:
            earliest_cluster = c
        elif c.first_seen.line_no and earliest_cluster.first_seen.line_no:
            if c.first_seen.line_no < earliest_cluster.first_seen.line_no:
                earliest_cluster = c

    if earliest_cluster:
        fo = earliest_cluster.first_seen
        ts_info = f" at {fo.ts}" if fo.ts else ""
        lines.append(
            f"Root Cause: Initial failure pattern [{earliest_cluster.level}] emerged at Line {fo.line_no}{ts_info}: "
            f"'{earliest_cluster.sample or earliest_cluster.template}'."
        )

    if result.crashes:
        primary = result.crashes[0]
        crash_ts = f" at {primary.trigger.ts}" if primary.trigger.ts else ""
        lines.append(
            f"Failure Cascade: Pre-crash domino effect of {len(primary.sequence)} events escalated "
            f"until terminating with trigger at Line {primary.trigger.line_no}{crash_ts}: '{primary.trigger.message}'."
        )
    elif earliest_cluster:
        lines.append(
            f"Failure Cascade: Error signature repeated {earliest_cluster.count:,} times across the recorded session."
        )

    lines.append(
        "Recommended Fix: Investigate connection pool exhaustion and upstream service timeouts leading up to the initial patient-zero onset."
    )
    return "\n".join(lines)


def generate_ai_summary(result: Result, model: str = "gemini-2.5-flash") -> Optional[str]:
    """Generate an AI summary using the Gemini API, with offline deterministic fallback.
    
    Reads GEMINI_API_KEY (or GOOGLE_API_KEY) from environment.
    If no key is present, generates a local deterministic synthesis so the feature
    works 100% offline without failing.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print(
            "\n[Log Detective AI] Notice: GEMINI_API_KEY not set. "
            "Using local deterministic root-cause synthesis (Core Offline Mode).",
            file=sys.stderr,
        )
        return synthesize_heuristic_summary(result)

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
        print(f"\n[Log Detective AI] Gemini API HTTP Error ({exc.code}): {exc.reason}. Falling back to offline synthesis.", file=sys.stderr)
        return synthesize_heuristic_summary(result)
    except Exception as exc:
        print(f"\n[Log Detective AI] Remote call failed ({exc}). Falling back to offline synthesis.", file=sys.stderr)
        return synthesize_heuristic_summary(result)

    return synthesize_heuristic_summary(result)
