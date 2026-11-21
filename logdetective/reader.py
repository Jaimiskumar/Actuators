"""Streaming log reader with flat memory O(1) buffer."""

import gzip
import io
import sys
from pathlib import Path
from typing import Generator, Union

# 128 KB buffer for optimal streaming throughput without buffering whole files
BUFFER_SIZE = 128 * 1024


def stream_lines(
    source: Union[str, Path, io.TextIOBase]
) -> Generator[tuple[int, str], None, None]:
    """Yields (line_no, line) from a plain file, .gz archive, or stdin.
    
    Guarantees flat O(1) memory usage regardless of file size.
    Lines are stripped of trailing newline characters but preserve original indentation.
    """
    if source == "-" or source is sys.stdin:
        line_no = 0
        for line in sys.stdin:
            line_no += 1
            yield line_no, line.rstrip("\r\n")
        return

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    if path.suffix.lower() == ".gz":
        with gzip.open(path, mode="rt", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                yield line_no, line.rstrip("\r\n")
    else:
        with open(path, mode="r", encoding="utf-8", errors="replace", buffering=BUFFER_SIZE) as f:
            for line_no, line in enumerate(f, start=1):
                yield line_no, line.rstrip("\r\n")
