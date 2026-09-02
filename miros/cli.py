"""
miros — command line.

    miros doctor                     check solvers and Python dependencies
    miros init DIR [--surface ...]   write a case.yaml (with detected caps)
    miros run DIR [--from S] [--until S] [--force]
    miros status DIR
    miros show caps DIR              labelled caps in a 3D window
    miros inflow edit DIR            draw the inflow waveform
"""
import argparse
import importlib
import os
import sys
from pathlib import Path

from . import __version__
from .ui import console


def cmd_doctor(args):
    from .solvers import find_onedsolver
    console.section("miros %s doctor" % __version__)
    console.info("python %s (%s)" % (sys.version.split()[0], sys.executable))
    rows = []
    for mod, note in [('numpy', ''), ('scipy', ''), ('pandas', ''), ('vtk', ''), ('pyvista', ''), ('matplotlib', ''),
                      ('yaml', 'PyYAML'), ('pwlf', 'ROM builder'), ('pyacvd', 'remesh'), ('tetgen', 'volume mesh'),
                      ('rich', 'optional, console'), ('pysvzerod', '0D solver'), ('seqseg', 'upstream segmentation')]:
        try:
            m = importlib.import_module(mod)
            rows.append((mod, 'ok', getattr(m, '__version__', ''), note))
        except Exception:
            rows.append((mod, 'MISSING', '', note))
    console.table(['package', 'status', 'version', 'note'], rows)
    exe = find_onedsolver()
    if exe:
        console.ok("OneDSolver: %s" % exe)
    else:
        console.warn("OneDSolver not found (set MIROS_ONEDSOLVER or solvers.onedsolver, or put it on PATH); "
                     "1D simulation will be unavailable")
    display = bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')) or not sys.platform.startswith('linux')
    console.info("display for interactive editors: %s" % ('yes' if display else 'no'))
    return 0


def _case_relative(path: Path, case_dir: Path) -> str:
    """Path as written into case.yaml: relative when inside/near the case, absolute otherwise."""
    rel = os.path.relpath(path, case_dir)
    return rel if rel.count('..') <= 2 else str(path)


def cmd_init(args):
    from .config import write_template
    from .geometry import caps as C
    d = Path(args.dir).resolve()
    d.mkdir(parents=True, exist_ok=True)
    yaml_path = d / 'case.yaml'
    if yaml_path.exists() and not args.force:
        console.error("%s exists (use --force to overwrite)" % yaml_path)
        return 1
    outlet_names = inlet = None
    surface = args.surface
    if surface:
        surface = _case_relative(Path(surface).resolve(), d)
        caps = C.make_caps(C.read_polydata(d / surface), inlet=args.inlet)
        ordered = [C.inlet_cap(caps)] + C.outlet_caps(caps)
        console.table(['cap', 'area', 'radius', 'role'],
                      [(c.name, '%.4f' % c.area, '%.3f' % c.radius, 'inlet' if c.is_inlet else 'outlet') for c in ordered])
        inlet = C.inlet_cap(caps).name
        outlet_names = [c.name for c in C.outlet_caps(caps)]
    inflow = _case_relative(Path(args.inflow).resolve(), d) if args.inflow else None
    write_template(yaml_path, name=args.name or d.name, surface=surface or 'input/surface.vtp', units=args.units,
                   inlet=inlet, inflow_file=inflow or 'input/inflow.flow',
                   inflow_source='file' if inflow else args.inflow_source, outlet_names=outlet_names,
                   onedsolver=args.onedsolver)
    console.ok("wrote %s" % yaml_path)
    steps = []
    if surface:
        steps.append("miros show caps %s        (which cap is which; set model.inlet if not the largest)" % d)
    if not inflow:
        steps.append("miros inflow edit %s      (draw one cardiac cycle)" % d)
    steps.append("edit %s: flow_split (percent per outlet) and pressure_mmHg" % yaml_path)
    steps.append("miros run %s" % d)
    console.info("next:")
    for k, s in enumerate(steps, 1):
        console.info("  %d. %s" % (k, s))
    return 0


