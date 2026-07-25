from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .common import atomic_json_write, epoch_ns_to_iso, load_json, read_ndjson, robust_linear_fit


class ClockModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.nominal_sample_rate_hz = float(payload["nominal_sample_rate_hz"])
        self.effective_sample_rate_hz = float(payload["effective_sample_rate_hz"])
        self.origin_sample = float(payload["sample_to_utc"]["origin_sample"])
        self.origin_utc_ns = int(payload["sample_to_utc"]["origin_utc_ns"])
        self.ns_per_sample = float(payload["sample_to_utc"]["ns_per_sample"])
        anchors = [item for item in payload.get("pps_anchors", []) if item.get("accepted", True)]
        unique: dict[int, dict[str, Any]] = {}
        for item in anchors:
            unique[int(item["utc_ns"])] = item
        anchors = [unique[key] for key in sorted(unique)]
        self.anchor_utc_ns = np.asarray([item["utc_ns"] for item in anchors], dtype=np.float64)
        self.anchor_sample = np.asarray([item["sample_index"] for item in anchors], dtype=np.float64)

    @classmethod
    def load(cls, path: Path) -> "ClockModel":
        return cls(load_json(path))

    def sample_to_utc_ns(self, sample_index: np.ndarray | float, piecewise: bool = True) -> np.ndarray:
        values = np.asarray(sample_index, dtype=np.float64)
        if piecewise and len(self.anchor_sample) >= 2:
            return _interp_extrap(values, self.anchor_sample, self.anchor_utc_ns)
        return self.origin_utc_ns + (values - self.origin_sample) * self.ns_per_sample

    def utc_ns_to_sample(self, utc_ns: np.ndarray | float, piecewise: bool = True) -> np.ndarray:
        values = np.asarray(utc_ns, dtype=np.float64)
        if piecewise and len(self.anchor_utc_ns) >= 2:
            return _interp_extrap(values, self.anchor_utc_ns, self.anchor_sample)
        return self.origin_sample + (values - self.origin_utc_ns) / self.ns_per_sample


def _interp_extrap(x: np.ndarray, xp: np.ndarray, fp: np.ndarray) -> np.ndarray:
    result = np.interp(x, xp, fp)
    left = x < xp[0]
    right = x > xp[-1]
    if np.any(left):
        slope = (fp[1] - fp[0]) / (xp[1] - xp[0])
        result[left] = fp[0] + (x[left] - xp[0]) * slope
    if np.any(right):
        slope = (fp[-1] - fp[-2]) / (xp[-1] - xp[-2])
        result[right] = fp[-1] + (x[right] - xp[-1]) * slope
    return result


