# ============================================================
# sign_pattern_onset.py
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
#   Detect onset candidates using sign-transition patterns.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["sign_pattern_onset"]
#
# Does:
#   - Finds candidate onset sample indexes
#   - Uses sign-transition patterns
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


def detect_sign_pattern_onsets(
    signal,
    config,
    sample_rate_hz,
    debug=False
):
    """
    Detect onset candidates using sign-transition patterns.

    Example patterns:
        ----++++
        ++++----

    Parameters
    ----------
    signal:
        Audio signal array.

    config:
        Full TDOA config dictionary or the sign_pattern_onset
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
        "method": "sign_pattern_onset",
        "detections": [],
        "debug": {},
        "errors": []
    }

    try:
        # ----------------------------------------------------
        # CONFIGURATION
        # ----------------------------------------------------

        detector_config = config.get(
            "sign_pattern_onset",
            config
        )

        run_length = detector_config.get(
            "run_length",
            3
        )

        max_backtrack_samples = detector_config.get(
            "max_backtrack_samples",
            7
        )

        minimum_detection_spacing_seconds = detector_config.get(
            "minimum_detection_spacing_seconds",
            0.025
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

        if run_length <= 0:
            raise ValueError(
                "run_length must be greater than zero."
            )

        if max_backtrack_samples < 0:
            raise ValueError(
                "max_backtrack_samples cannot be negative."
            )

        # ----------------------------------------------------
        # SIGN STREAM
        # ----------------------------------------------------

        signs = np.sign(signal)

        detections = []

        last_detection_index = None

        # ----------------------------------------------------
        # MAIN LOOP
        # ----------------------------------------------------

        i = 0

        while i < len(signal) - run_length * 2:

            first_block = signs[
                i:
                i + run_length
            ]

            second_block = signs[
                i + run_length:
                i + run_length * 2
            ]

            neg_to_pos = (
                np.all(first_block == -1)
                and
                np.all(second_block == 1)
            )

            pos_to_neg = (
                np.all(first_block == 1)
                and
                np.all(second_block == -1)
            )

            valid_pattern = (
                neg_to_pos
                or
                pos_to_neg
            )

            if valid_pattern:

                candidate_index = i

                target_sign = signs[i]

                backtrack_count = 0

                while (
                    candidate_index > 0
                    and signs[candidate_index - 1] == target_sign
                    and backtrack_count < max_backtrack_samples
                ):
                    candidate_index -= 1
                    backtrack_count += 1

                spacing_allowed = (
                    last_detection_index is None
                    or
                    candidate_index - last_detection_index
                    >= minimum_detection_spacing_samples
                )

                if spacing_allowed:

                    detections.append(
                        {
                            "sample_index": int(candidate_index),
                            "time_seconds": float(
                                candidate_index / sample_rate_hz
                            ),
                            "pattern": (
                                "neg_to_pos"
                                if neg_to_pos
                                else
                                "pos_to_neg"
                            ),
                            "backtrack_count": int(
                                backtrack_count
                            )
                        }
                    )

                    last_detection_index = candidate_index

            i += 1

        # ----------------------------------------------------
        # FINALIZE
        # ----------------------------------------------------

        result["success"] = True

        result["detections"] = detections

        if debug:
            result["debug"] = {
                "run_length": int(run_length),
                "max_backtrack_samples": int(
                    max_backtrack_samples
                ),
                "minimum_detection_spacing_seconds": float(
                    minimum_detection_spacing_seconds
                ),
                "minimum_detection_spacing_samples": int(
                    minimum_detection_spacing_samples
                ),
                "sample_rate_hz": float(sample_rate_hz),
                "signal_length": int(len(signal)),
                "total_detections": int(len(detections))
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