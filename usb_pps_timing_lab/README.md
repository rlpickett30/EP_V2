# USB + PPS Precision Audio Timing Laboratory

This is a standalone research system for testing whether inexpensive USB microphones on Raspberry Pi 4 nodes can be placed onto a shared GPS time axis using a ZED-F9P PPS reference.

It is intentionally independent of EnviroPulse. Nothing here imports the EnviroPulse event bus, node configuration, BirdNET, or TDOA production code.

## What the system does

1. Opens one USB microphone once and keeps the stream running continuously.
2. Writes continuous audio into numbered WAV chunks without resetting the microphone clock.
3. Counts every audio frame received from PortAudio.
4. Records PortAudio's `inputBufferAdcTime` and `currentTime` for every callback block.
5. Records LinuxPPS assertions from `/sys/class/pps/pps0/assert`.
6. Optionally reads ZED-F9P RMC sentences from `/dev/ttyACM0` and pairs each valid UTC second to the most recent PPS edge.
7. Fits the free-running USB audio sample clock to the PPS/GPS time axis.
8. Extracts a requested UTC interval from the continuous session.
9. Preserves the nearest-sample raw WAV.
10. Produces a derived WAV warped onto an exact 48 kHz GPS-time grid.
11. Compares pipe-strike arrival times across corrected node recordings using band-limited GCC-PHAT.
12. Optionally solves a source position from measured microphone geometry.

## Scientific boundary

The software measures two related quantities:

- **Clock slope:** how quickly the USB microphone actually produces samples.
- **Clock offset:** where that sample stream lies relative to PPS/GPS time.

PortAudio provides the estimated ADC time of the first sample in each callback buffer. LinuxPPS provides a kernel timestamp for each PPS edge. This system relates those two time domains and reports residuals.

A low residual proves that the software observations are internally consistent. It does **not**, by itself, prove the physical ADC-to-PPS offset to microsecond accuracy. Your equal-radius pipe experiment is the independent physical validation of that offset.

## Project layout

```text
01_inspect_hardware.py       List microphones and verify PPS/GNSS paths
02_capture_continuous.py     Continuous USB stream + audio/PPS/RMC evidence
03_fit_clock.py              Fit sample index to GPS/PPS time
04_extract_correct.py        Extract raw and GPS-corrected UTC windows
05_compare_center.py         Compare an equal-radius pipe strike
06_localize.py               Solve location from the timing report
07_plot_clock_diagnostics.py Plot clock residuals, interval ppm, and Pi temperature
simulate_demo.py             Hardware-free end-to-end verification
usb_pps_lab/                 Reusable implementation modules
```

## Raspberry Pi preparation

```bash
sudo apt update
sudo apt install -y \
    python3 python3-venv python3-dev \
    portaudio19-dev libsndfile1-dev \
    pps-tools alsa-utils

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The user running the scripts needs access to the microphone and GNSS serial device. On a normal Debian installation:

```bash
sudo usermod -aG audio,dialout "$USER"
```

Log out and back in after changing groups.

Stop any EnviroPulse microphone or RTK process that already owns the USB audio device or `/dev/ttyACM0` before this standalone test. The LinuxPPS sysfs timestamp may be readable concurrently, but the GNSS serial port usually cannot be shared safely.

## 1. Inspect one node

```bash
source .venv/bin/activate
python 01_inspect_hardware.py
```

Confirm:

- The desired USB microphone has an input device index and reports `supports_48000_mono_int16: true`.
- Choose the direct **ALSA hardware** entry for the USB device when possible. Avoid PulseAudio, PipeWire compatibility, `default`, `pulse`, or other software-mixing devices for this timing experiment.
- `/sys/class/pps/pps0/assert` exists and its sequence changes once per second.
- `/dev/ttyACM0` exists.

Copy the example configuration for each Pi:

```bash
cp config.example.json node_01.json
```

Edit at least:

```json
{
  "node_id": "node_01",
  "audio": {
    "device": 2
  }
}
```

Use the audio device index reported on that Pi. Keep all nodes at 48,000 Hz, mono, and the same block size for the first experiment.

## 2. Capture continuously

Start one session on each Pi:

```bash
python 02_capture_continuous.py --config node_01.json
```

The nodes do not need to be started in the same millisecond. Each session is placed on the GPS timeline afterward.

Recommended physical test:

1. Place microphone capsules at equal measured radius from the marked center.
2. Keep capsule height and orientation consistent.
3. Start all recorders.
4. Allow at least five minutes of warm-up.
5. Make several sharp pipe strikes at the measured center.
6. Continue recording for several minutes.
7. Press Ctrl+C once on each Pi and allow the session to close cleanly.

A session contains:

```text
session.json
pps_observations.ndjson
pps_anchors.ndjson
nmea_rmc.ndjson
audio_blocks.ndjson
audio_chunks.ndjson
audio/chunk_000000.wav
...
```

## 3. Fit each microphone clock

```bash
python 03_fit_clock.py sessions/node_01_YYYYMMDDTHHMMSSZ
```

Inspect:

- Effective sample rate.
- Sample-rate error in ppm.
- PortAudio block timing residual.
- PPS fit residual.
- Whether anchors came from `gnss_rmc_paired_to_pps` or `system_realtime_fallback`.

GNSS-paired anchors are preferred. System-realtime fallback is useful for development but is not equivalent to direct GNSS UTC pairing unless the system clock is independently disciplined and verified.


Create diagnostic plots for each fitted session:

```bash
python 07_plot_clock_diagnostics.py sessions/node_01_YYYYMMDDTHHMMSSZ
```

This writes separate plots for PPS fit residuals, one-second clock-rate error in ppm, and Raspberry Pi CPU temperature when available.

## 4. Choose one common UTC window

The clock report prints the first and last fitted UTC timestamps. Choose an interval present in every node session and containing the pipe strikes.

Example:

```bash
python 04_extract_correct.py \
    sessions/node_01_YYYYMMDDTHHMMSSZ \
    --start-utc 2026-07-16T15:30:00Z \
    --duration 20 \
    --output windows/node_01
