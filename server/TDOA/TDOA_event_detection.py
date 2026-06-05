# ============================================================
# TDOA_event_detection.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Role:
#   Specialized helper / event-window detection orchestrator.
#
# Purpose:
#   Detect event windows inside one audio channel by combining
#   onset detection, offset detection, and general feature
#   extraction.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["TDOA_event_detection"]
#
# Does:
#   - Select configured onset detector
#   - Select configured offset detector
#   - Run onset and offset helper detectors
#   - Match onset candidates to offset candidates
#   - Build event windows
#   - Attach general signal features
#   - Return structured channel event results
#
# Does NOT:
#   - Load TDOA_config.json directly
#   - Publish events
#   - Own subsystem workflow
#   - Maintain platform state
#   - Solve TDOA geometry
#   - Perform final event matching across channels
#   - Perform solver consensus
#   - Build final canonical TDOA result objects
#
# Owner:
#   TDOA_manager.py
#
# ============================================================

from typing import Optional, Callable, List

from energy_threshold_onset import (
    detect_energy_threshold_onsets
)

from energy_threshold_offset import (
    detect_energy_threshold_offsets
)

from sign_pattern_onset import (
    detect_sign_pattern_onsets
)

from sign_pattern_offset import (
    detect_sign_pattern_offsets
)

from general_features import (
    extract_general_features
)


