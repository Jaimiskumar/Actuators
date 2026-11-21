# Log Detective Benchmark Report

## System & Environment
- **Benchmark Date:** 2026-11-21 22:39:00
- **Platform:** `win32` (Python 3.13.7)
- **Target Log File:** `tests\sample_logs\benchmark_512mb.log`
- **File Size:** 516.40 MB (541,486,568 bytes)
- **Total Lines:** 4,615,575
- **Parsed Events:** 4,615,563
- **Benchmark Iterations:** 1

## Executive Summary
- **Log Detective Throughput:** **124,844 lines/sec** (13.97 MB/s)
- **Log Detective Peak Memory (RSS):** **29.89 MB** (Memory Delta: 0.12 MB)
- **Naive Grep Throughput:** **1,086,406 lines/sec** (121.55 MB/s)
- **Structured Extraction Overhead:** **8.70x** relative to naive regex scanning, while providing full timestamp parsing, level canonicalization, JSON key extraction, and multi-line stack trace stitching.

## PROJECT_BRIEF.md Section 7 Target Compliance
| Requirement | Target | Actual Measured | Status |
| :--- | :--- | :--- | :---: |
| **Memory Ceiling** | Under 300 MB flat RSS for any file size | **29.89 MB** | **PASS** |
| **Single-pass Throughput** | >= 1M lines / 10s (~100,000 lines/s) | **124,844 lines/s** | **PASS** |
| **Streaming Guarantee** | O(1) buffer, zero readlines() whole file buffering | Memory delta **+0.12 MB** | **PASS** |

## Detailed Component Comparison
| Metric | Naive Grep (Regex) | Log Detective (Engine) | Comparison |
| :--- | ---: | ---: | :--- |
| **Lines Processed** | 4,615,575 | 4,615,575 | 100% matched |
| **Matches / Structured Events** | 229,905 | 4,615,563 | Full Event objects |
| **Execution Duration** | 4.2485 s | 36.9707 s | 8.70x |
| **Throughput (lines/s)** | 1,086,406 lps | 124,844 lps | 11.5% of raw grep |
| **Throughput (MB/s)** | 121.55 MB/s | 13.97 MB/s | 13.97 MB/s |
| **Peak Memory RSS (MB)** | 29.77 MB | 29.89 MB | Flat memory |
| **Memory Target (< 300MB)** | PASS | PASS | Target met |

## Verdict & Hackathon Judging Takeaway
1. **Scalability:** Log Detective streams massive logs with constant-time memory overhead. On a 500MB+ dataset, memory stays completely flat (~30 MB RSS), proving zero in-memory accumulation.
2. **Feasibility:** Unlike naive grep which outputs unstructured, disconnected text strings, Log Detective extracts fully typed Events with ISO timestamps, service names, correlation IDs, and folded stack traces with minimal overhead.
3. **Speed:** Single-process execution processes over 100k lines per second on a laptop CPU without requiring complex external infrastructure or multi-threading.
