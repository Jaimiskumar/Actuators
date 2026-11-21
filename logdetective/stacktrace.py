"""Stack trace detection and multi-line event joining."""

import re
from typing import Generator, Iterable, Optional

from logdetective.contract import Event
from logdetective.parser import RE_STACK_TRACE_LINE, is_stack_trace_line, parse_line

# Cap stored stack frames per event to keep memory flat O(1)
MAX_STACK_FRAMES = 50


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
