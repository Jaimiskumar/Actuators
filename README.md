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