def fit_session_clock(session_directory: Path) -> dict[str, Any]:
    session_directory = session_directory.resolve()
    session = load_json(session_directory / "session.json")
    config = session["config"]
    fit_cfg = config["clock_fit"]
    nominal_rate = float(config["audio"]["sample_rate_hz"])

    blocks = read_ndjson(session_directory / "audio_blocks.ndjson")
    anchors_raw = read_ndjson(session_directory / "pps_anchors.ndjson")
    deduplicated: dict[int, dict[str, Any]] = {}
    for anchor in anchors_raw:
        deduplicated[int(anchor["sequence"])] = anchor
    anchors = sorted(deduplicated.values(), key=lambda item: (int(item["utc_ns"]), int(item["sequence"])))
    if len(blocks) < int(fit_cfg["minimum_audio_blocks"]):
        raise ValueError(f"Only {len(blocks)} audio blocks were recorded; more are required.")
    if len(anchors) < int(fit_cfg["minimum_pps_anchors"]):
        raise ValueError(f"Only {len(anchors)} PPS anchors were recorded; more are required.")

    first_samples = np.asarray([item["first_sample"] for item in blocks], dtype=np.float64)
    adc_mono_ns = np.asarray([item["estimated_adc_monotonic_ns"] for item in blocks], dtype=np.float64)
    sigma_clip = float(fit_cfg.get("sigma_clip", 4.0))
    audio_fit = robust_linear_fit(first_samples, adc_mono_ns, sigma_clip=sigma_clip)
    ns_per_sample_audio = float(audio_fit["slope"])
    effective_rate_audio = 1e9 / ns_per_sample_audio

    pps_mono_ns = np.asarray([item["estimated_monotonic_ns"] for item in anchors], dtype=np.float64)
    pps_utc_ns = np.asarray([item["utc_ns"] for item in anchors], dtype=np.float64)
    sample_at_pps = audio_fit["x_origin"] + (pps_mono_ns - audio_fit["intercept_at_origin"]) / audio_fit["slope"]

    utc_origin = float(np.median(pps_utc_ns))
    utc_relative_ns = pps_utc_ns - utc_origin
    utc_fit = robust_linear_fit(sample_at_pps, utc_relative_ns, sigma_clip=sigma_clip)
    ns_per_sample_utc = float(utc_fit["slope"])
    effective_rate_utc = 1e9 / ns_per_sample_utc
    origin_sample = float(utc_fit["x_origin"])
    origin_utc_ns = int(round(utc_origin + utc_fit["intercept_at_origin"]))

    predicted_utc_ns = origin_utc_ns + (sample_at_pps - origin_sample) * ns_per_sample_utc
    pps_residual_us = (pps_utc_ns - predicted_utc_ns) / 1e3

    accepted_mask = np.asarray(utc_fit["mask"], dtype=bool)
    accepted_abs = np.abs(pps_residual_us[accepted_mask])
    p95_us = float(np.percentile(accepted_abs, 95))
    warning = float(fit_cfg.get("warning_residual_us", 1000.0))
    failure = float(fit_cfg.get("failure_residual_us", 5000.0))
    utc_sources = [str(item.get("utc_source", "unknown")) for item in anchors]
    gnss_paired_count = sum(source == "gnss_rmc_paired_to_pps" for source in utc_sources)
    if p95_us <= warning:
        quality = "PASS"
    elif p95_us <= failure:
        quality = "WARN"
    else:
        quality = "FAIL"
    if gnss_paired_count < len(anchors) and quality == "PASS":
        quality = "WARN"

    anchor_records = []
    for index, item in enumerate(anchors):
        anchor_records.append(
            {
                "sequence": item["sequence"],
                "utc_ns": int(item["utc_ns"]),
                "utc_iso": epoch_ns_to_iso(int(item["utc_ns"])),
                "utc_source": item.get("utc_source"),
                "pps_monotonic_ns": int(item["estimated_monotonic_ns"]),
                "sample_index": float(sample_at_pps[index]),
                "fit_residual_us": float(pps_residual_us[index]),
                "accepted": bool(accepted_mask[index]),
                "rmc_arrival_delay_ms": item.get("rmc_arrival_delay_ms"),
            }
        )

    model = {
        "schema": "usb_pps_clock_model_v1",
        "session_directory": str(session_directory),
        "node_id": session["node_id"],
        "nominal_sample_rate_hz": nominal_rate,
        "effective_sample_rate_hz": effective_rate_utc,
        "sample_rate_error_ppm": (effective_rate_utc / nominal_rate - 1.0) * 1e6,
        "portaudio_sample_rate_hz": effective_rate_audio,
        "sample_to_monotonic": {
            "origin_sample": float(audio_fit["x_origin"]),
            "origin_monotonic_ns": float(audio_fit["intercept_at_origin"]),
            "ns_per_sample": ns_per_sample_audio,
            "accepted_blocks": int(audio_fit["accepted_count"]),
            "rejected_blocks": int(audio_fit["rejected_count"]),
            "residual_p95_us": float(audio_fit["residual_p95_abs"] / 1e3),
            "residual_max_us": float(audio_fit["residual_max_abs"] / 1e3),
        },
        "sample_to_utc": {
            "origin_sample": origin_sample,
            "origin_utc_ns": origin_utc_ns,
            "origin_utc_iso": epoch_ns_to_iso(origin_utc_ns),
            "ns_per_sample": ns_per_sample_utc,
        },
        "quality": {
            "status": quality,
            "pps_anchor_count": len(anchor_records),
            "accepted_pps_anchors": int(accepted_mask.sum()),
            "rejected_pps_anchors": int(len(anchor_records) - accepted_mask.sum()),
            "pps_residual_p95_us": p95_us,
            "pps_residual_max_us": float(np.max(accepted_abs)),
            "warning_threshold_us": warning,
            "failure_threshold_us": failure,
            "gnss_paired_anchor_count": gnss_paired_count,
            "system_time_fallback_anchor_count": len(anchors) - gnss_paired_count,
            "utc_sources": sorted(set(utc_sources)),
            "absolute_offset_notice": "A low residual proves internal consistency, not independently verified physical ADC-to-PPS offset accuracy.",
        },
        "coverage": {
            "first_utc_ns": int(min(item["utc_ns"] for item in anchor_records)),
            "last_utc_ns": int(max(item["utc_ns"] for item in anchor_records)),
            "first_utc_iso": epoch_ns_to_iso(int(min(item["utc_ns"] for item in anchor_records))),
            "last_utc_iso": epoch_ns_to_iso(int(max(item["utc_ns"] for item in anchor_records))),
            "duration_seconds": (max(item["utc_ns"] for item in anchor_records) - min(item["utc_ns"] for item in anchor_records)) / 1e9,
        },
        "pps_anchors": anchor_records,
    }
    atomic_json_write(session_directory / "clock_model.json", model)
    return model
