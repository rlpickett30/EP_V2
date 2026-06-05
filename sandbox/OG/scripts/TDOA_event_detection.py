# ============================================================
# ENVIROPULSE
# TDOA EVENT DETECTION
# ============================================================

"""
Purpose
-------
This module performs event lifecycle management.

Responsibilities:
- onset/offset state management
- armed/disarmed event tracking
- detector orchestration
- event interval construction
- signal statistics extraction

This module DOES NOT:
- perform localization
- solve TDOA geometry
- perform cross-correlation alignment
- build the final canonical event object

Those responsibilities belong to:
    TDOA_manager.py
"""

# ============================================================
# IMPORTS
# ============================================================

import numpy as np

from onset_offset_manager import (
    OnsetOffsetManager
)


# ============================================================
# EVENT DETECTOR
# ============================================================

class TDOAEventDetection:

    def __init__(

        self,

        onset_config,
        offset_config,
        debug=False

    ):

        # ====================================================
        # CONFIGURATION
        # ====================================================

        self.onset_config = onset_config

        self.offset_config = offset_config

        self.debug = debug

        # ====================================================
        # DETECTOR MANAGER
        # ====================================================

        self.detector_manager = (
            OnsetOffsetManager()
        )

    # ========================================================
    # MAIN EVENT DETECTION
    # ========================================================

    def process_channel(

        self,
        signal,
        sample_rate,
        channel_name="CH1"

    ):

        """
        Process one channel and extract
        event interval information.
        """

        result = {

            "success": False,

            "channel_name": channel_name,

            "events": [],

            "debug": {},

            "errors": []

        }

        try:

            # =================================================
            # DETECTOR CALLS
            # =================================================

            onset_result = (

                self.detector_manager.detect_onsets(

                    signal=signal,

                    config=self.onset_config,

                    debug=self.debug

                )

            )

            offset_result = (

                self.detector_manager.detect_offsets(

                    signal=signal,

                    config=self.offset_config,

                    debug=self.debug

                )

            )

            # =================================================
            # VALIDATION
            # =================================================

            if not onset_result["success"]:

                raise RuntimeError(

                    "Onset detector failed."

                )

            if not offset_result["success"]:

                raise RuntimeError(

                    "Offset detector failed."

                )

            onset_candidates = (
                onset_result["detections"]
            )

            offset_candidates = (
                offset_result["detections"]
            )

            # =================================================
            # STATE MACHINE
            # =================================================

            armed = True

            current_event = None

            offset_index = 0

            events = []

            # =================================================
            # PROCESS ONSETS
            # =================================================

            for onset in onset_candidates:

                if not armed:

                    continue

                onset_sample = (
                    onset["sample_index"]
                )

                # =============================================
                # FIND MATCHING OFFSET
                # =============================================

                matched_offset = None

                while offset_index < len(
                    offset_candidates
                ):

                    candidate_offset = (

                        offset_candidates[
                            offset_index
                        ]["sample_index"]

                    )

                    offset_index += 1

                    if candidate_offset > onset_sample:

                        matched_offset = (
                            candidate_offset
                        )

                        break

                # =============================================
                # NO OFFSET FOUND
                # =============================================

                if matched_offset is None:

                    continue

                # =============================================
                # BUILD EVENT WINDOW
                # =============================================

                event_window = signal[

                    onset_sample:
                    matched_offset

                ]

                if len(event_window) == 0:

                    continue

                # =============================================
                # SIGNAL METRICS
                # =============================================

                peak_amplitude = float(

                    np.max(
                        np.abs(event_window)
                    )

                )

                rms_energy = float(

                    np.sqrt(
                        np.mean(
                            event_window ** 2
                        )
                    )

                )

                duration_samples = int(

                    matched_offset
                    -
                    onset_sample

                )

                duration_seconds = float(

                    duration_samples
                    /
                    sample_rate

                )

                local_noise_floor = float(

                    np.mean(
                        np.abs(
                            signal[
                                max(
                                    0,
                                    onset_sample - 5000
                                ):
                                onset_sample
                            ]
                        )
                    )

                )

                # =============================================
                # EVENT RECORD
                # =============================================

                event_record = {

                    "onset_sample":
                        int(onset_sample),

                    "offset_sample":
                        int(matched_offset),

                    "duration_samples":
                        duration_samples,

                    "duration_seconds":
                        duration_seconds,

                    "peak_amplitude":
                        peak_amplitude,

                    "rms_energy":
                        rms_energy,

                    "local_noise_floor":
                        local_noise_floor,

                    "event_window":
                        event_window,

                    "sample_rate":
                        sample_rate,

                    "onset_metadata":
                        onset,

                    "channel_name":
                        channel_name

                }

                events.append(
                    event_record
                )

                armed = False

                # =============================================
                # RE-ARM
                # =============================================

                armed = True

            # =================================================
            # FINALIZE
            # =================================================

            result["success"] = True

            result["events"] = events

            # =================================================
            # DEBUG
            # =================================================

            if self.debug:

                result["debug"] = {

                    "total_onsets":
                        len(onset_candidates),

                    "total_offsets":
                        len(offset_candidates),

                    "total_events":
                        len(events),

                    "active_methods":

                        self.detector_manager
                        .get_active_methods(),

                    "onset_debug":
                        onset_result["debug"],

                    "offset_debug":
                        offset_result["debug"]

                }

        # ====================================================
        # ERROR HANDLING
        # ====================================================

        except Exception as e:

            result["errors"].append(
                str(e)
            )

            if self.debug:

                result["debug"]["exception_type"] = (
                    type(e).__name__
                )

        return result