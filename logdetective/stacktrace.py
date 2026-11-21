"""Stack trace detection and multi-line event joining."""

import re
from typing import Generator, Iterable, Optional

from logdetective.contract import Event
from logdetective.parser import parse_line

# Cap stored stack frames per event to keep memory flat O(1)
MAX_STACK_FRAMES = 50

# Regex patterns identifying stack trace lines across Python, Java, JS, Go
RE_STACK_TRACE_LINE = re.compile(
    r"^(?:"
    r"\s+at\s+.*"                                  # Java/JavaScript: '  at com.foo.Bar(Bar.java:42)'
    r"|Traceback \(most recent call last\):"        # Python traceback header
    r"|\s*File\s+\".*\",\s+line\s+\d+.*"           # Python frame: '  File "app.py", line 12'
    r"|\s*(?:Caused by:|Suppressed:).*"             # Java root cause
    r"|\s*\.\.\.\s*\d+\s+more"                      # Java omitted frames: '... 32 more'
    r"|\s*[a-zA-Z0-9_.]*(?:Exception|Error|Failure|Panic):\s*.*"  # Exception message line
    r"|\s*panic:\s*.*"                             # Go panic
    r"|\s*goroutine\s+\d+\s+\[.*\]:"               # Go goroutine dump
    r")"
)


def is_stack_trace_line(line: str) -> bool:
    """Check if a line matches known stack trace or traceback patterns."""
    return bool(RE_STACK_TRACE_LINE.match(line))


def join_events(
    line_stream: Iterable[tuple[int, str]]
) -> Generator[Event, None, None]:
    """Consumes raw (line_no, line) stream and yields joined Events.
    
    Continues multi-line stack traces onto their parent Event.
    Maintains strictly O(1) memory by keeping at most 1 in-flight Event.
    """
    current_event: Optional[Event] = None

    for line_no, raw_line in line_stream:
        event, is_continuation = parse_line(line_no, raw_line)

        if is_continuation:
            if current_event is not None and is_stack_trace_line(raw_line):
                if len(current_event.stack) < MAX_STACK_FRAMES:
                    current_event.stack.append(raw_line.rstrip("\r\n"))
                    current_event.fmt = "trace"
            elif current_event is not None:
                # Continuation line that isn't a strict stack frame; append to stack if already in trace
                if current_event.fmt == "trace" and len(current_event.stack) < MAX_STACK_FRAMES:
                    current_event.stack.append(raw_line.rstrip("\r\n"))
            continue

        # A new base event arrived
        if current_event is not None:
            yield current_event
        current_event = event

    if current_event is not None:
        yield current_event
