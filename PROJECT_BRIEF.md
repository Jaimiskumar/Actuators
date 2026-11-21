# Log Detective: AI Coding Agent Brief

*Give this entire document to your AI coding agent (Antigravity, Cursor, Claude Code, etc.) as the first message. It is the project spec, the build plan, and the working rules.*

---

## 0. How to use this document

Paste everything below into the agent. Then start with: **"Read the brief. Do Phase 0 only and wait for my answers."**

---

## 1. Your role

You are the lead engineer on a **12-hour hackathon project** (we have about 10-11 hours of build time). You will build the project **from scratch** with me (the user) and my team. You write code, run it, test it, and explain your decisions briefly.

**Core working rule: ASK BEFORE ASSUMING.** At the start of every phase, and any time a decision is optional, expensive, or needs access, you must stop and ask me. See Section 9 (the Ask Protocol). Never silently add extras, install heavy dependencies, or call external APIs without my approval.

---

## 2. The problem statement (verbatim requirements)

**Terminal-Native Log Detective (Software, CLI/Desktop)**

Developers lose hours digging through gigabytes of messy, mixed-format logs. Build a command-line or desktop tool that:

1. Ingests large log files (JSON, plain text, and stack traces mixed together)
2. Automatically clusters similar errors
3. Finds the first occurrence of each failure pattern
4. Reconstructs the likely sequence of events leading to a crash
5. Handles files too large to load into memory
6. Gives useful output within seconds
7. Is installable and usable by a stranger with one command

Judges will score on: **technicality, feasibility, scalability, novelty, future enhancement**. Judges also want **visualization**.

---

## 3. Decisions already made (do not re-debate)

| Decision | Choice |
| --- | --- |
| Language | **Python 3.10+** (unless I tell you otherwise in Phase 0) |
| Core product | A **CLI**: `logdetective <file>` |
| Visualization | A **local, self-contained HTML report** (`--html`) and a **local dashboard** (`logdetective serve`). **No hosted website, no database, no login.** |
| Privacy | Logs never leave the machine. AI features are **opt-in only** |
| Clustering | Start with **from-scratch normalization + hashing**. Offer Drain3 as an upgrade only after asking me |
| AI | Optional `--ai` flag. Core must work fully offline with no API key |
| VS Code extension | **Future scope only.** Do not build unless I explicitly ask |

---

## 4. What the user experiences (target behavior)

```
pipx install logdetective
logdetective crash.log
logdetective crash.log --html report.html --open
logdetective serve
logdetective crash.log --ai          # optional
```

The user has a multi-GB log with JSON lines, plain text lines, and multi-line stack traces mixed together. In seconds they must see:

1. **Stats:** file size, lines processed, time taken, peak memory.
2. **Top error clusters:** pattern template, count, first seen, last seen, a sample line.
3. **First occurrence** of every cluster (timestamp and line number).
4. **Crash story:** the ordered events leading up to each detected crash.
5. **Optional AI summary:** plain-English likely root cause.

---

## 5. Architecture

```
file -> reader -> parser -> stack-trace joiner -> Event stream
   Event stream -> fingerprint/cluster (dict of patterns)
   Event stream -> rolling buffer -> crash snapshots
   -> Result JSON -> terminal (rich) | HTML report | dashboard | AI summary
```

**Rules:** one streaming pass, O(lines) time, O(patterns + buffer) memory. Never call `readlines()` or load the whole file.

### Project structure

```
logdetective/
  __init__.py
  cli.py            # typer commands: analyze, serve
  reader.py         # streaming reader, .gz, stdin
  parser.py         # JSON / text / continuation detection
  stacktrace.py     # joins stack trace lines into one Event
  cluster.py        # normalize + fingerprint + cluster store
  timeline.py       # rolling buffer + crash snapshots
  engine.py         # orchestrates the single pass, returns Result
  report_terminal.py
  report_html.py
  server.py         # FastAPI local dashboard
  ai.py             # optional LLM summary (opt-in)
  templates/report.html
  static/           # dashboard JS/CSS (Chart.js bundled locally)
tools/
  generate_logs.py  # synthetic log generator with a planted failure story
  benchmark.py
tests/
  sample_logs/
pyproject.toml
README.md
```

---

## 6. Module specifications

### 6.1 reader.py

- Generator yielding `(line_no, line)`; open with `errors="replace"`.
- Support plain files, `.gz` (`gzip.open`), and stdin (`-`).
- Use a large read buffer. Memory must stay flat for any file size.

### 6.2 parser.py

For each line decide the type, cheapest checks first:

