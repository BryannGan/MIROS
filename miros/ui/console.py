"""
The one place console output is formatted. Uses rich when installed, plain
text otherwise, so nothing else in MIROS needs to know which.
"""
import sys
from typing import Iterable, List, Optional, Sequence

try:
    from rich.console import Console as _RichConsole
    from rich.table import Table as _RichTable
    _console = _RichConsole(highlight=False)
except Exception:          # rich not installed
    _console = None


def section(title: str) -> None:
    if _console:
        _console.rule("[bold]%s[/bold]" % title)
    else:
        print("\n" + "=" * 70 + "\n  " + title + "\n" + "=" * 70)


def info(msg: str) -> None:
    print("  " + msg)


def ok(msg: str) -> None:
    if _console:
        _console.print("  [green]OK[/green] " + msg)
    else:
        print("  OK " + msg)


def warn(msg: str) -> None:
    if _console:
        _console.print("  [yellow]WARNING[/yellow] " + msg)
    else:
        print("  WARNING " + msg)


def error(msg: str) -> None:
    if _console:
        _console.print("  [red]ERROR[/red] " + msg)
    else:
        print("  ERROR " + msg, file=sys.stderr)


def table(columns: Sequence[str], rows: Iterable[Sequence], title: Optional[str] = None) -> None:
    rows = [[str(c) for c in r] for r in rows]
    if _console:
        t = _RichTable(title=title, show_edge=False, pad_edge=False)
        for c in columns:
            t.add_column(str(c))
        for r in rows:
            t.add_row(*r)
        _console.print(t)
        return
    widths = [max(len(str(c)), *(len(r[i]) for r in rows)) if rows else len(str(c)) for i, c in enumerate(columns)]
    if title:
        print("  " + title)
    print("  " + "  ".join(str(c).ljust(w) for c, w in zip(columns, widths)))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print("  " + "  ".join(v.ljust(w) for v, w in zip(r, widths)))