```

Repeat with the exact same UTC start, duration, and target rate for every node.

Each output contains:

```text
node_01_raw_window.wav
node_01_gps_corrected.wav
node_01_window_timing.json
```

The raw window is evidence. The corrected window is a derived analytical product. Do not delete the raw session.

## 5. Compare the equal-radius center strike

Copy the corrected WAV files to one analysis machine, or run the comparison on one Pi:

```bash
python 05_compare_center.py \
    --recording node_01=windows/node_01/node_01_gps_corrected.wav \
    --recording node_02=windows/node_02/node_02_gps_corrected.wav \
    --recording node_03=windows/node_03/node_03_gps_corrected.wav \
    --recording node_04=windows/node_04/node_04_gps_corrected.wav \
    --output comparison
```

The script automatically selects the strongest transient. For multiple strikes, provide `--event-time` in seconds from the corrected-window start and run each strike separately.

At an accurately measured equal-radius center, the expected direct-arrival spread is approximately zero. The report provides:

- Relative delay to the reference microphone.
- Every pairwise delay.
- Delay in microseconds.
- Equivalent path-length difference in centimeters.
- GCC-PHAT peak strength.
- Total arrival spread.

## 6. Optional location solve

Update `positions.example.json` with microphone-capsule coordinates, not GNSS-antenna coordinates.

For a planar lab experiment with a known source height:

```bash
python 06_localize.py \
    --timing-report comparison/array_timing_report.json \
    --positions positions.example.json \
    --fixed-z 1.0 \
    --output localization
```

A free 3D solution requires sufficient non-coplanar geometry. Four microphones mounted in one horizontal plane cannot uniquely constrain every 3D case.

## Hardware-free verification

```bash
python simulate_demo.py
```

This creates four synthetic free-running microphones with different ppm errors and different stream start times, fits their clocks, extracts the same UTC window, corrects them, compares a shared impulse, and performs a fixed-height localization.

## How to interpret failure

- **Large PortAudio block residuals:** the host audio timestamp is unstable or callback timing is unsuitable.
- **Good block residuals but poor PPS residuals:** the PPS-to-system/PortAudio time bridge is unstable.
- **Good numerical residuals but the center pipe remains offset:** a repeatable or variable physical ADC/USB latency is not represented correctly by the software timestamps.
- **Offsets remain constant across sessions:** per-device fixed-delay calibration may be possible.
- **Offsets change after every stream open:** software-only absolute alignment may be inadequate for that microphone/driver.
- **Alignment is good after correction but drifts before correction:** the experiment has successfully measured and corrected sample-rate error.

## Recommended first-day acceptance criteria

Do not begin with an arbitrary pass/fail claim. Record enough evidence to answer:

1. Are ppm estimates stable during one session?
2. Do ppm estimates repeat after reboot?
3. Does correction reduce first-to-last strike drift?
4. Does the equal-radius arrival spread repeat across at least ten strikes?
5. Does reopening the USB stream change a node's fixed offset?
6. Does microphone/enclosure temperature correlate with the fitted rate?

That evidence determines whether the USB microphones are merely correctable in slope, or correctable in both slope and absolute offset.
