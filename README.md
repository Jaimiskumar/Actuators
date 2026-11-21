# Log Detective

Terminal-Native Log Detective: Fast, memory-flat error clustering & crash timeline reconstruction.

## Quickstart

```bash
# In virtual environment:
pip install -e .

# Run CLI help:
logdetective --help

# Generate a synthetic sample log (with planted failure story & ground truth):
python3 tools/generate_logs.py --lines 20000

# Run analysis:
logdetective tests/sample_logs/sample.log
```

## Benchmarking & Performance Validation

Log Detective is designed to maintain strictly flat memory (< 300 MB) and high throughput (>= 100k lines/sec).

```bash
# Benchmark against any log file vs naive grep baseline:
python tools/benchmark.py tests/sample_logs/sample.log

# Benchmark against real-world Loghub datasets (auto-download & run):
python tools/benchmark.py --download-sample hdfs
python tools/benchmark.py --download-sample apache

# Generate custom-scale synthetic logs and benchmark:
python tools/benchmark.py --generate-lines 50000 --output-report BENCHMARK_REPORT.md

# Machine-readable JSON output for CI / grading:
python tools/benchmark.py --json tests/sample_logs/sample.log
```

## Real-World Open-Source Datasets (Loghub)

Download real-world distributed systems, supercomputing, and web server logs:

```bash
# List available datasets
python tools/download_logs.py --list

# Download specific dataset (e.g. HDFS, Apache, BGL, Spark, Linux)
python tools/download_logs.py --dataset hdfs
python tools/download_logs.py --dataset apache
```

## Packaging & Docker

Verify one-command installation and container readiness:

```bash
# Verify clean one-command install in an isolated environment:
python tools/verify_install.py

# Run packaging test suite:
pytest tests/test_packaging.py

# Build and run Docker container:
docker build -t logdetective .
docker run --rm logdetective tests/sample_logs/sample.log
```

## Architecture & Contract

Log Detective runs in a single streaming pass:
```
file -> reader -> parser -> stack-trace joiner -> Event stream
   Event stream -> fingerprint/cluster (dict of patterns)
   Event stream -> rolling buffer -> crash snapshots
   -> Result JSON -> terminal (rich) | HTML report | dashboard | AI summary
```

The frozen schema is located at `tests/mock_result.json` and mirrored in `logdetective/contract.py`.

## Team Workstreams

* **Teammate 1 (Frontend):** Build `templates/report.html` and `static/` against `tests/mock_result.json`.
* **Teammate 2 (DevOps & Testing):** Benchmark scripts, packaging, and real Loghub datasets.
* **Teammate 3 (Lead + Agent):** Streaming engine, parsing, clustering, crash timeline.
