from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import matplotlib.pyplot as plt
from scipy.optimize import least_squares
from scipy.signal import butter, sosfiltfilt

from .common import atomic_json_write


def load_mono(path: Path) -> tuple[np.ndarray, int]:
    signal, sample_rate = sf.read(str(path), dtype="float64", always_2d=True)
    return np.mean(signal, axis=1), int(sample_rate)


def bandpass(signal: np.ndarray, sample_rate: int, fmin_hz: float, fmax_hz: float) -> np.ndarray:
    nyquist = sample_rate / 2.0
    low = max(1.0, float(fmin_hz))
    high = min(float(fmax_hz), nyquist * 0.98)
    if not 0 < low < high < nyquist:
        raise ValueError(f"Invalid band {low}-{high} Hz for {sample_rate} Hz audio.")
    sos = butter(4, [low, high], btype="bandpass", fs=sample_rate, output="sos")
    return sosfiltfilt(sos, signal)


def detect_transient(signals: list[np.ndarray], sample_rate: int) -> int:
    minimum = min(len(item) for item in signals)
    stack = np.vstack([item[:minimum] for item in signals])
    normalized = []
    for row in stack:
        scale = np.median(np.abs(row - np.median(row))) * 1.4826
        normalized.append(row / max(scale, 1e-9))
    combined = np.median(np.abs(np.diff(np.vstack(normalized), axis=1, prepend=0.0)), axis=0)
    smooth_frames = max(1, int(round(sample_rate * 0.001)))
    kernel = np.ones(smooth_frames) / smooth_frames
    envelope = np.convolve(combined, kernel, mode="same")
    edge_guard = max(1, int(round(sample_rate * 0.05)))
    if len(envelope) <= 2 * edge_guard:
        return int(np.argmax(envelope))
    return edge_guard + int(np.argmax(envelope[edge_guard:-edge_guard]))


