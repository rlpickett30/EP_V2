from __future__ import annotations

import json
import math
import os
import platform
import socket
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def epoch_ns_to_iso(epoch_ns: int) -> str:
    return datetime.fromtimestamp(epoch_ns / 1e9, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> int:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("UTC timestamp must include Z or an explicit UTC offset.")
    return int(round(dt.timestamp() * 1e9))


def atomic_json_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(to_jsonable(data), handle, indent=4, sort_keys=False)
        handle.write("\n")
    temp.replace(path)


def append_ndjson(path: Path, record: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(to_jsonable(record), handle, separators=(",", ":"))
        handle.write("\n")


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid NDJSON in {path} at line {line_number}: {error}") from error
    return records


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def system_identity() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version,
        "pid": os.getpid(),
    }


def robust_linear_fit(
    x: np.ndarray,
    y: np.ndarray,
    sigma_clip: float = 4.0,
    max_iterations: int = 8,
) -> dict[str, Any]:
    """Fit y = intercept + slope * (x - x_origin) with iterative MAD clipping."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    finite = np.isfinite(x) & np.isfinite(y)
    if finite.sum() < 2:
        raise ValueError("At least two finite points are required for a linear fit.")

    x_origin = float(np.median(x[finite]))
    xc = x - x_origin
    mask = finite.copy()

    for _ in range(max_iterations):
        design = np.column_stack([np.ones(mask.sum()), xc[mask]])
        coefficients, *_ = np.linalg.lstsq(design, y[mask], rcond=None)
        predicted = coefficients[0] + coefficients[1] * xc
        residuals = y - predicted
        residual_median = float(np.median(residuals[mask]))
        mad = float(np.median(np.abs(residuals[mask] - residual_median)))
        scale = 1.4826 * mad
        if not math.isfinite(scale) or scale <= 0.0:
            break
        new_mask = finite & (np.abs(residuals - residual_median) <= sigma_clip * scale)
        if new_mask.sum() < 2 or np.array_equal(new_mask, mask):
            mask = new_mask if new_mask.sum() >= 2 else mask
            break
        mask = new_mask

    design = np.column_stack([np.ones(mask.sum()), xc[mask]])
    coefficients, *_ = np.linalg.lstsq(design, y[mask], rcond=None)
    predicted = coefficients[0] + coefficients[1] * xc
    residuals = y - predicted
    accepted = residuals[mask]
    abs_accepted = np.abs(accepted)

    return {
        "x_origin": x_origin,
        "intercept_at_origin": float(coefficients[0]),
        "slope": float(coefficients[1]),
        "mask": mask,
        "predicted": predicted,
        "residuals": residuals,
        "accepted_count": int(mask.sum()),
        "rejected_count": int(finite.sum() - mask.sum()),
        "residual_median": float(np.median(accepted)),
        "residual_mad": float(np.median(np.abs(accepted - np.median(accepted)))),
        "residual_p95_abs": float(np.percentile(abs_accepted, 95)),
        "residual_max_abs": float(np.max(abs_accepted)),
    }


def linear_predict(model: dict[str, Any], x: np.ndarray | float) -> np.ndarray:
    values = np.asarray(x, dtype=np.float64)
    return model["intercept_at_origin"] + model["slope"] * (values - model["x_origin"])


def ensure_monotonic(values: Iterable[float], name: str) -> None:
    array = np.asarray(list(values), dtype=np.float64)
    if array.size > 1 and np.any(np.diff(array) <= 0):
        raise ValueError(f"{name} must be strictly increasing.")
