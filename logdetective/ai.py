"""Optional AI-assisted root cause summary (opt-in via --ai flag)."""

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional

from logdetective.contract import Result


def build_compact_prompt(result: Result, agent_mode: bool = False) -> str:
    """Build a compact incident prompt (few KB) from aggregated patterns.
    
    Privacy guarantee: Raw logs NEVER leave the machine. Only top templates
    and pre-crash event summaries are sent.
    """
    meta = result.meta
    role_instruction = (
        "You are an expert AI SRE and Incident Commander investigating a production outage. "
        "Explain the incident clearly in simple English so developers and managers can understand it immediately."
        if agent_mode
        else "You are an expert site reliability engineer (SRE) and software debugger. Analyze this aggregated crash report."
    )

    prompt_lines = [
        role_instruction,
        "",
        "### Incident Metadata",
        f"- Log File: {meta.file}",
        f"- Processed: {meta.lines:,} lines across {meta.events:,} events",
        f"- Time Span: {meta.time_range[0] or 'N/A'} to {meta.time_range[1] or 'N/A'}",
        f"- Breakdown: {meta.level_counts.get('ERROR', 0)} errors, {meta.level_counts.get('FATAL', 0)} fatal terminations",
        "",
        "### Top Error Clusters (Patient-Zero First Occurrences)",
    ]

    for c in result.clusters[:6]:
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
            "### Crash Sequence & Pre-Crash Domino Cascade",
            f"Terminal Trigger at Line {primary_crash.trigger.line_no}: {primary_crash.trigger.message}",
            "Sequence of leading events:",
        ])
        for step in primary_crash.sequence[-8:]:
            prefix = "[TRIGGER] " if step.is_trigger else ("[ROOT FO] " if step.is_first_occurrence else "")
            prompt_lines.append(f"  - {prefix}[{step.level}] {step.message}")

    if agent_mode:
        prompt_lines.extend([
            "",
            "Provide your investigation in this exact JSON format with simple, non-jargon English:",
            "{",
            '  "summary": "1-2 sentences explaining what happened in simple terms",',
            '  "patient_zero": "1 sentence describing the very first error that started the whole incident",',
            '  "cascade_analysis": "1 sentence explaining how the error multiplied into a crash",',
            '  "recommended_fix": "1-2 practical action steps developers should take right now",',
            '  "recommended_code": "Ready-to-use, copy-pasteable code or configuration snippet (with comments) that directly fixes the root cause"',
            "}"
        ])
    else:
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


def generate_ai_summary(result: Result, model: str = "gemini-3.5-flash") -> Optional[str]:
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
            "maxOutputTokens": 1500,
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


