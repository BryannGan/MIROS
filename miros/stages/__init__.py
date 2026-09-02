"""
Pipeline stages. Each stage declares what it reads (hashed into the
manifest), what it writes, whether it is enabled by the case config, and
how to run it. Order matters and is the order below.
"""
from dataclasses import dataclass
from typing import Callable, Dict, List

from . import (extract_0d, extract_1d, inflow, preprocess, rom_model, sim_0d, sim_1d, tune,
               volume_mesh)


@dataclass
class Stage:
    name: str
    inputs: Callable                      # case -> {label: hash}
    outputs: Callable                     # case -> [Path]
    run: Callable                         # case -> [Path]
    enabled: Callable = lambda case: True
    disabled_reason: Callable = lambda case: ''


REGISTRY: List[Stage] = [
    Stage('preprocess', preprocess.inputs, preprocess.outputs, preprocess.run),
    Stage('inflow', inflow.inputs, inflow.outputs, inflow.run),
    Stage('rom_model', rom_model.inputs, rom_model.outputs, rom_model.run),
    Stage('tune', tune.inputs, tune.outputs, tune.run),
    Stage('sim_0d', sim_0d.inputs, sim_0d.outputs, sim_0d.run),
    Stage('extract_0d', extract_0d.inputs, extract_0d.outputs, extract_0d.run),
    Stage('volume_mesh', volume_mesh.inputs, volume_mesh.outputs, volume_mesh.run,
          volume_mesh.enabled, volume_mesh.disabled_reason),
    Stage('sim_1d', sim_1d.inputs, sim_1d.outputs, sim_1d.run, sim_1d.enabled, sim_1d.disabled_reason),
    Stage('extract_1d', extract_1d.inputs, extract_1d.outputs, extract_1d.run, sim_1d.enabled, sim_1d.disabled_reason),
]
