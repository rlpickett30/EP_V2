# System Design

## Measurement objective

For each Raspberry Pi node, estimate the mapping

```text
GPS UTC nanoseconds = origin_utc + (audio_sample - origin_sample) × ns_per_sample
```

and preserve enough raw evidence to determine whether that mapping is physically accurate, not merely mathematically smooth.

## Independent time domains

The capture process observes three clocks:

1. **USB microphone sample clock** — represented by the continuous sample counter.
2. **PortAudio stream clock** — represented by `inputBufferAdcTime` and `currentTime`.
3. **ZED-F9P GPS/PPS clock** — represented by LinuxPPS assertions paired with valid RMC UTC seconds.

The software first fits audio sample index to the estimated ADC monotonic time. It then evaluates where each PPS edge falls on that sample axis. Finally, it fits those PPS/sample anchors to UTC.

## Why the microphone stream remains open

Repeatedly opening a USB stream creates a new, potentially variable startup delay. A continuously open stream keeps one sample counter and one free-running oscillator. Analysis windows become slices from a measured timeline rather than separate recordings with unrelated beginnings.

## Raw evidence

The system never overwrites the continuous capture. Each session retains:

- Numbered source WAV chunks.
- Per-callback sample indices and PortAudio timestamps.
- Raw LinuxPPS observations.
- GNSS RMC sentences.
- Paired PPS/UTC anchors.
- Stream continuity events.
- CPU temperature samples.
- Fitted clock model and residuals.

## Correction

A corrected window is generated on an exact target UTC grid. For every desired target sample time, the fitted PPS anchors are used to determine the corresponding fractional source sample position. The signal is interpolated at those positions.

This corrects:

- Nominal sample-rate error.
- Linear crystal drift.
- Slowly changing drift represented by neighboring PPS anchors.
- Different stream start times across nodes.

It does not automatically prove or remove:

- A hidden fixed USB/driver latency not represented by PortAudio timestamps.
- A latency that changes every time the stream opens.
- Dropped samples that were not detected.
- Acoustic path differences, reflections, or microphone group delay.

The equal-radius center-pipe experiment is therefore an essential physical calibration.

## Quality states

`PASS`, `WARN`, and `FAIL` describe model residuals. A model that depends on system-realtime fallback is downgraded to `WARN`, even when its fit residual is small. GNSS RMC-paired PPS anchors are preferred.

A low residual means the observed timestamps agree with one another. It does not independently guarantee that the actual microphone diaphragm/ADC sample is aligned to PPS at the same accuracy.

## Expected EnviroPulse boundary later

The node microphone subsystem would own:

- Continuous capture.
- Sample counting.
- PPS/audio clock evidence.
- Buffering and raw UTC-window extraction.

The server TDOA subsystem would own:

- Clock-model validation.
- Common-time-grid correction.
- Cross-node feature alignment.
- ARM refinement.
- TDOA localization and uncertainty.
