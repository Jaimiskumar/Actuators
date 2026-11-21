"""Unit and integration tests for engine and ground truth verification."""

import json
from pathlib import Path
from logdetective.engine import Engine


def test_engine_on_sample_and_ground_truth():
    sample_file = Path("tests/sample_logs/sample.log")
    gt_file = Path("tests/sample_logs/ground_truth.json")

    assert sample_file.exists()
    assert gt_file.exists()

    gt = json.loads(gt_file.read_text(encoding="utf-8"))

    engine = Engine()
    result = engine.analyze(sample_file)

    # 1. Verify metadata
    assert result.meta.lines >= 5000
    assert result.meta.events > 0
    assert result.meta.peak_mem_mb > 0
    assert result.meta.duration_s >= 0

    # 2. Verify planted cluster templates exist
    templates = {c.template: c for c in result.clusters}

    expected_warning = gt["planted_events"]["c2_pool_warning"]
    assert expected_warning["template"] in templates
    cluster_warn = templates[expected_warning["template"]]
    assert cluster_warn.first_seen.line_no == expected_warning["expected_first_seen_line"]

    expected_timeout = gt["planted_events"]["c1_db_timeout"]
    assert expected_timeout["template"] in templates
    cluster_timeout = templates[expected_timeout["template"]]
    assert cluster_timeout.first_seen.line_no == expected_timeout["expected_first_seen_line"]

    # 3. Verify crash reconstruction captured the trigger
    assert len(result.crashes) >= 1
    expected_trigger = gt["planted_events"]["crash_trigger"]
    oom_crashes = [
        c for c in result.crashes
        if expected_trigger["trigger_word"].lower() in c.trigger.message.lower()
    ]
    assert len(oom_crashes) >= 1
    oom_crash = oom_crashes[0]
    assert oom_crash.trigger.line_no == expected_trigger["expected_line"]
