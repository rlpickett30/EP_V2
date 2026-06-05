# ============================================================
# energy_threshold_offset.py
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
#   Detect offset candidates using an adaptive energy-threshold
#   quiet-duration method.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["energy_threshold_offset"]
#
# Does:
#   - Finds candidate offset sample indexes
#   - Uses a dynamic noise floor
#   - Requires a minimum quiet duration
#   - Returns structured detection results
#
# Does NOT:
#   - Load TDOA_config.json directly
#   - Own workflow
#   - Manage event state
#   - Manage onsets
#   - Arm/disarm detection
#   - Construct TDOA events
#   - Publish events
#
# Owner:
#   TDOA_event_detection.py or TDOA_manager.py
#
# ============================================================

import numpy as np


def detect_energy_threshold_offsets(
    signal,
    config,
    sample_rate_hz,
    debug=False
):
    """
    Detect offset candidates using adaptive quiet-duration logic.

    Parameters
    ----------
    signal:
        Audio signal array.

    config:
        Full TDOA config dictionary or the energy_threshold_offset
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
        "method": "energy_threshold_offset",
        "detections": [],
        "debug": {},
        "errors": []
    }

    try:
        # ----------------------------------------------------
        # CONFIGURATION
        # ----------------------------------------------------

        detector_config = config.get(
            "energy_threshold_offset",
            config
        )

        noise_window_seconds = detector_config.get(
            "noise_window_seconds",
            2.0
        )

        offset_multiplier = detector_config.get(
            "offset_multiplier",
            4.0
        )

        min_quiet_seconds = detector_config.get(
            "min_quiet_seconds",
            0.15
        )

        minimum_detection_spacing_seconds = detector_config.get(
            "minimum_detection_spacing_seconds",
            0.025
        )

        noise_sample_count = int(
            noise_window_seconds * sample_rate_hz
        )

        min_quiet_samples = int(
            min_quiet_seconds * sample_rate_hz
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

        if min_quiet_samples <= 0:
            raise ValueError(
                "min_quiet_seconds must produce at least one sample."
            )

        if offset_multiplier <= 0:
            raise ValueError(
                "offset_multiplier must be greater than zero."
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

        offset_threshold = (
            noise_floor
            *
            offset_multiplier
        )

        detections = []

        quiet_counter = 0

        last_detection_index = None

        # ----------------------------------------------------
        # MAIN LOOP
        # ----------------------------------------------------

        i = 0

        while i < len(signal):

            current_energy = abs(
                signal[i]
            )

            if current_energy < offset_threshold:
                quiet_counter += 1
            else:
                quiet_counter = 0

            if quiet_counter >= min_quiet_samples:

                estimated_offset_index = (
                    i
                    - min_quiet_samples
                    + 1
                )

                confirmation_index = i

                spacing_allowed = (
                    last_detection_index is None
                    or
                    estimated_offset_index - last_detection_index
                    >= minimum_detection_spacing_samples
                )

                if spacing_allowed:

                    detections.append(
                        {
                            "sample_index": int(
                                estimated_offset_index
                            ),
                            "time_seconds": float(
                                estimated_offset_index
                                / sample_rate_hz
                            ),
                            "confirmed_at_sample_index": int(
                                confirmation_index
                            ),
                            "confirmed_at_time_seconds": float(
                                confirmation_index
                                / sample_rate_hz
                            ),
                            "quiet_samples": int(
                                quiet_counter
                            ),
                            "quiet_seconds": float(
                                quiet_counter
                                / sample_rate_hz
                            ),
                            "threshold": float(
                                offset_threshold
                            ),
                            "noise_floor": float(
                                noise_floor
                            )
                        }
                    )

                    last_detection_index = estimated_offset_index

                quiet_counter = 0

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
                "offset_multiplier": float(
                    offset_multiplier
                ),
                "min_quiet_seconds": float(
                    min_quiet_seconds
                ),
                "min_quiet_samples": int(
                    min_quiet_samples
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
                "offset_threshold": float(
                    offset_threshold
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