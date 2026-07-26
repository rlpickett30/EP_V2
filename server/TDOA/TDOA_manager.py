# ============================================================
# TDOA_manager.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Role:
#   Manager.
#
# Purpose:
#   Perform TDOA calculation work requested by TDOA_dispatcher.py.
#
# Does:
#   - Applies mode changes from dispatcher
#   - Applies weather updates from dispatcher
#   - Validates exact request-scoped UTC-aligned recording inputs
#   - Loads only server-derived aligned WAV files
#   - Runs event detection
#   - Runs event analysis
#   - Runs event solver
#   - Runs solver consensus
#   - Returns canonical publishable calculation results to dispatcher
#
# Does NOT:
#   - Subscribe to events
#   - Publish events
#   - Own subsystem workflow
#   - Decide when TDOA should run
#   - Track node capability state
#   - Perform candidate filtering
#   - Select recordings from global history
#   - Load node-local or raw guarded WAV paths
#
# Owner:
#   TDOA_dispatcher.py
#
# ============================================================

import copy
import hashlib
import logging
import wave
from pathlib import Path

import numpy as np

from typing import Any, Optional

from TDOA.TDOA_event_detection import (
    TDOAEventDetection
)

from TDOA.TDOA_event_analysis import (
    TDOAEventAnalysis
)

from TDOA.TDOA_event_solver import (
    TDOAEventSolver
)

from TDOA.solver_consensus import (
    SolverConsensus
)