class TDOAEventDetection:
    """
    Event-window detection orchestrator for one channel.

    This class coordinates lower-level detector helpers but does
    not own the larger TDOA workflow.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        config: dict,
        debug: bool = False
    ):
        self.config = config
        self.debug = debug

        detection_config = self.config.get(
            "TDOA_event_detection",
            {}
        )

        self.onset_method = detection_config.get(
            "onset_method",
            "energy_threshold_onset"
        )

        self.offset_method = detection_config.get(
            "offset_method",
            "energy_threshold_offset"
        )

        self.include_event_window = detection_config.get(
            "include_event_window",
            True
        )

        self.minimum_event_duration_seconds = detection_config.get(
            "minimum_event_duration_seconds",
            0.0
        )

        self.maximum_event_duration_seconds = detection_config.get(
            "maximum_event_duration_seconds",
            None
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def process_channel(
        self,
        signal,
        sample_rate_hz: float,
        channel_name: str = "CH1"
    ) -> dict:
        """
        Process one audio channel and return detected event windows.
        """

        result = {
            "success": False,
            "channel_name": channel_name,
            "events": [],
            "debug": {},
            "errors": []
        }

        try:
            self._validate_signal_input(
                signal=signal,
                sample_rate_hz=sample_rate_hz
            )

            onset_result = self._run_onset_detector(
                signal=signal,
                sample_rate_hz=sample_rate_hz
            )

            offset_result = self._run_offset_detector(
                signal=signal,
                sample_rate_hz=sample_rate_hz
            )

            if not onset_result.get("success", False):
                raise RuntimeError(
                    "Onset detector failed."
                )

            if not offset_result.get("success", False):
                raise RuntimeError(
                    "Offset detector failed."
                )

            onset_candidates = onset_result.get(
                "detections",
                []
            )

            offset_candidates = offset_result.get(
                "detections",
                []
            )

            events = self._build_event_windows(
                signal=signal,
                sample_rate_hz=sample_rate_hz,
                channel_name=channel_name,
                onset_candidates=onset_candidates,
                offset_candidates=offset_candidates
            )

            result["success"] = True
            result["events"] = events

            if self.debug:
                result["debug"] = {
                    "channel_name": channel_name,
                    "onset_method": self.onset_method,
                    "offset_method": self.offset_method,
                    "total_onsets": len(onset_candidates),
                    "total_offsets": len(offset_candidates),
                    "total_events": len(events),
                    "include_event_window": bool(
                        self.include_event_window
                    ),
                    "minimum_event_duration_seconds": float(
                        self.minimum_event_duration_seconds
                    ),
                    "maximum_event_duration_seconds":
                        self.maximum_event_duration_seconds,
                    "onset_debug": onset_result.get(
                        "debug",
                        {}
                    ),
                    "offset_debug": offset_result.get(
                        "debug",
                        {}
                    )
                }

        except Exception as error:
            result["errors"].append(
                str(error)
            )

            if self.debug:
                result["debug"]["exception_type"] = (
                    type(error).__name__
                )

        return result

    # ========================================================
    # DETECTOR SELECTION
    # ========================================================

    def _run_onset_detector(
        self,
        signal,
        sample_rate_hz: float
    ) -> dict:
        """
        Run the configured onset detector.
        """

        detector = self._get_onset_detector(
            self.onset_method
        )

        return detector(
            signal=signal,
            config=self.config,
            sample_rate_hz=sample_rate_hz,
            debug=self.debug
        )

    def _run_offset_detector(
        self,
        signal,
        sample_rate_hz: float
    ) -> dict:
        """
        Run the configured offset detector.
        """

        detector = self._get_offset_detector(
            self.offset_method
        )

        return detector(
            signal=signal,
            config=self.config,
            sample_rate_hz=sample_rate_hz,
            debug=self.debug
        )

    def _get_onset_detector(
        self,
        method_name: str
    ) -> Callable:
        """
        Return onset detector helper function by name.
        """

        onset_detectors = {
            "energy_threshold_onset":
                detect_energy_threshold_onsets,

            "sign_pattern_onset":
                detect_sign_pattern_onsets
        }

        if method_name not in onset_detectors:
            raise ValueError(
                f"Unknown onset detector method: {method_name}"
            )

        return onset_detectors[method_name]

    def _get_offset_detector(
        self,
        method_name: str
    ) -> Callable:
        """
        Return offset detector helper function by name.
        """

        offset_detectors = {
            "energy_threshold_offset":
                detect_energy_threshold_offsets,

            "sign_pattern_offset":
                detect_sign_pattern_offsets
        }

        if method_name not in offset_detectors:
            raise ValueError(
                f"Unknown offset detector method: {method_name}"
            )

        return offset_detectors[method_name]

    # ========================================================
    # EVENT WINDOW CONSTRUCTION
    # ========================================================

    def _build_event_windows(
        self,
        signal,
        sample_rate_hz: float,
        channel_name: str,
        onset_candidates: List[dict],
        offset_candidates: List[dict]
    ) -> List[dict]:
        """
        Match onset candidates to offset candidates and build
        event-window records.
        """

        events = []

        offset_index = 0

        for onset in onset_candidates:

            onset_sample = onset.get(
                "sample_index"
            )

            if onset_sample is None:
                continue

            matched_offset = self._find_next_offset_after_onset(
                onset_sample=onset_sample,
                offset_candidates=offset_candidates,
                offset_start_index=offset_index
            )

            if matched_offset is None:
                continue

            offset_sample = matched_offset.get(
                "sample_index"
            )

            offset_index = matched_offset.get(
                "next_offset_index",
                offset_index
            )

            if offset_sample is None:
                continue

            event_record = self._build_single_event_record(
                signal=signal,
                sample_rate_hz=sample_rate_hz,
                channel_name=channel_name,
                onset=onset,
                offset=matched_offset.get(
                    "offset_metadata",
                    {}
                ),
                onset_sample=onset_sample,
                offset_sample=offset_sample
            )

            if event_record is not None:
                events.append(
                    event_record
                )

        return events

    def _find_next_offset_after_onset(
        self,
        onset_sample: int,
        offset_candidates: List[dict],
        offset_start_index: int
    ) -> Optional[dict]:
        """
        Find the next offset candidate occurring after onset_sample.
        """

        offset_index = offset_start_index

        while offset_index < len(offset_candidates):

            offset = offset_candidates[
                offset_index
            ]

            offset_sample = offset.get(
                "sample_index"
            )

            offset_index += 1

            if offset_sample is None:
                continue

            if offset_sample > onset_sample:
                return {
                    "sample_index": offset_sample,
                    "offset_metadata": offset,
                    "next_offset_index": offset_index
                }

        return None

    def _build_single_event_record(
        self,
        signal,
        sample_rate_hz: float,
        channel_name: str,
        onset: dict,
        offset: dict,
        onset_sample: int,
        offset_sample: int
    ) -> Optional[dict]:
        """
        Build one event record from matched onset and offset samples.
        """

        duration_samples = int(
            offset_sample - onset_sample
        )

        if duration_samples <= 0:
            return None

        duration_seconds = float(
            duration_samples / sample_rate_hz
        )

        if duration_seconds < self.minimum_event_duration_seconds:
            return None

        if (
            self.maximum_event_duration_seconds is not None
            and
            duration_seconds > self.maximum_event_duration_seconds
        ):
            return None

        event_window = signal[
            onset_sample:
            offset_sample
        ]

        if len(event_window) == 0:
            return None

        feature_result = extract_general_features(
            signal=event_window,
            config=self.config,
            sample_rate_hz=sample_rate_hz,
            debug=self.debug
        )

        if not feature_result.get("success", False):
            raise RuntimeError(
                "General feature extraction failed."
            )

        event_record = {
            "channel_name": channel_name,
            "onset_sample": int(onset_sample),
            "offset_sample": int(offset_sample),
            "duration_samples": duration_samples,
            "duration_seconds": duration_seconds,
            "sample_rate_hz": float(sample_rate_hz),
            "onset_metadata": onset,
            "offset_metadata": offset,
            "features": feature_result.get(
                "features",
                {}
            )
        }

        if self.include_event_window:
            event_record["event_window"] = event_window

        if self.debug:
            event_record["feature_debug"] = feature_result.get(
                "debug",
                {}
            )

        return event_record

    # ========================================================
    # VALIDATION
    # ========================================================

    def _validate_signal_input(
        self,
        signal,
        sample_rate_hz: float
    ) -> None:
        """
        Validate signal input before detection.
        """

        if signal is None:
            raise ValueError(
                "Signal is None."
            )

        if len(signal) == 0:
            raise ValueError(
                "Signal is empty."
            )

        if sample_rate_hz is None or sample_rate_hz <= 0:
            raise ValueError(
                "sample_rate_hz must be greater than zero."
            )