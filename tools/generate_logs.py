#!/usr/bin/env python3
"""Synthetic log generator with planted failure story and ground truth tracking."""

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path


def generate_logs(output_file: Path, target_lines: int = 50000, target_size_mb: float = 0.0):
    start_time = datetime(2026, 11, 21, 10, 0, 0)
    current_time = start_time

    # Planted story configuration
    # 1. Pool usage warning at line ~100
    # 2. First DB timeout storm at line ~200
    # 3. Retry storm at line ~300
    # 4. Pool exhausted at line ~450
    # 5. OutOfMemoryError / Crash at line ~500

    ground_truth = {
        "planted_events": {
            "c2_pool_warning": {
                "level": "WARN",
                "template": "Connection pool usage above threshold: <NUM>%",
                "sample": "Connection pool usage above threshold: 88%",
                "expected_first_seen_ts": None,
                "expected_first_seen_line": None,
            },
            "c1_db_timeout": {
                "level": "ERROR",
                "template": "Connection to database <IP> timed out after <NUM>ms",
                "sample": "Connection to database 10.0.4.12:5432 timed out after 5000ms",
                "expected_first_seen_ts": None,
                "expected_first_seen_line": None,
            },
            "c3_retry_storm": {
                "level": "WARN",
                "template": "Retrying operation after error: <STR>",
                "sample": "Retrying operation after error: 'Connection refused'",
                "expected_first_seen_ts": None,
                "expected_first_seen_line": None,
            },
            "c4_pool_exhausted": {
                "level": "FATAL",
                "template": "Pool exhausted: cannot allocate connection to <PATH>",
                "sample": "Pool exhausted: cannot allocate connection to /var/run/postgresql/.s.PGSQL.5432",
                "expected_first_seen_ts": None,
                "expected_first_seen_line": None,
            },
            "crash_trigger": {
                "level": "FATAL",
                "trigger_word": "OutOfMemoryError",
                "message": "fatal error: OutOfMemoryError in worker thread pool",
                "expected_line": None,
                "expected_ts": None,
            }
        },
        "planted_crash_sequence_order": [
            "Connection pool usage above threshold: 88%",
            "Connection to database 10.0.4.12:5432 timed out after 5000ms",
            "Retrying operation after error: 'Connection refused'",
            "Pool exhausted: cannot allocate connection to /var/run/postgresql/.s.PGSQL.5432",
            "fatal error: OutOfMemoryError in worker thread pool"
        ]
    }

    # Stack traces
    python_stack = [
        'Traceback (most recent call last):',
        '  File "/app/services/checkout.py", line 142, in process_payment',
        '    conn = db_pool.get_connection(timeout=5.0)',
        '  File "/app/db/pool.py", line 89, in get_connection',
        '    raise TimeoutError("Database connection timed out")',
        'TimeoutError: Database connection timed out'
    ]

    java_stack = [
        'com.zaxxer.hikari.pool.HikariPool$PoolInitializationException: Failed to initialize pool.',
        '\tat com.zaxxer.hikari.pool.HikariPool.throwPoolInitializationException(HikariPool.java:595)',
        '\tat com.zaxxer.hikari.pool.HikariPool.checkFailFast(HikariPool.java:581)',
        '\tat com.zaxxer.hikari.pool.HikariPool.<init>(HikariPool.java:115)',
        '\tCaused by: java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 5000ms.',
        '\t\tat com.zaxxer.hikari.util.ConcurrentBag.borrow(ConcurrentBag.java:125)',
        '\t\t... 32 more'
    ]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    line_no = 0
    bytes_written = 0
    target_bytes = int(target_size_mb * 1024 * 1024) if target_size_mb > 0 else 0

    warning_planted = False
    timeout_planted = False
    retry_planted = False
    exhaust_planted = False
    crash_planted = False

    warning_idx = int(target_lines * 0.15) if target_lines else 1500
    timeout_idx = int(target_lines * 0.35) if target_lines else 3500
    retry_idx = int(target_lines * 0.55) if target_lines else 5500
    exhaust_idx = int(target_lines * 0.85) if target_lines else 8500
    crash_idx = int(target_lines * 0.95) if target_lines else 9500

    with open(output_file, "w", encoding="utf-8", buffering=1024*1024) as out:
        # Pre-generate noise templates for high-speed generation of large multi-hundred-MB logs
        noise_pool = []
        for i in range(200):
            uid = 1000 + i
            rid = f"req-{8000 + i}"
            noise_pool.append((
                1, # JSON
                '{"ts": "%TS%", "level": "INFO", "service": "' + random.choice(["auth-service", "gateway", "inventory-service"]) + '", "request_id": "' + rid + '", "message": "Processed HTTP GET /api/v1/items/' + str(uid) + ' in ' + str(random.randint(5, 45)) + 'ms with status 200"}\n'
            ))
            noise_pool.append((
                2, # Text
                '%STD_TS% [INFO] [gateway] [' + rid + '] User ' + str(uid) + ' authenticated successfully\n'
            ))
            noise_pool.append((
                3, # Syslog
                '%SYS_TS% web-01 kernel[102]: INFO packet accepted from 192.168.1.' + str(random.randint(2, 250)) + '\n'
            ))

        noise_idx = 0
        pool_len = len(noise_pool)
        chunk_lines = []
        chunk_bytes = 0

        while True:
            line_no += 1
            current_time += timedelta(milliseconds=random.randint(5, 50))
            iso_ts = current_time.isoformat() + "Z"
            std_ts = current_time.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
            syslog_ts = current_time.strftime("%b %d %H:%M:%S")

            # Check if it is time to plant one of our sequence events
            if not warning_planted and line_no >= warning_idx:
                warning_planted = True
                ground_truth["planted_events"]["c2_pool_warning"]["expected_first_seen_ts"] = iso_ts
                ground_truth["planted_events"]["c2_pool_warning"]["expected_first_seen_line"] = line_no
                entry = json.dumps({
                    "ts": iso_ts,
                    "level": "WARN",
                    "service": "order-service",
                    "request_id": "req-9801",
                    "message": "Connection pool usage above threshold: 88%"
                }) + "\n"
                chunk_lines.append(entry)
                chunk_bytes += len(entry)
                bytes_written += len(entry)
                continue

            if not timeout_planted and line_no >= timeout_idx:
                timeout_planted = True
                ground_truth["planted_events"]["c1_db_timeout"]["expected_first_seen_ts"] = iso_ts
                ground_truth["planted_events"]["c1_db_timeout"]["expected_first_seen_line"] = line_no
                entry = f"{std_ts} [ERROR] [order-service] [req-9801] Connection to database 10.0.4.12:5432 timed out after 5000ms\n"
                chunk_lines.append(entry)
                chunk_bytes += len(entry)
                bytes_written += len(entry)
                # Plant python stack trace continuation
                for frame in python_stack:
                    line_no += 1
                    s_entry = frame + "\n"
                    chunk_lines.append(s_entry)
                    chunk_bytes += len(s_entry)
                    bytes_written += len(s_entry)
                continue

            if not retry_planted and line_no >= retry_idx:
                retry_planted = True
                ground_truth["planted_events"]["c3_retry_storm"]["expected_first_seen_ts"] = iso_ts
                ground_truth["planted_events"]["c3_retry_storm"]["expected_first_seen_line"] = line_no
                entry = f"{syslog_ts} myhost order-service[9801]: WARN Retrying operation after error: 'Connection refused'\n"
                chunk_lines.append(entry)
                chunk_bytes += len(entry)
                bytes_written += len(entry)
                continue

            if not exhaust_planted and line_no >= exhaust_idx:
                exhaust_planted = True
                ground_truth["planted_events"]["c4_pool_exhausted"]["expected_first_seen_ts"] = iso_ts
                ground_truth["planted_events"]["c4_pool_exhausted"]["expected_first_seen_line"] = line_no
                entry = json.dumps({
                    "timestamp": iso_ts,
                    "severity": "FATAL",
                    "service": "order-service",
                    "request_id": "req-9801",
                    "message": "Pool exhausted: cannot allocate connection to /var/run/postgresql/.s.PGSQL.5432"
                }) + "\n"
                chunk_lines.append(entry)
                chunk_bytes += len(entry)
                bytes_written += len(entry)
                for frame in java_stack:
                    line_no += 1
                    s_entry = frame + "\n"
                    chunk_lines.append(s_entry)
                    chunk_bytes += len(s_entry)
                    bytes_written += len(s_entry)
                continue

            if not crash_planted and line_no >= crash_idx:
                crash_planted = True
                ground_truth["planted_events"]["crash_trigger"]["expected_line"] = line_no
                ground_truth["planted_events"]["crash_trigger"]["expected_ts"] = iso_ts
                entry = f"{iso_ts} [FATAL] [order-service] [req-9801] fatal error: OutOfMemoryError in worker thread pool\n"
                chunk_lines.append(entry)
                chunk_bytes += len(entry)
                bytes_written += len(entry)
                continue

            # Intermittent repeated warnings / errors after failure onset
            if timeout_planted and (line_no % 20 == 0):
                ip = f"10.0.4.{(line_no % 80) + 10}"
                ms = 3000 + (line_no % 7000)
                entry = f"{std_ts} [ERROR] [order-service] [req-{(line_no % 9000) + 1000}] Connection to database {ip}:5432 timed out after {ms}ms\n"
                chunk_lines.append(entry)
                chunk_bytes += len(entry)
                bytes_written += len(entry)
                if chunk_bytes >= 512 * 1024:
                    out.write("".join(chunk_lines))
                    chunk_lines.clear()
                    chunk_bytes = 0
                continue

            # Fast noise pool rotation
            t_type, t_tmpl = noise_pool[noise_idx % pool_len]
            noise_idx += 1

            if t_type == 1:
                entry = t_tmpl.replace("%TS%", iso_ts)
            elif t_type == 2:
                entry = t_tmpl.replace("%STD_TS%", std_ts)
            else:
                entry = t_tmpl.replace("%SYS_TS%", syslog_ts)

            chunk_lines.append(entry)
            chunk_bytes += len(entry)
            bytes_written += len(entry)

            if chunk_bytes >= 512 * 1024:
                out.write("".join(chunk_lines))
                chunk_lines.clear()
                chunk_bytes = 0

            # Stopping condition
            if target_bytes > 0 and bytes_written >= target_bytes:
                break
            if target_bytes == 0 and line_no >= target_lines:
                break

        if chunk_lines:
            out.write("".join(chunk_lines))

    ground_truth["total_lines"] = line_no
    ground_truth["total_bytes"] = bytes_written

    gt_file = output_file.parent / "ground_truth.json"
    with open(gt_file, "w", encoding="utf-8") as gtf:
        json.dump(ground_truth, gtf, indent=2)

    return line_no, bytes_written, gt_file


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic logs with planted failure story")
    parser.add_argument("--output", "-o", type=Path, default=Path("tests/sample_logs/sample.log"), help="Output path")
    parser.add_argument("--lines", "-n", type=int, default=15000, help="Number of lines")
    parser.add_argument("--size-mb", type=float, default=0.0, help="Target size in MB (overrides lines)")
    parser.add_argument("--size-gb", type=float, default=0.0, help="Target size in GB (overrides lines and MB)")

    args = parser.parse_args()

    size_mb = args.size_mb
    if args.size_gb > 0:
        size_mb = args.size_gb * 1024.0

    lines, size, gt_path = generate_logs(args.output, target_lines=args.lines, target_size_mb=size_mb)
    print(f"Generated {lines:,} lines ({size / (1024*1024):.2f} MB) to {args.output}")
    print(f"Ground truth written to {gt_path}")


if __name__ == "__main__":
    main()