class TDOAManager:
    """
    Work-performing manager for the TDOA subsystem.

    The dispatcher decides when this manager is called.
    This manager performs the calculation pipeline and returns
    completed result dictionaries.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        config: dict
    ):
        self.config = copy.deepcopy(
            config
            if config is not None
            else {}
        )

        manager_config = self.config.get(
            "tdoa_manager",
            {}
        )

        self.debug = manager_config.get(
            "debug",
            False
        )

        self.debug_event_detection = manager_config.get(
            "debug_event_detection",
            False
        )

        self.debug_event_analysis = manager_config.get(
            "debug_event_analysis",
            False
        )

        self.debug_event_solver = manager_config.get(
            "debug_event_solver",
            False
        )

        self.debug_solver_consensus = manager_config.get(
            "debug_solver_consensus",
            False
        )

        self.default_sample_rate_hz = manager_config.get(
            "default_sample_rate_hz",
            self.config.get(
                "TDOA_event_solver",
                {}
            ).get(
                "sample_rate_hz",
                96000
            )
        )

        self.minimum_solver_nodes = int(
            manager_config.get(
                "minimum_solver_nodes",
                4
            )
        )

        alignment_config = self.config.get(
            "tdoa_clock_alignment",
            {}
        )

        self.expected_aligned_sample_rate_hz = int(
            alignment_config.get(
                "target_sample_rate_hz",
                self.default_sample_rate_hz
            )
        )

        self.expected_aligned_duration_seconds = float(
            alignment_config.get(
                "target_duration_seconds",
                15.0
            )
        )

        self.expected_aligned_frame_count = int(
            round(
                self.expected_aligned_sample_rate_hz
                *
                self.expected_aligned_duration_seconds
            )
        )

        self.weather_state = {}

        self.mode_state = {}

        self.microphone_positions = self._load_microphone_positions()

        self.event_detection = TDOAEventDetection(
            config=self.config,
            debug=self.debug_event_detection
        )

        self.event_analysis = TDOAEventAnalysis(
            config=self.config,
            debug=self.debug_event_analysis
        )

        self.event_solver = TDOAEventSolver(
            config=self.config,
            microphone_positions=self.microphone_positions,
            debug=self.debug_event_solver
        )

        self.solver_consensus = SolverConsensus(
            config=self.config,
            debug=self.debug_solver_consensus
        )

        logging.info(
            "TDOA manager initialized."
        )

    # ========================================================
    # DISPATCHER-EXPECTED PUBLIC API
    # ========================================================

    def update_mode(
        self,
        mode_name: str,
        mode_value: Any
    ) -> Optional[dict]:
        """
        Apply a TDOA mode change.

        Called by:
            TDOA_dispatcher._handle_mode_change()
        """

        if mode_name is None:
            raise ValueError(
                "mode_name is None."
            )

        self.mode_state[mode_name] = mode_value

        self._apply_mode_to_config(
            mode_name=mode_name,
            mode_value=mode_value
        )

        self._rebuild_helpers()

        return {
            "manager": "TDOA",
            "update_type": "mode_update",
            "mode_name": mode_name,
            "mode_value": mode_value,
            "mode_state": dict(
                self.mode_state
            )
        }

    def update_weather(
        self,
        weather_event: dict
    ) -> Optional[dict]:
        """
        Store weather update and update speed-of-sound value if present.

        Called by:
            TDOA_dispatcher._handle_weather_update()
        """

        if weather_event is None:
            raise ValueError(
                "weather_event is None."
            )

        payload = weather_event.get(
            "payload",
            weather_event
        )

        if not isinstance(payload, dict):
            raise TypeError(
                "weather payload must be a dictionary."
            )

        self.weather_state.update(
            payload
        )

        speed_of_sound_mps = payload.get(
            "speed_of_sound_mps"
        )

        if speed_of_sound_mps is not None:

            self.config.setdefault(
                "TDOA_event_solver",
                {}
            )["speed_of_sound_mps"] = float(
                speed_of_sound_mps
            )

            self._rebuild_solver_helpers()

        return {
            "manager": "TDOA",
            "update_type": "weather_update",
            "weather_state": dict(
                self.weather_state
            ),
            "speed_of_sound_mps": self.config.get(
                "TDOA_event_solver",
                {}
            ).get(
                "speed_of_sound_mps"
            )
        }

    def tdoa_estimate(
        self,
        candidate: dict,
        recording_events: Optional[list] = None
    ) -> dict:
        """
        Run the full TDOA calculation pipeline for one candidate.

        Called by:
            TDOA_dispatcher._handle_tdoa_complete_set()

        Pipeline:
            candidate + exact validated recording events
                ↓
            recordings normalized
                ↓
            TDOA_event_detection.py
                ↓
            TDOA_event_analysis.py
                ↓
            TDOA_event_solver.py
                ↓
            solver_consensus.py
        """

        result = {
            "schema_version": 1,
            "success": False,
            "status": "failed",
            "manager": "TDOA",
            "calculation": "TDOA_CALC",
            "input_contract": "aligned_complete_set",
            "tdoa_request_id": None,
            "candidate": copy.deepcopy(
                candidate
            ),
            "calculation_input": {},
            "calculation_attempted": False,
            "solver_attempt_count": 0,
            "localization_valid": False,
            "solution": {},
            "channel_event_counts": {},
            "channel_event_summary": {},
            "analysis_groups": [],
            "solver_results": [],
            "solver_consensus": {},
            "errors": [],
            "debug": {}
        }

        try:
            self._validate_candidate(
                candidate
            )

            if recording_events is None:
                raise ValueError(
                    "TDOA_COMPLETE_SET recording_events are required. "
                    "Global recording-history fallback is disabled."
                )

            recordings = self._normalize_exact_recording_events(
                recording_events
            )

            if not recordings:
                raise RuntimeError(
                    "TDOA_COMPLETE_SET contains no aligned recordings."
                )

            self._validate_shared_aligned_grid(
                recordings
            )

            self._validate_candidate_recording_lineage(
                candidate=candidate,
                recordings=recordings
            )

            result["calculation_input"] = (
                self._build_calculation_input(
                    recordings
                )
            )

            result["tdoa_request_id"] = result[
                "calculation_input"
            ].get(
                "tdoa_request_id"
            )

            result["calculation_attempted"] = True

            self._prepare_solver_for_recordings(
                recordings=recordings
            )

            channel_events = self._run_event_detection(
                recordings=recordings
            )

            analysis_result = self.event_analysis.analyze(
                channel_events=channel_events
            )

            if not analysis_result.get("success", False):
                raise RuntimeError(
                    "TDOA event analysis failed."
                )

            analysis_groups = analysis_result.get(
                "analysis_groups",
                []
            )

            solver_results = self._run_solver(
                analysis_groups=analysis_groups
            )

            result["solver_attempt_count"] = len(
                solver_results
            )

            consensus_result = self.solver_consensus.compute(
                solver_results=solver_results
            )

            if not consensus_result.get("success", False):
                raise RuntimeError(
                    "Solver consensus failed."
                )

            public_consensus = self._public_consensus_result(
                consensus_result
            )

            consensus_solution = public_consensus.get(
                "consensus_solution",
                {}
            )

            result["success"] = True
            result["status"] = "complete"
            result["channel_event_counts"] = {
                channel_name: len(events)
                for channel_name, events in channel_events.items()
            }
            result["channel_event_summary"] = (
                self._summarize_channel_events(
                    channel_events
                )
            )
            result["analysis_groups"] = [
                self._public_analysis_group(
                    analysis_group
                )
                for analysis_group in analysis_groups
            ]
            result["solver_results"] = [
                self._public_solver_result(
                    solver_result
                )
                for solver_result in solver_results
            ]
            result["solver_consensus"] = public_consensus
            result["localization_valid"] = bool(
                consensus_solution.get(
                    "solver_consensus_valid",
                    False
                )
            )
            result["solution"] = copy.deepcopy(
                consensus_solution
            )

            if self.debug:
                result["debug"] = {
                    "matched_recording_count": len(
                        recordings
                    ),
                    "channel_count": len(
                        channel_events
                    ),
                    "analysis_group_count": len(
                        analysis_groups
                    ),
                    "solver_result_count": len(
                        solver_results
                    ),
                    "analysis_debug": analysis_result.get(
                        "debug",
                        {}
                    ),
                    "consensus_debug": consensus_result.get(
                        "debug",
                        {}
                    )
                }

        except Exception as error:

            logging.exception(
                "TDOA manager estimate failed."
            )

            result["errors"].append(
                str(error)
            )

            if self.debug:
                result["debug"]["exception_type"] = (
                    type(error).__name__
                )

        return self._to_builtin(
            result
        )

    # ========================================================
    # EXACT ALIGNED RECORDING INPUT
    # ========================================================

    def _normalize_exact_recording_events(
        self,
        recording_events: list
    ) -> list:
        """
        Normalize exact request-scoped events from TDOA_COMPLETE_SET.

        Block 9 deliberately refuses generic, raw, node-local, or
        global-history recording selection.
        """

        if not isinstance(recording_events, list):
            raise TypeError(
                "Exact TDOA recording events must be a list."
            )

        normalized_recordings = []
        seen_node_ids = set()
        seen_channel_names = set()

        for recording_event in recording_events:

            if not isinstance(recording_event, dict):
                raise TypeError(
                    "Exact TDOA recording event must be a dictionary."
                )

            normalized_recording = (
                self._normalize_aligned_recording_event(
                    recording_event
                )
            )

            node_id = normalized_recording.get(
                "node_id"
            )

            if node_id in seen_node_ids:
                raise ValueError(
                    f"Duplicate exact TDOA recording node: {node_id}"
                )

            seen_node_ids.add(
                node_id
            )

            channel_name = normalized_recording.get(
                "channel_name"
            )

            if channel_name in seen_channel_names:
                raise ValueError(
                    "Duplicate exact TDOA recording channel: "
                    f"{channel_name}"
                )

            seen_channel_names.add(
                channel_name
            )

            normalized_recordings.append(
                normalized_recording
            )

        if len(normalized_recordings) < self.minimum_solver_nodes:
            raise ValueError(
                "Not enough exact aligned recordings for TDOA calculation. "
                f"Required={self.minimum_solver_nodes}, "
                f"Available={len(normalized_recordings)}"
            )

        return normalized_recordings

    def _normalize_aligned_recording_event(
        self,
        recording_event: dict
    ) -> dict:
        """
        Validate and load one exact aligned recording.
        """

        payload = recording_event.get(
            "payload"
        )

        if not isinstance(payload, dict):
            raise TypeError(
                "Aligned TDOA recording event must contain a payload "
                "dictionary."
            )

        status = payload.get(
            "status",
            recording_event.get(
                "status"
            )
        )

        if status != "success":
            raise ValueError(
                "Exact aligned TDOA recording status is not success."
            )

        if payload.get("alignment_status") != "PASS":
            raise ValueError(
                "Exact TDOA recording alignment_status is not PASS."
            )

        if payload.get("timing_state") != "utc_grid_aligned":
            raise ValueError(
                "Exact TDOA recording timing_state is not utc_grid_aligned."
            )

        if payload.get("corrected_tdoa_eligible") is not True:
            raise ValueError(
                "Exact aligned TDOA recording is not calculation eligible."
            )

        node_id = payload.get(
            "node_id",
            recording_event.get(
                "node_id"
            )
        )

        if node_id in (None, ""):
            raise ValueError(
                "Exact aligned TDOA recording is missing node_id."
            )

        aligned_wav_path = payload.get(
            "aligned_wav_path"
        )

        if aligned_wav_path in (None, ""):
            raise ValueError(
                f"Exact TDOA recording for {node_id} is missing "
                "aligned_wav_path. Generic wav_path and recording_path "
                "fallbacks are disabled."
            )

        expected_sha256 = payload.get(
            "aligned_wav_sha256"
        )

        if expected_sha256 in (None, ""):
            raise ValueError(
                f"Exact TDOA recording for {node_id} is missing "
                "aligned_wav_sha256."
            )

        actual_sha256 = self._sha256_file(
            aligned_wav_path
        )

        if actual_sha256.lower() != str(
            expected_sha256
        ).lower():
            raise ValueError(
                f"Aligned WAV checksum mismatch for {node_id}."
            )

        signal, wav_properties = self._load_aligned_wav_signal(
            aligned_wav_path
        )

        declared_sample_rate_hz = payload.get(
            "sample_rate_hz",
            payload.get(
                "sample_rate"
            )
        )

        if (
            declared_sample_rate_hz is not None
            and
            int(declared_sample_rate_hz)
            !=
            wav_properties["sample_rate_hz"]
        ):
            raise ValueError(
                f"Aligned WAV sample-rate metadata mismatch for {node_id}."
            )

        declared_frame_count = payload.get(
            "frame_count"
        )

        if (
            declared_frame_count is not None
            and
            int(declared_frame_count)
            !=
            wav_properties["frame_count"]
        ):
            raise ValueError(
                f"Aligned WAV frame-count metadata mismatch for {node_id}."
            )

        declared_channels = payload.get(
            "channels"
        )

        if (
            declared_channels is not None
            and
            int(declared_channels)
            !=
            wav_properties["channels"]
        ):
            raise ValueError(
                f"Aligned WAV channel metadata mismatch for {node_id}."
            )

        return {
            "tdoa_request_id": payload.get(
                "tdoa_request_id",
                payload.get(
                    "request_id"
                )
            ),
            "node_id": node_id,
            "avis_lite_id": payload.get(
                "avis_lite_id",
                recording_event.get(
                    "avis_lite_id"
                )
            ),
            "channel_name": payload.get(
                "channel_name",
                node_id
            ),
            "signal": signal,
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
            "duration_seconds": wav_properties[
                "duration_seconds"
            ],
            "scheduled_start_utc": payload.get(
                "scheduled_start_utc"
            ),
            "recording_id": payload.get(
                "recording_id"
            ),
            "aligned_wav_path": str(
                Path(
                    aligned_wav_path
                ).resolve()
            ),
            "aligned_wav_sha256": actual_sha256,
            "aligned_metadata_path": payload.get(
                "aligned_metadata_path"
            ),
            "position": payload.get(
                "position"
            )
        }

    def _load_aligned_wav_signal(
        self,
        wav_path
    ) -> tuple:
        """
        Load one server-derived aligned WAV into a mono float signal.
        """

        path = Path(
            wav_path
        )

        if not path.is_file():
            raise FileNotFoundError(
                f"Aligned TDOA WAV does not exist on server: {path}"
            )

        with wave.open(
            str(path),
            "rb"
        ) as wav_file:

            channels = wav_file.getnchannels()
            sample_rate_hz = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            frame_count = wav_file.getnframes()
            raw_audio = wav_file.readframes(
                frame_count
            )

        if sample_width == 2:
            signal = np.frombuffer(
                raw_audio,
                dtype="<i2"
            ).astype(
                np.float32
            ) / 32768.0

        elif sample_width == 4:
            signal = np.frombuffer(
                raw_audio,
                dtype="<i4"
            ).astype(
                np.float32
            ) / float(1 << 31)

        else:
            raise ValueError(
                f"Unsupported TDOA WAV sample width: {sample_width}"
            )

        if channels > 1:
            usable_length = (
                signal.size // channels
            ) * channels

            signal = signal[:usable_length].reshape(
                -1,
                channels
            ).mean(
                axis=1
            )

        return signal, {
            "sample_rate_hz": int(
                sample_rate_hz
            ),
            "channels": int(
                channels
            ),
            "sample_width_bytes": int(
                sample_width
            ),
            "frame_count": int(
                frame_count
            ),
            "duration_seconds": float(
                frame_count
                /
                sample_rate_hz
            )
        }

    @staticmethod
    def _sha256_file(
        wav_path
    ) -> str:

        digest = hashlib.sha256()

        with Path(
            wav_path
        ).open(
            "rb"
        ) as wav_file:

            for block in iter(
                lambda: wav_file.read(
                    1024
                    *
                    1024
                ),
                b""
            ):
                digest.update(
                    block
                )

        return digest.hexdigest()

    def _validate_shared_aligned_grid(
        self,
        recordings: list
    ) -> None:
        """
        Confirm every exact input occupies the same canonical audio grid.
        """

        request_ids = {
            recording.get(
                "tdoa_request_id"
            )
            for recording in recordings
        }

        if None in request_ids or "" in request_ids:
            raise ValueError(
                "Exact aligned recordings are missing tdoa_request_id."
            )

        if len(request_ids) != 1:
            raise ValueError(
                "Exact aligned recordings contain mixed tdoa_request_id "
                "values."
            )

        scheduled_starts = {
            recording.get(
                "scheduled_start_utc"
            )
            for recording in recordings
        }

        if None in scheduled_starts or "" in scheduled_starts:
            raise ValueError(
                "Exact aligned recordings are missing scheduled_start_utc."
            )

        if len(scheduled_starts) != 1:
            raise ValueError(
                "Exact aligned recordings do not share scheduled_start_utc."
            )

        for recording in recordings:

            node_id = recording.get(
                "node_id"
            )

            if (
                recording.get(
                    "sample_rate_hz"
                )
                !=
                self.expected_aligned_sample_rate_hz
            ):
                raise ValueError(
                    f"Aligned sample rate is not the configured target "
                    f"for {node_id}."
                )

            if (
                recording.get(
                    "frame_count"
                )
                !=
                self.expected_aligned_frame_count
            ):
                raise ValueError(
                    f"Aligned frame count is not the configured target "
                    f"for {node_id}."
                )

    @staticmethod
    def _validate_candidate_recording_lineage(
        candidate: dict,
        recordings: list
    ) -> None:
        """
        Confirm the exact aligned members belong to the triggering candidate.
        """

        candidate_node_ids = set(
            candidate.get(
                "node_ids",
                []
            )
        )

        if candidate_node_ids:

            recording_node_ids = {
                recording.get(
                    "node_id"
                )
                for recording in recordings
            }

            unexpected_node_ids = (
                recording_node_ids
                -
                candidate_node_ids
            )

            if unexpected_node_ids:
                raise ValueError(
                    "Exact aligned recordings contain nodes outside the "
                    "triggering candidate: "
                    f"{sorted(unexpected_node_ids)}"
                )

        candidate_avis_lite_id = candidate.get(
            "avis_lite_id"
        )

        if candidate_avis_lite_id in (None, ""):
            return

        mismatched_node_ids = [
            recording.get(
                "node_id"
            )
            for recording in recordings
            if (
                recording.get(
                    "avis_lite_id"
                )
                not in (
                    None,
                    "",
                    candidate_avis_lite_id
                )
            )
        ]

        if mismatched_node_ids:
            raise ValueError(
                "Exact aligned recordings contain AVIS_LITE lineage "
                "outside the triggering candidate: "
                f"{sorted(mismatched_node_ids)}"
            )

    def _build_calculation_input(
        self,
        recordings: list
    ) -> dict:

        return {
            "source_event": "TDOA_COMPLETE_SET",
            "timing_state": "utc_grid_aligned",
            "tdoa_request_id": recordings[
                0
            ].get(
                "tdoa_request_id"
            ),
            "scheduled_start_utc": recordings[
                0
            ].get(
                "scheduled_start_utc"
            ),
            "sample_rate_hz": recordings[
                0
            ].get(
                "sample_rate_hz"
            ),
            "frame_count": recordings[
                0
            ].get(
                "frame_count"
            ),
            "duration_seconds": recordings[
                0
            ].get(
                "duration_seconds"
            ),
            "recording_count": len(
                recordings
            ),
            "node_ids": [
                recording.get(
                    "node_id"
                )
                for recording in recordings
            ],
            "recordings": [
                {
                    "node_id": recording.get(
                        "node_id"
                    ),
                    "recording_id": recording.get(
                        "recording_id"
                    ),
                    "channel_name": recording.get(
                        "channel_name"
                    ),
                    "aligned_wav_path": recording.get(
                        "aligned_wav_path"
                    ),
                    "aligned_wav_sha256": recording.get(
                        "aligned_wav_sha256"
                    ),
                    "aligned_metadata_path": recording.get(
                        "aligned_metadata_path"
                    )
                }
                for recording in recordings
            ]
        }


    def _prepare_solver_for_recordings(
        self,
        recordings: list
    ) -> None:
        """
        Build a temporary microphone-position map for the returned node set.

        In deployment, node positions should come from registry/GPS payloads.
        During the current indoor/bad-geometry milestone, fall back to a
        deterministic tetrahedron so the solver door can open and attempt a
        calculation.
        """

        fallback_positions = [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 1.0, 0.0],
            [1.0, 0.0, 1.0],
            [0.0, 1.0, 1.0],
            [1.0, 1.0, 1.0],
        ]

        microphone_positions = {}

        for index, recording in enumerate(recordings):

            channel_name = recording.get(
                "channel_name"
            )

            if channel_name is None:
                continue

            position = recording.get(
                "position"
            )

            if not isinstance(position, (list, tuple)) or len(position) != 3:
                position = fallback_positions[
                    index % len(fallback_positions)
                ]

            microphone_positions[channel_name] = position

        if len(microphone_positions) >= 4:

            self.microphone_positions = microphone_positions

            self._rebuild_solver_helpers()

    # ========================================================
    # DETECTION / ANALYSIS / SOLVE PIPELINE
    # ========================================================

    def _run_event_detection(
        self,
        recordings: list
    ) -> dict:
        """
        Run event detection on each selected recording.
        """

        channel_events = {}

        for recording in recordings:

            channel_name = recording.get(
                "channel_name"
            )

            signal = recording.get(
                "signal"
            )

            sample_rate_hz = recording.get(
                "sample_rate_hz",
                self.default_sample_rate_hz
            )

            if channel_name is None:
                continue

            detection_result = self.event_detection.process_channel(
                signal=signal,
                sample_rate_hz=sample_rate_hz,
                channel_name=channel_name
            )

            if not detection_result.get("success", False):
                raise RuntimeError(
                    f"TDOA event detection failed for channel: "
                    f"{channel_name}"
                )

            channel_events[channel_name] = detection_result.get(
                "events",
                []
            )

        return channel_events

    def _run_solver(
        self,
        analysis_groups: list
    ) -> list:
        """
        Run solver on all analysis groups.
        """

        solver_results = []

        for analysis_group in analysis_groups:

            solver_result = self.event_solver.solve(
                analysis_group=analysis_group
            )

            solver_results.append(
                solver_result
            )

        return solver_results

    # ========================================================
    # CANONICAL RESULT BUILDING
    # ========================================================

    def _summarize_channel_events(
        self,
        channel_events: dict
    ) -> dict:
        """
        Preserve bounded per-channel detection evidence.
        """

        summary = {}

        for channel_name, events in channel_events.items():

            onset_samples = [
                event.get(
                    "onset_sample"
                )
                for event in events
                if event.get(
                    "onset_sample"
                ) is not None
            ]

            summary[channel_name] = {
                "event_count": len(
                    events
                ),
                "first_onset_sample": (
                    min(
                        onset_samples
                    )
                    if onset_samples
                    else
                    None
                ),
                "last_onset_sample": (
                    max(
                        onset_samples
                    )
                    if onset_samples
                    else
                    None
                )
            }

        return self._to_builtin(
            summary
        )

    def _public_analysis_group(
        self,
        analysis_group: dict
    ) -> dict:
        """
        Preserve solver-ready timing evidence without matched audio windows.
        """

        matched_channels = analysis_group.get(
            "matched_channels",
            {}
        )

        return self._to_builtin({
            "group_id": analysis_group.get(
                "group_id"
            ),
            "reference_channel": analysis_group.get(
                "reference_channel"
            ),
            "alignment_feature": analysis_group.get(
                "alignment_feature"
            ),
            "feature_values": copy.deepcopy(
                analysis_group.get(
                    "feature_values",
                    {}
                )
            ),
            "reference_value": analysis_group.get(
                "reference_value"
            ),
            "tdoa_values": copy.deepcopy(
                analysis_group.get(
                    "tdoa_values",
                    {}
                )
            ),
            "residuals": copy.deepcopy(
                analysis_group.get(
                    "residuals",
                    {}
                )
            ),
            "spread": analysis_group.get(
                "spread"
            ),
            "std_deviation": analysis_group.get(
                "std_deviation"
            ),
            "channel_count": analysis_group.get(
                "channel_count"
            ),
            "consensus_valid": analysis_group.get(
                "consensus_valid"
            ),
            "matched_channel_names": sorted(
                matched_channels.keys()
            ),
            "match_errors": copy.deepcopy(
                analysis_group.get(
                    "match_errors",
                    {}
                )
            )
        })

    def _public_solver_result(
        self,
        solver_result: dict
    ) -> dict:
        """
        Preserve one solver attempt without duplicating analysis internals.
        """

        solution = solver_result.get(
            "solution",
            {}
        )

        return self._to_builtin({
            "success": solver_result.get(
                "success",
                False
            ),
            "solution": self._public_solution(
                solution
            ),
            "errors": copy.deepcopy(
                solver_result.get(
                    "errors",
                    []
                )
            ),
            "debug": copy.deepcopy(
                solver_result.get(
                    "debug",
                    {}
                )
            )
        })

    def _public_consensus_result(
        self,
        consensus_result: dict
    ) -> dict:
        """
        Preserve consensus evidence without nested analysis/audio copies.
        """

        raw_consensus_solution = consensus_result.get(
            "consensus_solution",
            {}
        )

        consensus_solution = {
            key: copy.deepcopy(
                value
            )
            for key, value in raw_consensus_solution.items()
            if key != "best_solution"
        }

        best_solution = raw_consensus_solution.get(
            "best_solution"
        )

        if isinstance(best_solution, dict):
            consensus_solution["best_solution"] = (
                self._public_solution(
                    best_solution
                )
            )

        return self._to_builtin({
            "success": consensus_result.get(
                "success",
                False
            ),
            "consensus_solution": consensus_solution,
            "valid_solutions": [
                self._public_solution(
                    solution
                )
                for solution in consensus_result.get(
                    "valid_solutions",
                    []
                )
            ],
            "errors": copy.deepcopy(
                consensus_result.get(
                    "errors",
                    []
                )
            ),
            "debug": copy.deepcopy(
                consensus_result.get(
                    "debug",
                    {}
                )
            )
        })

    def _public_solution(
        self,
        solution: dict
    ) -> dict:

        return {
            key: self._to_builtin(
                value
            )
            for key, value in solution.items()
            if key != "analysis_group"
        }

    def _to_builtin(
        self,
        value
    ):
        """
        Convert calculation evidence into JSON-safe Python builtins.
        """

        if isinstance(value, np.ndarray):
            return value.tolist()

        if isinstance(value, np.generic):
            return value.item()

        if isinstance(value, Path):
            return str(
                value
            )

        if isinstance(value, dict):
            return {
                str(key): self._to_builtin(
                    item
                )
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [
                self._to_builtin(
                    item
                )
                for item in value
            ]

        return value

    # ========================================================
    # MODE HANDLING
    # ========================================================

    def _apply_mode_to_config(
        self,
        mode_name: str,
        mode_value: Any
    ) -> None:
        """
        Apply dispatcher mode updates to local manager config.

        The dispatcher already converts event names into simplified
        mode names.
        """

        if mode_value is None:
            return

        self.config.setdefault(
            "TDOA_event_detection",
            {}
        )

        self.config.setdefault(
            "event_matching",
            {}
        )

        self.config.setdefault(
            "matching_consensus",
            {}
        )

        # ----------------------------------------------------
        # Detector method changes
        # ----------------------------------------------------

        if mode_name == "energy_onset":

            self.config["TDOA_event_detection"]["onset_method"] = (
                "energy_threshold_onset"
            )

            return

        if mode_name == "pattern_onset":

            self.config["TDOA_event_detection"]["onset_method"] = (
                "sign_pattern_onset"
            )

            return

        if mode_name == "energy_offset":

            self.config["TDOA_event_detection"]["offset_method"] = (
                "energy_threshold_offset"
            )

            return

        if mode_name == "pattern_offset":

            self.config["TDOA_event_detection"]["offset_method"] = (
                "sign_pattern_offset"
            )

            return

        # ----------------------------------------------------
        # Alignment feature changes
        # ----------------------------------------------------

        if mode_name == "onset_feature":

            self.config["event_matching"]["alignment_feature"] = (
                mode_value
            )

            self.config["matching_consensus"]["alignment_feature"] = (
                mode_value
            )

            return

        if mode_name == "amp_feature":

            self.config["event_matching"]["alignment_feature"] = (
                mode_value
            )

            self.config["matching_consensus"]["alignment_feature"] = (
                mode_value
            )

            return

    def _rebuild_helpers(
        self
    ) -> None:
        """
        Rebuild helper objects after mode/config changes.
        """

        self.event_detection = TDOAEventDetection(
            config=self.config,
            debug=self.debug_event_detection
        )

        self.event_analysis = TDOAEventAnalysis(
            config=self.config,
            debug=self.debug_event_analysis
        )

        self._rebuild_solver_helpers()

    def _rebuild_solver_helpers(
        self
    ) -> None:
        """
        Rebuild solver-side helpers after solver/weather changes.
        """

        self.event_solver = TDOAEventSolver(
            config=self.config,
            microphone_positions=self.microphone_positions,
            debug=self.debug_event_solver
        )

        self.solver_consensus = SolverConsensus(
            config=self.config,
            debug=self.debug_solver_consensus
        )

    # ========================================================
    # CONFIG HELPERS
    # ========================================================

    def _load_microphone_positions(
        self
    ) -> dict:
        """
        Load microphone positions from TDOA_config.json.

        Expected shape:
            {
                "microphone_positions": {
                    "CH1": [0.0, 0.0, 0.0],
                    "CH2": [1.0, 0.0, 0.0],
                    "CH3": [0.0, 1.0, 0.0],
                    "CH4": [0.0, 0.0, 1.0]
                }
            }
        """

        microphone_positions = self.config.get(
            "microphone_positions",
            {}
        )

        if not microphone_positions:
            logging.warning(
                "No microphone_positions found in TDOA config. "
                "Using placeholder 4-channel geometry."
            )

            microphone_positions = {
                "CH1": [0.0, 0.0, 0.0],
                "CH2": [1.0, 0.0, 0.0],
                "CH3": [0.0, 1.0, 0.0],
                "CH4": [0.0, 0.0, 1.0]
            }

        return microphone_positions

    # ========================================================
    # VALIDATION
    # ========================================================

    def _validate_candidate(
        self,
        candidate: dict
    ) -> None:
        """
        Validate candidate package from candidate_filter.py.
        """

        if candidate is None:
            raise ValueError(
                "candidate is None."
            )

        if not isinstance(candidate, dict):
            raise TypeError(
                "candidate must be a dictionary."
            )

        if not candidate.get("candidate_valid", False):
            raise ValueError(
                "candidate_valid is not True."
            )
