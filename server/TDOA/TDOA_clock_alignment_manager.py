# ============================================================
# TDOA_clock_alignment_manager.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Role:
#   Manager
#
# Purpose:
#   Map request-scoped guarded WAV files onto one common UTC sample grid.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["tdoa_clock_alignment"]
#
# Does:
#   - Validate recording-time sample-clock evidence
#   - Preserve immutable guarded WAV inputs
#   - Resample each accepted input onto one canonical UTC grid
#   - Write derived aligned WAV and JSON evidence files
#   - Return a calculation-ready complete set or a structured failure
#
# Does NOT:
#   - Subscribe to or publish events
#   - Decide when alignment workflow runs
#   - Modify node recordings or clock models
#   - Perform TDOA event detection or localization
#
# Owner:
#   TDOA_dispatcher.py
#
# ============================================================

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import copy
import hashlib
import json
import math
import os
import uuid
import wave

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from scipy.signal import butter, sosfiltfilt


# ============================================================
# EXCEPTIONS
# ============================================================

class ClockAlignmentError(Exception):
    """
    One machine-readable recording alignment rejection.
    """

    def __init__(
        self,
        reason,
        detail
    ):

        super().__init__(
            detail
        )

        self.reason = str(
            reason
        )

        self.detail = str(
            detail
        )


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class TDOAClockAlignmentManager:
    """
    Perform Block 8 server-side clock alignment.

    The dispatcher owns workflow. This manager performs one bounded
    transformation and returns all evidence needed for the dispatcher to
    publish either TDOA_COMPLETE_SET or TDOA_REQUEST_FAILED.
    """

    MODEL_SCHEMA = (
        "enviro_pulse_sample_clock_model_v1"
    )

    FIT_WINDOW_POLICY = (
        "rolling_recent_utc"
    )

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        config=None
    ):

        self.config = copy.deepcopy(
            config
            if isinstance(
                config,
                dict
            )
            else {}
        )

        alignment_config = self.config.get(
            "tdoa_clock_alignment",
            {}
        )

        subsystem_config = self.config.get(
            "tdoa_subsystem",
            {}
        )

        self.target_sample_rate_hz = self._positive_int(
            alignment_config.get(
                "target_sample_rate_hz",
                subsystem_config.get(
                    "default_sample_rate_hz",
                    48000
                )
            ),
            "target_sample_rate_hz"
        )

        self.target_duration_seconds = self._positive_float(
            alignment_config.get(
                "target_duration_seconds",
                15.0
            ),
            "target_duration_seconds"
        )

        self.minimum_aligned_recordings = self._positive_int(
            alignment_config.get(
                "minimum_aligned_recordings",
                subsystem_config.get(
                    "minimum_tdoa_nodes",
                    4
                )
            ),
            "minimum_aligned_recordings"
        )

        self.maximum_model_residual_p95_us = (
            self._positive_float(
                alignment_config.get(
                    "maximum_model_residual_p95_us",
                    1000.0
                ),
                "maximum_model_residual_p95_us"
            )
        )

        self.scheduled_time_tolerance_us = (
            self._nonnegative_float(
                alignment_config.get(
                    "scheduled_time_tolerance_us",
                    10.0
                ),
                "scheduled_time_tolerance_us"
            )
        )

        self.scheduled_time_tolerance_ns = int(
            round(
                self.scheduled_time_tolerance_us
                *
                1000.0
            )
        )

        self.anti_alias_trigger_ratio = self._positive_float(
            alignment_config.get(
                "anti_alias_trigger_ratio",
                1.01
            ),
            "anti_alias_trigger_ratio"
        )

        if self.anti_alias_trigger_ratio < 1.0:
            raise ValueError(
                "anti_alias_trigger_ratio must be at least 1.0."
            )

        self.anti_alias_cutoff_ratio = self._positive_float(
            alignment_config.get(
                "anti_alias_cutoff_ratio",
                0.95
            ),
            "anti_alias_cutoff_ratio"
        )

        if self.anti_alias_cutoff_ratio >= 1.0:
            raise ValueError(
                "anti_alias_cutoff_ratio must be less than 1.0."
            )

        self.anti_alias_filter_order = self._positive_int(
            alignment_config.get(
                "anti_alias_filter_order",
                8
            ),
            "anti_alias_filter_order"
        )

        self.target_frame_count = int(
            round(
                self.target_duration_seconds
                *
                self.target_sample_rate_hz
            )
        )

        if self.target_frame_count < 1:
            raise ValueError(
                "Clock alignment target frame count must be positive."
            )

        represented_duration_seconds = (
            self.target_frame_count
            /
            float(
                self.target_sample_rate_hz
            )
        )

        if not math.isclose(
            represented_duration_seconds,
            self.target_duration_seconds,
            rel_tol=0.0,
            abs_tol=1e-12
        ):
            raise ValueError(
                "target_duration_seconds must produce an exact integer "
                "target frame count."
            )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def align_complete_set(
        self,
        raw_complete_set
    ):
        """
        Align every eligible recording in one raw collection result.
        """

        if not isinstance(
            raw_complete_set,
            dict
        ):
            raise TypeError(
                "raw_complete_set must be a dictionary."
            )

        raw_recording_events = raw_complete_set.get(
            "recording_events",
            []
        )

        if not isinstance(
            raw_recording_events,
            list
        ):
            raise TypeError(
                "raw complete-set recording_events must be a list."
            )

        try:

            target_start_ns = self._select_target_start_ns(
                raw_recording_events
            )

            target_grid = self._build_target_grid(
                target_start_ns
            )

        except ClockAlignmentError as error:

            alignment_results = [
                self._rejected_result(
                    recording_event=recording_event,
                    reason=error.reason,
                    detail=error.detail
                )
                for recording_event in sorted(
                    raw_recording_events,
                    key=self._event_sort_key
                )
            ]

            alignment_summary = {
                "schema_version": 1,
                "status": "FAIL",
                "target_grid": None,
                "input_recording_count": len(
                    raw_recording_events
                ),
                "aligned_recording_count": 0,
                "rejected_recording_count": len(
                    alignment_results
                ),
                "required_aligned_recordings": (
                    self.minimum_aligned_recordings
                ),
                "aligned_node_ids": [],
                "rejected_node_ids": [
                    result.get(
                        "node_id"
                    )
                    for result in alignment_results
                ],
                "recording_results": alignment_results,
                "completed_at_utc": self._utc_now()
            }

            failure_payload = self._build_failure_payload(
                raw_complete_set=raw_complete_set,
                passed_results=[],
                alignment_summary=alignment_summary
            )

            return {
                "success": False,
                "status": "failed",
                "failure_reason": (
                    "clock_alignment_below_quorum"
                ),
                "complete_set": None,
                "failure_payload": failure_payload,
                "clock_alignment": alignment_summary
            }

        alignment_results = []

        for recording_event in sorted(
            raw_recording_events,
            key=self._event_sort_key
        ):

            try:

                aligned_result = self._align_recording_event(
                    recording_event=recording_event,
                    target_grid=target_grid
                )

            except ClockAlignmentError as error:

                aligned_result = self._rejected_result(
                    recording_event=recording_event,
                    reason=error.reason,
                    detail=error.detail
                )

            except Exception as error:

                aligned_result = self._rejected_result(
                    recording_event=recording_event,
                    reason="clock_alignment_exception",
                    detail=(
                        f"{type(error).__name__}: {error}"
                    )
                )

            alignment_results.append(
                aligned_result
            )

        alignment_results = (
            self._enforce_common_output_geometry(
                alignment_results
            )
        )

        passed_results = [
            result
            for result in alignment_results
            if result.get(
                "success",
                False
            )
        ]

        rejected_results = [
            result
            for result in alignment_results
            if not result.get(
                "success",
                False
            )
        ]

        alignment_summary = {
            "schema_version": 1,
            "status": (
                "PASS"
                if len(
                    passed_results
                )
                >=
                self.minimum_aligned_recordings
                else
                "FAIL"
            ),
            "target_grid": copy.deepcopy(
                target_grid
            ),
            "input_recording_count": len(
                raw_recording_events
            ),
            "aligned_recording_count": len(
                passed_results
            ),
            "rejected_recording_count": len(
                rejected_results
            ),
            "required_aligned_recordings": (
                self.minimum_aligned_recordings
            ),
            "aligned_node_ids": [
                result.get(
                    "node_id"
                )
                for result in passed_results
            ],
            "rejected_node_ids": [
                result.get(
                    "node_id"
                )
                for result in rejected_results
            ],
            "recording_results": copy.deepcopy(
                alignment_results
            ),
            "completed_at_utc": self._utc_now()
        }

        if (
            len(
                passed_results
            )
            <
            self.minimum_aligned_recordings
        ):

            failure_payload = self._build_failure_payload(
                raw_complete_set=raw_complete_set,
                passed_results=passed_results,
                alignment_summary=alignment_summary
            )

            return {
                "success": False,
                "status": "failed",
                "failure_reason": (
                    "clock_alignment_below_quorum"
                ),
                "complete_set": None,
                "failure_payload": failure_payload,
                "clock_alignment": alignment_summary
            }

        complete_set = self._build_aligned_complete_set(
            raw_complete_set=raw_complete_set,
            passed_results=passed_results,
            alignment_summary=alignment_summary
        )

        return {
            "success": True,
            "status": "complete",
            "failure_reason": None,
            "complete_set": complete_set,
            "failure_payload": None,
            "clock_alignment": alignment_summary
        }

    # ========================================================
    # RECORDING ALIGNMENT
    # ========================================================

    def _align_recording_event(
        self,
        recording_event,
        target_grid
    ):

        payload = self._payload(
            recording_event
        )

        node_id = self._required_identity(
            payload.get(
                "node_id"
            )
            or
            recording_event.get(
                "node_id"
            ),
            "node_id"
        )

        recording_id = self._required_identity(
            payload.get(
                "recording_id"
            )
            or
            recording_event.get(
                "recording_id"
            ),
            "recording_id"
        )

        self._validate_recording_state(
            payload
        )

        scheduled_start_ns = self._scheduled_start_ns(
            payload
        )

        if (
            abs(
                scheduled_start_ns
                -
                target_grid[
                    "start_utc_ns"
                ]
            )
            >
            self.scheduled_time_tolerance_ns
        ):
            raise ClockAlignmentError(
                "scheduled_start_mismatch",
                (
                    f"{node_id} scheduled_start_utc does not match "
                    "the canonical complete-set UTC grid."
                )
            )

        self._validate_recording_time_lineage(
            payload=payload,
            scheduled_start_ns=scheduled_start_ns,
            target_end_ns=target_grid[
                "end_utc_ns"
            ]
        )

        raw_path = self._raw_wav_path(
            payload
        )

        raw_sha256_before = self._sha256_file(
            raw_path
        )

        self._validate_server_checksum(
            payload=payload,
            raw_sha256=raw_sha256_before
        )

        (
            source_audio,
            wav_properties
        ) = self._read_pcm_wav(
            raw_path
        )

        self._validate_wav_metadata(
            payload=payload,
            wav_properties=wav_properties
        )

        model = self._validate_clock_model(
            payload=payload,
            node_id=node_id,
            source_sample_rate_hz=wav_properties[
                "sample_rate_hz"
            ]
        )

        guarded_start_sample = self._strict_int(
            payload.get(
                "guarded_stream_start_sample"
            ),
            "guarded_stream_start_sample"
        )

        guarded_end_sample = self._strict_int(
            payload.get(
                "guarded_stream_end_sample_exclusive"
            ),
            "guarded_stream_end_sample_exclusive"
        )

        if (
            guarded_end_sample
            -
            guarded_start_sample
            !=
            wav_properties[
                "frame_count"
            ]
        ):
            raise ClockAlignmentError(
                "guarded_sample_range_mismatch",
                (
                    f"{node_id} guarded stream range does not equal "
                    "the raw WAV frame count."
                )
            )

        sample_to_utc = model[
            "sample_to_utc"
        ]

        origin_sample = self._finite_float(
            sample_to_utc.get(
                "origin_sample"
            ),
            "clock_model.sample_to_utc.origin_sample"
        )

        origin_utc_ns = self._strict_int(
            sample_to_utc.get(
                "origin_utc_ns"
            ),
            "clock_model.sample_to_utc.origin_utc_ns"
        )

        ns_per_sample = self._positive_float(
            sample_to_utc.get(
                "ns_per_sample"
            ),
            "clock_model.sample_to_utc.ns_per_sample"
        )

        target_start_sample_absolute = (
            origin_sample
            +
            (
                target_grid[
                    "start_utc_ns"
                ]
                -
                origin_utc_ns
            )
            /
            ns_per_sample
        )

        source_samples_per_output_sample = (
            (
                1_000_000_000.0
                /
                self.target_sample_rate_hz
            )
            /
            ns_per_sample
        )

        target_start_sample_relative = (
            target_start_sample_absolute
            -
            guarded_start_sample
        )

        target_last_sample_relative = (
            target_start_sample_relative
            +
            (
                self.target_frame_count
                -
                1
            )
            *
            source_samples_per_output_sample
        )

        self._validate_source_coverage(
            node_id=node_id,
            first_source_sample_relative=(
                target_start_sample_relative
            ),
            last_source_sample_relative=(
                target_last_sample_relative
            ),
            source_frame_count=wav_properties[
                "frame_count"
            ]
        )

        source_positions = (
            target_start_sample_relative
            +
            np.arange(
                self.target_frame_count,
                dtype=np.float64
            )
            *
            source_samples_per_output_sample
        )

        effective_sample_rate_hz = self._positive_float(
            model.get(
                "effective_sample_rate_hz"
            ),
            "clock_model.effective_sample_rate_hz"
        )

        (
            aligned_audio,
            resampling_method
        ) = self._interpolate_audio(
            source_audio=source_audio,
            source_positions=source_positions,
            effective_sample_rate_hz=(
                effective_sample_rate_hz
            )
        )

        aligned_wav_path = self._aligned_wav_path(
            raw_path=raw_path
        )

        self._write_pcm_wav_atomic(
            wav_path=aligned_wav_path,
            audio=aligned_audio,
            channels=wav_properties[
                "channels"
            ],
            sample_width_bytes=wav_properties[
                "sample_width_bytes"
            ]
        )

        self._validate_aligned_wav(
            wav_path=aligned_wav_path,
            expected_channels=wav_properties[
                "channels"
            ],
            expected_sample_width_bytes=wav_properties[
                "sample_width_bytes"
            ]
        )

        raw_sha256_after = self._sha256_file(
            raw_path
        )

        if raw_sha256_after != raw_sha256_before:
            raise ClockAlignmentError(
                "raw_wav_changed",
                (
                    f"{node_id} raw guarded WAV changed during "
                    "clock alignment."
                )
            )

        aligned_sha256 = self._sha256_file(
            aligned_wav_path
        )

        alignment_evidence = {
            "schema_version": 1,
            "status": "PASS",
            "node_id": node_id,
            "recording_id": recording_id,
            "timing_authority": "scheduled_start_utc",
            "target_grid": copy.deepcopy(
                target_grid
            ),
            "source": {
                "raw_wav_path": str(
                    raw_path
                ),
                "raw_wav_sha256_before": (
                    raw_sha256_before
                ),
                "raw_wav_sha256_after": (
                    raw_sha256_after
                ),
                "raw_wav_immutable": True,
                "sample_rate_hz": wav_properties[
                    "sample_rate_hz"
                ],
                "channels": wav_properties[
                    "channels"
                ],
                "sample_width_bytes": wav_properties[
                    "sample_width_bytes"
                ],
                "frame_count": wav_properties[
                    "frame_count"
                ],
                "guarded_stream_start_sample": (
                    guarded_start_sample
                ),
                "guarded_stream_end_sample_exclusive": (
                    guarded_end_sample
                ),
                "target_first_source_sample_absolute": (
                    target_start_sample_absolute
                ),
                "target_last_source_sample_absolute": (
                    guarded_start_sample
                    +
                    target_last_sample_relative
                ),
                "target_first_source_sample_relative": (
                    target_start_sample_relative
                ),
                "target_last_source_sample_relative": (
                    target_last_sample_relative
                )
            },
            "output": {
                "aligned_wav_path": str(
                    aligned_wav_path
                ),
                "aligned_wav_sha256": aligned_sha256,
                "sample_rate_hz": (
                    self.target_sample_rate_hz
                ),
                "channels": wav_properties[
                    "channels"
                ],
                "sample_width_bytes": wav_properties[
                    "sample_width_bytes"
                ],
                "frame_count": (
                    self.target_frame_count
                ),
                "duration_seconds": (
                    self.target_duration_seconds
                )
            },
            "clock_model": {
                "schema": model.get(
                    "schema"
                ),
                "model_id": model.get(
                    "model_id"
                ),
                "quality": copy.deepcopy(
                    model.get(
                        "quality",
                        {}
                    )
                ),
                "coverage": copy.deepcopy(
                    model.get(
                        "coverage",
                        {}
                    )
                ),
                "nominal_sample_rate_hz": model.get(
                    "nominal_sample_rate_hz"
                ),
                "effective_sample_rate_hz": (
                    effective_sample_rate_hz
                ),
                "sample_rate_error_ppm": model.get(
                    "sample_rate_error_ppm"
                ),
                "sample_to_utc": copy.deepcopy(
                    sample_to_utc
                )
            },
            "clock_model_association": copy.deepcopy(
                payload.get(
                    "clock_model_association",
                    {}
                )
            ),
            "nearby_pps_anchors": copy.deepcopy(
                payload.get(
                    "nearby_pps_anchors",
                    []
                )
            ),
            "resampling": {
                "method": resampling_method,
                "source_samples_per_output_sample": (
                    source_samples_per_output_sample
                ),
                "output_samples_per_source_sample": (
                    1.0
                    /
                    source_samples_per_output_sample
                ),
                "sample_rate_correction_ratio": (
                    self.target_sample_rate_hz
                    /
                    effective_sample_rate_hz
                ),
                "anti_alias_trigger_ratio": (
                    self.anti_alias_trigger_ratio
                ),
                "anti_alias_cutoff_ratio": (
                    self.anti_alias_cutoff_ratio
                ),
                "anti_alias_filter_order": (
                    self.anti_alias_filter_order
                )
            },
            "created_at_utc": self._utc_now()
        }

        aligned_metadata_path = (
            aligned_wav_path.with_suffix(
                ".json"
            )
        )

        alignment_evidence[
            "output"
        ][
            "aligned_metadata_path"
        ] = str(
            aligned_metadata_path
        )

        self._write_json_atomic(
            path=aligned_metadata_path,
            payload=alignment_evidence
        )

        event_alignment_evidence = (
            self._compact_alignment_evidence(
                alignment_evidence
            )
        )

        aligned_event = self._build_aligned_event(
            recording_event=recording_event,
            payload=payload,
            aligned_wav_path=aligned_wav_path,
            aligned_metadata_path=aligned_metadata_path,
            alignment_evidence=event_alignment_evidence,
            wav_properties=wav_properties
        )

        aligned_reference = self._build_aligned_reference(
            aligned_event=aligned_event,
            alignment_evidence=event_alignment_evidence
        )

        return {
            "success": True,
            "status": "PASS",
            "node_id": node_id,
            "recording_id": recording_id,
            "failure_reason": None,
            "failure_detail": None,
            "aligned_wav_path": str(
                aligned_wav_path
            ),
            "aligned_metadata_path": str(
                aligned_metadata_path
            ),
            "raw_wav_path": str(
                raw_path
            ),
            "alignment_evidence": event_alignment_evidence,
            "event": aligned_event,
            "reference": aligned_reference
        }

    # ========================================================
    # VALIDATION
    # ========================================================

    def _validate_recording_state(
        self,
        payload
    ):

        if str(
            payload.get(
                "status",
                ""
            )
        ).strip().lower() != "success":
            raise ClockAlignmentError(
                "recording_status_not_success",
                "Only successful TDOA recordings may be aligned."
            )

        if str(
            payload.get(
                "validation_status",
                ""
            )
        ).strip().lower() != "accepted":
            raise ClockAlignmentError(
                "server_validation_missing",
                "The recording was not accepted by Server Communication."
            )

        if payload.get(
            "recording_engine"
        ) != "continuous_pps":
            raise ClockAlignmentError(
                "recording_engine_invalid",
                "Clock alignment requires recording_engine=continuous_pps."
            )

        if payload.get(
            "continuous_stream"
        ) is not True:
            raise ClockAlignmentError(
                "continuous_stream_required",
                "Clock alignment requires a continuous microphone stream."
            )

        if payload.get(
            "raw_wav_immutable"
        ) is not True:
            raise ClockAlignmentError(
                "raw_wav_not_immutable",
                "The source recording is not marked immutable."
            )

        if payload.get(
            "audio_correction_state"
        ) != "raw_unmodified":
            raise ClockAlignmentError(
                "raw_wav_already_corrected",
                "Block 8 accepts only unmodified guarded source audio."
            )

        if str(
            payload.get(
                "raw_timing_quality",
                ""
            )
        ).strip().upper() != "CLEAN":
            raise ClockAlignmentError(
                "raw_timing_quality_not_clean",
                "The guarded source window has degraded timing evidence."
            )

        timing_issues = payload.get(
            "timing_issues"
        )

        if (
            not isinstance(
                timing_issues,
                list
            )
            or
            timing_issues
        ):
            raise ClockAlignmentError(
                "raw_timing_issues_present",
                "The guarded source window contains timing issues."
            )

        if payload.get(
            "corrected_tdoa_eligible"
        ) is not True:
            raise ClockAlignmentError(
                "recording_not_correction_eligible",
                "The node withheld corrected-TDOA eligibility."
            )

    def _validate_recording_time_lineage(
        self,
        payload,
        scheduled_start_ns,
        target_end_ns
    ):

        scheduled_start_epoch = self._finite_float(
            payload.get(
                "scheduled_start_epoch"
            ),
            "scheduled_start_epoch"
        )

        scheduled_epoch_ns = int(
            round(
                scheduled_start_epoch
                *
                1_000_000_000.0
            )
        )

        if (
            abs(
                scheduled_epoch_ns
                -
                scheduled_start_ns
            )
            >
            self.scheduled_time_tolerance_ns
        ):
            raise ClockAlignmentError(
                "scheduled_start_epoch_mismatch",
                "scheduled_start_epoch does not match scheduled_start_utc."
            )

        for field_name in (
            "recording_utc",
            "window_utc",
        ):

            field_value = payload.get(
                field_name
            )

            if field_value in (
                None,
                ""
            ):
                continue

            field_ns = self._parse_utc_ns(
                field_value,
                field_name
            )

            if (
                abs(
                    field_ns
                    -
                    scheduled_start_ns
                )
                >
                self.scheduled_time_tolerance_ns
            ):
                raise ClockAlignmentError(
                    "recording_time_lineage_mismatch",
                    (
                        f"{field_name} does not match "
                        "scheduled_start_utc."
                    )
                )

        boundary_ns = self._parse_utc_ns(
            payload.get(
                "boundary_utc"
            ),
            "boundary_utc"
        )

        if (
            abs(
                boundary_ns
                -
                target_end_ns
            )
            >
            self.scheduled_time_tolerance_ns
        ):
            raise ClockAlignmentError(
                "recording_boundary_mismatch",
                "boundary_utc does not equal the canonical interval end."
            )

    def _validate_clock_model(
        self,
        payload,
        node_id,
        source_sample_rate_hz
    ):

        if payload.get(
            "clock_model_quality"
        ) != "PASS":
            raise ClockAlignmentError(
                "clock_model_not_pass",
                "The recording-time clock model did not pass."
            )

        association = payload.get(
            "clock_model_association"
        )

        if not isinstance(
            association,
            dict
        ):
            raise ClockAlignmentError(
                "clock_model_association_missing",
                "The recording has no clock-model association evidence."
            )

        required_association_flags = (
            "model_valid",
            "same_stream_instance",
            "same_timing_segment",
            "guarded_range_valid",
            "guarded_range_within_extrapolation_limit",
        )

        failed_association_flags = [
            field_name
            for field_name in required_association_flags
            if association.get(
                field_name
            )
            is not True
        ]

        if failed_association_flags:
            raise ClockAlignmentError(
                "clock_model_association_invalid",
                (
                    "Clock-model association failed: "
                    +
                    ", ".join(
                        failed_association_flags
                    )
                )
            )

        nearby_anchors = payload.get(
            "nearby_pps_anchors"
        )

        if (
            not isinstance(
                nearby_anchors,
                list
            )
            or
            len(
                nearby_anchors
            )
            <
            2
        ):
            raise ClockAlignmentError(
                "nearby_pps_anchors_insufficient",
                "At least two nearby PPS/sample anchors are required."
            )

        model = payload.get(
            "clock_model"
        )

        if not isinstance(
            model,
            dict
        ):
            raise ClockAlignmentError(
                "clock_model_missing",
                "The recording-time clock model is missing."
            )

        if model.get(
            "schema"
        ) != self.MODEL_SCHEMA:
            raise ClockAlignmentError(
                "clock_model_schema_invalid",
                "The recording uses an unsupported clock-model schema."
            )

        model_id = self._required_identity(
            model.get(
                "model_id"
            ),
            "clock_model.model_id"
        )

        if model_id != self._required_identity(
            payload.get(
                "clock_model_id"
            ),
            "clock_model_id"
        ):
            raise ClockAlignmentError(
                "clock_model_id_mismatch",
                "clock_model_id does not match the attached model."
            )

        model_node_id = model.get(
            "node_id"
        )

        if (
            model_node_id not in (
                None,
                ""
            )
            and
            str(
                model_node_id
            )
            !=
            node_id
        ):
            raise ClockAlignmentError(
                "clock_model_node_mismatch",
                "The clock model belongs to another node."
            )

        quality = model.get(
            "quality"
        )

        if not isinstance(
            quality,
            dict
        ):
            raise ClockAlignmentError(
                "clock_model_quality_missing",
                "The clock model has no quality evidence."
            )

        if (
            quality.get(
                "status"
            )
            !=
            "PASS"
            or
            quality.get(
                "model_valid"
            )
            is not True
        ):
            raise ClockAlignmentError(
                "clock_model_not_pass",
                "The attached clock model is not valid PASS evidence."
            )

        if quality.get(
            "unresolved_discontinuity",
            False
        ):
            raise ClockAlignmentError(
                "clock_model_discontinuity_unresolved",
                "The clock model reports an unresolved discontinuity."
            )

        residual_p95_us = self._nonnegative_float(
            quality.get(
                "residual_p95_us"
            ),
            "clock_model.quality.residual_p95_us"
        )

        if (
            residual_p95_us
            >
            self.maximum_model_residual_p95_us
        ):
            raise ClockAlignmentError(
                "clock_model_residual_outside_limit",
                (
                    "Clock-model residual p95 exceeds the "
                    "configured Block 8 limit."
                )
            )

        coverage = model.get(
            "coverage"
        )

        if not isinstance(
            coverage,
            dict
        ):
            raise ClockAlignmentError(
                "clock_model_coverage_missing",
                "The clock model has no coverage evidence."
            )

        if coverage.get(
            "fit_window_policy"
        ) != self.FIT_WINDOW_POLICY:
            raise ClockAlignmentError(
                "clock_model_fit_window_invalid",
                "Block 8 requires the bounded rolling clock-fit policy."
            )

        nominal_sample_rate_hz = self._positive_float(
            model.get(
                "nominal_sample_rate_hz"
            ),
            "clock_model.nominal_sample_rate_hz"
        )

        if not math.isclose(
            nominal_sample_rate_hz,
            float(
                source_sample_rate_hz
            ),
            rel_tol=0.0,
            abs_tol=1e-6
        ):
            raise ClockAlignmentError(
                "clock_model_sample_rate_mismatch",
                "Clock-model nominal rate does not match the raw WAV."
            )

        self._positive_float(
            model.get(
                "effective_sample_rate_hz"
            ),
            "clock_model.effective_sample_rate_hz"
        )

        if not isinstance(
            model.get(
                "sample_to_utc"
            ),
            dict
        ):
            raise ClockAlignmentError(
                "clock_model_mapping_missing",
                "The clock model has no sample_to_utc mapping."
            )

        return model

    def _validate_server_checksum(
        self,
        payload,
        raw_sha256
    ):

        server_validation = payload.get(
            "server_validation",
            {}
        )

        if not isinstance(
            server_validation,
            dict
        ):
            return

        expected_sha256 = server_validation.get(
            "sha256"
        )

        if (
            expected_sha256 not in (
                None,
                ""
            )
            and
            str(
                expected_sha256
            ).lower()
            !=
            raw_sha256.lower()
        ):
            raise ClockAlignmentError(
                "raw_wav_checksum_mismatch",
                "The raw WAV no longer matches Server Communication evidence."
            )

    def _validate_wav_metadata(
        self,
        payload,
        wav_properties
    ):

        comparisons = (
            (
                "channels",
                payload.get(
                    "channels"
                ),
                wav_properties[
                    "channels"
                ],
            ),
            (
                "sample_rate",
                (
                    payload.get(
                        "sample_rate_hz"
                    )
                    or
                    payload.get(
                        "sample_rate"
                    )
                ),
                wav_properties[
                    "sample_rate_hz"
                ],
            ),
            (
                "frame_count",
                (
                    payload.get(
                        "guarded_frame_count"
                    )
                    or
                    payload.get(
                        "frame_count"
                    )
                ),
                wav_properties[
                    "frame_count"
                ],
            ),
        )

        for (
            field_name,
            metadata_value,
            wav_value,
        ) in comparisons:

            if self._strict_int(
                metadata_value,
                field_name
            ) != wav_value:
                raise ClockAlignmentError(
                    "raw_wav_metadata_mismatch",
                    (
                        f"Raw WAV {field_name} does not match "
                        "the uploaded timing metadata."
                    )
                )

    def _validate_source_coverage(
        self,
        node_id,
        first_source_sample_relative,
        last_source_sample_relative,
        source_frame_count
    ):

        epsilon = 1e-6

        if (
            first_source_sample_relative
            <
            -epsilon
            or
            last_source_sample_relative
            >
            (
                source_frame_count
                -
                1
                +
                epsilon
            )
        ):
            raise ClockAlignmentError(
                "canonical_grid_outside_guarded_wav",
                (
                    f"{node_id} guarded WAV does not cover the entire "
                    "canonical 15-second UTC grid."
                )
            )

    # ========================================================
    # PCM WAV IO
    # ========================================================

    def _read_pcm_wav(
        self,
        wav_path
    ):

        try:

            with wave.open(
                str(
                    wav_path
                ),
                "rb"
            ) as wav_file:

                channels = wav_file.getnchannels()
                sample_width_bytes = wav_file.getsampwidth()
                sample_rate_hz = wav_file.getframerate()
                frame_count = wav_file.getnframes()
                compression_type = wav_file.getcomptype()

                raw_audio = wav_file.readframes(
                    frame_count
                )

        except (
            EOFError,
            OSError,
            wave.Error,
        ) as error:
            raise ClockAlignmentError(
                "raw_wav_unreadable",
                f"Raw guarded WAV is unreadable: {error}"
            ) from error

        if compression_type != "NONE":
            raise ClockAlignmentError(
                "raw_wav_compressed",
                "Clock alignment requires uncompressed PCM WAV input."
            )

        if sample_width_bytes == 2:
            dtype = np.dtype(
                "<i2"
            )

        elif sample_width_bytes == 4:
            dtype = np.dtype(
                "<i4"
            )

        else:
            raise ClockAlignmentError(
                "raw_wav_sample_width_unsupported",
                (
                    "Clock alignment supports 16-bit and 32-bit "
                    "integer PCM WAV input."
                )
            )

        samples = np.frombuffer(
            raw_audio,
            dtype=dtype
        )

        expected_sample_count = (
            frame_count
            *
            channels
        )

        if samples.size != expected_sample_count:
            raise ClockAlignmentError(
                "raw_wav_truncated",
                "Raw guarded WAV PCM data is truncated."
            )

        audio = samples.reshape(
            frame_count,
            channels
        )

        return (
            audio,
            {
                "channels": channels,
                "sample_width_bytes": sample_width_bytes,
                "sample_rate_hz": sample_rate_hz,
                "frame_count": frame_count,
                "duration_seconds": (
                    frame_count
                    /
                    float(
                        sample_rate_hz
                    )
                )
            }
        )

    def _interpolate_audio(
        self,
        source_audio,
        source_positions,
        effective_sample_rate_hz
    ):

        working_audio = source_audio.astype(
            np.float64,
            copy=False
        )

        resampling_method = (
            "linear_interpolation"
        )

        if (
            effective_sample_rate_hz
            >
            (
                self.target_sample_rate_hz
                *
                self.anti_alias_trigger_ratio
            )
        ):

            normalized_cutoff = (
                self.anti_alias_cutoff_ratio
                *
                self.target_sample_rate_hz
                /
                effective_sample_rate_hz
            )

            if (
                normalized_cutoff
                <=
                0.0
                or
                normalized_cutoff
                >=
                1.0
            ):
                raise ClockAlignmentError(
                    "anti_alias_filter_invalid",
                    "Could not design the required anti-alias filter."
                )

            filter_sections = butter(
                self.anti_alias_filter_order,
                normalized_cutoff,
                btype="lowpass",
                output="sos"
            )

            working_audio = sosfiltfilt(
                filter_sections,
                working_audio,
                axis=0
            )

            resampling_method = (
                "zero_phase_lowpass_then_linear_interpolation"
            )

        source_frame_positions = np.arange(
            working_audio.shape[
                0
            ],
            dtype=np.float64
        )

        aligned_channels = []

        for channel_index in range(
            working_audio.shape[
                1
            ]
        ):

            aligned_channel = np.interp(
                source_positions,
                source_frame_positions,
                working_audio[
                    :,
                    channel_index
                ]
            )

            aligned_channels.append(
                aligned_channel
            )

        return (
            np.column_stack(
                aligned_channels
            ),
            resampling_method
        )

    def _write_pcm_wav_atomic(
        self,
        wav_path,
        audio,
        channels,
        sample_width_bytes
    ):

        if sample_width_bytes == 2:
            minimum_value = -(1 << 15)
            maximum_value = (1 << 15) - 1
            dtype = np.dtype(
                "<i2"
            )

        elif sample_width_bytes == 4:
            minimum_value = -(1 << 31)
            maximum_value = (1 << 31) - 1
            dtype = np.dtype(
                "<i4"
            )

        else:
            raise ClockAlignmentError(
                "aligned_wav_sample_width_unsupported",
                "Aligned output supports 16-bit and 32-bit integer PCM."
            )

        output = np.clip(
            np.rint(
                audio
            ),
            minimum_value,
            maximum_value
        ).astype(
            dtype
        )

        wav_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temporary_path = wav_path.with_name(
            wav_path.name
            +
            ".tmp-"
            +
            uuid.uuid4().hex
        )

        try:

            with wave.open(
                str(
                    temporary_path
                ),
                "wb"
            ) as wav_file:

                wav_file.setnchannels(
                    channels
                )

                wav_file.setsampwidth(
                    sample_width_bytes
                )

                wav_file.setframerate(
                    self.target_sample_rate_hz
                )

                wav_file.writeframes(
                    output.tobytes(
                        order="C"
                    )
                )

            os.replace(
                temporary_path,
                wav_path
            )

        finally:

            if temporary_path.exists():
                temporary_path.unlink()

    def _validate_aligned_wav(
        self,
        wav_path,
        expected_channels,
        expected_sample_width_bytes
    ):

        try:

            with wave.open(
                str(
                    wav_path
                ),
                "rb"
            ) as wav_file:

                channels = wav_file.getnchannels()
                sample_width_bytes = wav_file.getsampwidth()
                sample_rate_hz = wav_file.getframerate()
                frame_count = wav_file.getnframes()
                compression_type = wav_file.getcomptype()

                expected_pcm_bytes = (
                    frame_count
                    *
                    channels
                    *
                    sample_width_bytes
                )

                actual_pcm_bytes = 0

                while True:

                    block = wav_file.readframes(
                        65536
                    )

                    if not block:
                        break

                    actual_pcm_bytes += len(
                        block
                    )

        except (
            EOFError,
            OSError,
            wave.Error,
        ) as error:
            raise ClockAlignmentError(
                "aligned_wav_unreadable",
                f"Derived aligned WAV is unreadable: {error}"
            ) from error

        if (
            compression_type != "NONE"
            or
            channels != expected_channels
            or
            sample_width_bytes != expected_sample_width_bytes
            or
            sample_rate_hz != self.target_sample_rate_hz
            or
            frame_count != self.target_frame_count
            or
            actual_pcm_bytes != expected_pcm_bytes
        ):
            raise ClockAlignmentError(
                "aligned_wav_verification_failed",
                (
                    "Derived WAV does not match the canonical output "
                    "rate, channels, width, frame count, or PCM length."
                )
            )

    # ========================================================
    # EVENT AND RESULT BUILDING
    # ========================================================

    def _build_aligned_event(
        self,
        recording_event,
        payload,
        aligned_wav_path,
        aligned_metadata_path,
        alignment_evidence,
        wav_properties
    ):

        aligned_event = copy.deepcopy(
            recording_event
        )

        aligned_payload = copy.deepcopy(
            payload
        )

        raw_path = alignment_evidence[
            "source"
        ][
            "raw_wav_path"
        ]

        aligned_payload.update({
            "recording_path": str(
                aligned_wav_path
            ),
            "wav_path": str(
                aligned_wav_path
            ),
            "server_wav_path": str(
                aligned_wav_path
            ),
            "aligned_wav_path": str(
                aligned_wav_path
            ),
            "aligned_metadata_path": str(
                aligned_metadata_path
            ),
            "raw_server_wav_path": raw_path,
            "raw_guarded_wav_path": raw_path,
            "raw_wav_sha256": alignment_evidence[
                "source"
            ][
                "raw_wav_sha256_before"
            ],
            "aligned_wav_sha256": alignment_evidence[
                "output"
            ][
                "aligned_wav_sha256"
            ],
            "sample_rate": self.target_sample_rate_hz,
            "sample_rate_hz": self.target_sample_rate_hz,
            "channels": wav_properties[
                "channels"
            ],
            "sample_width_bytes": wav_properties[
                "sample_width_bytes"
            ],
            "duration_sec": self.target_duration_seconds,
            "duration_seconds": self.target_duration_seconds,
            "frame_count": self.target_frame_count,
            "timing_state": "utc_grid_aligned",
            "alignment_status": "PASS",
            "audio_correction_state": "utc_grid_aligned",
            "raw_wav_immutable": True,
            "corrected_tdoa_eligible": True,
            "alignment_evidence": copy.deepcopy(
                alignment_evidence
            )
        })

        aligned_event.update({
            "status": "success",
            "recording_path": str(
                aligned_wav_path
            ),
            "wav_path": str(
                aligned_wav_path
            ),
            "server_wav_path": str(
                aligned_wav_path
            ),
            "aligned_wav_path": str(
                aligned_wav_path
            ),
            "payload": aligned_payload
        })

        return aligned_event

    @staticmethod
    def _compact_alignment_evidence(
        alignment_evidence
    ):

        clock_model = alignment_evidence.get(
            "clock_model",
            {}
        )

        quality = clock_model.get(
            "quality",
            {}
        )

        association = alignment_evidence.get(
            "clock_model_association",
            {}
        )

        return {
            "schema_version": alignment_evidence.get(
                "schema_version"
            ),
            "status": alignment_evidence.get(
                "status"
            ),
            "node_id": alignment_evidence.get(
                "node_id"
            ),
            "recording_id": alignment_evidence.get(
                "recording_id"
            ),
            "timing_authority": alignment_evidence.get(
                "timing_authority"
            ),
            "target_grid": copy.deepcopy(
                alignment_evidence.get(
                    "target_grid",
                    {}
                )
            ),
            "source": copy.deepcopy(
                alignment_evidence.get(
                    "source",
                    {}
                )
            ),
            "output": copy.deepcopy(
                alignment_evidence.get(
                    "output",
                    {}
                )
            ),
            "clock_model": {
                "schema": clock_model.get(
                    "schema"
                ),
                "model_id": clock_model.get(
                    "model_id"
                ),
                "quality_status": quality.get(
                    "status"
                ),
                "model_valid": quality.get(
                    "model_valid"
                ),
                "residual_p95_us": quality.get(
                    "residual_p95_us"
                ),
                "residual_max_us": quality.get(
                    "residual_max_us"
                ),
                "nominal_sample_rate_hz": clock_model.get(
                    "nominal_sample_rate_hz"
                ),
                "effective_sample_rate_hz": clock_model.get(
                    "effective_sample_rate_hz"
                ),
                "sample_rate_error_ppm": clock_model.get(
                    "sample_rate_error_ppm"
                )
            },
            "clock_model_association": {
                "model_valid": association.get(
                    "model_valid"
                ),
                "same_stream_instance": association.get(
                    "same_stream_instance"
                ),
                "same_timing_segment": association.get(
                    "same_timing_segment"
                ),
                "guarded_range_valid": association.get(
                    "guarded_range_valid"
                ),
                (
                    "guarded_range_within_"
                    "extrapolation_limit"
                ): association.get(
                    (
                        "guarded_range_within_"
                        "extrapolation_limit"
                    )
                ),
                "nearby_anchor_count": association.get(
                    "nearby_anchor_count"
                )
            },
            "resampling": copy.deepcopy(
                alignment_evidence.get(
                    "resampling",
                    {}
                )
            ),
            "created_at_utc": alignment_evidence.get(
                "created_at_utc"
            )
        }

    def _build_aligned_reference(
        self,
        aligned_event,
        alignment_evidence
    ):

        payload = self._payload(
            aligned_event
        )

        return {
            "tdoa_request_id": payload.get(
                "tdoa_request_id"
            ),
            "request_id": payload.get(
                "tdoa_request_id"
            ),
            "node_id": payload.get(
                "node_id"
            ),
            "recording_id": payload.get(
                "recording_id"
            ),
            "server_wav_path": payload.get(
                "aligned_wav_path"
            ),
            "wav_path": payload.get(
                "aligned_wav_path"
            ),
            "recording_path": payload.get(
                "aligned_wav_path"
            ),
            "aligned_wav_path": payload.get(
                "aligned_wav_path"
            ),
            "aligned_metadata_path": payload.get(
                "aligned_metadata_path"
            ),
            "raw_server_wav_path": payload.get(
                "raw_server_wav_path"
            ),
            "raw_wav_sha256": payload.get(
                "raw_wav_sha256"
            ),
            "aligned_wav_sha256": payload.get(
                "aligned_wav_sha256"
            ),
            "sample_rate_hz": self.target_sample_rate_hz,
            "channels": payload.get(
                "channels"
            ),
            "sample_width_bytes": payload.get(
                "sample_width_bytes"
            ),
            "frame_count": self.target_frame_count,
            "duration_seconds": self.target_duration_seconds,
            "alignment_status": "PASS",
            "alignment_evidence": copy.deepcopy(
                alignment_evidence
            )
        }

    def _build_aligned_complete_set(
        self,
        raw_complete_set,
        passed_results,
        alignment_summary
    ):

        complete_set = copy.deepcopy(
            raw_complete_set
        )

        raw_recording_references = copy.deepcopy(
            raw_complete_set.get(
                "recording_references",
                []
            )
        )

        raw_recording_events = copy.deepcopy(
            raw_complete_set.get(
                "recording_events",
                []
            )
        )

        aligned_node_ids = [
            result[
                "node_id"
            ]
            for result in passed_results
        ]

        complete_set.update({
            "schema_version": 2,
            "success": True,
            "status": "complete",
            "failure_reason": None,
            "failure_detail": None,
            "raw_collection_closure_reason": (
                raw_complete_set.get(
                    "closure_reason"
                )
            ),
            "raw_valid_node_ids": copy.deepcopy(
                raw_complete_set.get(
                    "valid_node_ids",
                    []
                )
            ),
            "raw_valid_recording_count": len(
                raw_recording_events
            ),
            "raw_recording_references": (
                raw_recording_references
            ),
            "raw_recording_events": (
                raw_recording_events
            ),
            "valid_node_ids": aligned_node_ids,
            "valid_recording_count": len(
                passed_results
            ),
            "aligned_node_ids": aligned_node_ids,
            "aligned_recording_count": len(
                passed_results
            ),
            "alignment_rejected_node_ids": copy.deepcopy(
                alignment_summary[
                    "rejected_node_ids"
                ]
            ),
            "recording_references": [
                copy.deepcopy(
                    result[
                        "reference"
                    ]
                )
                for result in passed_results
            ],
            "recording_events": [
                copy.deepcopy(
                    result[
                        "event"
                    ]
                )
                for result in passed_results
            ],
            "clock_alignment": copy.deepcopy(
                alignment_summary
            )
        })

        return complete_set

    def _build_failure_payload(
        self,
        raw_complete_set,
        passed_results,
        alignment_summary
    ):

        failure_payload = copy.deepcopy(
            raw_complete_set
        )

        raw_recording_references = copy.deepcopy(
            raw_complete_set.get(
                "recording_references",
                []
            )
        )

        raw_recording_events = copy.deepcopy(
            raw_complete_set.get(
                "recording_events",
                []
            )
        )

        failure_payload.update({
            "schema_version": 2,
            "success": False,
            "status": "failed",
            "raw_collection_closure_reason": (
                raw_complete_set.get(
                    "closure_reason"
                )
            ),
            "closure_reason": (
                "clock_alignment_rejected"
            ),
            "failure_reason": (
                "clock_alignment_below_quorum"
            ),
            "failure_detail": (
                "Server clock alignment produced "
                f"{len(passed_results)} valid recordings; "
                f"{self.minimum_aligned_recordings} are required."
            ),
            "raw_valid_node_ids": copy.deepcopy(
                raw_complete_set.get(
                    "valid_node_ids",
                    []
                )
            ),
            "raw_valid_recording_count": len(
                raw_recording_events
            ),
            "raw_recording_references": (
                raw_recording_references
            ),
            "raw_recording_events": (
                raw_recording_events
            ),
            "valid_node_ids": [
                result[
                    "node_id"
                ]
                for result in passed_results
            ],
            "valid_recording_count": len(
                passed_results
            ),
            "aligned_node_ids": [
                result[
                    "node_id"
                ]
                for result in passed_results
            ],
            "aligned_recording_count": len(
                passed_results
            ),
            "alignment_rejected_node_ids": copy.deepcopy(
                alignment_summary[
                    "rejected_node_ids"
                ]
            ),
            "recording_references": [
                copy.deepcopy(
                    result[
                        "reference"
                    ]
                )
                for result in passed_results
            ],
            "recording_events": [
                copy.deepcopy(
                    result[
                        "event"
                    ]
                )
                for result in passed_results
            ],
            "clock_alignment": copy.deepcopy(
                alignment_summary
            )
        })

        return failure_payload

    def _rejected_result(
        self,
        recording_event,
        reason,
        detail
    ):

        payload = self._payload(
            recording_event
        )

        return {
            "success": False,
            "status": "FAIL",
            "node_id": (
                payload.get(
                    "node_id"
                )
                or
                recording_event.get(
                    "node_id"
                )
            ),
            "recording_id": (
                payload.get(
                    "recording_id"
                )
                or
                recording_event.get(
                    "recording_id"
                )
            ),
            "failure_reason": str(
                reason
            ),
            "failure_detail": str(
                detail
            ),
            "aligned_wav_path": None,
            "aligned_metadata_path": None,
            "raw_wav_path": (
                payload.get(
                    "server_wav_path"
                )
                or
                payload.get(
                    "guarded_wav_path"
                )
                or
                payload.get(
                    "wav_path"
                )
            )
        }

    def _enforce_common_output_geometry(
        self,
        alignment_results
    ):
        """
        Keep only the largest group with an identical channel count.

        Target sample rate, duration, and frame count are manager-owned
        constants. Channel count comes from each source WAV and must also be
        identical before a set can be calculation-ready.
        """

        successful_results = [
            result
            for result in alignment_results
            if result.get(
                "success",
                False
            )
        ]

        if not successful_results:
            return alignment_results

        groups = {}

        for result in successful_results:

            channels = (
                result.get(
                    "alignment_evidence",
                    {}
                )
                .get(
                    "output",
                    {}
                )
                .get(
                    "channels"
                )
            )

            groups.setdefault(
                channels,
                []
            ).append(
                result
            )

        selected_channels = sorted(
            groups,
            key=lambda channels: (
                -len(
                    groups[
                        channels
                    ]
                ),
                int(
                    channels
                )
                if channels is not None
                else
                0
            )
        )[
            0
        ]

        normalized_results = []

        for result in alignment_results:

            if not result.get(
                "success",
                False
            ):
                normalized_results.append(
                    result
                )
                continue

            channels = (
                result.get(
                    "alignment_evidence",
                    {}
                )
                .get(
                    "output",
                    {}
                )
                .get(
                    "channels"
                )
            )

            if channels == selected_channels:
                normalized_results.append(
                    result
                )
                continue

            rejected_result = copy.deepcopy(
                result
            )

            rejected_result.update({
                "success": False,
                "status": "FAIL",
                "failure_reason": (
                    "aligned_channel_count_mismatch"
                ),
                "failure_detail": (
                    "Aligned recording channel count does not match "
                    "the complete-set channel consensus."
                )
            })

            rejected_result.pop(
                "event",
                None
            )

            rejected_result.pop(
                "reference",
                None
            )

            normalized_results.append(
                rejected_result
            )

        return normalized_results

    # ========================================================
    # TARGET GRID
    # ========================================================

    def _select_target_start_ns(
        self,
        recording_events
    ):

        if not recording_events:
            raise ClockAlignmentError(
                "recording_set_empty",
                "Clock alignment received no recording events."
            )

        starts = []

        for recording_event in recording_events:

            payload = self._payload(
                recording_event
            )

            try:

                start_ns = self._scheduled_start_ns(
                    payload
                )

            except ClockAlignmentError:
                continue

            starts.append(
                start_ns
            )

        if not starts:
            raise ClockAlignmentError(
                "scheduled_start_missing",
                "No recording supplied a valid scheduled_start_utc."
            )

        clusters = []

        for start_ns in sorted(
            starts
        ):

            matching_cluster = None

            for cluster in clusters:

                if (
                    abs(
                        start_ns
                        -
                        cluster[
                            "representative_ns"
                        ]
                    )
                    <=
                    self.scheduled_time_tolerance_ns
                ):
                    matching_cluster = cluster
                    break

            if matching_cluster is None:

                clusters.append(
                    {
                        "representative_ns": start_ns,
                        "values": [
                            start_ns
                        ]
                    }
                )

            else:

                matching_cluster[
                    "values"
                ].append(
                    start_ns
                )

        clusters.sort(
            key=lambda cluster: (
                -len(
                    cluster[
                        "values"
                    ]
                ),
                cluster[
                    "representative_ns"
                ]
            )
        )

        return int(
            clusters[
                0
            ][
                "representative_ns"
            ]
        )

    def _build_target_grid(
        self,
        start_utc_ns
    ):

        duration_ns = int(
            round(
                self.target_duration_seconds
                *
                1_000_000_000.0
            )
        )

        end_utc_ns = (
            int(
                start_utc_ns
            )
            +
            duration_ns
        )

        return {
            "schema_version": 1,
            "timing_authority": "scheduled_start_utc",
            "interval_semantics": "[start_utc, end_utc)",
            "start_utc": self._format_utc_ns(
                start_utc_ns
            ),
            "start_utc_ns": int(
                start_utc_ns
            ),
            "start_epoch": (
                start_utc_ns
                /
                1_000_000_000.0
            ),
            "end_utc": self._format_utc_ns(
                end_utc_ns
            ),
            "end_utc_ns": end_utc_ns,
            "end_epoch": (
                end_utc_ns
                /
                1_000_000_000.0
            ),
            "duration_seconds": (
                self.target_duration_seconds
            ),
            "target_sample_rate_hz": (
                self.target_sample_rate_hz
            ),
            "target_frame_count": (
                self.target_frame_count
            ),
            "sample_period_ns": (
                1_000_000_000.0
                /
                self.target_sample_rate_hz
            )
        }

    # ========================================================
    # FILE HELPERS
    # ========================================================

    def _raw_wav_path(
        self,
        payload
    ):

        path_value = (
            payload.get(
                "server_wav_path"
            )
            or
            payload.get(
                "guarded_wav_path"
            )
            or
            payload.get(
                "selected_wav_path"
            )
            or
            payload.get(
                "wav_path"
            )
        )

        if path_value in (
            None,
            ""
        ):
            raise ClockAlignmentError(
                "server_wav_path_missing",
                "The validated server guarded-WAV path is missing."
            )

        path = Path(
            path_value
        ).expanduser()

        try:
            path = path.resolve(
                strict=True
            )
        except FileNotFoundError as error:
            raise ClockAlignmentError(
                "server_wav_missing",
                f"Validated server guarded WAV does not exist: {path}"
            ) from error

        if not path.is_file():
            raise ClockAlignmentError(
                "server_wav_not_file",
                f"Validated server guarded WAV is not a file: {path}"
            )

        return path

    def _aligned_wav_path(
        self,
        raw_path
    ):

        duration_label = self._duration_label(
            self.target_duration_seconds
        )

        aligned_path = raw_path.with_name(
            raw_path.stem
            +
            "_aligned_"
            +
            duration_label
            +
            "_"
            +
            str(
                self.target_sample_rate_hz
            )
            +
            "hz.wav"
        )

        if aligned_path == raw_path:
            raise ClockAlignmentError(
                "aligned_path_conflicts_with_raw",
                "Aligned output path conflicts with the immutable raw WAV."
            )

        return aligned_path

    def _write_json_atomic(
        self,
        path,
        payload
    ):

        path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temporary_path = path.with_name(
            path.name
            +
            ".tmp-"
            +
            uuid.uuid4().hex
        )

        try:

            with temporary_path.open(
                "x",
                encoding="utf-8"
            ) as file:

                json.dump(
                    payload,
                    file,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False
                )

                file.write(
                    "\n"
                )

                file.flush()

                os.fsync(
                    file.fileno()
                )

            os.replace(
                temporary_path,
                path
            )

        finally:

            if temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _sha256_file(
        path
    ):

        sha256 = hashlib.sha256()

        with path.open(
            "rb"
        ) as file:

            while True:

                block = file.read(
                    1024
                    *
                    1024
                )

                if not block:
                    break

                sha256.update(
                    block
                )

        return sha256.hexdigest()

    # ========================================================
    # TIME HELPERS
    # ========================================================

    def _scheduled_start_ns(
        self,
        payload
    ):

        return self._parse_utc_ns(
            payload.get(
                "scheduled_start_utc"
            ),
            "scheduled_start_utc"
        )

    @staticmethod
    def _parse_utc_ns(
        value,
        field_name
    ):

        if value in (
            None,
            ""
        ):
            raise ClockAlignmentError(
                f"{field_name}_missing",
                f"{field_name} is required."
            )

        timestamp = str(
            value
        ).strip()

        if timestamp.endswith(
            "Z"
        ):
            timestamp = (
                timestamp[
                    :-1
                ]
                +
                "+00:00"
            )

        try:
            parsed = datetime.fromisoformat(
                timestamp
            )
        except ValueError as error:
            raise ClockAlignmentError(
                f"{field_name}_invalid",
                f"{field_name} is not a valid ISO-8601 UTC timestamp."
            ) from error

        if parsed.tzinfo is None:
            raise ClockAlignmentError(
                f"{field_name}_timezone_missing",
                f"{field_name} must include a UTC timezone."
            )

        parsed_utc = parsed.astimezone(
            timezone.utc
        )

        return int(
            round(
                parsed_utc.timestamp()
                *
                1_000_000_000.0
            )
        )

    @staticmethod
    def _format_utc_ns(
        value
    ):

        seconds = (
            int(
                value
            )
            /
            1_000_000_000.0
        )

        return (
            datetime.fromtimestamp(
                seconds,
                timezone.utc
            )
            .isoformat(
                timespec="microseconds"
            )
            .replace(
                "+00:00",
                "Z"
            )
        )

    @staticmethod
    def _utc_now(
    ):

        return (
            datetime.now(
                timezone.utc
            )
            .isoformat(
                timespec="microseconds"
            )
            .replace(
                "+00:00",
                "Z"
            )
        )

    # ========================================================
    # GENERAL HELPERS
    # ========================================================

    @staticmethod
    def _payload(
        event
    ):

        if not isinstance(
            event,
            dict
        ):
            return {}

        payload = event.get(
            "payload",
            event
        )

        return (
            payload
            if isinstance(
                payload,
                dict
            )
            else {}
        )

    def _event_sort_key(
        self,
        event
    ):

        payload = self._payload(
            event
        )

        return (
            str(
                payload.get(
                    "node_id"
                )
                or
                event.get(
                    "node_id"
                )
                or
                ""
            ),
            str(
                payload.get(
                    "recording_id"
                )
                or
                event.get(
                    "recording_id"
                )
                or
                ""
            )
        )

    @staticmethod
    def _required_identity(
        value,
        field_name
    ):

        if value in (
            None,
            ""
        ):
            raise ClockAlignmentError(
                f"{field_name}_missing",
                f"{field_name} is required."
            )

        normalized = str(
            value
        ).strip()

        if not normalized:
            raise ClockAlignmentError(
                f"{field_name}_missing",
                f"{field_name} is required."
            )

        return normalized

    @staticmethod
    def _strict_int(
        value,
        field_name
    ):

        if isinstance(
            value,
            bool
        ):
            raise ClockAlignmentError(
                f"{field_name}_invalid",
                f"{field_name} must be an integer."
            )

        try:
            normalized = int(
                value
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise ClockAlignmentError(
                f"{field_name}_invalid",
                f"{field_name} must be an integer."
            ) from error

        if isinstance(
            value,
            float
        ) and not value.is_integer():
            raise ClockAlignmentError(
                f"{field_name}_invalid",
                f"{field_name} must be an integer."
            )

        return normalized

    @staticmethod
    def _finite_float(
        value,
        field_name
    ):

        try:
            normalized = float(
                value
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise ClockAlignmentError(
                f"{field_name}_invalid",
                f"{field_name} must be numeric."
            ) from error

        if not math.isfinite(
            normalized
        ):
            raise ClockAlignmentError(
                f"{field_name}_invalid",
                f"{field_name} must be finite."
            )

        return normalized

    @classmethod
    def _positive_float(
        cls,
        value,
        field_name
    ):

        normalized = cls._finite_float(
            value,
            field_name
        )

        if normalized <= 0.0:
            raise ClockAlignmentError(
                f"{field_name}_invalid",
                f"{field_name} must be positive."
            )

        return normalized

    @classmethod
    def _nonnegative_float(
        cls,
        value,
        field_name
    ):

        normalized = cls._finite_float(
            value,
            field_name
        )

        if normalized < 0.0:
            raise ClockAlignmentError(
                f"{field_name}_invalid",
                f"{field_name} must be nonnegative."
            )

        return normalized

    @staticmethod
    def _positive_int(
        value,
        field_name
    ):

        if isinstance(
            value,
            bool
        ):
            raise ValueError(
                f"{field_name} must be a positive integer."
            )

        try:
            normalized = int(
                value
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"{field_name} must be a positive integer."
            ) from error

        if (
            isinstance(
                value,
                float
            )
            and
            not value.is_integer()
        ):
            raise ValueError(
                f"{field_name} must be a positive integer."
            )

        if normalized < 1:
            raise ValueError(
                f"{field_name} must be a positive integer."
            )

        return normalized

    @staticmethod
    def _duration_label(
        duration_seconds
    ):

        if float(
            duration_seconds
        ).is_integer():
            return (
                str(
                    int(
                        duration_seconds
                    )
                )
                +
                "s"
            )

        return (
            str(
                duration_seconds
            )
            .replace(
                ".",
                "p"
            )
            +
            "s"
        )
