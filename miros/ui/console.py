"""
The one place console output is formatted. Uses rich when installed and
the output is a terminal; plain text otherwise (or when set_plain(True) is
called, e.g. by the GUI, which captures the output into a text pane).
"""
import sys
from typing import Callable, Iterable, Optional, Sequence

try:
    from rich.console import Console as _RichConsole
    from rich.table import Table as _RichTable
    _rich_console = _RichConsole(highlight=False)
except Exception:          # rich not installed
    _rich_console = None

PLAIN = False


def set_plain(flag: bool) -> None:
    """Force plain text (no colours, no box drawing)."""
    global PLAIN
    PLAIN = bool(flag)


INTERACTIVE = True


def set_interactive(flag: bool) -> None:
    """False when no one can answer a dialog (GUI worker thread, CI): stages must not block."""
    global INTERACTIVE
    INTERACTIVE = bool(flag)


def _rich():
    return _rich_console if (_rich_console is not None and not PLAIN) else None


# ---- progress of the running step -----------------------------------------
# A long stage reports where it is (SeqSeg's step counter, for one). The GUI
# installs a handler and draws a bar; on a terminal the line updates in
# place; piped, a line goes out about every tenth so a log stays readable.

_progress_handler: Optional[Callable] = None
_progress_on_line = False          # a \r-updated line is on the terminal now
_progress_last_bucket = None


def set_progress_handler(fn: Optional[Callable]) -> None:
    """fn(done, total, text) receives every report; None restores printing."""
    global _progress_handler
    _progress_handler = fn


def progress(done: Optional[float], total: Optional[float] = None, text: str = '') -> None:
    """
    Where the running step is: `done` of `total` (None when the total is not
    known) and a short text. done=None clears the report.
    """
    global _progress_on_line, _progress_last_bucket
    if _progress_handler is not None:
        _progress_handler(done, total, text)
        return
    if done is None:
        _end_progress_line()
        _progress_last_bucket = None
        return
    line = text or ('%s of %s' % (done, total) if total else str(done))
    if getattr(sys.stdout, 'isatty', lambda: False)():
        print('\r  ' + line.ljust(78)[:78], end='', flush=True)
        _progress_on_line = True
        return
    bucket = int(10.0 * done / total) if total else int(done) // 25
    if bucket != _progress_last_bucket:
        _progress_last_bucket = bucket
        print('  ' + line)


def _end_progress_line() -> None:
    global _progress_on_line
    if _progress_on_line:
        print()
        _progress_on_line = False


def section(title: str) -> None:
    _end_progress_line()
    c = _rich()
    if c:
        c.rule("[bold]%s[/bold]" % title)
    else:
        print("\n" + "=" * 70 + "\n  " + title + "\n" + "=" * 70)


def info(msg: str) -> None:
    _end_progress_line()
    print("  " + msg)


def ok(msg: str) -> None:
    _end_progress_line()
    c = _rich()
    if c:
        c.print("  [green]OK[/green] " + msg)
    else:
        print("  OK " + msg)


def warn(msg: str) -> None:
    _end_progress_line()
    c = _rich()
    if c:
        c.print("  [yellow]WARNING[/yellow] " + msg)
    else:
        print("  WARNING " + msg)


def error(msg: str) -> None:
    _end_progress_line()
    c = _rich()
    if c:
        c.print("  [red]ERROR[/red] " + msg)
    else:
        print("  ERROR " + msg, file=sys.stderr)


def table(columns: Sequence[str], rows: Iterable[Sequence], title: Optional[str] = None) -> None:
    _end_progress_line()
    rows = [[str(c) for c in r] for r in rows]
    c = _rich()
    if c:
        t = _RichTable(title=title, show_edge=False, pad_edge=False)
        for col in columns:
            t.add_column(str(col))
        for r in rows:
            t.add_row(*r)
        c.print(t)
        return
    widths = [max(len(str(col)), *(len(r[i]) for r in rows)) if rows else len(str(col)) for i, col in enumerate(columns)]
    if title:
        print("  " + title)
    print("  " + "  ".join(str(col).ljust(w) for col, w in zip(columns, widths)))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print("  " + "  ".join(v.ljust(w) for v, w in zip(r, widths)))
