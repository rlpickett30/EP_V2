#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from usb_pps_lab.common import load_json, read_ndjson


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot fitted clock residuals, interval ppm, and CPU temperature.")
    parser.add_argument("session", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    session = args.session.resolve()
    output = (args.output or (session / "clock_plots")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    model = load_json(session / "clock_model.json")
    anchors = [item for item in model["pps_anchors"] if item.get("accepted", True)]
    if len(anchors) < 2:
        raise ValueError("At least two accepted PPS anchors are required.")

    utc_ns = np.asarray([item["utc_ns"] for item in anchors], dtype=np.float64)
    samples = np.asarray([item["sample_index"] for item in anchors], dtype=np.float64)
    elapsed = (utc_ns - utc_ns[0]) / 1e9
    residual_us = np.asarray([item["fit_residual_us"] for item in anchors], dtype=np.float64)

    figure = plt.figure(figsize=(11, 6))
    axis = figure.add_subplot(1, 1, 1)
    axis.plot(elapsed, residual_us, marker=".", linewidth=0.8)
    axis.axhline(0.0, linestyle="--", linewidth=1.0)
    axis.set_title(f"{model['node_id']} PPS-to-Audio Clock-Fit Residuals")
    axis.set_xlabel("Elapsed GPS Time (s)")
    axis.set_ylabel("Residual (µs)")
    axis.grid(True)
    figure.tight_layout()
    figure.savefig(output / "pps_fit_residuals.png", dpi=160, bbox_inches="tight")
    plt.close(figure)

    interval_seconds = np.diff(utc_ns) / 1e9
    interval_samples = np.diff(samples)
    interval_rate = interval_samples / interval_seconds
    nominal = float(model["nominal_sample_rate_hz"])
    interval_ppm = (interval_rate / nominal - 1.0) * 1e6
    interval_mid = (elapsed[:-1] + elapsed[1:]) / 2.0

    figure = plt.figure(figsize=(11, 6))
    axis = figure.add_subplot(1, 1, 1)
    axis.plot(interval_mid, interval_ppm, marker=".", linewidth=0.8)
    axis.axhline(float(model["sample_rate_error_ppm"]), linestyle="--", linewidth=1.0)
    axis.set_title(f"{model['node_id']} Measured USB Audio Clock Error by PPS Interval")
    axis.set_xlabel("Elapsed GPS Time (s)")
    axis.set_ylabel("Sample-Rate Error (ppm)")
    axis.grid(True)
    figure.tight_layout()
    figure.savefig(output / "interval_clock_error_ppm.png", dpi=160, bbox_inches="tight")
    plt.close(figure)

    telemetry = read_ndjson(session / "telemetry.ndjson")
    temperature = [item for item in telemetry if item.get("cpu_temperature_c") is not None]
    if temperature:
        mono = np.asarray([item["monotonic_ns"] for item in temperature], dtype=np.float64)
        temp_c = np.asarray([item["cpu_temperature_c"] for item in temperature], dtype=np.float64)
        temp_elapsed = (mono - mono[0]) / 1e9
        figure = plt.figure(figsize=(11, 6))
        axis = figure.add_subplot(1, 1, 1)
        axis.plot(temp_elapsed, temp_c, linewidth=1.0)
        axis.set_title(f"{model['node_id']} Raspberry Pi CPU Temperature During Capture")
        axis.set_xlabel("Elapsed Monotonic Time (s)")
        axis.set_ylabel("CPU Temperature (°C)")
        axis.grid(True)
        figure.tight_layout()
        figure.savefig(output / "cpu_temperature.png", dpi=160, bbox_inches="tight")
        plt.close(figure)

    print(f"Saved diagnostics to {output}")


if __name__ == "__main__":
    main()
