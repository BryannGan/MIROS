"""rom_model: centerlines and the 0D model (with placeholder RCRs) from the prepared surface."""
from ..manifest import file_hash, value_hash
from ..rom_model import Physics, RomSettings, build_rom_model
from ..ui import console


def _solver_name(name: str) -> str:
    """OneDSolver's MODEL card is one whitespace-free token."""
    clean = ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in str(name)).strip('_')
    return clean or 'model'


def settings(case) -> RomSettings:
    s = case.config.simulation
    mat = s.material
    return RomSettings(cycles=s.cycles, seg_min_num=s.seg_min_num, element_size=s.element_size,
                       save_data_freq=s.save_data_freq, model_name=_solver_name(case.config.name),
                       physics=Physics(density=s.density, viscosity=s.viscosity,
                                       olufsen_k1=mat.olufsen_k1, olufsen_k2=mat.olufsen_k2,
                                       olufsen_k3=mat.olufsen_k3, olufsen_exponent=mat.olufsen_exponent,
                                       olufsen_pressure=mat.olufsen_pressure, linear_ehr=mat.linear_ehr,
                                       linear_pressure=mat.linear_pressure))


def inputs(case):
    return {'surface': file_hash(case.surface_work), 'caps': file_hash(case.caps_json),
            'inflow': file_hash(case.inflow_work),
            'simulation': value_hash({k: v for k, v in case.config.section('simulation').items()
                                      if k not in ('run_1d', 'max_1d_retries', 'save_data_freq')})}


def outputs(case):
    return [case.centerlines, case.outlets_file, case.zerod_json]


def run(case):
    info = case.caps_info()
    r = build_rom_model(case.surface_work, case.work, case.inflow_work, inlet=info['inlet'],
                        outlet_names=info['names_by_area'], settings=settings(case),
                        write_0d=True, write_1d=False, verbose=True)
    if r.outlet_names != info['outlets']:
        raise RuntimeError("outlet order changed between preprocess and rom_model: %s vs %s" %
                           (info['outlets'], r.outlet_names))
    console.info("outlets: %s" % ', '.join(r.outlet_names))
    return outputs(case)