- Starts with `{`: try `json.loads`. Map keys: time (`timestamp`, `ts`, `time`, `@timestamp`, `datetime`), level (`level`, `severity`, `lvl`, `levelname`), message (`message`, `msg`, `log`, `error`), request id (`request_id`, `trace_id`, `req_id`, `correlation_id`), thread (`thread`, `thread_id`), service (`service`, `logger`, `app`).
- Matches a timestamp at line start: plain text. Support **ISO 8601, `YYYY-MM-DD HH:MM:SS[,.]ms`, and syslog (`Nov 21 03:01:02`)** well. Extract time, level, message, and a request/thread id if present.
- Otherwise: continuation line (candidate for stack trace).
- Pre-compile all regexes at import time.
- If JSON fails to parse, fall back to text handling. Never crash on bad input; count it as `malformed_lines`.

### 6.3 stacktrace.py

A line belongs to the **previous event** if it matches: leading whitespace plus ` at  `, Python `File "...", line N`, `Traceback (most recent call last):`, `Caused by:`, `... N more`, or an exception class line directly after a traceback. Append to `event.stack`. Cap the stored stack at a sane length (for example 50 lines) to protect memory.

### 6.4 Event model

```python
@dataclass(slots=True)
class Event:
    line_no: int
    ts: datetime | None
    level: str            # DEBUG/INFO/WARN/ERROR/FATAL/UNKNOWN
    message: str
    stack: list[str]
    fmt: str              # json | text | trace
    request_id: str | None
    service: str | None
```

### 6.5 cluster.py

