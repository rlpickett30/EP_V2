# ============================================================
# energy_threshold_onset.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Role:
#   Helper script.
#
# Purpose:
#   Detect onset candidates using an adaptive energy-threshold
#   active-duration method.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["energy_threshold_onset"]
#
# Does:
#   - Finds candidate onset sample indexes
#   - Uses a dynamic noise floor
#   - Requires a minimum active duration
#   - Returns structured detection results
#
# Does NOT:
#   - Load TDOA_config.json directly
#   - Own workflow
#   - Manage event state
#   - Manage offsets
#   - Arm/disarm detection
#   - Construct TDOA events
#   - Publish events
#
# Owner:
#   TDOA_event_detection.py or TDOA_manager.py
#
# ============================================================

import numpy as np


def detect_energy_threshold_onsets(
    signal,
    config,
    sample_rate_hz,
    debug=False
):
    """
    Detect onset candidates using adaptive active-duration logic.

    Parameters
    ----------
    signal:
        Audio signal array.

    config:
        Full TDOA config dictionary or the energy_threshold_onset
        subsection from TDOA_config.json.

    sample_rate_hz:
        Audio sample rate in Hz.

    debug:
        If True, returns additional diagnostic information.

    Returns
    -------
    dict:
        Structured detection result.
    """

    result = {
        "success": False,
        "method": "energy_threshold_onset",
        "detections": [],
        "debug": {},
        "errors": []
    }

    try:
        # ----------------------------------------------------
        # CONFIGURATION
        # ----------------------------------------------------

        detector_config = config.get(
            "energy_threshold_onset",
            config
        )

        noise_window_seconds = detector_config.get(
            "noise_window_seconds",
            2.0
        )

        onset_multiplier = detector_config.get(
            "onset_multiplier",
            6.0
        )

        min_active_seconds = detector_config.get(
            "min_active_seconds",
            0.01
        )

        minimum_detection_spacing_seconds = detector_config.get(
            "minimum_detection_spacing_seconds",
            0.025
        )

        noise_sample_count = int(
            noise_window_seconds * sample_rate_hz
        )

        min_active_samples = int(
            min_active_seconds * sample_rate_hz
        )

        minimum_detection_spacing_samples = int(
            minimum_detection_spacing_seconds * sample_rate_hz
        )

        # ----------------------------------------------------
        # VALIDATION
        # ----------------------------------------------------

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

        if noise_sample_count <= 0:
            raise ValueError(
                "noise_window_seconds must produce at least one sample."
            )

        if min_active_samples <= 0:
            raise ValueError(
                "min_active_seconds must produce at least one sample."
            )

        if onset_multiplier <= 0:
            raise ValueError(
                "onset_multiplier must be greater than zero."
            )

        # ----------------------------------------------------
        # BASELINE REGION
        # ----------------------------------------------------

        baseline_region = signal[
            :noise_sample_count
        ]

        if len(baseline_region) == 0:
            raise ValueError(
                "Baseline region is empty."
            )

        # ----------------------------------------------------
        # DYNAMIC NOISE FLOOR
        # ----------------------------------------------------

        noise_floor = np.mean(
            np.abs(baseline_region)
        )

        onset_threshold = (
            noise_floor
            *
            onset_multiplier
        )

        detections = []

        active_counter = 0

        last_detection_index = None

        # ----------------------------------------------------
        # MAIN LOOP
        # ----------------------------------------------------

        i = 0

        while i < len(signal):

            current_energy = abs(
                signal[i]
            )

            if current_energy > onset_threshold:
                active_counter += 1
            else:
                active_counter = 0

            if active_counter >= min_active_samples:

                estimated_onset_index = (
                    i
                    - min_active_samples
                    + 1
                )

                confirmation_index = i

                spacing_allowed = (
                    last_detection_index is None
                    or
                    estimated_onset_index - last_detection_index
                    >= minimum_detection_spacing_samples
                )

                if spacing_allowed:

                    detections.append(
                        {
                            "sample_index": int(
                                estimated_onset_index
                            ),
                            "time_seconds": float(
                                estimated_onset_index
                                / sample_rate_hz
                            ),
                            "confirmed_at_sample_index": int(
                                confirmation_index
                            ),
                            "confirmed_at_time_seconds": float(
                                confirmation_index
                                / sample_rate_hz
                            ),
                            "active_samples": int(
                                active_counter
                            ),
                            "active_seconds": float(
                                active_counter
                                / sample_rate_hz
                            ),
                            "threshold": float(
                                onset_threshold
                            ),
                            "noise_floor": float(
                                noise_floor
                            )
                        }
                    )

                    last_detection_index = estimated_onset_index

                active_counter = 0

            i += 1

        # ----------------------------------------------------
        # FINALIZE
        # ----------------------------------------------------

        result["success"] = True

        result["detections"] = detections

        if debug:
            result["debug"] = {
                "noise_window_seconds": float(
                    noise_window_seconds
                ),
                "noise_sample_count": int(
                    noise_sample_count
                ),
                "onset_multiplier": float(
                    onset_multiplier
                ),
                "min_active_seconds": float(
                    min_active_seconds
                ),
                "min_active_samples": int(
                    min_active_samples
                ),
                "minimum_detection_spacing_seconds": float(
                    minimum_detection_spacing_seconds
                ),
                "minimum_detection_spacing_samples": int(
                    minimum_detection_spacing_samples
                ),
                "noise_floor": float(
                    noise_floor
                ),
                "onset_threshold": float(
                    onset_threshold
                ),
                "sample_rate_hz": float(
                    sample_rate_hz
                ),
                "signal_length": int(
                    len(signal)
                ),
                "total_detections": int(
                    len(detections)
                )
            }

    except Exception as error:

        result["errors"].append(
            str(error)
        )

        if debug:
            result["debug"]["exception_type"] = (
                type(error).__name__
            )

    return result
