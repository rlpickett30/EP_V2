from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np
import soundfile as sf
from scipy.interpolate import CubicSpline

from .audioio import SessionAudioReader
from .clock import ClockModel
from .common import atomic_json_write, epoch_ns_to_iso, robust_linear_fit


def _build_utc_to_sample_mapper(
    model: ClockModel,
    start_utc_ns: int,
    stop_utc_ns: int,
    mode: str,
    local_margin_seconds: float = 30.0,
) -> tuple[Callable[[np.ndarray | float], np.ndarray], dict[str, Any]]:
    if mode == "global_linear":
        return (
            lambda utc: model.utc_ns_to_sample(utc, piecewise=False),
            {
                "mode": mode,
                "effective_sample_rate_hz": model.effective_sample_rate_hz,
                "anchors_used": 0,
            },
        )

    if mode == "piecewise":
        return (
            lambda utc: model.utc_ns_to_sample(utc, piecewise=True),
            {
                "mode": mode,
                "effective_sample_rate_hz": None,
                "anchors_used": int(len(model.anchor_utc_ns)),
            },
        )

    if mode != "local_linear":
        raise ValueError("time_map_mode must be global_linear, local_linear, or piecewise.")

    utc = model.anchor_utc_ns
    samples = model.anchor_sample
    if len(utc) < 2:
        return (
            lambda value: model.utc_ns_to_sample(value, piecewise=False),
            {
                "mode": "global_linear_fallback",
                "effective_sample_rate_hz": model.effective_sample_rate_hz,
                "anchors_used": int(len(utc)),
            },
        )

    margin_ns = local_margin_seconds * 1e9
    mask = (utc >= start_utc_ns - margin_ns) & (utc <= stop_utc_ns + margin_ns)
    selected_utc = utc[mask]
    selected_samples = samples[mask]
    if len(selected_utc) < 5:
        center = (start_utc_ns + stop_utc_ns) / 2.0
        order = np.argsort(np.abs(utc - center))
        take = order[: min(10, len(order))]
        take.sort()
        selected_utc = utc[take]
        selected_samples = samples[take]

    utc_origin_ns = float(np.median(selected_utc))
    utc_seconds = (selected_utc - utc_origin_ns) / 1e9
    fit = robust_linear_fit(utc_seconds, selected_samples, sigma_clip=4.0)
    slope_samples_per_second = float(fit["slope"])
    sample_at_fit_origin = float(
        fit["intercept_at_origin"]
        + fit["slope"] * (0.0 - fit["x_origin"])
    )

    def mapper(value: np.ndarray | float) -> np.ndarray:
        target = np.asarray(value, dtype=np.float64)
        return sample_at_fit_origin + ((target - utc_origin_ns) / 1e9) * slope_samples_per_second

    return mapper, {
        "mode": mode,
        "utc_origin_ns": int(round(utc_origin_ns)),
        "sample_at_origin": sample_at_fit_origin,
        "effective_sample_rate_hz": slope_samples_per_second,
        "anchors_used": int(fit["accepted_count"]),
        "anchors_rejected": int(fit["rejected_count"]),
        "sample_fit_residual_p95": float(fit["residual_p95_abs"]),
        "local_margin_seconds": local_margin_seconds,
    }


