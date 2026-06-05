# ============================================================
# general_features.py
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
#   Extract general signal features that may be useful for
#   matching, consensus, event analysis, and future TDOA logic.
#
# Current features:
#   - Peak amplitude
#   - Peak sample index
#   - Peak time in seconds
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["general_features"]
#
# Does:
#   - Extract reusable signal features
#   - Return structured feature results
#
# Does NOT:
#   - Load TDOA_config.json directly
#   - Own workflow
#   - Manage event state
#   - Detect onsets
#   - Detect offsets
#   - Match events
#   - Solve TDOA
#   - Publish events
#
# Owner:
#   TDOA_event_detection.py or TDOA_event_analysis.py
#
# ============================================================

import numpy as np


def extract_general_features(
    signal,
    config,
    sample_rate_hz,
    debug=False
):
    """
    Extract general signal features.

    Parameters
    ----------
    signal:
        Audio signal array.

    config:
        Full TDOA config dictionary or the general_features
        subsection from TDOA_config.json.

    sample_rate_hz:
        Audio sample rate in Hz.

    debug:
        If True, returns additional diagnostic information.

    Returns
    -------
    dict:
        Structured feature extraction result.
    """

    result = {
        "success": False,
        "method": "general_features",
        "features": {},
        "debug": {},
        "errors": []
    }

    try:
        # ----------------------------------------------------
        # CONFIGURATION
        # ----------------------------------------------------

        feature_config = config.get(
            "general_features",
            config
        )

        extract_peak_amplitude = feature_config.get(
            "extract_peak_amplitude",
            True
        )

        use_absolute_peak = feature_config.get(
            "use_absolute_peak",
            True
        )

        return_peak_time = feature_config.get(
            "return_peak_time",
            True
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

        # ----------------------------------------------------
        # NORMALIZE INPUT
        # ----------------------------------------------------

        signal_array = np.asarray(
            signal
        )

        # ----------------------------------------------------
        # PEAK AMPLITUDE
        # ----------------------------------------------------

        if extract_peak_amplitude:

            peak_features = _extract_peak_amplitude(
                signal_array=signal_array,
                sample_rate_hz=sample_rate_hz,
                use_absolute_peak=use_absolute_peak,
                return_peak_time=return_peak_time
            )

            result["features"]["peak_amplitude"] = peak_features

        # ----------------------------------------------------
        # FINALIZE
        # ----------------------------------------------------

        result["success"] = True

        if debug:
            result["debug"] = {
                "sample_rate_hz": float(
                    sample_rate_hz
                ),
                "signal_length": int(
                    len(signal_array)
                ),
                "extract_peak_amplitude": bool(
                    extract_peak_amplitude
                ),
                "use_absolute_peak": bool(
                    use_absolute_peak
                ),
                "return_peak_time": bool(
                    return_peak_time
                ),
                "feature_names": list(
                    result["features"].keys()
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


# ============================================================
# FEATURE HELPERS
# ============================================================

def _extract_peak_amplitude(
    signal_array,
    sample_rate_hz,
    use_absolute_peak=True,
    return_peak_time=True
):
    """
    Extract peak amplitude information from a signal.
    """

    if use_absolute_peak:

        peak_index = int(
            np.argmax(
                np.abs(signal_array)
            )
        )

        peak_value = float(
            signal_array[peak_index]
        )

        peak_magnitude = float(
            abs(peak_value)
        )

    else:

        peak_index = int(
            np.argmax(
                signal_array
            )
        )

        peak_value = float(
            signal_array[peak_index]
        )

        peak_magnitude = float(
            peak_value
        )

    peak_features = {
        "sample_index": peak_index,
        "value": peak_value,
        "magnitude": peak_magnitude
    }

    if return_peak_time:

        peak_features["time_seconds"] = float(
            peak_index / sample_rate_hz
        )

    return peak_features