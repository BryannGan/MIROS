"""extract_0d: last-cycle statistics per outlet and plots from the 0D results."""
import json

import numpy as np
import pandas as pd

from ..io import inflow as IO
from ..io import zerod as Z
from ..manifest import file_hash, value_hash
from ..ui import console


def inputs(case):
    return {'results': file_hash(case.results_0d / '0D_results.csv'), 'zerod': file_hash(case.zerod_tuned_json),
            'outputs': value_hash(case.config.section('outputs'))}


def outputs(case):
    return [case.results_0d / '0D_statistics.csv', case.results_0d / '0D_summary.json']


def run(case):
    names = case.outlet_names()
    cfg = Z.load(case.zerod_tuned_json)
    vmap = Z.VesselMap(cfg, names)
    df = pd.read_csv(case.results_0d / '0D_results.csv')
    T = IO.cycle_duration(case.inflow_work)
    last = Z.last_cycle(df, T)

    rows, stats = [], []
    for cap in names:
        v = vmap.outlet_vessel[cap]
        seg = last[last['name'] == v]
        p = seg['pressure_out'].to_numpy() / Z.MMHG_TO_CGS
        q = seg['flow_out'].to_numpy()
        stats.append({'outlet': cap, 'vessel': v, 'mean_flow_mL_s': float(q.mean()), 'max_flow_mL_s': float(q.max()),
                      'min_flow_mL_s': float(q.min()), 'systolic_mmHg': float(p.max()),
                      'diastolic_mmHg': float(p.min()), 'mean_pressure_mmHg': float(p.mean())})
    tot = sum(abs(s['mean_flow_mL_s']) for s in stats)
    for s in stats:
        s['flow_split_pct'] = 100.0 * abs(s['mean_flow_mL_s']) / tot if tot > 0 else 0.0
    inlet = Z.pressure_at(last, vmap, 'inlet')
    q_in = last.loc[last['name'] == vmap.inlet_vessel, 'flow_in'].to_numpy()

    case.results_0d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(stats).to_csv(case.results_0d / '0D_statistics.csv', index=False)
    summary = {'cycle_duration_s': T, 'inlet': {'vessel': vmap.inlet_vessel, 'mean_flow_mL_s': float(q_in.mean()),
                                                'pressure_mmHg': inlet}, 'outlets': stats}
    (case.results_0d / '0D_summary.json').write_text(json.dumps(summary, indent=2))

    console.table(['outlet', 'split %', 'mean Q [mL/s]', 'sys', 'dia', 'mean [mmHg]'],
                  [(s['outlet'], '%.1f' % s['flow_split_pct'], '%.1f' % s['mean_flow_mL_s'], '%.1f' % s['systolic_mmHg'],
                    '%.1f' % s['diastolic_mmHg'], '%.1f' % s['mean_pressure_mmHg']) for s in stats])
    console.info("inlet pressure %.1f / %.1f (mean %.1f) mmHg" % (inlet['systolic'], inlet['diastolic'], inlet['mean']))

    if case.config.outputs.plots:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        n = len(names)
        fig, axes = plt.subplots(n, 2, figsize=(12, 2.6 * n), squeeze=False)
        for i, cap in enumerate(names):
            seg = last[last['name'] == vmap.outlet_vessel[cap]]
            tt = seg['time'].to_numpy() - seg['time'].min()
            axes[i, 0].plot(tt, seg['flow_out'], lw=1.4)
            axes[i, 0].set_ylabel('Q [mL/s]'); axes[i, 0].set_title(cap + ' flow'); axes[i, 0].grid(alpha=.3)
            axes[i, 1].plot(tt, seg['pressure_out'] / Z.MMHG_TO_CGS, lw=1.4, color='C3')
            axes[i, 1].set_ylabel('P [mmHg]'); axes[i, 1].set_title(cap + ' pressure'); axes[i, 1].grid(alpha=.3)
        axes[-1, 0].set_xlabel('t [s]'); axes[-1, 1].set_xlabel('t [s]')
        fig.tight_layout()
        fig.savefig(case.results_0d / '0D_outlets.png', dpi=130)
        plt.close(fig)
        console.info("plot: %s" % (case.results_0d / '0D_outlets.png'))
    return outputs(case)
