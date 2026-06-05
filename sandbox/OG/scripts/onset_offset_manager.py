# ============================================================
# ENVIROPULSE
# ONSET / OFFSET MANAGER
# ============================================================

"""
Purpose
-------
Central routing layer for onset and offset detectors.

This manager:
- selects WHICH detector methods are active
- loads detector modules
- exposes a unified interface to TDOA_event_detection.py
- allows easy manual tuning and swapping

This is intentionally simple for now.

Future versions may:
- dynamically choose detectors
- adapt to environmental conditions
- support detector ensembles
- load configs remotely
"""

# ============================================================
# IMPORT DETECTORS
# ============================================================

import sign_pattern_onset

import energy_threshold_offset


# ============================================================
# MANAGER
# ============================================================

class OnsetOffsetManager:

    def __init__(self):

        """
        Manual detector selection.

        This is where YOU decide which methods
        are currently active.
        """

        # ====================================================
        # ACTIVE DETECTOR CONFIGURATION
        # ====================================================

        self.onset_method = "sign_pattern"

        self.offset_method = "energy_threshold"

        # ====================================================
        # DETECTOR REGISTRY
        # ====================================================

        self.onset_detectors = {

            "sign_pattern":
                sign_pattern_onset

        }

        self.offset_detectors = {

            "energy_threshold":
                energy_threshold_offset

        }

        # ====================================================
        # LOAD ACTIVE DETECTORS
        # ====================================================

        self.onset_detector = (
            self._load_onset_detector()
        )

        self.offset_detector = (
            self._load_offset_detector()
        )

    # ========================================================
    # LOAD ONSET DETECTOR
    # ========================================================

    def _load_onset_detector(self):

        if self.onset_method not in self.onset_detectors:

            raise ValueError(

                f"Unknown onset detector: "
                f"{self.onset_method}"

            )

        return self.onset_detectors[
            self.onset_method
        ]

    # ========================================================
    # LOAD OFFSET DETECTOR
    # ========================================================

    def _load_offset_detector(self):

        if self.offset_method not in self.offset_detectors:

            raise ValueError(

                f"Unknown offset detector: "
                f"{self.offset_method}"

            )

        return self.offset_detectors[
            self.offset_method
        ]

    # ========================================================
    # DETECT ONSETS
    # ========================================================

    def detect_onsets(

        self,
        signal,
        config,
        debug=False

    ):

        """
        Route onset detection
        to the active detector.
        """

        return self.onset_detector.detect(

            signal=signal,
            config=config,
            debug=debug

        )

    # ========================================================
    # DETECT OFFSETS
    # ========================================================

    def detect_offsets(

        self,
        signal,
        config,
        debug=False

    ):

        """
        Route offset detection
        to the active detector.
        """

        return self.offset_detector.detect(

            signal=signal,
            config=config,
            debug=debug

        )

    # ========================================================
    # DETECTOR STATUS
    # ========================================================

    def get_active_methods(self):

        """
        Return active detector names.
        """

        return {

            "onset_method":
                self.onset_method,

            "offset_method":
                self.offset_method

        }
