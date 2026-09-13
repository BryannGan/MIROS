# Boundary-condition tuning

With `boundary_conditions.mode: tune`, MIROS finds RCR (three-element Windkessel) parameters for
every outlet so that the 0D model reproduces the flow distribution and the pressure you asked
for. With `mode: file` it takes your own `rcrt.dat` instead.

1. **Analytic start, no solves.** From the mean inflow and the target mean pressure the network
   resistance follows; each outlet gets its share according to the flow split, minus the
   resistance of the vessels on its path. The total compliance comes from the diastolic decay
   time constant and is distributed in proportion to flow, so every outlet has the same RC time
   constant. The proximal fraction Rp/(Rp+Rd) starts at the smaller of `rp_fraction` and what the
   target pulse pressure allows.
2. **Fixed-point loop, a few 0D solves.** Each iteration measures the achieved splits and the
   pressure waveform and moves four knobs: the split scales each resistance, the level moves all
   resistances by the ratio of target to measured pressure, the pulse moves the proximal fraction
   with compliance taking over at a bound, and the shape moves compliance by the ratio of
   (mean − diastolic) to pulse pressure. The best iterate is kept; the loop stops on `tolerance_pct`,
   after `max_iterations`, or when four iterations fail to improve.

On the example the flow splits are within 5 % after the first solve and exact by the third; the
whole thing takes a few seconds. `work/tuning_report.json` records every iteration.

## Reachable targets

The pulse pressure at the **inlet** has a floor: part of it is the inertial and viscous pressure
drop along the vessels themselves, which depends on the inflow waveform and the geometry, not on
the outlets. With a waveform that swings from −120 to +610 mL/s, 120/80 at the inlet of the
example is not attainable; the best trade-off is about 129/75, which is why the example targets
130/75. When a target is out of reach the tuner keeps its best iterate, stops, and says why.
Target an outlet instead (`pressure_mmHg.at: cap_2`), use a smoother waveform, or accept the
values.

Outlet mean pressures come out nearly identical to one another. That is physics, not a defect:
the pressure drops along the paths are a fraction of a mmHg.

## Settings

```yaml
boundary_conditions:
  mode: tune                    # tune | file
  file: null                    # an rcrt.dat, for mode: file
  flow_split: {cap_2: 50, cap_3: 20, cap_4: 30}   # percent per outlet, sums to 100
  pressure_mmHg: {at: inlet, systolic: 130, diastolic: 75, mean: null}
  tolerance_pct: 5              # done when every error is within this
  max_iterations: 12
  rp_fraction: 0.09             # Rp / (Rp + Rd) to start from
  tuning_cycles: 5              # 0D cycles per tuning solve; the last is measured
```
