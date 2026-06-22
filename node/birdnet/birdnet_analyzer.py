# ============================================================
# birdnet_analyzer.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   BirdNET
#
# Role:
#   Helper Script
#
# Purpose:
#   Analyze WAV recordings with birdnetlib and return normalized
#   detection dictionaries to birdnet_manager.py.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Initialize the BirdNET analyzer once
#   - Analyze supplied WAV files
#   - Accept runtime latitude, longitude, week, and confidence values
#   - Normalize BirdNET detections into stable dictionaries
#   - Return detections sorted by confidence
#
# Does NOT:
#   - Subscribe to the event bus
#   - Publish events
#   - Build AVIS_LITE events
#   - Own BirdNET workflow
#   - Own GPS state
#   - Read or write configuration files
#   - Call BirdNET-Analyzer internal core imports directly
#
# Owner:
#   birdnet_manager.py
#
# ============================================================

from __future__ import annotations

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import pathlib
import time

from typing import Any
from typing import Dict
from typing import List

# ============================================================
# IMPORT THIRD-PARTY SUPPORT LIBRARIES
# ============================================================

from birdnetlib import Recording
from birdnetlib.analyzer import Analyzer


# ============================================================
# MODULE DEFAULTS
# ============================================================

DEFAULT_LATITUDE = 37.2753
DEFAULT_LONGITUDE = -107.8801
DEFAULT_WEEK = 26
DEFAULT_MIN_CONFIDENCE = 0.01

_ANALYZER = None


# ============================================================
# DEBUG
# ============================================================

def _log(
    message: str
):
    print(
        f"[BirdNET] {message}"
    )


# ============================================================
# ANALYZER LIFECYCLE
# ============================================================

def _get_analyzer():
    """
    Initialize the BirdNET analyzer once.

    Analyzer startup is expensive. Keeping one module-level analyzer avoids
    reloading the model for every recording.
    """

    global _ANALYZER

    if _ANALYZER is not None:

        return _ANALYZER

    _log(
        "Initializing BirdNET model..."
    )

    _ANALYZER = Analyzer()

    _log(
        "BirdNET model is ready."
    )

    return _ANALYZER


# ============================================================
# NORMALIZATION HELPERS
# ============================================================

def _make_species_code(
    common_name: str
) -> str:
    """
    Convert a common name into a compact species code.
    """

    name = (
        str(common_name)
        .lower()
        .replace("-", " ")
        .replace("_", " ")
    )

    parts = name.split()

    if len(parts) == 1:

        return parts[0][:6]

    if len(parts) >= 2:

        return (
            parts[0][:2]
            + parts[1][:4]
        )

    return (
        str(common_name)
        .lower()
        .replace(" ", "")[:6]
    )


def _safe_float(
    value: Any,
    default: float = 0.0
) -> float:
    """
    Convert a value to float without letting malformed data crash analysis.
    """

    try:

        if value is None:

            return default

        return float(
            value
        )

    except Exception:

        return default


def _normalize_detection(
    detection: dict
) -> dict | None:
    """
    Normalize one birdnetlib detection dictionary.
    """

    common_name = (
        detection.get("common_name")
        or detection.get("common")
        or detection.get("label")
    )

    if not common_name:

        _log(
            f"Skipping detection with missing common_name: {detection}"
        )

        return None

    normalized = {
        "common_name": str(common_name),
        "scientific_name": str(
            detection.get(
                "scientific_name",
                "unknown"
            )
        ),
        "species_code": _make_species_code(
            common_name
        ),
        "confidence": _safe_float(
            detection.get(
                "confidence",
                0.0
            )
        ),
        "start_time": _safe_float(
            detection.get(
                "start_time",
                0.0
            )
        ),
        "end_time": _safe_float(
            detection.get(
                "end_time",
                0.0
            )
        )
    }

    return normalized


def _normalize_week(
    week: int | None
) -> int:
    """
    Birdnetlib expects week_48.

    If no week is supplied, use the module default.
    """

    if week is None:

        return DEFAULT_WEEK

    try:

        return int(
            week
        )

    except Exception:

        return DEFAULT_WEEK


def _normalize_latitude(
    lat: float | None
) -> float:
    """
    Return a safe latitude value.
    """

    if lat is None:

        return DEFAULT_LATITUDE

    return _safe_float(
        lat,
        DEFAULT_LATITUDE
    )


def _normalize_longitude(
    lon: float | None
) -> float:
    """
    Return a safe longitude value.
    """

    if lon is None:

        return DEFAULT_LONGITUDE

    return _safe_float(
        lon,
        DEFAULT_LONGITUDE
    )


def _normalize_min_confidence(
    min_conf: float | None
) -> float:
    """
    Return a safe minimum confidence value.
    """

    if min_conf is None:

        return DEFAULT_MIN_CONFIDENCE

    return _safe_float(
        min_conf,
        DEFAULT_MIN_CONFIDENCE
    )


# ============================================================
# PUBLIC API
# ============================================================

def analyze_wav(
    audio_path: pathlib.Path | str,
    *,
    lat: float | None = None,
    lon: float | None = None,
    week: int | None = None,
    min_conf: float | None = None
) -> List[Dict]:
    """
    Analyze one WAV file and return normalized BirdNET detections.

    Output format:
        {
            "common_name": str,
            "scientific_name": str,
            "species_code": str,
            "confidence": float,
            "start_time": float,
            "end_time": float
        }
    """

    path = pathlib.Path(
        audio_path
    )

    _log(
        f"Analyzing file: {path}"
    )

    if not path.exists():

        _log(
            f"File does not exist: {path}"
        )

        return []

    analyzer = _get_analyzer()

    latitude = _normalize_latitude(
        lat
    )

    longitude = _normalize_longitude(
        lon
    )

    week_48 = _normalize_week(
        week
    )

    min_confidence = _normalize_min_confidence(
        min_conf
    )

    start_time = time.perf_counter()

    try:

        recording = Recording(
            analyzer,
            str(path),
            lat=latitude,
            lon=longitude,
            week_48=week_48,
            min_conf=min_confidence
        )

        recording.analyze()

    except Exception as error:

        _log(
            f"Analysis failed: {error}"
        )

        return []

    elapsed = (
        time.perf_counter()
        - start_time
    )

    raw_detections = list(
        getattr(
            recording,
            "detections",
            []
        )
    )

    _log(
        f"Raw detection count: {len(raw_detections)}"
    )

    _log(
        f"Analysis time: {elapsed:.2f} s"
    )

    normalized_detections = []

    for detection in raw_detections:

        if not isinstance(
            detection,
            dict
        ):

            _log(
                f"Skipping malformed detection: {detection}"
            )

            continue

        normalized = _normalize_detection(
            detection
        )

        if normalized is None:

            continue

        normalized_detections.append(
            normalized
        )

    normalized_detections.sort(
        key=lambda detection: detection["confidence"],
        reverse=True
    )

    _log(
        f"Normalized detections: {len(normalized_detections)}"
    )

    for detection in normalized_detections[:10]:

        _log(
            (
                f"{detection['common_name']} "
                f"({detection['species_code']}) "
                f"conf={detection['confidence']:.3f} "
                f"{detection['start_time']:.1f}s-"
                f"{detection['end_time']:.1f}s"
            )
        )

    return normalized_detections