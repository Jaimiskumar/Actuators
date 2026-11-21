# Log Detective Benchmark Report
- **Date:** 2026-11-21 22:14:39
- **Log File:** `tests\sample_logs\benchmark_generated.log`
- **Size:** 2.24 MB
- **Iterations:** 1

## Results Table
| Component | Total Lines | Duration (s) | Throughput (lines/s) | Peak Memory RSS (MB) | Targets Met |
| --- | ---: | ---: | ---: | ---: | :---: |
| Naive Grep (Regex) | 20,000 | 0.0329s | 608,080 | 26.60 MB | PASS |
| Log Detective (Engine) | 20,000 | 0.1732s | 115,477 | 26.73 MB | PASS |
