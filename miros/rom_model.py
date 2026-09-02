"""
Build reduced-order (0D and 1D) models from an open vessel surface, with no
SimVascular installation:

    surface (open at inlet/outlets)
      -> caps                        miros.geometry.caps
      -> centerlines                 miros.geometry.centerlines (Voronoi + Dijkstra)
      -> annotated centerline tree   miros.geometry.centerline_tree
      -> 0D JSON / 1D solver input   miros.rom (vendored SimVascular ROM builder)

`build_rom_model` is the function; the module is also runnable:

    python -m miros.rom_model --surface model.vtp --inflow inflow.flow --out case/
"""
import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .geometry import caps as C
from .geometry.centerlines import compute_centerlines
from .geometry.centerline_tree import annotate, write_outlet_names
from .io import inflow as IO_inflow
from .io.rcrt import write_default_rcrt
from .rom.centerlines import Centerlines
from .rom.manage import get_logger_name
from .rom.mesh import Mesh
from .rom.parameters import Parameters


@dataclass
class Physics:
    density: float = 1.06
    viscosity: float = 0.04
    olufsen_k1: float = 0.0
    olufsen_k2: float = -22.5267
    olufsen_k3: float = 1.0e7
    olufsen_exponent: float = 1.0
    olufsen_pressure: float = 0.0
    linear_ehr: float = 1e7
    linear_pressure: float = 0.0


@dataclass
class RomSettings:
    cycles: int = 8
    seg_min_num: int = 4
    seg_size_adaptive_1d: bool = True
    element_size: float = 0.01
    save_data_freq: int = 5
    model_name: str = 'model'
    physics: Physics = field(default_factory=Physics)


@dataclass
class RomOutputs:
    out_dir: Path
    centerlines: Path
    outlets_file: Path
    boundary_dir: Path
    rcrt: Path
    zerod_json: Optional[Path]
    oned_input: Optional[Path]
    outlet_names: List[str]
    inlet_name: str
    cap_areas: Dict[str, float]


def rom_parameters(out_dir: Path, boundary_dir: Path, outlets_file: Path, rcrt: Path,
                   inflow: Path, s: RomSettings, model_order: int) -> Parameters:
    """Parameters for the vendored ROM builder (model_order 0 or 1)."""
    P = Parameters()
    P.output_directory = str(out_dir)
    P.boundary_surfaces_dir = str(boundary_dir)
    P.inlet_face_input_file = 'inlet.vtp'
    P.inflow_input_file = str(inflow)
    P.model_name = s.model_name
    P.outflow_bc_type = 'rcr'
    P.uniform_bc = False
    P.outlet_face_names_file = str(outlets_file)
    P.outflow_bc_file = str(rcrt)
    P.model_order = model_order
    P.seg_min_num = s.seg_min_num
    P.seg_size_adaptive = s.seg_size_adaptive_1d if model_order == 1 else False
    P.element_size = s.element_size
    P.save_data_freq = s.save_data_freq
    P.time_step = IO_inflow.time_step(inflow)
    P.num_time_steps = IO_inflow.num_time_steps(inflow, s.cycles)
    ph = s.physics
    P.density = ph.density
    P.viscosity = ph.viscosity
    P.olufsen_material_k1 = ph.olufsen_k1
    P.olufsen_material_k2 = ph.olufsen_k2
    P.olufsen_material_k3 = ph.olufsen_k3
    P.olufsen_material_exponent = ph.olufsen_exponent
    P.olufsen_material_pressure = ph.olufsen_pressure
    P.linear_material_ehr = ph.linear_ehr
    P.linear_material_pressure = ph.linear_pressure
    if model_order == 0:
        P.solver_output_file = '0D_solver_input.json'
    else:
        P.solver_output_file = '1D_solver_input.in'
        P.mesh_output_file = '1d_model.vtp'
    return P