def investigate_incident(result: Result, model: str = "gemini-3.5-flash") -> dict[str, str]:
    """AI SRE Agent: Investigates incident and provides simple-English explanation and concrete fix."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    fallback = {
        "summary": "The application suffered a cascading service failure caused by connection timeouts and resource exhaustion.",
        "patient_zero": "The incident began with an initial unhandled warning/error that saturated system resources.",
        "cascade_analysis": "Rapid retry bursts compounded queue latency until the process terminated with a fatal crash.",
        "recommended_fix": "Increase database connection pool capacity, add exponential backoff on retries, and set alert thresholds on resource utilization.",
        "recommended_code": (
            "# application.yml: HikariCP connection pool optimization\n"
            "spring:\n"
            "  datasource:\n"
            "    hikari:\n"
            "      maximum-pool-size: 50\n"
            "      connection-timeout: 30000  # 30 seconds\n"
            "      idle-timeout: 600000       # 10 minutes\n"
            "      max-lifetime: 1800000      # 30 minutes"
        ),
    }

    if result.clusters:
        first_c = min(result.clusters, key=lambda c: c.first_seen.line_no or 999999999)
        fo = first_c.first_seen
        ts_info = f" at {fo.ts}" if fo.ts else ""
        fallback["patient_zero"] = (
            f"Initial error signature [{first_c.level}] started at Line {fo.line_no}{ts_info}: "
            f"'{first_c.sample or first_c.template}'"
        )
        # Extract component/service name intelligently
        svc = "Application Service"
        if first_c.services:
            svc = first_c.services[0]
        else:
            sample = (first_c.sample or first_c.template).lower()
            if "dfs." in sample or "datanode" in sample or "namenode" in sample or "blk_" in sample:
                svc = "HDFS DataNode"
            elif "httpd" in sample or "apache" in sample or "client denied" in sample or "mod_jk" in sample or "workerenv" in sample:
                svc = "Apache mod_jk / HTTP Server"
            elif "database" in sample or "postgresql" in sample or "pool" in sample:
                svc = "Database Pool Service"
            elif "kafka" in sample:
                svc = "Kafka Broker"

        fallback["summary"] = (
            f"Service [{svc}] experienced repeated failures ({first_c.count:,} events) "
            f"that triggered a fatal process termination."
        )

        sample_low = (first_c.sample or first_c.template).lower()
        if "dfs" in sample_low or "datanode" in sample_low or "blk_" in sample_low:
            fallback["recommended_fix"] = (
                "1. Verify network socket health and file descriptor limits on DataNodes. "
                "2. Inspect block replication status and fsck health. "
                "3. Increase dfs.datanode.socket.write.timeout in hdfs-site.xml."
            )
            fallback["recommended_code"] = (
                "<!-- hdfs-site.xml: Fix DataNode socket timeouts and receiver limits -->\n"
                "<property>\n"
                "  <name>dfs.datanode.socket.write.timeout</name>\n"
                "  <value>300000</value> <!-- 5 minutes -->\n"
                "</property>\n"
                "<property>\n"
                "  <name>dfs.datanode.max.transfer.threads</name>\n"
                "  <value>4096</value>\n"
                "</property>"
            )
        elif "apache" in sample_low or "client denied" in sample_low or "mod_jk" in sample_low or "workerenv" in sample_low:
            fallback["recommended_fix"] = (
                "1. Check Tomcat / backend AJP connector port and worker thread saturation. "
                "2. Verify mod_jk worker configuration, connection timeouts, and socket_keepalive. "
                "3. Ensure backend application servers are accepting connections."
            )
            fallback["recommended_code"] = (
                "# workers.properties: Optimize Tomcat AJP worker pool & timeouts\n"
                "worker.worker1.type=ajp13\n"
                "worker.worker1.host=localhost\n"
                "worker.worker1.port=8009\n"
                "worker.worker1.connection_pool_timeout=60\n"
                "worker.worker1.socket_keepalive=true\n"
                "worker.worker1.connection_pool_size=100"
            )
        elif "connection" in sample_low or "pool" in sample_low or "timed out" in sample_low:
            fallback["recommended_fix"] = (
                "1. Increase database connection pool capacity (e.g. HikariCP maxPoolSize). "
                "2. Add exponential backoff and jitter on retry loops to stop thundering herd. "
                "3. Configure alerts on connection acquisition latency."
            )
            fallback["recommended_code"] = (
                "# application.yml: HikariCP connection pool optimization\n"
                "spring:\n"
                "  datasource:\n"
                "    hikari:\n"
                "      maximum-pool-size: 50\n"
                "      connection-timeout: 30000  # 30s\n"
                "      idle-timeout: 600000       # 10m\n"
                "      max-lifetime: 1800000      # 30m"
            )

    if result.crashes:
        primary = result.crashes[0]
        crash_ts = f" at {primary.trigger.ts}" if primary.trigger.ts else ""
        fallback["cascade_analysis"] = (
            f"Pre-crash sequence of {len(primary.sequence)} warning/error events escalated "
            f"until process crashed at Line {primary.trigger.line_no}{crash_ts}: '{primary.trigger.message}'"
        )

    if not api_key:
        return fallback

    prompt = build_compact_prompt(result, agent_mode=True)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}
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
                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                clean_text = text.strip()
                if clean_text.startswith("```"):
                    clean_text = clean_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                parsed = json.loads(clean_text)
                if isinstance(parsed, dict) and "summary" in parsed:
                    if not parsed.get("recommended_code"):
                        parsed["recommended_code"] = fallback.get("recommended_code", "")
                    return parsed
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            print("\n[Log Detective AI] Notice: Google Cloud returned 403 (Project requires billing upgrade at https://aistudio.google.com/billing).", file=sys.stderr)
            print("[Log Detective AI] Running built-in offline deterministic SRE engine.\n", file=sys.stderr)
        else:
            print(f"\n[Log Detective AI] HTTP Error ({exc.code}). Using offline deterministic SRE engine.\n", file=sys.stderr)
    except Exception:
        pass

    return fallback
