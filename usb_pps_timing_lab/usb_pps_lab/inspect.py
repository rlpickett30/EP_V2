from __future__ import annotations

from pathlib import Path
from typing import Any

import sounddevice as sd

from .pps import parse_pps_assert


def inspect_system(pps_path: Path, serial_device: Path | None = None) -> dict[str, Any]:
    hostapis = sd.query_hostapis()
    devices = []
    for index, item in enumerate(sd.query_devices()):
        supports_48k_mono_int16 = False
        check_error = None
        if int(item["max_input_channels"]) >= 1:
            try:
                sd.check_input_settings(device=index, channels=1, dtype="int16", samplerate=48000)
                supports_48k_mono_int16 = True
            except Exception as error:
                check_error = str(error)
        hostapi_index = int(item["hostapi"])
        devices.append(
            {
                "index": index,
                "name": item["name"],
                "hostapi_index": hostapi_index,
                "hostapi_name": hostapis[hostapi_index]["name"],
                "max_input_channels": int(item["max_input_channels"]),
                "default_sample_rate": float(item["default_samplerate"]),
                "default_low_input_latency": float(item["default_low_input_latency"]),
                "supports_48000_mono_int16": supports_48k_mono_int16,
                "48000_check_error": check_error,
            }
        )

    pps = {"path": str(pps_path), "exists": pps_path.exists()}
    if pps_path.exists():
        text = pps_path.read_text(encoding="utf-8").strip()
        epoch_ns, sequence = parse_pps_assert(text)
        pps.update({"assert_text": text, "epoch_ns": epoch_ns, "sequence": sequence})

    serial_info = None
    if serial_device is not None:
        serial_info = {"path": str(serial_device), "exists": serial_device.exists()}

    return {"audio_devices": devices, "pps": pps, "serial": serial_info}