def gcc_phat_delay(
    signal: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    max_delay_seconds: float,
) -> tuple[float, float]:
    n = len(signal) + len(reference)
    nfft = 1 << int(np.ceil(np.log2(max(2, n))))
    spectrum_signal = np.fft.rfft(signal, n=nfft)
    spectrum_reference = np.fft.rfft(reference, n=nfft)
    cross = spectrum_signal * np.conj(spectrum_reference)
    cross /= np.maximum(np.abs(cross), 1e-15)
    correlation = np.fft.irfft(cross, n=nfft)

    max_shift = min(int(round(max_delay_seconds * sample_rate)), nfft // 2 - 1)
    correlation = np.concatenate((correlation[-max_shift:], correlation[:max_shift + 1]))
    absolute = np.abs(correlation)
    peak = int(np.argmax(absolute))
    shift = peak - max_shift

    fractional = 0.0
    if 0 < peak < len(absolute) - 1:
        left, center, right = absolute[peak - 1], absolute[peak], absolute[peak + 1]
        denominator = left - 2.0 * center + right
        if abs(denominator) > 1e-15:
            fractional = 0.5 * (left - right) / denominator
    delay_seconds = (shift + fractional) / sample_rate
    peak_strength = float(absolute[peak] / max(np.sum(absolute), 1e-15))
    return delay_seconds, peak_strength


def compare_recordings(
    recordings: dict[str, Path],
    output_directory: Path,
    fmin_hz: float = 300.0,
    fmax_hz: float = 10000.0,
    event_time_seconds: float | None = None,
    analysis_half_window_seconds: float = 0.04,
    max_delay_seconds: float = 0.02,
    speed_of_sound_mps: float = 343.2,
) -> dict[str, Any]:
    if len(recordings) < 2:
        raise ValueError("At least two recordings are required.")
    output_directory.mkdir(parents=True, exist_ok=True)

    names = list(recordings)
    loaded = {name: load_mono(path) for name, path in recordings.items()}
    rates = {rate for _, rate in loaded.values()}
    if len(rates) != 1:
        raise ValueError(f"Recordings do not share one sample rate: {sorted(rates)}")
    sample_rate = rates.pop()
    minimum_frames = min(len(signal) for signal, _ in loaded.values())
    filtered = {
        name: bandpass(signal[:minimum_frames], sample_rate, fmin_hz, fmax_hz)
        for name, (signal, _) in loaded.items()
    }

    if event_time_seconds is None:
        event_sample = detect_transient(list(filtered.values()), sample_rate)
    else:
        event_sample = int(round(event_time_seconds * sample_rate))
    half = int(round(analysis_half_window_seconds * sample_rate))
    start = max(0, event_sample - half)
    stop = min(minimum_frames, event_sample + half)
    if stop - start < 32:
        raise ValueError("Analysis window is too short.")

    reference_name = names[0]
    reference = filtered[reference_name][start:stop]
    relative_delays: dict[str, float] = {reference_name: 0.0}
    reference_strengths: dict[str, float] = {reference_name: 1.0}
    for name in names[1:]:
        delay, strength = gcc_phat_delay(
            filtered[name][start:stop],
            reference,
            sample_rate,
            max_delay_seconds,
        )
        relative_delays[name] = delay
        reference_strengths[name] = strength

    pairwise = []
    matrix_us = {name: {} for name in names}
    for index_a, name_a in enumerate(names):
        for index_b, name_b in enumerate(names):
            matrix_us[name_a][name_b] = (relative_delays[name_a] - relative_delays[name_b]) * 1e6
        for name_b in names[index_a + 1:]:
            delay, strength = gcc_phat_delay(
                filtered[name_a][start:stop],
                filtered[name_b][start:stop],
                sample_rate,
                max_delay_seconds,
            )
            pairwise.append(
                {
                    "microphone_a": name_a,
                    "microphone_b": name_b,
                    "delay_seconds_a_minus_b": delay,
                    "delay_microseconds_a_minus_b": delay * 1e6,
                    "equivalent_distance_m": delay * speed_of_sound_mps,
                    "equivalent_distance_cm": delay * speed_of_sound_mps * 100.0,
                    "gcc_phat_peak_strength": strength,
                }
            )

    delays = np.asarray(list(relative_delays.values()), dtype=np.float64)
    result = {
        "schema": "usb_pps_array_comparison_v1",
        "recordings": {name: str(path.resolve()) for name, path in recordings.items()},
        "sample_rate_hz": sample_rate,
        "event_sample": event_sample,
        "event_time_seconds": event_sample / sample_rate,
        "analysis_window_start_seconds": start / sample_rate,
        "analysis_window_stop_seconds": stop / sample_rate,
        "frequency_band_hz": [fmin_hz, fmax_hz],
        "reference_microphone": reference_name,
        "relative_delays_seconds": relative_delays,
        "reference_correlation_strengths": reference_strengths,
        "arrival_spread_microseconds": (float(np.max(delays)) - float(np.min(delays))) * 1e6,
        "arrival_spread_equivalent_cm": (float(np.max(delays)) - float(np.min(delays))) * speed_of_sound_mps * 100.0,
        "pairwise": pairwise,
        "pairwise_delay_matrix_microseconds": matrix_us,
    }
    atomic_json_write(output_directory / "array_timing_report.json", result)
    with (output_directory / "pairwise_delays.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pairwise[0].keys()))
        writer.writeheader()
        writer.writerows(pairwise)

    time_ms = (np.arange(stop - start) + start - event_sample) * 1000.0 / sample_rate
    figure = plt.figure(figsize=(12, 7))
    axis = figure.add_subplot(1, 1, 1)
    for offset_index, name in enumerate(names):
        segment = filtered[name][start:stop]
        scale = np.max(np.abs(segment))
        normalized = segment / max(scale, 1e-12)
        axis.plot(time_ms, normalized + offset_index * 2.2, linewidth=0.9, label=name)
    axis.axvline(0.0, linestyle="--", linewidth=1.0)
    axis.set_title("Band-Limited Pipe-Strike Waveforms on the Common GPS Time Grid")
    axis.set_xlabel("Time Relative to Detected Event (ms)")
    axis.set_ylabel("Normalized Waveforms, Vertically Offset")
    axis.legend(loc="upper right")
    axis.grid(True)
    figure.tight_layout()
    figure.savefig(output_directory / "event_overlay.png", dpi=160, bbox_inches="tight")
    plt.close(figure)

    matrix = np.asarray([[matrix_us[a][b] for b in names] for a in names], dtype=float)
    figure = plt.figure(figsize=(8, 7))
    axis = figure.add_subplot(1, 1, 1)
    image = axis.imshow(matrix)
    axis.set_xticks(range(len(names)), labels=names, rotation=45, ha="right")
    axis.set_yticks(range(len(names)), labels=names)
    axis.set_title("Pairwise Delay Matrix (microseconds)")
    figure.colorbar(image, ax=axis, label="Delay (µs)")
    figure.tight_layout()
    figure.savefig(output_directory / "pairwise_delay_matrix.png", dpi=160, bbox_inches="tight")
    plt.close(figure)
    return result


def localize_from_relative_delays(
    microphone_positions: dict[str, list[float]],
    relative_delays_seconds: dict[str, float],
    speed_of_sound_mps: float,
    fixed_z: float | None = None,
) -> dict[str, Any]:
    names = [name for name in relative_delays_seconds if name in microphone_positions]
    if len(names) < 4 and fixed_z is None:
        raise ValueError("At least four microphones are required for unconstrained 3D localization.")
    if len(names) < 3 and fixed_z is not None:
        raise ValueError("At least three microphones are required when z is fixed.")

    positions = np.asarray([microphone_positions[name] for name in names], dtype=np.float64)
    delays = np.asarray([relative_delays_seconds[name] for name in names], dtype=np.float64)
    reference_position = positions[0]
    reference_delay = delays[0]
    center = np.mean(positions, axis=0)

    if fixed_z is None:
        initial = center.copy()

        def residual(parameters: np.ndarray) -> np.ndarray:
            source = parameters
            distances = np.linalg.norm(positions - source, axis=1)
            predicted = (distances - distances[0]) / speed_of_sound_mps
            return predicted - (delays - reference_delay)
    else:
        initial = center[:2].copy()

        def residual(parameters: np.ndarray) -> np.ndarray:
            source = np.asarray([parameters[0], parameters[1], fixed_z], dtype=np.float64)
            distances = np.linalg.norm(positions - source, axis=1)
            predicted = (distances - distances[0]) / speed_of_sound_mps
            return predicted - (delays - reference_delay)

    solution = least_squares(residual, initial, loss="soft_l1")
    if fixed_z is None:
        source = solution.x
    else:
        source = np.asarray([solution.x[0], solution.x[1], fixed_z])
    residual_seconds = residual(solution.x)

    return {
        "microphones_used": names,
        "source_position_m": source.tolist(),
        "success": bool(solution.success),
        "message": solution.message,
        "cost": float(solution.cost),
        "residuals_microseconds": (residual_seconds * 1e6).tolist(),
        "residual_rms_microseconds": float(np.sqrt(np.mean(residual_seconds ** 2)) * 1e6),
        "speed_of_sound_mps": speed_of_sound_mps,
        "fixed_z": fixed_z,
    }
