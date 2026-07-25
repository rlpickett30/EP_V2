#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import soundfile as sf

from usb_pps_lab.analysis import compare_recordings, localize_from_relative_delays
from usb_pps_lab.clock import fit_session_clock
from usb_pps_lab.common import atomic_json_write, append_ndjson, epoch_ns_to_iso
from usb_pps_lab.correction import extract_and_correct


def build_session(root: Path, node_id: str, ppm: float, stream_offset_s: float, seed: int) -> Path:
    nominal_rate = 48000
    actual_rate = nominal_rate * (1.0 + ppm * 1e-6)
    duration_s = 20.0
    base_utc_ns = 1_800_000_000_000_000_000
    stream_start_utc_ns = base_utc_ns + int(round(stream_offset_s * 1e9))
    event_utc_ns = base_utc_ns + 10_000_000_000
    sample_count = int(np.ceil(duration_s * actual_rate))
    sample_index = np.arange(sample_count, dtype=np.float64)
    sample_utc_ns = stream_start_utc_ns + sample_index * (1e9 / actual_rate)

    rng = np.random.default_rng(seed)
    audio = rng.normal(0.0, 0.002, sample_count)
    event_sample = (event_utc_ns - stream_start_utc_ns) * actual_rate / 1e9
    x = sample_index - event_sample
    pulse = np.exp(-0.5 * (x / 2.0) ** 2)
    ring = np.sin(2.0 * np.pi * 2200.0 * x / actual_rate) * np.exp(-np.maximum(x, 0) / 500.0)
    ring[x < 0] = 0.0
    audio += 0.8 * pulse + 0.25 * ring
    audio = np.clip(audio, -1.0, 1.0)

    session = root / f"{node_id}_simulated"
    (session / "audio").mkdir(parents=True, exist_ok=True)
    wav_path = session / "audio" / "chunk_000000.wav"
    sf.write(str(wav_path), audio[:, None], nominal_rate, subtype="PCM_16")

    config = {
        "node_id": node_id,
        "audio": {
            "sample_rate_hz": nominal_rate,
            "channels": 1,
            "dtype": "int16",
            "block_frames": 1024,
        },
        "clock_fit": {
            "sigma_clip": 4.0,
            "minimum_audio_blocks": 100,
            "minimum_pps_anchors": 5,
            "warning_residual_us": 1000.0,
            "failure_residual_us": 5000.0,
        },
    }
    atomic_json_write(
        session / "session.json",
        {
            "schema": "usb_pps_timing_session_v1",
            "state": "complete",
            "node_id": node_id,
            "config": config,
            "total_stream_samples": sample_count,
        },
    )
    append_ndjson(
        session / "audio_chunks.ndjson",
        {
            "chunk_index": 0,
            "path": "audio/chunk_000000.wav",
            "start_sample": 0,
            "frame_count": sample_count,
            "end_sample_exclusive": sample_count,
        },
    )

    mono_start_ns = 4_000_000_000_000 + seed * 1_000_000
    block_frames = 1024
    for first_sample in range(0, sample_count, block_frames):
        frame_count = min(block_frames, sample_count - first_sample)
        jitter_ns = rng.normal(0.0, 15_000.0)
        adc_mono_ns = mono_start_ns + first_sample * 1e9 / actual_rate + jitter_ns
        append_ndjson(
            session / "audio_blocks.ndjson",
            {
                "first_sample": first_sample,
                "frame_count": frame_count,
                "estimated_adc_monotonic_ns": int(round(adc_mono_ns)),
                "status": "",
            },
        )

    first_integer_second = int(np.ceil(stream_start_utc_ns / 1e9))
    last_integer_second = int(np.floor((stream_start_utc_ns + duration_s * 1e9) / 1e9))
    sequence = 1000
    for utc_second in range(first_integer_second, last_integer_second + 1):
        utc_ns = utc_second * 1_000_000_000
        pps_mono_ns = mono_start_ns + (utc_ns - stream_start_utc_ns)
        append_ndjson(
            session / "pps_anchors.ndjson",
            {
                "sequence": sequence,
                "utc_ns": utc_ns,
                "utc_iso": epoch_ns_to_iso(utc_ns),
                "utc_source": "simulation",
                "estimated_monotonic_ns": int(round(pps_mono_ns)),
                "rmc_arrival_delay_ms": 120.0,
            },
        )
        sequence += 1
    return session


def main() -> None:
    root = Path("simulated_demo_output").resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    nodes = {
        "node_01": (+35.0, 0.13),
        "node_02": (-22.0, 0.41),
        "node_03": (+8.0, 0.77),
        "node_04": (-47.0, 0.05),
    }
    sessions = {}
    corrected = {}
    start_utc_ns = 1_800_000_000_000_000_000 + 9_500_000_000
    for index, (node, (ppm, offset)) in enumerate(nodes.items(), start=1):
        session = build_session(root, node, ppm, offset, index)
        sessions[node] = session
        model = fit_session_clock(session)
        output = root / "corrected" / node
        metadata = extract_and_correct(
            session,
            start_utc_ns=start_utc_ns,
            duration_seconds=1.0,
            output_directory=output,
            target_rate_hz=48000,
            interpolation="cubic",
        )
        corrected[node] = Path(metadata["corrected_window_path"])
        print(f"{node}: actual fit {model['effective_sample_rate_hz']:.6f} Hz ({model['sample_rate_error_ppm']:+.2f} ppm)")

    timing = compare_recordings(
        corrected,
        output_directory=root / "comparison",
        fmin_hz=300.0,
        fmax_hz=10000.0,
        event_time_seconds=0.5,
        analysis_half_window_seconds=0.03,
        max_delay_seconds=0.005,
    )
    geometry = json.loads((Path(__file__).parent / "positions.example.json").read_text(encoding="utf-8"))
    location = localize_from_relative_delays(
        geometry["microphones"],
        timing["relative_delays_seconds"],
        geometry["speed_of_sound_mps"],
        fixed_z=1.0,
    )
    atomic_json_write(root / "comparison" / "simulation_localization.json", location)
    print(f"Arrival spread after correction: {timing['arrival_spread_microseconds']:.3f} us")
    print(f"Solved location: {location['source_position_m']}")
    print(f"Output: {root}")


if __name__ == "__main__":
    main()
