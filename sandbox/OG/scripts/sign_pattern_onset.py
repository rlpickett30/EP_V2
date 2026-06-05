# ============================================================
# ENVIROPULSE
# SIGN PATTERN ONSET DETECTOR
# ============================================================

import numpy as np


# ============================================================
# DETECTOR
# ============================================================

def detect(
    signal,
    config,
    debug=False
):

    """
    Detect onset candidates using sign-transition patterns.

    Example patterns:

        ----++++
        ++++----

    This detector ONLY finds candidate onset positions.

    It does NOT:
    - manage event state
    - manage offsets
    - arm/disarm
    - construct events

    Those responsibilities belong to:
        TDOA_event_detection.py
    """

    # ========================================================
    # RESULT CONTAINER
    # ========================================================

    result = {

        "success": False,

        "method": "sign_pattern_onset",

        "detections": [],

        "debug": {},

        "errors": []

    }

    try:

        # ====================================================
        # CONFIGURATION
        # ====================================================

        run_length = config.get(
            "run_length",
            3
        )

        max_backtrack = config.get(
            "max_backtrack",
            7
        )

        # ====================================================
        # VALIDATION
        # ====================================================

        if signal is None:

            raise ValueError(
                "Signal is None."
            )

        if len(signal) == 0:

            raise ValueError(
                "Signal is empty."
            )

        # ====================================================
        # SIGN STREAM
        # ====================================================

        signs = np.sign(signal)

        detections = []

        # ====================================================
        # MAIN LOOP
        # ====================================================

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

            # =================================================
            # PATTERN TESTS
            # =================================================

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

            # =================================================
            # DETECTION
            # =================================================

            if valid_pattern:

                candidate = i

                target_sign = signs[i]

                backtrack_count = 0

                # =============================================
                # LIMITED BACKTRACK
                # =============================================

                while (

                    candidate > 0
                    and
                    signs[candidate - 1] == target_sign
                    and
                    backtrack_count < max_backtrack

                ):

                    candidate -= 1

                    backtrack_count += 1

                detections.append({

                    "sample_index": int(candidate),

                    "pattern": (

                        "neg_to_pos"
                        if neg_to_pos
                        else
                        "pos_to_neg"

                    ),

                    "backtrack_count": int(
                        backtrack_count
                    )

                })

            i += 1

        # ====================================================
        # FINALIZE
        # ====================================================

        result["success"] = True

        result["detections"] = detections

        # ====================================================
        # DEBUG
        # ====================================================

        if debug:

            result["debug"] = {

                "run_length": run_length,

                "max_backtrack": max_backtrack,

                "signal_length": int(
                    len(signal)
                ),

                "total_detections": int(
                    len(detections)
                )

            }

    # ========================================================
    # ERROR HANDLING
    # ========================================================

    except Exception as e:

        result["errors"].append(
            str(e)
        )

        if debug:

            result["debug"]["exception_type"] = (
                type(e).__name__
            )

    return result