def cmd_run(args):
    from .case import Case, StageError
    try:
        case = Case(args.dir)
        ran = case.run(from_stage=getattr(args, 'from'), until=args.until, force=args.force)
    except StageError as e:
        console.error(str(e))
        return 1
    console.section("done")
    console.info("stages run: %s" % (', '.join(ran) if ran else 'none (everything up to date)'))
    console.info("results: %s" % case.results)
    return 0


def cmd_status(args):
    from .case import Case
    case = Case(args.dir)
    console.table(['stage', 'state', 'detail'], case.status(), title=str(case.dir))
    return 0


def cmd_show(args):
    from .case import Case
    from .geometry import caps as C
    import pyvista as pv
    case = Case(args.dir)
    m = case.config.model
    surf = C.read_polydata(case.surface_work if case.surface_work.exists() else case.resolve(m.surface))
    caps = C.make_caps(surf, inlet=m.inlet, names=m.cap_names)
    pl = pv.Plotter(title='MIROS caps: %s' % case.config.name)
    pl.add_mesh(pv.wrap(surf), color='lightgray', opacity=0.5)
    for c in caps:
        pl.add_mesh(pv.wrap(c.polydata), color='crimson' if c.is_inlet else 'steelblue', opacity=0.9)
        pl.add_point_labels([c.centroid + 1.5 * c.radius * c.normal],
                            ['%s%s\n%.3f cm²' % (c.name, ' (inlet)' if c.is_inlet else '', c.area)],
                            font_size=12, point_size=0, shape_opacity=0.6)
    pl.show()
    return 0


def cmd_inflow(args):
    from .case import Case
    from .io.inflow import read_inflow, write_inflow
    from .ui.waveform_editor import edit_waveform
    case = Case(args.dir)
    i = case.config.inflow
    initial = None
    target = case.resolve(i.file) if i.file else case.dir / 'input' / 'inflow.flow'
    if target.exists():
        initial = read_inflow(target)
    t, q = edit_waveform(i.heart_rate_bpm, i.points_per_cycle, i.peak_flow_mL_s, initial=initial)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_inflow(t, q, target)
    tz = getattr(__import__('numpy'), 'trapezoid', None) or __import__('numpy').trapz
    console.ok("wrote %s (%d points, cycle %.3f s, mean %.1f mL/s, peak %.1f mL/s)" % (
        target, len(t), t[-1], tz(q, t) / (t[-1] - t[0]), q.max()))
    console.info("`miros run %s` will use it (the inflow stage is now stale)" % case.dir)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='miros', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--version', action='version', version='miros ' + __version__)
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('doctor', help='check solvers and dependencies').set_defaults(fn=cmd_doctor)

    p = sub.add_parser('init', help='create a case directory with a case.yaml')
    p.add_argument('dir')
    p.add_argument('--surface', help='open (clipped) surface .vtp/.stl')
    p.add_argument('--inflow', help='inflow .flow file (one cycle)')
    p.add_argument('--inflow-source', default='file', choices=['file', 'gui'])
    p.add_argument('--units', default='cm', choices=['cm', 'mm'])
    p.add_argument('--inlet', help='cap name to use as inlet (default: largest)')
    p.add_argument('--name')
    p.add_argument('--onedsolver', help='path to the OneDSolver executable')
    p.add_argument('--force', action='store_true')
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser('run', help='run stale stages')
    p.add_argument('dir')
    p.add_argument('--from', dest='from', help='rerun from this stage onward')
    p.add_argument('--until', help='stop after this stage')
    p.add_argument('--force', action='store_true', help='rerun every stage')
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser('status', help='which stages are up to date')
    p.add_argument('dir')
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser('show', help='3D view')
    p.add_argument('what', choices=['caps'])
    p.add_argument('dir')
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser('inflow', help='inflow waveform tools')
    p.add_argument('what', choices=['edit'])
    p.add_argument('dir')
    p.set_defaults(fn=cmd_inflow)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
