import gzip
import io
import sys
from pathlib import Path
import pytest

from logdetective.reader import stream_lines


def test_stream_lines_plain(tmp_path: Path):
    test_file = tmp_path / "test.log"
    test_file.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")

    lines = list(stream_lines(test_file))
    assert len(lines) == 3
    assert lines[0] == (1, "line 1")
    assert lines[1] == (2, "line 2")
    assert lines[2] == (3, "line 3")


def test_stream_lines_gz(tmp_path: Path):
    gz_file = tmp_path / "test.log.gz"
    with gzip.open(gz_file, "wt", encoding="utf-8") as f:
        f.write("entry alpha\nentry beta\n")

    lines = list(stream_lines(gz_file))
    assert len(lines) == 2
    assert lines[0] == (1, "entry alpha")
    assert lines[1] == (2, "entry beta")


def test_stream_lines_nonexistent():
    with pytest.raises(FileNotFoundError):
        list(stream_lines("nonexistent_file_path.log"))
