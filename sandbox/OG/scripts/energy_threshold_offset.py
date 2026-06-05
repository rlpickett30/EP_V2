# ============================================================
# ENVIROPULSE
# ENERGY THRESHOLD OFFSET DETECTOR
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
    Detect offset candidates using an adaptive
    energy-threshold quiet-duration method.

    This detector ONLY finds candidate offset positions.

    It does NOT:
    - manage event state
    - manage onsets
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

        "method": "energy_threshold_offset",

        "detections": [],

        "debug": {},

        "errors": []

    }

    try:

        # ====================================================
        # CONFIGURATION
        # ====================================================

        noise_sample_count = config.get(
            "noise_sample_count",
            200000
        )

        offset_multiplier = config.get(
            "offset_multiplier",
            4.0
        )

        min_quiet_samples = config.get(
            "min_quiet_samples",
            15000
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
        # BASELINE REGION
        # ====================================================

        baseline_region = signal[
            :noise_sample_count
        ]

        if len(baseline_region) == 0:

            raise ValueError(
                "Baseline region is empty."
            )

        # ====================================================
        # DYNAMIC NOISE FLOOR
        # ====================================================

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

        i = 0

        # ====================================================
        # MAIN LOOP
        # ====================================================

        while i < len(signal):

            current_energy = abs(signal[i])

            # =================================================
            # QUIET REGION
            # =================================================

            if current_energy < offset_threshold:

                quiet_counter += 1

            else:

                quiet_counter = 0

            # =================================================
            # OFFSET DETECTED
            # =================================================

            if quiet_counter >= min_quiet_samples:

                detections.append({

                    "sample_index": int(i),

                    "quiet_samples": int(
                        quiet_counter
                    ),

                    "threshold": float(
                        offset_threshold
                    ),

                    "noise_floor": float(
                        noise_floor
                    )

                })

                # =============================================
                # RESET COUNTER
                # =============================================

                quiet_counter = 0

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

                "noise_sample_count":
                    int(noise_sample_count),

                "offset_multiplier":
                    float(offset_multiplier),

                "min_quiet_samples":
                    int(min_quiet_samples),

                "noise_floor":
                    float(noise_floor),

                "offset_threshold":
                    float(offset_threshold),

                "signal_length":
                    int(len(signal)),

                "total_detections":
                    int(len(detections))

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