def extract_and_correct(
    session_directory: Path,
    start_utc_ns: int,
    duration_seconds: float,
    output_directory: Path,
    target_rate_hz: int,
    interpolation: str = "cubic",
    time_map_mode: str = "local_linear",
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive.")
    output_directory.mkdir(parents=True, exist_ok=True)

    reader = SessionAudioReader(session_directory)
    model = ClockModel.load(session_directory / "clock_model.json")
    duration_ns = int(round(duration_seconds * 1e9))
    stop_utc_ns = start_utc_ns + duration_ns
    utc_to_sample, time_map = _build_utc_to_sample_mapper(
        model,
        start_utc_ns,
        stop_utc_ns,
        mode=time_map_mode,
    )

    source_start = float(utc_to_sample(start_utc_ns))
    source_stop = float(utc_to_sample(stop_utc_ns))
    if source_start < reader.first_sample or source_stop > reader.end_sample_exclusive:
        raise ValueError("Requested UTC interval extends outside the captured audio coverage.")

    guard = 4
    raw_start = max(reader.first_sample, int(np.floor(source_start)) - guard)
    raw_stop = min(reader.end_sample_exclusive, int(np.ceil(source_stop)) + guard)
    source_audio = reader.read_samples(raw_start, raw_stop)
    source_positions = np.arange(raw_start, raw_stop, dtype=np.float64)

    nearest_start = int(round(source_start))
    nearest_stop = int(round(source_stop))
    raw_window = reader.read_samples(nearest_start, nearest_stop)
    raw_path = output_directory / f"{model.payload['node_id']}_raw_window.wav"
    sf.write(str(raw_path), raw_window, reader.sample_rate, subtype="PCM_16")

    target_frames = int(round(duration_seconds * target_rate_hz))
    target_utc_ns = start_utc_ns + np.arange(target_frames, dtype=np.float64) * (1e9 / target_rate_hz)
    target_source_positions = utc_to_sample(target_utc_ns)

    corrected = np.empty((target_frames, reader.channels), dtype=np.float64)
    for channel in range(reader.channels):
        if interpolation == "linear":
            corrected[:, channel] = np.interp(target_source_positions, source_positions, source_audio[:, channel])
        elif interpolation == "cubic":
            interpolator = CubicSpline(source_positions, source_audio[:, channel], extrapolate=False)
            corrected[:, channel] = interpolator(target_source_positions)
        else:
            raise ValueError("interpolation must be 'linear' or 'cubic'.")
    if not np.all(np.isfinite(corrected)):
        raise ValueError("Interpolation produced non-finite corrected audio samples.")
    corrected = np.clip(corrected, -1.0, 1.0)

    corrected_path = output_directory / f"{model.payload['node_id']}_gps_corrected.wav"
    sf.write(str(corrected_path), corrected, target_rate_hz, subtype="PCM_16")

    local_effective_rate = (source_stop - source_start) / duration_seconds
    anchors_used = [
        item for item in model.payload.get("pps_anchors", [])
        if item.get("accepted", True)
        and start_utc_ns - 35_000_000_000 <= item["utc_ns"] <= stop_utc_ns + 35_000_000_000
    ]
    metadata = {
        "schema": "usb_pps_corrected_window_v1",
        "node_id": model.payload["node_id"],
        "session_directory": str(session_directory.resolve()),
        "requested_start_utc_ns": start_utc_ns,
        "requested_start_utc_iso": epoch_ns_to_iso(start_utc_ns),
        "requested_stop_utc_ns": stop_utc_ns,
        "requested_stop_utc_iso": epoch_ns_to_iso(stop_utc_ns),
        "requested_duration_seconds": duration_seconds,
        "source_start_sample_fractional": source_start,
        "source_stop_sample_fractional": source_stop,
        "source_sample_span": source_stop - source_start,
        "local_effective_sample_rate_hz": local_effective_rate,
        "nominal_source_sample_rate_hz": reader.sample_rate,
        "target_sample_rate_hz": target_rate_hz,
        "target_frame_count": target_frames,
        "correction_ratio_target_over_source": target_rate_hz / local_effective_rate,
        "interpolation": interpolation,
        "time_map": time_map,
        "raw_window_path": str(raw_path.resolve()),
        "corrected_window_path": str(corrected_path.resolve()),
        "clock_quality": model.payload["quality"],
        "pps_anchors_near_window": anchors_used,
        "evidence_notice": "The raw WAV is preserved. The corrected WAV is a derived GPS-time-grid product.",
    }
    metadata_path = output_directory / f"{model.payload['node_id']}_window_timing.json"
    atomic_json_write(metadata_path, metadata)
    return metadata