- Process only WARN, ERROR, FATAL events (just count INFO and DEBUG).
- Normalize message: UUIDs to `<ID>`, IPs to `<IP>`, hex to `<HEX>`, numbers to `<NUM>`, quoted strings to `<STR>`, file paths to `<PATH>`, URLs to `<URL>`, emails to `<EMAIL>`.
- Fingerprint = hash(normalized message + top 3 stack frames, with line numbers stripped).
- Store per cluster: `id, template, count, first_seen (ts + line_no), last_seen, sample_raw, levels, services, count_over_time buckets`.
- Keep timeline buckets adaptive (about 100 to 200 buckets across the file's time range) so memory stays bounded.
- Merge similar clusters only if cheap; otherwise leave it as a documented limitation.

### 6.6 timeline.py (crash reconstruction)

- Maintain a `deque(maxlen=N)` of recent events (default N=300).
- **Crash triggers:** level FATAL; keywords such as `panic`, `segfault`, `SIGSEGV`, `OutOfMemoryError`, `core dumped`, `fatal error`, `unhandled exception`, `killed`, `exit code` (nonzero); an uncaught Traceback at end of process.
- On trigger, snapshot the buffer, then refine:
  1. Keep events within the last T seconds (default 120).
  2. Boost events sharing the crash's request/trace/thread/service id.
  3. Always include the first-seen event of any new error cluster inside the window.
  4. Collapse repeated identical events into `"... repeated xN"`.
  5. Drop low-value INFO/DEBUG noise.
- Output an ordered list: `{ts, level, message, cluster_id, is_first_occurrence, is_trigger}`.
- Cap the number of stored crash snapshots (default 10) and keep the first and the last.

### 6.7 engine.py

Single pass: reader, parser, joiner, then fan out to cluster store and timeline. Emit a progress callback every N lines. Return a `Result`.

### 6.8 Result JSON schema (shared contract: engine, HTML, dashboard, AI)

Agree on and freeze this in Phase 1. The frontend must be able to build against a mock file.

```json
{
  "meta": {"file": "crash.log", "size_bytes": 0, "lines": 0, "events": 0,
           "malformed_lines": 0, "duration_s": 0.0, "peak_mem_mb": 0,
           "time_range": ["ISO", "ISO"], "level_counts": {}},
  "clusters": [{"id": "c1", "template": "", "count": 0, "level": "ERROR",
                "first_seen": {"ts": "ISO", "line_no": 0},
                "last_seen": {"ts": "ISO", "line_no": 0},
                "sample": "", "stack_top": [], "services": [],
                "buckets": [0, 0, 0]}],
  "timeline": {"bucket_edges": ["ISO"], "errors_per_bucket": [0]},
  "crashes": [{"trigger": {"ts": "ISO", "line_no": 0, "message": ""},
               "sequence": [{"ts": "ISO", "level": "", "message": "",
                             "cluster_id": "c1", "is_first_occurrence": true,
                             "is_trigger": false}]}],
  "ai_summary": null
}
```

### 6.9 Terminal report (`rich`)

Stats panel, top-N clusters table, first-occurrence list, crash timeline per crash, a progress bar during the pass, and a clean message for no errors found.

### 6.10 HTML report and dashboard

One self-contained file, works offline, light/dark friendly. Sections:

1. Summary header (file size, lines, time, memory).
2. **Error timeline** chart with the first crash marked.
3. **Cluster bar chart** (top patterns by count).
4. **First-occurrence cards** (click to expand sample and stack).
5. **Crash sequence** as a vertical timeline with the trigger and first-occurrence events highlighted.
6. Optional AI summary box.

`logdetective serve`: FastAPI on localhost, one page with drag-and-drop **and** a "enter file path" box (the server reads big files in place), a live progress bar (SSE or polling), then the same visuals. Bundle Chart.js locally so it works offline.

### 6.11 ai.py (opt-in)

- Build a compact prompt (a few KB): top 5 clusters, first occurrences, the first crash sequence. **Never send the raw log.**
- Providers: configurable (env var for the API key; support a local model such as Ollama as an option).
- On any failure, print a warning and continue with the normal report.
- **Agentic mode (only if I approve):** the LLM gets tools `get_cluster(id)`, `search_logs(pattern)`, `events_before(timestamp)`, backed by an index of the already-computed results.

---

## 7. Performance and quality targets

| Target | Goal |
| --- | --- |
| Throughput | At least 1M lines per 10 s single process on a laptop (report actual numbers) |
| Memory | Flat; under about 300 MB for any file size |
| First feedback | Progress bar visible within 1 second |
| Optimization step (after correctness) | Optional multiprocessing by byte-range chunks with merge of cluster dicts (ask me first) |
| Robustness | Handles empty files, binary junk, huge single lines, mixed encodings, no timestamps |
| Tests | `pytest` unit tests for parser, stacktrace joiner, normalizer, crash snapshot. One end-to-end test on the generated log |

---

## 8. Build plan (about 10.5 hours)

Do **one phase at a time**. At the end of every phase: run the code, show me the result, summarize in 5 lines or fewer, then use the Ask Protocol before starting the next phase.

| Phase | Hours | Goal | Done when |
| --- | --- | --- | --- |
| **0. Kickoff** | 0 - 0.5 | Ask me the setup questions (Section 9.1). Confirm stack, team split, and extras | I have answered |
| **1. Skeleton and contract** | 0.5 - 1.5 | `pyproject.toml`, entry point, `cli.py`, `reader.py`, the frozen Result schema, a **mock result JSON** for the frontend, and `tools/generate_logs.py` | `logdetective --help` works and a sample log exists |
| **2. Parsing** | 1.5 - 3.5 | `parser.py`, `stacktrace.py`, Event model, unit tests | Mixed sample log yields correct Events |
| **3. Clustering and first occurrence** | 3.5 - 5.5 | `cluster.py`, `engine.py` | Planted failure patterns in the generated log are found with correct first-seen times |
| **4. Crash reconstruction** | 5.5 - 7 | `timeline.py` | The planted crash story is recovered in the right order |
| **5. Reports and visualization** | 7 - 9 | `report_terminal.py`, `report_html.py`, and `serve` if approved | HTML opens offline with all 5 sections |
| **6. Packaging, benchmark, polish** | 9 - 10 | Clean install test in a fresh venv, `tools/benchmark.py` on a 1-2 GB file, README with install, usage, supported formats, limits | One-command install works from scratch |
| **7. Demo and optional extras** | 10 - 10.5+ | Optional `--ai`, demo script, roadmap slide | Demo runs end to end twice |

**Parallel track for a team:** one person can build the HTML/dashboard (Phase 5) from the mock JSON starting in Phase 1. Tell me if we are working in parallel so you keep the schema frozen and avoid conflicting edits.

**Time check rule:** at each phase end, tell me hours used versus planned and propose what to cut if we are behind. Cut order: AI agent mode, multiprocessing, `serve`, then polish. Never cut: streaming, parsing, clustering, first occurrence, crash sequence, one-command install, the HTML report.

---

## 9. The Ask Protocol (mandatory)

### 9.1 Phase 0 questions (ask these first, as short tappable-style options where possible)

1. Team size and each person's strongest skills (Python, frontend, systems).
2. Operating system(s) the demo will run on (Windows, macOS, Linux).
3. Python version installed, and whether `pipx` is available.
4. Are we building in parallel (backend and frontend at the same time) or alone?
5. Do we have API keys or accounts, and which? (Anthropic, OpenAI, Gemini, or local Ollama.)
6. Is a test log file available, or should I generate synthetic logs? Any real logs we are allowed to use (for example Loghub datasets)?
7. Is there a GitHub repo, and should I commit and push after each phase?
8. Should the demo hardware be a laptop only, or is a projector or internet available?

### 9.2 Recommendation questions (ask at the end of EVERY phase)

At the end of each phase, give me a short list titled **"Recommended extras"** with, for each item: what it is, why it helps the judges, time cost, and your verdict (**Need / Nice to have / Skip**). Then ask which ones to include. Examples of items you should consider raising at the right moment:

- Drain3 for smarter template mining (about 1 hour saved or quality gain)
- Multiprocessing for large files
- `serve` local dashboard versus HTML report only
- Live `--follow` (tail -f) mode
- `--ai` summary, then the agentic investigator
- JSON/CSV export of results
- Colored diff between the first-error and last-error samples
- Docker image or a single-file binary (PyInstaller)
- GitHub Actions CI and a PyPI release
- VS Code extension (future scope slide only unless I approve)
- Anomaly detection (sudden spike in rate)

Never implement an extra before I say yes.

### 9.3 Access and tools requests

Whenever you need any of the following, **stop and ask me in one clear message** (what, why, and what happens if I say no):

- API keys or secrets (tell me to set them as environment variables; never write them in code or commit them)
- Installing system packages or global tools
- Adding any new Python dependency (name, size, license, and why)
- Network access (downloading datasets, calling APIs, publishing to PyPI)
- Creating or pushing to a GitHub repo, or publishing anything
- Running long or heavy jobs (generating multi-GB files, benchmarks)
- Deleting or overwriting files

### 9.4 Decision format

When asking me something, use this format:

```
QUESTION: <one sentence>
OPTIONS: A) ...  B) ...  C) ...
MY RECOMMENDATION: <letter and one-line reason>
IMPACT ON TIME: <hours>
```

If I don't answer, proceed with your recommendation **only for reversible, low-cost choices**, and tell me you did.

---

## 10. Coding rules

- Type hints, short docstrings, small functions; no clever one-liners that hide logic.
- Pre-compiled regexes; avoid per-line allocations in the hot path.
- No global mutable state except inside the engine object.
- Every user-facing error message is human-readable; no raw tracebacks unless `--debug`.
- Dependencies stay minimal. Baseline: `typer`, `rich`. Add `fastapi` and `uvicorn` only if `serve` is approved. Add `psutil` only for memory measurement. Ask before anything else.
- Commit messages are short and per feature.
- Never print secrets. Never send raw log content off the machine.
- After any change, run the tests and the CLI on the sample log before telling me it works.

---

## 11. Test data and benchmarking

`tools/generate_logs.py` must create a configurable-size file (for example `--size-gb 2`) that mixes:

- JSON lines with varied key names (`ts`/`timestamp`, `level`/`severity`)
- Plain text lines in 2 to 3 timestamp styles
- Java and Python multi-line stack traces
- Normal INFO noise (about 95 percent of lines)
- A **planted failure story** with known ground truth, for example: pool usage warning, then DB timeout storm (first occurrence at a known time), retry storm, pool exhausted, then a FATAL crash

Write the ground truth to `ground_truth.json` so tests can verify cluster count, first-seen times, and crash sequence order. The benchmark script reports lines per second, total time, and peak memory, and compares against a naive `grep`-style baseline.

---

## 12. Definition of done

- [ ] `pipx install .` works in a fresh environment and `logdetective` runs
- [ ] Handles JSON, plain text, and stack traces mixed in one file
- [ ] Streaming only; memory stays flat on a 1 to 2 GB file (benchmark shown)
- [ ] Clusters errors and shows first occurrence per cluster
- [ ] Reconstructs the sequence before each detected crash
- [ ] Terminal report and offline HTML report with the 5 visual sections
- [ ] Works with no internet and no API key
- [ ] Tests pass; README documents install, usage, supported formats, and known limits
- [ ] Demo script rehearsed; roadmap slide lists future scope

---

## 13. Demo script (3 minutes)

1. Show the problem: open the huge log in an editor (it struggles) or `grep ERROR | wc -l` (tens of thousands of lines).
2. Run `logdetective crash.log`. Point out speed, flat memory, and the pattern count.
3. Run with `--html --open`. Walk through the timeline, the clusters, the first-occurrence cards, and the crash story.
4. Optional: `--ai` for the plain-English cause.
5. Close with future scope: live follow mode, VS Code extension, Kubernetes and Docker integration, anomaly alerts, a team-shared history.

**Pitch line:** *"lnav shows you logs, Drain3 groups messages, Sentry needs infrastructure. Log Detective is the one command that tells you what broke first and what led up to it."*

---

## 14. Future enhancements (for the judges' slide)

Live tail mode, anomaly detection, LLM investigator agent with tools, VS Code extension with clickable stack frames, Kubernetes and Docker log adapters, OpenTelemetry trace correlation, plugin system for custom log formats, regression comparison between two runs, and a Slack or GitHub issue exporter.

---

## 15. First message the agent should send

> "I have read the brief. Starting Phase 0. Please answer these setup questions (Section 9.1). Then I will propose the exact Phase 1 plan and recommended extras before writing any code."
