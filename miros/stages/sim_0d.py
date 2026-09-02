"""sim_0d: run svZeroDSolver with the tuned boundary conditions."""
from ..io import zerod as Z
from ..io.rcrt import read_rcrt
from ..manifest import file_hash, value_hash
from ..ui import console


def inputs(case):
    return {'zerod': file_hash(case.zerod_json), 'rcrt': file_hash(case.rcrt),
            'cycles': value_hash(case.config.simulation.cycles)}


def outputs(case):
    return [case.zerod_tuned_json, case.results_0d / '0D_results.csv']


def run(case):
    names = case.outlet_names()
    cfg = Z.load(case.zerod_json)
    vmap = Z.VesselMap(cfg, names)
    cfg = Z.set_cycles(Z.apply_rcr(cfg, read_rcrt(case.rcrt), vmap), case.config.simulation.cycles)
    Z.save(cfg, case.zerod_tuned_json)
    df = Z.run(cfg)
    Z.results_to_csv(df, case.results_0d / '0D_results.csv')
    console.info("%d cycles, %d vessels, %d rows" % (case.config.simulation.cycles, df['name'].nunique(), len(df)))
    return outputs(case)
