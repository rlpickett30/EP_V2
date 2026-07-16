# Validation Status

## Completed without hardware

The entire source tree passes Python bytecode compilation.

The included `simulate_demo.py` was executed end to end with four synthetic USB microphones having different stream start times and clock errors:

| Node | Injected clock error | Fitted effective rate |
|---|---:|---:|
| node_01 | +35 ppm | 48001.687035 Hz |
| node_02 | -22 ppm | 47998.944631 Hz |
| node_03 | +8 ppm | 48000.377486 Hz |
| node_04 | -47 ppm | 47997.756619 Hz |

After fitting and time-grid correction, the synthetic equal-radius event had an arrival spread of approximately **21.9 microseconds**. The fixed-height localization solved approximately:

```text
x = -0.0012 m
y = -0.0037 m
z =  1.0000 m
```

for a simulated source at `(0, 0, 1)`.

The synthetic test validates the data flow, model fitting, window extraction, interpolation, GCC-PHAT comparison, reporting, and localization interfaces.

## Not yet validated

No claim is made yet about real Raspberry Pi USB microphone absolute timing. Hardware testing must determine:

- Whether the selected PortAudio/ALSA backend provides meaningful ADC timestamps.
- The repeatability of the physical ADC-to-PPS offset.
- The effect of USB buffering and stream reopening.
- Clock drift during thermal warm-up.
- Real pipe-strike arrival spread before and after correction.

Those are the purpose of the standalone experiment.
