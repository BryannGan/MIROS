"""
The one place console output is formatted. Uses rich when installed and
the output is a terminal; plain text otherwise (or when set_plain(True) is
called, e.g. by the GUI, which captures the output into a text pane).
"""
import sys
from typing import Iterable, Optional, Sequence

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


def _rich():
    return _rich_console if (_rich_console is not None and not PLAIN) else None


def section(title: str) -> None:
    c = _rich()
    if c:
        c.rule("[bold]%s[/bold]" % title)
    else:
        print("\n" + "=" * 70 + "\n  " + title + "\n" + "=" * 70)


def info(msg: str) -> None:
    print("  " + msg)


def ok(msg: str) -> None:
    c = _rich()
    if c:
        c.print("  [green]OK[/green] " + msg)
    else:
        print("  OK " + msg)


def warn(msg: str) -> None:
    c = _rich()
    if c:
        c.print("  [yellow]WARNING[/yellow] " + msg)
    else:
        print("  WARNING " + msg)


def error(msg: str) -> None:
    c = _rich()
    if c:
        c.print("  [red]ERROR[/red] " + msg)
    else:
        print("  ERROR " + msg, file=sys.stderr)


def table(columns: Sequence[str], rows: Iterable[Sequence], title: Optional[str] = None) -> None:
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
