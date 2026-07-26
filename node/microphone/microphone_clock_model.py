# ============================================================
# microphone_clock_model.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Microphone
#
# Role:
#   Manager
#
# Purpose:
#   Fit the continuous microphone sample timeline to accepted GNSS-labeled
#   PPS anchors and associate a quality-graded model with raw recordings.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Consume accepted PPS/sample/UTC anchor evidence
#   - Reuse the laboratory robust linear clock-fit method
#   - Produce PASS, WARN, and FAIL model quality states
#   - Preserve per-anchor fit residuals
#   - Reset the fit across stream or timing-segment discontinuities
#   - Persist the latest model atomically
#   - Associate one model and nearby anchors with each guarded recording
#
# Does NOT:
#   - Publish events
#   - Subscribe to the event bus
#   - Read microphone hardware
#   - Modify WAV files
#   - Stretch, compress, resample, or clip audio
#   - Declare server-side clock correction complete
#   - Decide TDOA calculation workflow
#
# Owner:
#   microphone_dispatcher.py
#
# ============================================================

from __future__ import annotations

import copy
import json
import math
import re
import threading

from datetime import datetime
from datetime import timezone
from pathlib import Path

import numpy as np


class MicrophoneClockModelManager:

    def __init__(
        self,
        recordings_root,
        node_id,
        nominal_sample_rate_hz,
        anchor_evidence_path=None,
        minimum_anchor_count=5,
        minimum_coverage_seconds=15.0,
        maximum_anchor_count=1200,
        sigma_clip=4.0,
        warning_residual_us=1000.0,
        failure_residual_us=5000.0,
        minimum_fit_acceptance_ratio=0.80,
        maximum_rate_error_ppm=5000.0,
        maximum_recording_extrapolation_sec=2.0,
        debug=True,
    ):

        self.recordings_root = Path(
            recordings_root
        )
        self.node_id = str(
            node_id or "unknown_node"
        )
        self.nominal_sample_rate_hz = float(
            nominal_sample_rate_hz
        )
        self.anchor_evidence_path = (
            str(
                anchor_evidence_path
            )
            if anchor_evidence_path
            else None
        )

        self.minimum_anchor_count = max(
            2,
            int(
                minimum_anchor_count
            ),
        )
        self.minimum_coverage_seconds = max(
            0.0,
            float(
                minimum_coverage_seconds
            ),
        )
        self.maximum_anchor_count = max(
            self.minimum_anchor_count,
            int(
                maximum_anchor_count
            ),
        )
        self.sigma_clip = float(
            sigma_clip
        )
        self.warning_residual_us = float(
            warning_residual_us
        )
        self.failure_residual_us = float(
            failure_residual_us
        )
        self.minimum_fit_acceptance_ratio = min(
            1.0,
            max(
                0.5,
                float(
                    minimum_fit_acceptance_ratio
                ),
            ),
        )
        self.maximum_rate_error_ppm = abs(
            float(
                maximum_rate_error_ppm
            )
        )
        self.maximum_recording_extrapolation_sec = max(
            0.0,
            float(
                maximum_recording_extrapolation_sec
            ),
        )
        self.debug = bool(
            debug
        )

        safe_node_id = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            self.node_id,
        ).strip(
            "._"
        )

        if not safe_node_id:
            safe_node_id = "unknown_node"

        self.output_path = (
            self.recordings_root
            /
            "timing"
            /
            (
                f"{safe_node_id}_sample_clock_"
                "model_latest.json"
            )
        )

        self._lock = threading.RLock()
        self._anchors = []
        self._latest_model = None
        self._stream_instance_id = None
        self._timing_segment_id = None
        self._last_reset_reason = None
        self._reset_count = 0
        self._rejected_anchor_count = 0

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(
        self,
        message,
    ):

        if self.debug:
            print(
                (
                    "[MicrophoneClockModelManager] "
                    f"{message}"
                )
            )

    # --------------------------------------------------
    # Anchor Input
    # --------------------------------------------------

    def observe_anchor(
        self,
        anchor_record,
    ):

        normalized, rejection_reason = (
            self._normalize_anchor(
                anchor_record
            )
        )

        if rejection_reason is not None:

            with self._lock:
                self._rejected_anchor_count += 1

            return {
                "accepted": False,
                "reason": rejection_reason,
                "model": self.get_latest_model(),
            }

        with self._lock:

            stream_instance_id = normalized[
                "stream_instance_id"
            ]
            timing_segment_id = normalized[
                "timing_segment_id"
            ]

            if self._anchors and (
                stream_instance_id
                !=
                self._stream_instance_id
                or
                timing_segment_id
                !=
                self._timing_segment_id
            ):
                self._reset_locked(
                    (
                        "stream_or_timing_segment_"
                        "changed"
                    )
                )

            if not self._anchors:
                self._stream_instance_id = (
                    stream_instance_id
                )
                self._timing_segment_id = (
                    timing_segment_id
                )

            duplicate = next(
                (
                    item
                    for item in self._anchors
                    if item.get("pps_seq")
                    ==
                    normalized.get("pps_seq")
                ),
                None,
            )

            if duplicate is not None:

                if (
                    duplicate["gnss_utc_ns"]
                    ==
                    normalized["gnss_utc_ns"]
                    and
                    math.isclose(
                        duplicate[
                            "sample_position"
                        ],
                        normalized[
                            "sample_position"
                        ],
                        rel_tol=0.0,
                        abs_tol=1e-6,
                    )
                ):
                    return {
                        "accepted": True,
                        "duplicate": True,
                        "model": copy.deepcopy(
                            self._latest_model
                        ),
                    }

                self._rejected_anchor_count += 1

                return {
                    "accepted": False,
                    "reason": (
                        "conflicting_pps_sequence"
                    ),
                    "model": copy.deepcopy(
                        self._latest_model
                    ),
                }

            if self._anchors:
                previous = self._anchors[-1]

                if (
                    normalized["gnss_utc_ns"]
                    <=
                    previous["gnss_utc_ns"]
                ):
                    self._rejected_anchor_count += 1

                    return {
                        "accepted": False,
                        "reason": (
                            "gnss_utc_not_increasing"
                        ),
                        "model": copy.deepcopy(
                            self._latest_model
                        ),
                    }

                if (
                    normalized["sample_position"]
                    <=
                    previous["sample_position"]
                ):
                    self._rejected_anchor_count += 1

                    return {
                        "accepted": False,
                        "reason": (
                            "sample_position_not_"
                            "increasing"
                        ),
                        "model": copy.deepcopy(
                            self._latest_model
                        ),
                    }

            self._anchors.append(
                normalized
            )

            if (
                len(self._anchors)
                >
                self.maximum_anchor_count
            ):
                self._anchors = self._anchors[
                    -self.maximum_anchor_count:
                ]

            self._latest_model = (
                self._fit_locked()
            )

            model = copy.deepcopy(
                self._latest_model
            )

        quality = (
            model.get(
                "quality",
                {},
            ).get(
                "status"
            )
            if isinstance(
                model,
                dict,
            )
            else None
        )

        self.log(
            (
                "Clock anchor accepted: "
                f"pps_seq={normalized.get('pps_seq')} "
                f"anchors={len(self._anchors)} "
                f"quality={quality}"
            )
        )

        return {
            "accepted": True,
            "duplicate": False,
            "model": model,
        }

    def _normalize_anchor(
        self,
        anchor_record,
    ):

        if not isinstance(
            anchor_record,
            dict,
        ):
            return None, "anchor_record_invalid"

        if not bool(
            anchor_record.get(
                "anchor_accepted",
                False,
            )
        ):
            return None, "anchor_not_accepted"

        if not bool(
            anchor_record.get(
                "utc_label_valid",
                False,
            )
        ):
            return None, "gnss_utc_label_invalid"

        if (
            anchor_record.get(
                "utc_source"
            )
            !=
            "gnss_rmc_paired_to_pps"
        ):
            return None, "gnss_utc_source_invalid"

        sample_lookup = anchor_record.get(
            "sample_lookup",
            {},
        )

        if not isinstance(
            sample_lookup,
            dict,
        ):
            return None, "sample_lookup_invalid"

        if not bool(
            sample_lookup.get(
                "accepted",
                False,
            )
        ):
            return None, "sample_lookup_not_accepted"

        try:
            pps_seq = int(
                anchor_record[
                    "pps_seq"
                ]
            )
            sample_position = float(
                sample_lookup[
                    "sample_position_fractional"
                ]
            )
            gnss_utc_ns = int(
                anchor_record[
                    "gnss_utc_ns"
                ]
            )
            timing_segment_id = int(
                sample_lookup[
                    "timing_segment_id"
                ]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return None, "anchor_timing_fields_invalid"

        stream_instance_id = str(
            sample_lookup.get(
                "stream_instance_id",
                "",
            )
        ).strip()

        if not stream_instance_id:
            return None, "stream_instance_id_invalid"

        if (
            not math.isfinite(
                sample_position
            )
            or
            sample_position < 0
            or
            gnss_utc_ns <= 0
        ):
            return None, "anchor_numeric_fields_invalid"

        return {
            "pps_seq": pps_seq,
            "gnss_utc_ns": gnss_utc_ns,
            "gnss_utc": anchor_record.get(
                "gnss_utc"
            ),
            "utc_source": anchor_record.get(
                "utc_source"
            ),
            "rmc_arrival_delay_ms": (
                anchor_record.get(
                    "rmc_arrival_delay_ms"
                )
            ),
            "sample_position": sample_position,
            "sample_position_rounded": (
                sample_lookup.get(
                    "sample_position_rounded"
                )
            ),
            "stream_instance_id": (
                stream_instance_id
            ),
            "timing_segment_id": (
                timing_segment_id
            ),
            "lookup_method": (
                sample_lookup.get(
                    "lookup_method"
                )
            ),
            "local_rate_hz": (
                sample_lookup.get(
                    "local_rate_hz"
                )
            ),
            "resolver_state": (
                anchor_record.get(
                    "resolver_state"
                )
            ),
            "created_utc": (
                anchor_record.get(
                    "created_utc"
                )
            ),
        }, None

    # --------------------------------------------------
    # Clock Fit
    # --------------------------------------------------

    def _fit_locked(
        self,
    ):

        anchors = list(
            self._anchors
        )

        if len(anchors) < 2:
            return None

        sample_positions = np.asarray(
            [
                item["sample_position"]
                for item in anchors
            ],
            dtype=np.float64,
        )

        utc_ns_integer = np.asarray(
            [
                item["gnss_utc_ns"]
                for item in anchors
            ],
            dtype=np.int64,
        )

        utc_origin_ns = int(
            anchors[
                len(anchors)
                //
                2
            ][
                "gnss_utc_ns"
            ]
        )

        utc_relative_ns = np.asarray(
            [
                int(
                    value
                )
                -
                utc_origin_ns
                for value in utc_ns_integer
            ],
            dtype=np.float64,
        )

        fit = self._robust_linear_fit(
            x=sample_positions,
            y=utc_relative_ns,
            sigma_clip=self.sigma_clip,
        )

        ns_per_sample = float(
            fit["slope"]
        )

        if ns_per_sample <= 0:
            return self._failed_model_locked(
                anchors=anchors,
                reason="clock_fit_slope_not_positive",
            )

        effective_sample_rate_hz = (
            1_000_000_000.0
            /
            ns_per_sample
        )

        origin_sample = float(
            fit["x_origin"]
        )

        origin_utc_ns = int(
            round(
                float(
                    utc_origin_ns
                )
                +
                fit["intercept_at_origin"]
            )
        )

        predicted_relative_ns = (
            fit["intercept_at_origin"]
            +
            (
                sample_positions
                -
                origin_sample
            )
            *
            ns_per_sample
        )

        residual_us = (
            utc_relative_ns
            -
            predicted_relative_ns
        ) / 1000.0

        accepted_mask = np.asarray(
            fit["mask"],
            dtype=bool,
        )

        accepted_absolute_residual_us = np.abs(
            residual_us[
                accepted_mask
            ]
        )

        residual_p95_us = float(
            np.percentile(
                accepted_absolute_residual_us,
                95,
            )
        )

        residual_max_us = float(
            np.max(
                accepted_absolute_residual_us
            )
        )

        accepted_anchor_count = int(
            accepted_mask.sum()
        )
        fit_acceptance_ratio = (
            accepted_anchor_count
            /
            len(
                anchors
            )
        )

        first_utc_ns = int(
            anchors[0][
                "gnss_utc_ns"
            ]
        )
        last_utc_ns = int(
            anchors[-1][
                "gnss_utc_ns"
            ]
        )
        coverage_seconds = (
            last_utc_ns
            -
            first_utc_ns
        ) / 1_000_000_000.0

        sample_rate_error_ppm = (
            (
                effective_sample_rate_hz
                /
                self.nominal_sample_rate_hz
            )
            -
            1.0
        ) * 1_000_000.0

        quality_reasons = []

        if (
            accepted_anchor_count
            <
            self.minimum_anchor_count
        ):
            quality_reasons.append(
                "insufficient_accepted_anchors"
            )

        if (
            coverage_seconds
            <
            self.minimum_coverage_seconds
        ):
            quality_reasons.append(
                "insufficient_clock_coverage"
            )

        if (
            fit_acceptance_ratio
            <
            self.minimum_fit_acceptance_ratio
        ):
            quality_reasons.append(
                "excessive_anchor_rejection"
            )

        if (
            abs(
                sample_rate_error_ppm
            )
            >
            self.maximum_rate_error_ppm
        ):
            quality_reasons.append(
                "sample_rate_error_outside_limit"
            )

        if quality_reasons:
            quality_status = "FAIL"

        elif (
            residual_p95_us
            <=
            self.warning_residual_us
        ):
            quality_status = "PASS"

        elif (
            residual_p95_us
            <=
            self.failure_residual_us
        ):
            quality_status = "WARN"
            quality_reasons.append(
                "clock_residual_warning"
            )

        else:
            quality_status = "FAIL"
            quality_reasons.append(
                "clock_residual_failure"
            )

        fit_residuals = []

        for index, anchor in enumerate(
            anchors
        ):
            fit_residuals.append(
                {
                    "pps_seq": anchor.get(
                        "pps_seq"
                    ),
                    "gnss_utc_ns": anchor[
                        "gnss_utc_ns"
                    ],
                    "sample_position": anchor[
                        "sample_position"
                    ],
                    "fit_residual_us": float(
                        residual_us[
                            index
                        ]
                    ),
                    "accepted_by_fit": bool(
                        accepted_mask[
                            index
                        ]
                    ),
                }
            )

        first_sequence = anchors[0].get(
            "pps_seq"
        )
        last_sequence = anchors[-1].get(
            "pps_seq"
        )

        model = {
            "schema": (
                "enviro_pulse_sample_"
                "clock_model_v1"
            ),
            "model_id": (
                f"{self.node_id}:"
                f"{self._stream_instance_id}:"
                f"{self._timing_segment_id}:"
                f"{first_sequence}-{last_sequence}"
            ),
            "created_utc": self._utc_now(),
            "node_id": self.node_id,
            "stream_instance_id": (
                self._stream_instance_id
            ),
            "timing_segment_id": (
                self._timing_segment_id
            ),
            "nominal_sample_rate_hz": (
                self.nominal_sample_rate_hz
            ),
            "effective_sample_rate_hz": (
                effective_sample_rate_hz
            ),
            "sample_rate_error_ppm": (
                sample_rate_error_ppm
            ),
            "sample_to_utc": {
                "origin_sample": (
                    origin_sample
                ),
                "origin_utc_ns": (
                    origin_utc_ns
                ),
                "origin_utc": (
                    self._epoch_ns_to_utc(
                        origin_utc_ns
                    )
                ),
                "ns_per_sample": (
                    ns_per_sample
                ),
            },
            "quality": {
                "status": quality_status,
                "model_valid": bool(
                    quality_status == "PASS"
                ),
                "quality_reasons": (
                    quality_reasons
                ),
                "observed_anchor_count": len(
                    anchors
                ),
                "accepted_anchor_count": (
                    accepted_anchor_count
                ),
                "rejected_by_fit_count": (
                    len(anchors)
                    -
                    accepted_anchor_count
                ),
                "fit_acceptance_ratio": (
                    fit_acceptance_ratio
                ),
                "minimum_fit_acceptance_ratio": (
                    self.minimum_fit_acceptance_ratio
                ),
                "rejected_before_fit_count": (
                    self._rejected_anchor_count
                ),
                "residual_p95_us": (
                    residual_p95_us
                ),
                "residual_max_us": (
                    residual_max_us
                ),
                "warning_threshold_us": (
                    self.warning_residual_us
                ),
                "failure_threshold_us": (
                    self.failure_residual_us
                ),
                "minimum_anchor_count": (
                    self.minimum_anchor_count
                ),
                "minimum_coverage_seconds": (
                    self.minimum_coverage_seconds
                ),
                "maximum_rate_error_ppm": (
                    self.maximum_rate_error_ppm
                ),
                "all_utc_sources_gnss_rmc": all(
                    item.get("utc_source")
                    ==
                    "gnss_rmc_paired_to_pps"
                    for item in anchors
                ),
                "unresolved_discontinuity": bool(
                    quality_status != "PASS"
                    and
                    self._last_reset_reason
                    is not None
                ),
                "absolute_offset_notice": (
                    "A low residual proves internal "
                    "consistency; hardware validation "
                    "still establishes physical ADC-to-"
                    "PPS offset accuracy."
                ),
            },
            "coverage": {
                "first_sample": anchors[0][
                    "sample_position"
                ],
                "last_sample": anchors[-1][
                    "sample_position"
                ],
                "first_utc_ns": first_utc_ns,
                "last_utc_ns": last_utc_ns,
                "first_utc": (
                    self._epoch_ns_to_utc(
                        first_utc_ns
                    )
                ),
                "last_utc": (
                    self._epoch_ns_to_utc(
                        last_utc_ns
                    )
                ),
                "duration_seconds": (
                    coverage_seconds
                ),
            },
            "fit_residuals": fit_residuals,
            "anchor_evidence_path": (
                self.anchor_evidence_path
            ),
            "reset_count": self._reset_count,
            "last_reset_reason": (
                self._last_reset_reason
            ),
        }

        return model

    def _failed_model_locked(
        self,
        anchors,
        reason,
    ):

        return {
            "schema": (
                "enviro_pulse_sample_"
                "clock_model_v1"
            ),
            "model_id": None,
            "created_utc": self._utc_now(),
            "node_id": self.node_id,
            "stream_instance_id": (
                self._stream_instance_id
            ),
            "timing_segment_id": (
                self._timing_segment_id
            ),
            "nominal_sample_rate_hz": (
                self.nominal_sample_rate_hz
            ),
            "effective_sample_rate_hz": None,
            "sample_rate_error_ppm": None,
            "sample_to_utc": None,
            "quality": {
                "status": "FAIL",
                "model_valid": False,
                "quality_reasons": [
                    reason
                ],
                "observed_anchor_count": len(
                    anchors
                ),
            },
            "coverage": None,
            "fit_residuals": [],
            "anchor_evidence_path": (
                self.anchor_evidence_path
            ),
            "reset_count": self._reset_count,
            "last_reset_reason": (
                self._last_reset_reason
            ),
        }

    def _robust_linear_fit(
        self,
        x,
        y,
        sigma_clip=4.0,
        maximum_iterations=8,
    ):

        x = np.asarray(
            x,
            dtype=np.float64,
        )
        y = np.asarray(
            y,
            dtype=np.float64,
        )

        finite = (
            np.isfinite(
                x
            )
            &
            np.isfinite(
                y
            )
        )

        if finite.sum() < 2:
            raise ValueError(
                (
                    "At least two finite points "
                    "are required for a clock fit."
                )
            )

        x_origin = float(
            np.median(
                x[
                    finite
                ]
            )
        )
        centered_x = x - x_origin
        mask = finite.copy()

        for _ in range(
            int(
                maximum_iterations
            )
        ):
            design = np.column_stack(
                [
                    np.ones(
                        mask.sum()
                    ),
                    centered_x[
                        mask
                    ],
                ]
            )

            coefficients, *_ = (
                np.linalg.lstsq(
                    design,
                    y[
                        mask
                    ],
                    rcond=None,
                )
            )

            predicted = (
                coefficients[0]
                +
                coefficients[1]
                *
                centered_x
            )

            residuals = y - predicted

            residual_median = float(
                np.median(
                    residuals[
                        mask
                    ]
                )
            )

            median_absolute_deviation = float(
                np.median(
                    np.abs(
                        residuals[
                            mask
                        ]
                        -
                        residual_median
                    )
                )
            )

            scale = (
                1.4826
                *
                median_absolute_deviation
            )

            if (
                not math.isfinite(
                    scale
                )
                or
                scale <= 0.0
            ):
                break

            new_mask = (
                finite
                &
                (
                    np.abs(
                        residuals
                        -
                        residual_median
                    )
                    <=
                    sigma_clip
                    *
                    scale
                )
            )

            if (
                new_mask.sum() < 2
                or
                np.array_equal(
                    new_mask,
                    mask,
                )
            ):
                if new_mask.sum() >= 2:
                    mask = new_mask
                break

            mask = new_mask

        design = np.column_stack(
            [
                np.ones(
                    mask.sum()
                ),
                centered_x[
                    mask
                ],
            ]
        )

        coefficients, *_ = np.linalg.lstsq(
            design,
            y[
                mask
            ],
            rcond=None,
        )

        return {
            "x_origin": x_origin,
            "intercept_at_origin": float(
                coefficients[0]
            ),
            "slope": float(
                coefficients[1]
            ),
            "mask": mask,
        }

    # --------------------------------------------------
    # Recording Association
    # --------------------------------------------------

    def associate_recording(
        self,
        recording,
    ):

        if not isinstance(
            recording,
            dict,
        ):
            return recording

        with self._lock:
            model = copy.deepcopy(
                self._latest_model
            )
            anchors = copy.deepcopy(
                self._anchors
            )

        association = {
            "schema_version": 1,
            "model_available": bool(
                isinstance(
                    model,
                    dict,
                )
            ),
            "model_valid": False,
            "quality_status": (
                model.get(
                    "quality",
                    {},
                ).get(
                    "status"
                )
                if isinstance(
                    model,
                    dict,
                )
                else None
            ),
            "quality_reasons": [],
            "same_stream_instance": False,
            "same_timing_segment": False,
            "guarded_range_valid": False,
            "guarded_range_within_extrapolation_limit": (
                False
            ),
            "nearby_anchor_count": 0,
            "maximum_extrapolation_seconds": (
                self.maximum_recording_extrapolation_sec
            ),
        }

        if not isinstance(
            model,
            dict,
        ):
            association["quality_reasons"] = [
                "clock_model_unavailable"
            ]

            recording.update(
                {
                    "timing_state": (
                        "pps_clock_model_pending"
                    ),
                    "clock_model_id": None,
                    "clock_model_quality": None,
                    "clock_model": None,
                    "nearby_pps_anchors": [],
                    "clock_model_association": (
                        association
                    ),
                }
            )

            return recording

        boundary_snapshot = recording.get(
            "boundary_snapshot",
            {},
        )

        if not isinstance(
            boundary_snapshot,
            dict,
        ):
            boundary_snapshot = {}

        recording_stream_instance_id = (
            boundary_snapshot.get(
                "stream_instance_id"
            )
        )
        recording_timing_segment_id = (
            boundary_snapshot.get(
                "timing_segment_id"
            )
        )

        association["same_stream_instance"] = bool(
            recording_stream_instance_id
            ==
            model.get(
                "stream_instance_id"
            )
        )
        association["same_timing_segment"] = bool(
            recording_timing_segment_id
            ==
            model.get(
                "timing_segment_id"
            )
        )

        try:
            guarded_start_sample = float(
                recording[
                    "guarded_stream_start_sample"
                ]
            )
            guarded_end_sample = float(
                recording[
                    (
                        "guarded_stream_end_"
                        "sample_exclusive"
                    )
                ]
            )

            association[
                "guarded_range_valid"
            ] = bool(
                guarded_end_sample
                >
                guarded_start_sample
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            guarded_start_sample = None
            guarded_end_sample = None

        nearby_anchors = []

        if (
            guarded_start_sample is not None
            and
            guarded_end_sample is not None
            and
            association[
                "guarded_range_valid"
            ]
        ):
            margin_samples = (
                self.nominal_sample_rate_hz
                *
                self.maximum_recording_extrapolation_sec
            )

            nearby_anchors = [
                item
                for item in anchors
                if (
                    guarded_start_sample
                    -
                    margin_samples
                    <=
                    item["sample_position"]
                    <=
                    guarded_end_sample
                    +
                    margin_samples
                )
            ]

            if len(nearby_anchors) < 2:
                nearby_anchors = sorted(
                    anchors,
                    key=lambda item: min(
                        abs(
                            item["sample_position"]
                            -
                            guarded_start_sample
                        ),
                        abs(
                            item["sample_position"]
                            -
                            guarded_end_sample
                        ),
                    ),
                )[:4]

            coverage = model.get(
                "coverage",
                {},
            )

            if not isinstance(
                coverage,
                dict,
            ):
                coverage = {}

            try:
                first_model_sample = float(
                    coverage[
                        "first_sample"
                    ]
                )
                last_model_sample = float(
                    coverage[
                        "last_sample"
                    ]
                )

                allowed_extrapolation_samples = (
                    model[
                        "effective_sample_rate_hz"
                    ]
                    *
                    self.maximum_recording_extrapolation_sec
                )

                association[
                    (
                        "guarded_range_within_"
                        "extrapolation_limit"
                    )
                ] = bool(
                    guarded_start_sample
                    >=
                    (
                        first_model_sample
                        -
                        allowed_extrapolation_samples
                    )
                    and
                    guarded_end_sample
                    <=
                    (
                        last_model_sample
                        +
                        allowed_extrapolation_samples
                    )
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                pass

        fit_residual_by_sequence = {
            item.get(
                "pps_seq"
            ): item
            for item in model.get(
                "fit_residuals",
                []
            )
            if isinstance(
                item,
                dict,
            )
        }

        nearby_anchors = [
            {
                **item,
                **copy.deepcopy(
                    fit_residual_by_sequence.get(
                        item.get(
                            "pps_seq"
                        ),
                        {},
                    )
                ),
            }
            for item in nearby_anchors
        ]

        association["nearby_anchor_count"] = len(
            nearby_anchors
        )

        model_quality = model.get(
            "quality",
            {},
        )

        if not isinstance(
            model_quality,
            dict,
        ):
            model_quality = {}

        model_valid = bool(
            model_quality.get(
                "status"
            )
            ==
            "PASS"
            and
            model_quality.get(
                "model_valid",
                False,
            )
            and
            association[
                "same_stream_instance"
            ]
            and
            association[
                "same_timing_segment"
            ]
            and
            association[
                "guarded_range_valid"
            ]
            and
            association[
                (
                    "guarded_range_within_"
                    "extrapolation_limit"
                )
            ]
            and
            len(
                nearby_anchors
            )
            >=
            2
        )

        association["model_valid"] = (
            model_valid
        )

        if not association[
            "same_stream_instance"
        ]:
            association[
                "quality_reasons"
            ].append(
                "recording_stream_mismatch"
            )

        if not association[
            "same_timing_segment"
        ]:
            association[
                "quality_reasons"
            ].append(
                "recording_timing_segment_mismatch"
            )

        if not association[
            "guarded_range_valid"
        ]:
            association[
                "quality_reasons"
            ].append(
                "guarded_sample_range_invalid"
            )

        if not association[
            (
                "guarded_range_within_"
                "extrapolation_limit"
            )
        ]:
            association[
                "quality_reasons"
            ].append(
                (
                    "guarded_range_outside_"
                    "model_limit"
                )
            )

        if len(nearby_anchors) < 2:
            association[
                "quality_reasons"
            ].append(
                "insufficient_nearby_anchors"
            )

        if (
            model_quality.get(
                "status"
            )
            !=
            "PASS"
        ):
            association[
                "quality_reasons"
            ].append(
                "clock_model_not_pass"
            )

        recording.update(
            {
                "timing_state": (
                    "pps_clock_modeled_raw"
                    if model_valid
                    else
                    "pps_clock_model_unqualified"
                ),
                "clock_model_id": model.get(
                    "model_id"
                ),
                "clock_model_quality": (
                    model_quality.get(
                        "status"
                    )
                ),
                "clock_model": model,
                "nearby_pps_anchors": (
                    nearby_anchors
                ),
                "clock_model_association": (
                    association
                ),
            }
        )

        self.persist_latest_model()

        return recording

    # --------------------------------------------------
    # Status and Persistence
    # --------------------------------------------------

    def get_latest_model(
        self,
    ):

        with self._lock:
            return copy.deepcopy(
                self._latest_model
            )

    def persist_latest_model(
        self,
    ):

        model = self.get_latest_model()

        if not isinstance(
            model,
            dict,
        ):
            return False

        try:
            self.output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            temporary_path = (
                self.output_path.with_suffix(
                    self.output_path.suffix
                    +
                    ".tmp"
                )
            )

            with open(
                temporary_path,
                "w",
                encoding="utf-8",
            ) as output_file:
                json.dump(
                    model,
                    output_file,
                    indent=4,
                    allow_nan=False,
                )
                output_file.write(
                    "\n"
                )

            temporary_path.replace(
                self.output_path
            )

            return True

        except Exception as error:
            self.log(
                (
                    "Clock model persistence failed: "
                    f"{type(error).__name__}: {error}"
                )
            )

            return False

    def _reset_locked(
        self,
        reason,
    ):

        self._anchors = []
        self._latest_model = None
        self._stream_instance_id = None
        self._timing_segment_id = None
        self._last_reset_reason = str(
            reason
        )
        self._reset_count += 1

        self.log(
            (
                "Clock fit reset: "
                f"reason={reason} "
                f"reset_count={self._reset_count}"
            )
        )

    def _utc_now(
        self,
    ):

        return (
            datetime.now(
                timezone.utc
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        )

    def _epoch_ns_to_utc(
        self,
        epoch_ns,
    ):

        return (
            datetime.fromtimestamp(
                int(
                    epoch_ns
                )
                /
                1_000_000_000,
                timezone.utc,
            )
            .isoformat(
                timespec="microseconds"
            )
            .replace(
                "+00:00",
                "Z",
            )
        )
