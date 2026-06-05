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
#   - Stores incoming TDOA recording packages
#   - Applies mode changes from dispatcher
#   - Applies weather updates from dispatcher
#   - Runs event detection
#   - Runs event analysis
#   - Runs event solver
#   - Runs solver consensus
#   - Returns completed result packages to dispatcher
#
# Does NOT:
#   - Subscribe to events
#   - Publish events
#   - Own subsystem workflow
#   - Decide when TDOA should run
#   - Track node capability state
#   - Perform candidate filtering
#
# Owner:
#   TDOA_dispatcher.py
#
# ============================================================

import copy
import logging
from typing import Any, Optional

from TDOA_event_detection import (
    TDOAEventDetection
)

from TDOA_event_analysis import (
    TDOAEventAnalysis
)

from TDOA_event_solver import (
    TDOAEventSolver
)

from solver_consensus import (
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

        self.max_recordings_stored = manager_config.get(
            "max_recordings_stored",
            250
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

        self.recording_store = []

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

    def store_tdoa_recording(
        self,
        recording_event: dict
    ) -> Optional[dict]:
        """
        Store a TDOA recording package.

        Called by:
            TDOA_dispatcher._handle_tdoa_recording()

        Expected useful fields may include:
            node_id
            avis_lite_id
            channel_name
            signal
            sample_rate_hz
            timestamp
        """

        if recording_event is None:
            raise ValueError(
                "recording_event is None."
            )

        normalized_recording = self._normalize_recording_event(
            recording_event
        )

        self.recording_store.append(
            normalized_recording
        )

        self._trim_recording_store()

        return {
            "manager": "TDOA",
            "update_type": "recording_stored",
            "stored_recording_count": len(
                self.recording_store
            ),
            "node_id": normalized_recording.get(
                "node_id"
            ),
            "avis_lite_id": normalized_recording.get(
                "avis_lite_id"
            ),
            "channel_name": normalized_recording.get(
                "channel_name"
            )
        }

    def tdoa_estimate(
        self,
        candidate: dict
    ) -> dict:
        """
        Run the full TDOA calculation pipeline for one candidate.

        Called by:
            TDOA_dispatcher._handle_candidate_ready()

        Pipeline:
            candidate
                ↓
            recordings selected
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
            "success": False,
            "manager": "TDOA",
            "calculation": "tdoa_estimate",
            "candidate": candidate,
            "channel_events": {},
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

            recordings = self._select_recordings_for_candidate(
                candidate
            )

            if not recordings:
                raise RuntimeError(
                    "No stored TDOA recordings matched candidate."
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

            consensus_result = self.solver_consensus.compute(
                solver_results=solver_results
            )

            if not consensus_result.get("success", False):
                raise RuntimeError(
                    "Solver consensus failed."
                )

            result["success"] = True
            result["channel_events"] = channel_events
            result["analysis_groups"] = analysis_groups
            result["solver_results"] = solver_results
            result["solver_consensus"] = consensus_result

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

        return result

    # ========================================================
    # RECORDING SELECTION
    # ========================================================

    def _select_recordings_for_candidate(
        self,
        candidate: dict
    ) -> list:
        """
        Select stored recordings that belong to the candidate.
        """

        candidate_node_ids = set(
            candidate.get(
                "node_ids",
                []
            )
        )

        candidate_avis_lite_id = candidate.get(
            "avis_lite_id"
        )

        selected = []

        for recording in self.recording_store:

            node_id = recording.get(
                "node_id"
            )

            avis_lite_id = recording.get(
                "avis_lite_id"
            )

            node_matches = (
                not candidate_node_ids
                or
                node_id in candidate_node_ids
            )

            avis_lite_matches = (
                candidate_avis_lite_id is None
                or
                avis_lite_id == candidate_avis_lite_id
            )

            if node_matches and avis_lite_matches:
                selected.append(
                    recording
                )

        return selected

    def _normalize_recording_event(
        self,
        recording_event: dict
    ) -> dict:
        """
        Normalize an incoming recording event into one internal shape.
        """

        payload = recording_event.get(
            "payload",
            recording_event
        )

        if not isinstance(payload, dict):
            raise TypeError(
                "Recording payload must be a dictionary."
            )

        node_id = payload.get(
            "node_id",
            recording_event.get(
                "node_id"
            )
        )

        avis_lite_id = payload.get(
            "avis_lite_id",
            recording_event.get(
                "avis_lite_id"
            )
        )

        channel_name = payload.get(
            "channel_name",
            node_id
        )

        signal = payload.get(
            "signal"
        )

        sample_rate_hz = payload.get(
            "sample_rate_hz",
            self.default_sample_rate_hz
        )

        return {
            "node_id": node_id,
            "avis_lite_id": avis_lite_id,
            "channel_name": channel_name,
            "signal": signal,
            "sample_rate_hz": sample_rate_hz,
            "timestamp": payload.get(
                "timestamp",
                recording_event.get(
                    "timestamp"
                )
            ),
            "source_event": recording_event
        }

    def _trim_recording_store(
        self
    ) -> None:
        """
        Keep bounded recording history.
        """

        if len(self.recording_store) <= self.max_recordings_stored:
            return

        overflow = (
            len(self.recording_store)
            -
            self.max_recordings_stored
        )

        self.recording_store = self.recording_store[
            overflow:
        ]

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