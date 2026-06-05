"""
birdnet_analyzer.py

EnviroPulse V2 BirdNET wrapper.

Responsibilities:
- Call BirdNET-Analyzer
- Analyze WAV files
- Return normalized detections

No EventBus.
No dispatcher logic.
No GPS hardware.
No event construction.
"""

from __future__ import annotations

import pathlib
import sys
from pathlib import Path
from typing import Dict
from typing import List

# ----------------------------------------------------------------------
# Locate BirdNET-Analyzer repository
# ----------------------------------------------------------------------

BIRDNET_ROOT = Path.home() / "BirdNET-Analyzer"

if str(BIRDNET_ROOT) not in sys.path:
    sys.path.insert(0, str(BIRDNET_ROOT))

# ----------------------------------------------------------------------
# BirdNET Imports
# ----------------------------------------------------------------------

from birdnet_analyzer.analyze.core import analyze

# ----------------------------------------------------------------------
# Helper
# ----------------------------------------------------------------------

def _make_species_code(common_name: str) -> str:

    name = common_name.lower().replace("-", " ").replace("_", " ")
    parts = name.split()

    if len(parts) == 1:
        return parts[0][:6]

    if len(parts) >= 2:
        return parts[0][:2] + parts[1][:4]

    return common_name.lower().replace(" ", "")[:6]

# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def analyze_wav(
    audio_path: pathlib.Path | str,
    *,
    lat: float | None = None,
    lon: float | None = None,
    week: int | None = None,
    min_conf: float = 0.01,
) -> List[Dict]:

    path = pathlib.Path(audio_path)

    if not path.exists():
        print(f"[BirdNET] File not found: {path}")
        return []

    print(f"[BirdNET] Analyzing: {path}")

    try:

        results = analyze(
            audio_input=str(path),
            lat=lat,
            lon=lon,
            week=week,
            min_conf=min_conf,
            rtype="table",
            _return_only=True,
        )

    except Exception as exc:

        print(f"[BirdNET] Analysis failed: {exc}")
        return []

    if not results:
        return []

    normalized: List[Dict] = []

    for row in results:

        common_name = (
            row.get("common_name")
            or row.get("scientific_name")
            or "unknown"
        )

        normalized.append(
            {
                "common_name": common_name,
                "species_code": _make_species_code(common_name),
                "confidence": float(row.get("confidence", 0.0)),
                "start_time": float(row.get("start_time", 0.0)),
                "end_time": float(row.get("end_time", 0.0)),
            }
        )

    normalized.sort(
        key=lambda d: d["confidence"],
        reverse=True,
    )

    return normalized