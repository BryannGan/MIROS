"""tune: RCR boundary conditions from flow splits and pressure targets, or from a given rcrt.dat."""
import json

from ..config import ConfigError
from ..io import inflow as IO
from ..io import zerod as Z
from ..io.rcrt import read_rcrt, write_rcrt
from ..manifest import file_hash, value_hash
from ..tuning.windkessel import Targets, tune
from ..ui import console


def inputs(case):
    bc = case.config.boundary_conditions
    d = {'zerod': file_hash(case.zerod_json), 'inflow': file_hash(case.inflow_work),
         'bc': value_hash(case.config.section('boundary_conditions'))}
    if bc.mode == 'file':
        d['file'] = file_hash(case.resolve(bc.file))
    return d


def outputs(case):
    return [case.rcrt]


def run(case):
    bc = case.config.boundary_conditions
    names = case.outlet_names()
    if bc.mode == 'file':
        rcr = read_rcrt(case.resolve(bc.file))
        missing = [n for n in names if n not in rcr]
        if missing:
            raise ConfigError("%s has no entry for outlet(s) %s; outlets are %s" % (bc.file, missing, names))
        write_rcrt(rcr, names, case.rcrt)
        console.info("using boundary conditions from %s" % bc.file)
        if case.tuning_report.exists():
            case.tuning_report.unlink()
        return outputs(case)

    if not bc.flow_split:
        raise ConfigError("boundary_conditions.flow_split is empty. The outlets are known now (%s): set the flow "
                          "shares in `miros setup` or in case.yaml, then run again." % ', '.join(names))
    unknown = sorted(set(bc.flow_split) - set(names))
    if unknown:
        raise ConfigError("flow_split names %s are not outlets; outlets are %s" % (unknown, names))
    missing = [n for n in names if n not in bc.flow_split]
    if missing:
        raise ConfigError("flow_split is missing outlet(s) %s" % missing)
    p = bc.pressure_mmHg
    if p.at != 'inlet' and p.at not in names:
        raise ConfigError("pressure_mmHg.at must be 'inlet' or one of %s" % names)
    targets = Targets(flow_split={k: bc.flow_split[k] / 100.0 for k in names}, at=p.at,
                      systolic=p.systolic, diastolic=p.diastolic, mean=p.mean)
    cfg = Z.load(case.zerod_json)
    t, q = IO.read_inflow(case.inflow_work)
    console.info("targets: splits %s; %s %g/%g%s mmHg; tolerance %g%%" % (
        ' '.join('%s=%g' % (k, v) for k, v in bc.flow_split.items()), p.at, p.systolic, p.diastolic,
        ('/%g' % p.mean) if p.mean is not None else '', bc.tolerance_pct))
    rcr, report = tune(cfg, names, targets, t, q, float(t[-1]), tolerance_pct=bc.tolerance_pct,
                       max_iterations=bc.max_iterations, rp_fraction=bc.rp_fraction, cycles=bc.tuning_cycles,
                       log=console.info)
    write_rcrt(rcr, names, case.rcrt)
    case.tuning_report.write_text(json.dumps(report.as_dict(), indent=2, default=float))

    rows = []
    for n in names:
        rows.append((n, '%.1f' % (100 * targets.flow_split[n]), '%.1f' % (100 * report.achieved['flow_split'][n]),
                     '%.1f' % rcr[n]['Rp'], '%.3g' % rcr[n]['C'], '%.1f' % rcr[n]['Rd']))
    console.table(['outlet', 'target %', 'achieved %', 'Rp', 'C', 'Rd'], rows)
    a = report.achieved['pressure']
    console.info("pressure at %s: %.1f / %.1f (mean %.1f) mmHg, target %g / %g%s" % (
        p.at, a['systolic'], a['diastolic'], a['mean'], p.systolic, p.diastolic,
        (' / %g' % p.mean) if p.mean is not None else ''))
    if report.converged:
        console.ok("converged in %d solves (%.1f s)" % (report.solves, report.seconds))
    else:
        worst = max(abs(v) for v in report.errors_pct.values())
        console.warn("not within %g%% (%s after %d iterations, best worst-error %.1f%%); using the best "
                     "iterate; see %s" % (bc.tolerance_pct, report.stop_reason, report.iterations, worst,
                                          case.tuning_report.name))
        if report.note:
            console.warn(report.note)
    return outputs(case)
