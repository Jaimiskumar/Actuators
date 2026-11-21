"""HTML Report Generator for Log Detective.

Generates a standalone, self-contained offline HTML report and dashboard
embedding local Chart.js and raw analysis result JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

try:
    from logdetective.contract import Result
except ImportError:
    Result = Any  # type: ignore


class _JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder handling datetimes and dataclasses."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)
        return super().default(obj)


def _find_asset_file(relative_paths: list[Path]) -> Path:
    for p in relative_paths:
        if p.is_file():
            return p
    raise FileNotFoundError(f"Asset not found. Looked at: {[str(p) for p in relative_paths]}")


def get_template_path() -> Path:
    base = Path(__file__).resolve().parent
    candidates = [
        base / "templates" / "report.html",
        base.parent / "templates" / "report.html",
        base / "report.html",
    ]
    return _find_asset_file(candidates)


def get_chart_js_path() -> Path:
    base = Path(__file__).resolve().parent
    candidates = [
        base / "static" / "chart.umd.min.js",
        base.parent / "static" / "chart.umd.min.js",
        base.parent / "logdetective" / "static" / "chart.umd.min.js",
    ]
    return _find_asset_file(candidates)


def generate_html_report(
    result: Result | dict[str, Any],
    output_path: Optional[str | Path] = None,
    open_browser: bool = False,
) -> str:
    """Generate a self-contained offline HTML report from a Result object or dict.

    Args:
        result: Result dataclass instance or dict matching the contract schema.
        output_path: Optional file path where the HTML report should be saved.
        open_browser: If True and output_path is provided, open the report in the browser.

    Returns:
        The generated HTML content string.
    """
    # Convert result to serializable dict
    if hasattr(result, "to_dict") and callable(result.to_dict):
        data = result.to_dict()
    elif is_dataclass(result) and not isinstance(result, type):
        data = asdict(result)
    elif isinstance(result, dict):
        data = result
    else:
        raise TypeError(f"Expected Result or dict, got {type(result)}")

    json_str = json.dumps(data, cls=_JSONEncoder, indent=2)

    # Read template & Chart.js
    template_path = get_template_path()
    template_content = template_path.read_text(encoding="utf-8")

    chart_js_path = get_chart_js_path()
    chart_js_content = chart_js_path.read_text(encoding="utf-8")

    # Replace placeholders
    html_content = template_content
    html_content = html_content.replace("__CHART_JS__", chart_js_content)
    html_content = html_content.replace("{{ chart_js | safe }}", chart_js_content)
    html_content = html_content.replace("__RESULT_JSON__", json_str)
    html_content = html_content.replace("{{ result_json | safe }}", json_str)

    if output_path is not None:
        out_file = Path(output_path).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(html_content, encoding="utf-8")

        if open_browser:
            webbrowser.open(out_file.as_uri())

    return html_content


def main():
    parser = argparse.ArgumentParser(
        description="Generate self-contained offline HTML report from Result JSON"
    )
    parser.add_argument(
        "json_file",
        type=Path,
        help="Path to Result JSON file (e.g. tests/mock_result.json)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("report.html"),
        help="Output HTML path (default: report.html)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open HTML report automatically in browser",
    )
    args = parser.parse_args()

    with open(args.json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    out = generate_html_report(data, output_path=args.output, open_browser=args.open)
    print(f"Generated offline HTML report at {args.output.resolve()} ({len(out):,} bytes)")


if __name__ == "__main__":
    main()
