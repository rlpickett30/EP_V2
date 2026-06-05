# ============================================================
# ENVIROPULSE
# TDOA EVENT DETECTOR
# ============================================================
#
# Purpose:
#   First stage of the TDOA pipeline.
#
# Responsibilities:
#   - Load detector_config.json
#   - Select configured onset and offset detectors
#   - Run the selected detectors
#   - Pair onset and offset detections into events
#   - Return structured TDOA event candidates
#
# Does NOT:
#   - Subscribe to the event bus
#   - Manage global system state
#   - Route events to downstream systems
#   - Solve TDOA location
#
# ============================================================

import json
from pathlib import Path


# ============================================================
# DETECTOR IMPORTS
# ============================================================

from sign_pattern_onset import detect as sign_pattern_onset
from energy_threshold_offset import detect as energy_threshold_offset


# ============================================================
# DETECTOR REGISTRY
# ============================================================

DETECTOR_REGISTRY = {

    "sign_pattern_onset":
        sign_pattern_onset,

    "energy_threshold_offset":
        energy_threshold_offset

}


# ============================================================
# CONFIG LOADER
# ============================================================

def load_detector_config(config_path):

    config_path = Path(config_path)

    if not config_path.exists():

        raise FileNotFoundError(
            f"Detector config not found: {config_path}"
        )

    with open(config_path, "r") as file:

        return json.load(file)


# ============================================================
# DETECTOR RUNNER
# ============================================================

def run_detector(
    detector_name,
    signal,
    config,
    debug=False
):

    if detector_name not in DETECTOR_REGISTRY:

        raise ValueError(
            f"Detector not registered: {detector_name}"
        )

    detector_function = DETECTOR_REGISTRY[
        detector_name
    ]

    detector_config = config.get(
        detector_name,
        {}
    )

    return detector_function(
        signal=signal,
        config=detector_config,
        debug=debug
    )


# ============================================================
# DETECTION PAIRING
# ============================================================

def pair_onsets_and_offsets(
    onset_detections,
    offset_detections,
    sample_rate,
    min_event_duration_samples,
    max_event_duration_samples
):

    events = []

    event_id = 0

    for onset in onset_detections:

        onset_index = onset["sample_index"]

        valid_offsets = [

            offset for offset in offset_detections

            if offset["sample_index"] > onset_index

        ]

        if not valid_offsets:

            continue

        offset = valid_offsets[0]

        offset_index = offset["sample_index"]

        duration_samples = offset_index - onset_index

        if duration_samples < min_event_duration_samples:

            continue

        if duration_samples > max_event_duration_samples:

            continue

        events.append({

            "event_id": event_id,

            "onset_sample": int(onset_index),

            "offset_sample": int(offset_index),

            "duration_samples": int(duration_samples),

            "onset_time_seconds": float(
                onset_index / sample_rate
            ),

            "offset_time_seconds": float(
                offset_index / sample_rate
            ),

            "duration_seconds": float(
                duration_samples / sample_rate
            ),

            "onset_metadata": onset,

            "offset_metadata": offset

        })

        event_id += 1

    return events


# ============================================================
# MAIN EVENT DETECTION FUNCTION
# ============================================================

def detect_tdoa_events(
    signal,
    config_path="detector_config.json",
    debug=False
):

    result = {

        "success": False,

        "method": "TDOA_event_detector",

        "events": [],

        "detector_results": {},

        "debug": {},

        "errors": []

    }

    try:

        # ====================================================
        # LOAD CONFIG
        # ====================================================

        config = load_detector_config(
            config_path
        )

        pipeline_config = config.get(
            "pipeline",
            {}
        )

        active_detectors = config.get(
            "active_detectors",
            {}
        )

        sample_rate = pipeline_config.get(
            "sample_rate",
            96000
        )

        min_event_duration_samples = pipeline_config.get(
            "min_event_duration_samples",
            100
        )

        max_event_duration_samples = pipeline_config.get(
            "max_event_duration_samples",
            500000
        )

        onset_detector_name = active_detectors.get(
            "onset",
            "sign_pattern_onset"
        )

        offset_detector_name = active_detectors.get(
            "offset",
            "energy_threshold_offset"
        )

        # ====================================================
        # RUN ONSET DETECTOR
        # ====================================================

        onset_result = run_detector(
            detector_name=onset_detector_name,
            signal=signal,
            config=config,
            debug=debug
        )

        # ====================================================
        # RUN OFFSET DETECTOR
        # ====================================================

        offset_result = run_detector(
            detector_name=offset_detector_name,
            signal=signal,
            config=config,
            debug=debug
        )

        result["detector_results"] = {

            "onset": onset_result,

            "offset": offset_result

        }

        # ====================================================
        # VALIDATE DETECTOR RESULTS
        # ====================================================

        if not onset_result.get("success", False):

            raise RuntimeError(
                "Onset detector failed."
            )

        if not offset_result.get("success", False):

            raise RuntimeError(
                "Offset detector failed."
            )

        onset_detections = onset_result.get(
            "detections",
            []
        )

        offset_detections = offset_result.get(
            "detections",
            []
        )

        # ====================================================
        # PAIR DETECTIONS INTO EVENTS
        # ====================================================

        events = pair_onsets_and_offsets(
            onset_detections=onset_detections,
            offset_detections=offset_detections,
            sample_rate=sample_rate,
            min_event_duration_samples=min_event_duration_samples,
            max_event_duration_samples=max_event_duration_samples
        )

        # ====================================================
        # FINALIZE
        # ====================================================

        result["success"] = True

        result["events"] = events

        if debug:

            result["debug"] = {

                "config_path": str(config_path),

                "sample_rate": int(sample_rate),

                "onset_detector": onset_detector_name,

                "offset_detector": offset_detector_name,

                "onset_detection_count": int(
                    len(onset_detections)
                ),

                "offset_detection_count": int(
                    len(offset_detections)
                ),

                "event_count": int(
                    len(events)
                )

            }

    except Exception as e:

        result["errors"].append(
            str(e)
        )

        if debug:

            result["debug"]["exception_type"] = (
                type(e).__name__
            )

    return result


# ============================================================
# OPTIONAL DIRECT TEST
# ============================================================

if __name__ == "__main__":

    print(
        "TDOA_event_detector.py loaded successfully."
    )