def build_rom_model(surface, out_dir, inflow, inlet: Optional[str] = None,
                    outlet_names: Optional[Sequence[str]] = None, rcrt: Optional[str] = None,
                    settings: Optional[RomSettings] = None, write_0d: bool = True, write_1d: bool = True,
                    verbose: bool = True) -> RomOutputs:
    """
    surface:       open surface file (.vtp/.stl/.ply), clipped at inlet and outlets
    out_dir:       where everything is written
    inflow:        .flow file (one cycle, time and flow)
    inlet:         cap name to use as inlet (default: largest cap)
    outlet_names:  names for the caps in decreasing-area order (default cap_1..cap_n)
    rcrt:          existing rcrt.dat keyed by outlet name; if None a default template is written
    """
    s = settings or RomSettings()
    log = print if verbose else (lambda *a, **k: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # the vendored ROM code logs through this name; keep it quiet unless asked
    logging.getLogger(get_logger_name()).setLevel(logging.INFO if verbose else logging.WARNING)

    log("Caps")
    surf = C.read_polydata(surface)
    caps = C.make_caps(surf, inlet=inlet, names=outlet_names)
    caps_ordered = [C.inlet_cap(caps)] + C.outlet_caps(caps)
    log(C.cap_summary(caps_ordered))

    log("Centerlines")
    tree = compute_centerlines(surf, caps_ordered, verbose=verbose)
    closed = C.close_surface(surf, caps_ordered)
    cl_pd = annotate(tree, closed, verbose=verbose)
    cl_path = out_dir / 'extracted_centerlines.vtp'
    C.write_polydata(cl_path, cl_pd)
    outlets_file = out_dir / 'centerlines_outlets.dat'
    write_outlet_names(tree.outlet_names, outlets_file)
    boundary_dir = out_dir / 'caps_and_wall'
    C.write_boundary_dir(surf, caps_ordered, boundary_dir)

    # the ROM reader requires the file to be called rcrt.dat next to the outputs
    rcrt_path = out_dir / 'rcrt.dat'
    if rcrt is None:
        if not rcrt_path.exists():        # never clobber tuned or user-provided values
            write_default_rcrt(tree.outlet_names, rcrt_path)
            log("Wrote default rcrt.dat (placeholder values) for %d outlets" % len(tree.outlet_names))
    elif Path(rcrt).resolve() != rcrt_path.resolve():
        rcrt_path.write_bytes(Path(rcrt).read_bytes())

    zerod = oned = None
    centerlines = Centerlines.from_polydata(cl_pd, tree.outlet_names)
    if write_0d:
        log("0D model")
        P = rom_parameters(out_dir, boundary_dir, outlets_file, rcrt_path, Path(inflow), s, 0)
        if not Mesh().generate(P, centerlines):
            raise RuntimeError("0D model generation failed")
        zerod = out_dir / P.solver_output_file
    if write_1d:
        log("1D model")
        P = rom_parameters(out_dir, boundary_dir, outlets_file, rcrt_path, Path(inflow), s, 1)
        if not Mesh().generate(P, centerlines):
            raise RuntimeError("1D model generation failed")
        oned = out_dir / P.solver_output_file

    return RomOutputs(out_dir=out_dir, centerlines=cl_path, outlets_file=outlets_file,
                      boundary_dir=boundary_dir, rcrt=rcrt_path, zerod_json=zerod, oned_input=oned,
                      outlet_names=list(tree.outlet_names), inlet_name=tree.inlet_name,
                      cap_areas={c.name: c.area for c in caps_ordered})


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build 0D/1D reduced-order models from an open vessel surface.")
    ap.add_argument('--surface', required=True)
    ap.add_argument('--inflow', required=True, help='.flow file (time, flow) for one cycle')
    ap.add_argument('--out', required=True)
    ap.add_argument('--inlet', default=None, help='cap name to use as inlet (default: largest)')
    ap.add_argument('--rcrt', default=None, help='existing rcrt.dat keyed by outlet name')
    ap.add_argument('--cycles', type=int, default=8)
    ap.add_argument('--seg-min-num', type=int, default=4)
    ap.add_argument('--no-1d', action='store_true')
    ap.add_argument('--no-0d', action='store_true')
    a = ap.parse_args(argv)
    s = RomSettings(cycles=a.cycles, seg_min_num=a.seg_min_num)
    r = build_rom_model(a.surface, a.out, a.inflow, inlet=a.inlet, rcrt=a.rcrt, settings=s,
                        write_0d=not a.no_0d, write_1d=not a.no_1d)
    print("\nOutputs in %s" % r.out_dir)
    for k in ('centerlines', 'outlets_file', 'boundary_dir', 'rcrt', 'zerod_json', 'oned_input'):
        v = getattr(r, k)
        if v is not None:
            print("  %-14s %s" % (k, v))


if __name__ == '__main__':
    main()
