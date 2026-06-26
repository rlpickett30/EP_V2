#!/usr/bin/env python3
"""
install_node.py

EnviroPulse V2.0

Subsystem:
    Installer

Role:
    Node Install Wizard

Purpose:
    Create and update EnviroPulse node deployment configuration.

Writes:
    - node/node_config.json
    - node/communication/communication_config.json
    - node/microphone/microphone_config.json
    - node/RTK/RTK_config.json

Does:
    - Collect node identity and deployment facts.
    - Create the central node configuration file.
    - Update installer-owned values in subsystem JSON configs.
    - Preserve existing subsystem tuning values when possible.
    - Create timestamped backups before overwriting existing files.
    - Support dry-run mode.

Does NOT:
    - Modify production Python source files.
    - Start node runtime.
    - Install apt packages.
    - Install Python packages.
    - Configure systemd services.
    - Rewrite boot overlays.
    - Own subsystem runtime workflow.

Architecture Notes:
    - install_node.py is deployment tooling only.
    - node_config.json becomes the central install-time identity source.
    - Subsystem JSON files keep subsystem tuning values.
    - Runtime Main will later load node_config.json and pass identity into subsystem owners.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys

from copy import deepcopy
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional


# ------------------------------------------------------------
# Defaults
# ------------------------------------------------------------

DEFAULT_NODE_ID = "node_04"
DEFAULT_NODE_ROLE = "rover"

DEFAULT_LISTEN_PORT = 5006
DEFAULT_SEND_PORT = 5005

DEFAULT_MICROPHONE_TYPE = "SPH0645"
DEFAULT_MIC_SAMPLE_RATE = 48000
DEFAULT_MIC_CHANNELS = 1

DEFAULT_PPS_GPIO_BCM = 4
DEFAULT_PPS_PHYSICAL_PIN = 7

DEFAULT_REGISTER_HEARTBEAT_SEC = 300

PPS_GPIO_TO_PHYSICAL_PIN = {
    4: 7,
    17: 11,
    18: 12,
    22: 15,
    23: 16,
    24: 18,
    25: 22,
    27: 13,
}


DEFAULT_SUBSYSTEMS = {
    "journal": True,
    "rtk": True,
    "environmental": True,
    "microphone": True,
    "birdnet": True,
    "communication": True,
    "node_register": True,
}


DEFAULT_COMMUNICATION_CONFIG = {
    "wifi_enabled": True,
    "lora_enabled": False,
    "udp": {
        "enabled": True,
        "listen_host": "0.0.0.0",
        "listen_port": DEFAULT_LISTEN_PORT,
        "send_host": "",
        "send_port": DEFAULT_SEND_PORT,
        "max_packet_size": 4096,
    },
    "queue": {
        "enabled": True,
        "queue_file": "communication/data/send_queue.json",
    },
    "network": {
        "heartbeat_timeout_seconds": 30,
        "network_check_interval_seconds": 5,
    },
}


DEFAULT_MICROPHONE_CONFIG = {
    "node_id": "auto",
    "node_name": "auto",
    "microphone_type": DEFAULT_MICROPHONE_TYPE,
    "recordings_root": "recordings",
    "sample_rate": DEFAULT_MIC_SAMPLE_RATE,
    "channels": DEFAULT_MIC_CHANNELS,
    "recording_duration_sec": 15,
    "recording_interval_sec": 300,
    "tdoa_recording_duration_sec": 10,
    "tdoa_pps_lead_seconds": 1.0,
    "align_tdoa_to_pps_boundary": True,
    "align_recordings_to_pps_boundary": True,
    "microphone_pps_lead_seconds": 1.0,
    "microphone_sync_window_ms": 250.0,
    "storage_retention_days": 7,
    "bird_recording_retention_days": 30,
    "recycler_interval_sec": 3600,
    "require_pps_lock": False,
    "require_pps_lock_for_tdoa": False,
    "check_microphone_available_before_recording": False,
    "debug": True,
}


DEFAULT_RTK_CONFIG = {
    "node_id": "auto",
    "node_name": "auto",
    "loop_delay_sec": 1.0,
    "state_publish_interval_sec": 30,
    "gps": {
        "port": "/dev/ttyACM0",
        "baudrate": 38400,
        "min_satellites": 6,
        "max_hdop": 2.0,
        "coord_publish_interval_sec": 300,
    },
    "pps": {
        "gpio_bcm": DEFAULT_PPS_GPIO_BCM,
        "physical_pin": DEFAULT_PPS_PHYSICAL_PIN,
        "pin_numbering": "BCM",
        "active_edge": "rising",
        "pull": "down",
        "pps_timeout_sec": 2,
    },
    "rtk": {
        "mode": "auto",
        "base_node_ids": [],
        "udp_port": 5010,
        "report_interval_sec": 5,
        "base": {
            "enabled": True,
            "configure_on_start": True,
            "broadcast_enabled": False,
            "broadcast_address": "255.255.255.255",
            "udp_targets": [],
            "survey_in": {
                "enabled": True,
                "duration_sec": 120,
                "accuracy_limit_mm": 5000,
            },
            "rtcm_messages": [
                "1005",
                "1077",
                "1087",
                "1097",
                "1127",
                "1230",
            ],
        },
        "rover": {
            "enabled": True,
            "bind_host": "0.0.0.0",
        },
    },
    "base_survey": {
        "enabled": False,
        "survey_duration_sec": 86400,
        "save_results": True,
    },
    "debug": True,
}


# ------------------------------------------------------------
# Path Helpers
# ------------------------------------------------------------

def resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_config_paths(repo_root: Path) -> Dict[str, Path]:
    return {
        "node_config": repo_root / "node" / "node_config.json",
        "communication_config": repo_root / "node" / "communication" / "communication_config.json",
        "microphone_config": repo_root / "node" / "microphone" / "microphone_config.json",
        "rtk_config": repo_root / "node" / "RTK" / "RTK_config.json",
        "environmental_config": repo_root / "node" / "environmental" / "environmental_config.json",
    }


# ------------------------------------------------------------
# Display Helpers
# ------------------------------------------------------------

def print_header(message: str) -> None:
    print()
    print("=" * 60)
    print(message)
    print("=" * 60)
    print()


def print_step(message: str) -> None:
    print()
    print(f"[INSTALL_NODE] {message}")


def print_warn(message: str) -> None:
    print()
    print(f"[WARN] {message}")


def print_error(message: str) -> None:
    print()
    print(f"[ERROR] {message}", file=sys.stderr)


# ------------------------------------------------------------
# JSON Helpers
# ------------------------------------------------------------

def load_json_or_default(
    path: Path,
    default_value: Dict[str, Any],
) -> Dict[str, Any]:

    if not path.exists():
        return deepcopy(default_value)

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

        print_warn(f"Config was not a JSON object. Using defaults: {path}")
        return deepcopy(default_value)

    except Exception as error:
        print_warn(f"Could not read config. Using defaults: {path}")
        print_warn(str(error))
        return deepcopy(default_value)


def write_json(
    path: Path,
    data: Dict[str, Any],
    dry_run: bool,
    make_backup: bool = True,
) -> None:

    if dry_run:
        print()
        print(f"--- DRY RUN: {path} ---")
        print(json.dumps(data, indent=4))
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and make_backup:
        backup_path = get_backup_path(path)
        shutil.copy2(path, backup_path)
        print(f"Backup written: {backup_path}")

    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(data, file, indent=4)
        file.write("\n")

    print(f"Wrote: {path}")


def get_backup_path(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return path.with_name(f"{path.name}.bak_{timestamp}")


# ------------------------------------------------------------
# Prompt Helpers
# ------------------------------------------------------------

def prompt_text(
    label: str,
    default: Optional[str] = None,
    required: bool = False,
) -> str:

    while True:
        if default is None or default == "":
            prompt = f"{label}: "
        else:
            prompt = f"{label} [{default}]: "

        value = input(prompt).strip()

        if not value and default is not None:
            value = default

        if value or not required:
            return value

        print("Value is required.")


def prompt_int(
    label: str,
    default: int,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:

    while True:
        raw_value = prompt_text(
            label=label,
            default=str(default),
            required=True,
        )

        try:
            value = int(raw_value)
        except ValueError:
            print("Enter a whole number.")
            continue

        if minimum is not None and value < minimum:
            print(f"Value must be at least {minimum}.")
            continue

        if maximum is not None and value > maximum:
            print(f"Value must be no greater than {maximum}.")
            continue

        return value


def prompt_bool(
    label: str,
    default: bool,
) -> bool:

    default_label = "Y" if default else "N"

    while True:
        raw_value = input(f"{label} [y/N, default {default_label}]: ").strip().lower()

        if not raw_value:
            return default

        if raw_value in {"y", "yes", "true", "1"}:
            return True

        if raw_value in {"n", "no", "false", "0"}:
            return False

        print("Enter y or n.")


def prompt_choice(
    label: str,
    choices: List[str],
    default: str,
) -> str:

    normalized_choices = [choice.lower() for choice in choices]

    while True:
        raw_value = prompt_text(
            label=f"{label} ({'/'.join(choices)})",
            default=default,
            required=True,
        )

        value = raw_value.strip().lower()

        if value in normalized_choices:
            return value

        print(f"Choose one of: {', '.join(choices)}")


def prompt_csv_list(
    label: str,
    default_values: Optional[List[str]] = None,
) -> List[str]:

    default_values = default_values or []
    default_text = ", ".join(default_values)

    raw_value = prompt_text(
        label=label,
        default=default_text,
        required=False,
    )

    return [
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    ]


# ------------------------------------------------------------
# Normalizers
# ------------------------------------------------------------

def normalize_node_id(value: str) -> str:
    cleaned = value.strip()

    if not cleaned:
        return DEFAULT_NODE_ID

    digit_match = re.fullmatch(r"\d+", cleaned)

    if digit_match:
        return f"node_{int(cleaned):02d}"

    node_match = re.fullmatch(
        r"(?:ep[-_])?node[-_]?(\d+)",
        cleaned,
        flags=re.IGNORECASE,
    )

    if node_match:
        return f"node_{int(node_match.group(1)):02d}"

    cleaned = cleaned.lower()
    cleaned = cleaned.replace("-", "_")
    cleaned = re.sub(r"[^a-z0-9_]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("_")

    if not cleaned:
        return DEFAULT_NODE_ID

    return cleaned


def infer_node_name(node_id: str) -> str:
    match = re.fullmatch(r"node_(\d+)", node_id)

    if match:
        return f"EnviroPulse Node {int(match.group(1)):02d}"

    return node_id.replace("_", " ").title()


def infer_pps_physical_pin(gpio_bcm: int) -> int:
    return PPS_GPIO_TO_PHYSICAL_PIN.get(
        gpio_bcm,
        DEFAULT_PPS_PHYSICAL_PIN,
    )


def safe_existing_server_host(communication_config: Dict[str, Any]) -> str:
    udp_config = communication_config.get("udp", {})

    value = str(
        udp_config.get(
            "send_host",
            "",
        )
    ).strip()

    if value in {"", "127.0.0.1", "localhost"}:
        return ""

    return value


# ------------------------------------------------------------
# Existing Config Inspection
# ------------------------------------------------------------

def collect_existing_defaults(
    paths: Dict[str, Path],
) -> Dict[str, Any]:

    communication_config = load_json_or_default(
        paths["communication_config"],
        DEFAULT_COMMUNICATION_CONFIG,
    )

    microphone_config = load_json_or_default(
        paths["microphone_config"],
        DEFAULT_MICROPHONE_CONFIG,
    )

    rtk_config = load_json_or_default(
        paths["rtk_config"],
        DEFAULT_RTK_CONFIG,
    )

    udp_config = communication_config.get("udp", {})
    pps_config = rtk_config.get("pps", {})
    rtk_section = rtk_config.get("rtk", {})

    existing_node_id = str(
        microphone_config.get(
            "node_id",
            DEFAULT_NODE_ID,
        )
    ).strip()

    if existing_node_id in {"", "auto", "hostname"}:
        existing_node_id = DEFAULT_NODE_ID

    existing_node_id = normalize_node_id(existing_node_id)

    existing_node_name = str(
        microphone_config.get(
            "node_name",
            infer_node_name(existing_node_id),
        )
    ).strip()

    if existing_node_name in {"", "auto", "hostname"}:
        existing_node_name = infer_node_name(existing_node_id)

    role = str(
        rtk_section.get(
            "mode",
            DEFAULT_NODE_ROLE,
        )
    ).strip().lower()

    if role not in {"base", "rover", "standalone"}:
        if role in {"disabled", "off", "none"}:
            role = "standalone"
        else:
            role = DEFAULT_NODE_ROLE

    return {
        "node_id": existing_node_id,
        "node_name": existing_node_name,
        "node_role": role,
        "server_host": safe_existing_server_host(communication_config),
        "listen_port": int(
            udp_config.get(
                "listen_port",
                DEFAULT_LISTEN_PORT,
            )
        ),
        "send_port": int(
            udp_config.get(
                "send_port",
                DEFAULT_SEND_PORT,
            )
        ),
        "pps_gpio_bcm": int(
            pps_config.get(
                "gpio_bcm",
                DEFAULT_PPS_GPIO_BCM,
            )
        ),
        "pps_physical_pin": int(
            pps_config.get(
                "physical_pin",
                infer_pps_physical_pin(
                    int(
                        pps_config.get(
                            "gpio_bcm",
                            DEFAULT_PPS_GPIO_BCM,
                        )
                    )
                ),
            )
        ),
        "microphone_type": str(
            microphone_config.get(
                "microphone_type",
                DEFAULT_MICROPHONE_TYPE,
            )
        ).strip()
        or DEFAULT_MICROPHONE_TYPE,
        "sample_rate": int(
            microphone_config.get(
                "sample_rate",
                DEFAULT_MIC_SAMPLE_RATE,
            )
        ),
        "channels": int(
            microphone_config.get(
                "channels",
                DEFAULT_MIC_CHANNELS,
            )
        ),
        "base_node_ids": list(
            rtk_section.get(
                "base_node_ids",
                [],
            )
        ),
        "rtk_udp_targets": list(
            rtk_section.get(
                "base",
                {},
            ).get(
                "udp_targets",
                [],
            )
        ),
        "debug": bool(
            microphone_config.get(
                "debug",
                True,
            )
        ),
    }


# ------------------------------------------------------------
# Wizard
# ------------------------------------------------------------

def run_wizard(
    defaults: Dict[str, Any],
) -> Dict[str, Any]:

    print_header("EnviroPulse Node Install Wizard")

    print("This wizard writes node deployment configuration.")
    print("It does not modify runtime Python source files.")
    print()

    raw_node_id = prompt_text(
        label="Node ID",
        default=defaults["node_id"],
        required=True,
    )

    node_id = normalize_node_id(raw_node_id)

    node_name = prompt_text(
        label="Node display name",
        default=defaults.get("node_name") or infer_node_name(node_id),
        required=True,
    )

    node_role = prompt_choice(
        label="Node role",
        choices=["base", "rover", "standalone"],
        default=defaults.get("node_role", DEFAULT_NODE_ROLE),
    )

    server_host = prompt_text(
        label="Server IP or hostname",
        default=defaults.get("server_host", ""),
        required=True,
    )

    listen_port = prompt_int(
        label="Node UDP listen port",
        default=defaults.get("listen_port", DEFAULT_LISTEN_PORT),
        minimum=1,
        maximum=65535,
    )

    send_port = prompt_int(
        label="Server UDP receive port",
        default=defaults.get("send_port", DEFAULT_SEND_PORT),
        minimum=1,
        maximum=65535,
    )

    microphone_type = prompt_choice(
        label="Microphone type",
        choices=["SPH0645", "none"],
        default=defaults.get("microphone_type", DEFAULT_MICROPHONE_TYPE),
    )

    sample_rate_default = defaults.get("sample_rate", DEFAULT_MIC_SAMPLE_RATE)

    if microphone_type == "sph0645":
        sample_rate_default = DEFAULT_MIC_SAMPLE_RATE

    sample_rate = prompt_int(
        label="Microphone sample rate",
        default=sample_rate_default,
        minimum=8000,
        maximum=192000,
    )

    channels = prompt_int(
        label="Microphone channels",
        default=defaults.get("channels", DEFAULT_MIC_CHANNELS),
        minimum=1,
        maximum=8,
    )

    pps_gpio_default = defaults.get("pps_gpio_bcm", DEFAULT_PPS_GPIO_BCM)

    if microphone_type == "sph0645" and pps_gpio_default == 18:
        print()
        print("SPH0645 uses GPIO18 for I2S BCLK.")
        print("Defaulting PPS GPIO to GPIO4 to avoid the I2S/PPS conflict.")
        pps_gpio_default = DEFAULT_PPS_GPIO_BCM

    pps_gpio_bcm = prompt_int(
        label="PPS GPIO BCM pin",
        default=pps_gpio_default,
        minimum=0,
        maximum=27,
    )

    pps_physical_pin = prompt_int(
        label="PPS physical pin",
        default=infer_pps_physical_pin(pps_gpio_bcm),
        minimum=1,
        maximum=40,
    )

    base_node_ids = defaults.get("base_node_ids", [])

    if node_role == "base" and node_id not in base_node_ids:
        base_node_ids = [*base_node_ids, node_id]

    if node_role == "base":
        base_node_ids = prompt_csv_list(
            label="RTK base node IDs",
            default_values=base_node_ids,
        )

        rtk_udp_targets = prompt_csv_list(
            label="RTK base UDP target IPs",
            default_values=defaults.get("rtk_udp_targets", []),
        )

    elif node_role == "rover":
        base_node_ids = prompt_csv_list(
            label="Known RTK base node IDs",
            default_values=base_node_ids,
        )
        rtk_udp_targets = defaults.get("rtk_udp_targets", [])

    else:
        base_node_ids = []
        rtk_udp_targets = []

    debug = prompt_bool(
        label="Enable debug logging",
        default=defaults.get("debug", True),
    )

    return {
        "node_id": node_id,
        "node_name": node_name,
        "node_role": node_role,
        "server_host": server_host,
        "listen_port": listen_port,
        "send_port": send_port,
        "microphone_type": microphone_type.upper(),
        "sample_rate": sample_rate,
        "channels": channels,
        "pps_gpio_bcm": pps_gpio_bcm,
        "pps_physical_pin": pps_physical_pin,
        "base_node_ids": base_node_ids,
        "rtk_udp_targets": rtk_udp_targets,
        "debug": debug,
    }


# ------------------------------------------------------------
# Config Builders
# ------------------------------------------------------------

def build_node_config(
    answers: Dict[str, Any],
) -> Dict[str, Any]:

    return {
        "node_id": answers["node_id"],
        "node_name": answers["node_name"],
        "node_role": answers["node_role"],
        "server": {
            "host": answers["server_host"],
            "listen_port": answers["listen_port"],
            "send_port": answers["send_port"],
        },
        "hardware": {
            "pps_gpio_bcm": answers["pps_gpio_bcm"],
            "pps_physical_pin": answers["pps_physical_pin"],
            "pps_pin_numbering": "BCM",
            "pps_active_edge": "rising",
            "microphone_type": answers["microphone_type"],
        },
        "subsystems": deepcopy(DEFAULT_SUBSYSTEMS),
        "register": {
            "heartbeat_sec": DEFAULT_REGISTER_HEARTBEAT_SEC,
        },
        "debug": answers["debug"],
        "generated_by": "tools/install/install_node.py",
        "generated_at_utc": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }


def build_communication_config(
    existing_config: Dict[str, Any],
    answers: Dict[str, Any],
) -> Dict[str, Any]:

    config = deepcopy(existing_config)

    config["wifi_enabled"] = True
    config.setdefault("lora_enabled", False)

    config.setdefault("udp", {})
    config["udp"]["enabled"] = True
    config["udp"]["listen_host"] = "0.0.0.0"
    config["udp"]["listen_port"] = answers["listen_port"]
    config["udp"]["send_host"] = answers["server_host"]
    config["udp"]["send_port"] = answers["send_port"]
    config["udp"].setdefault("max_packet_size", 4096)

    config.setdefault("queue", {})
    config["queue"].setdefault("enabled", True)
    config["queue"].setdefault(
        "queue_file",
        "communication/data/send_queue.json",
    )

    config.setdefault("network", {})
    config["network"].setdefault("heartbeat_timeout_seconds", 30)
    config["network"].setdefault("network_check_interval_seconds", 5)

    return config


def build_microphone_config(
    existing_config: Dict[str, Any],
    answers: Dict[str, Any],
) -> Dict[str, Any]:

    config = deepcopy(existing_config)

    config["node_id"] = answers["node_id"]
    config["node_name"] = answers["node_name"]
    config["microphone_type"] = answers["microphone_type"]
    config["sample_rate"] = answers["sample_rate"]
    config["channels"] = answers["channels"]
    config["debug"] = answers["debug"]

    config.setdefault("recordings_root", "recordings")
    config.setdefault("recording_duration_sec", 15)
    config.setdefault("recording_interval_sec", 30)
    config.setdefault("tdoa_recording_duration_sec", 10)
    config.setdefault("tdoa_pps_lead_seconds", 1.0)
    config.setdefault("align_tdoa_to_pps_boundary", True)
    config.setdefault("storage_retention_days", 7)
    config.setdefault("bird_recording_retention_days", 30)
    config.setdefault("recycler_interval_sec", 3600)
    config.setdefault("require_pps_lock", False)
    config.setdefault("require_pps_lock_for_tdoa", False)
    config.setdefault("check_microphone_available_before_recording", False)

    return config


def build_rtk_config(
    existing_config: Dict[str, Any],
    answers: Dict[str, Any],
) -> Dict[str, Any]:

    config = deepcopy(existing_config)

    config["node_id"] = "auto"
    config["node_name"] = "auto"
    config["debug"] = answers["debug"]

    config.setdefault("pps", {})
    config["pps"]["gpio_bcm"] = answers["pps_gpio_bcm"]
    config["pps"]["physical_pin"] = answers["pps_physical_pin"]
    config["pps"]["pin_numbering"] = "BCM"
    config["pps"].setdefault("active_edge", "rising")
    config["pps"].setdefault("pull", "down")
    config["pps"].setdefault("pps_timeout_sec", 2)

    config.setdefault("gps", {})
    config["gps"].setdefault("port", "/dev/ttyACM0")
    config["gps"].setdefault("baudrate", 38400)
    config["gps"].setdefault("min_satellites", 6)
    config["gps"].setdefault("max_hdop", 2.0)
    config["gps"].setdefault("coord_publish_interval_sec", 300)

    config.setdefault("rtk", {})

    if answers["node_role"] == "standalone":
        rtk_mode = "disabled"
    else:
        rtk_mode = answers["node_role"]

    config["rtk"]["mode"] = rtk_mode
    config["rtk"]["base_node_ids"] = answers["base_node_ids"]
    config["rtk"].setdefault("udp_port", 5010)
    config["rtk"].setdefault("report_interval_sec", 5)

    config["rtk"].setdefault("base", {})
    config["rtk"]["base"]["enabled"] = answers["node_role"] == "base"
    config["rtk"]["base"].setdefault("configure_on_start", True)
    config["rtk"]["base"].setdefault("broadcast_enabled", False)
    config["rtk"]["base"].setdefault("broadcast_address", "255.255.255.255")
    config["rtk"]["base"]["udp_targets"] = answers["rtk_udp_targets"]

    config["rtk"]["base"].setdefault("survey_in", {})
    config["rtk"]["base"]["survey_in"].setdefault("enabled", True)
    config["rtk"]["base"]["survey_in"].setdefault("duration_sec", 120)
    config["rtk"]["base"]["survey_in"].setdefault("accuracy_limit_mm", 5000)

    config["rtk"]["base"].setdefault(
        "rtcm_messages",
        [
            "1005",
            "1077",
            "1087",
            "1097",
            "1127",
            "1230",
        ],
    )

    config["rtk"].setdefault("rover", {})
    config["rtk"]["rover"]["enabled"] = answers["node_role"] == "rover"
    config["rtk"]["rover"].setdefault("bind_host", "0.0.0.0")

    config.setdefault("base_survey", {})
    config["base_survey"].setdefault("enabled", False)
    config["base_survey"].setdefault("survey_duration_sec", 86400)
    config["base_survey"].setdefault("save_results", True)

    return config

def build_environmental_config(
    answers: Dict[str, Any],
) -> Dict[str, Any]:

    environmental_enabled = answers.get(
        "environmental_enabled",
        True,
    )

    sht45_enabled = answers.get(
        "sht45_enabled",
        environmental_enabled,
    )

    dps310_enabled = answers.get(
        "dps310_enabled",
        environmental_enabled,
    )

    bmp390_enabled = answers.get(
        "bmp390_enabled",
        False,
    )

    required_sensors = []

    if sht45_enabled:
        required_sensors.append("sht45")

    if dps310_enabled:
        required_sensors.append("dps310")

    if bmp390_enabled:
        required_sensors.append("bmp390")

    return {
        "enabled": environmental_enabled,
        "sample_hz": 1.0,
        "enviro_interval_sec": 300,
        "state_heartbeat_sec": 300,
        "loop_delay_sec": 1.0,
        "sea_level_pressure_hpa": 1013.25,
        "required_sensors": required_sensors,
        "sensors": {
            "sht45": {
                "enabled": sht45_enabled,
            },
            "dps310": {
                "enabled": dps310_enabled,
            },
            "bmp390": {
                "enabled": bmp390_enabled,
            },
        },
        "debug": answers["debug"],
    }


def build_all_configs(
    paths: Dict[str, Path],
    answers: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:

    existing_communication_config = load_json_or_default(
        paths["communication_config"],
        DEFAULT_COMMUNICATION_CONFIG,
    )

    existing_microphone_config = load_json_or_default(
        paths["microphone_config"],
        DEFAULT_MICROPHONE_CONFIG,
    )

    existing_rtk_config = load_json_or_default(
        paths["rtk_config"],
        DEFAULT_RTK_CONFIG,
    )

    return {
        "node_config": build_node_config(
            answers=answers,
        ),
        "communication_config": build_communication_config(
            existing_config=existing_communication_config,
            answers=answers,
        ),
        "microphone_config": build_microphone_config(
            existing_config=existing_microphone_config,
            answers=answers,
        ),
        "rtk_config": build_rtk_config(
            existing_config=existing_rtk_config,
            answers=answers,
        ),
        "environmental_config": build_environmental_config(
            answers=answers,
        ),
    }


# ------------------------------------------------------------
# Summary
# ------------------------------------------------------------

def print_summary(
    answers: Dict[str, Any],
    paths: Dict[str, Path],
) -> None:

    print_header("Node Install Summary")

    print(f"Node ID:              {answers['node_id']}")
    print(f"Node name:            {answers['node_name']}")
    print(f"Node role:            {answers['node_role']}")
    print(f"Server host:          {answers['server_host']}")
    print(f"Node listen port:     {answers['listen_port']}")
    print(f"Server receive port:  {answers['send_port']}")
    print(f"Microphone type:      {answers['microphone_type']}")
    print(f"Sample rate:          {answers['sample_rate']}")
    print(f"Channels:             {answers['channels']}")
    print(f"PPS GPIO BCM:         {answers['pps_gpio_bcm']}")
    print(f"PPS physical pin:     {answers['pps_physical_pin']}")
    print(f"Base node IDs:        {', '.join(answers['base_node_ids']) or '(none)'}")
    print(f"RTK UDP targets:      {', '.join(answers['rtk_udp_targets']) or '(none)'}")
    print(f"Debug:                {answers['debug']}")
    print()
    print("Files to write:")
    for path in paths.values():
        print(f"  - {path}")


def confirm_write() -> bool:
    print()
    raw_value = input("Write these configuration files now? [y/N]: ").strip().lower()

    return raw_value in {
        "y",
        "yes",
    }


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EnviroPulse V2 node install wizard.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show generated configs without writing files.",
    )

    parser.add_argument(
        "--write",
        action="store_true",
        help="Write generated configs without the final confirmation prompt.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    repo_root = resolve_repo_root()
    paths = get_config_paths(repo_root)

    if not (repo_root / "node").exists():
        print_error("Could not find node/ directory.")
        print_error(f"Resolved repository root was: {repo_root}")
        return 1

    defaults = collect_existing_defaults(
        paths=paths,
    )

    answers = run_wizard(
        defaults=defaults,
    )

    configs = build_all_configs(
        paths=paths,
        answers=answers,
    )

    print_summary(
        answers=answers,
        paths=paths,
    )

    dry_run = args.dry_run

    if dry_run:
        print_header("Dry Run Output")

        for key, path in paths.items():
            write_json(
                path=path,
                data=configs[key],
                dry_run=True,
                make_backup=False,
            )

        print_header("Dry Run Complete")
        return 0

    if not args.write and not confirm_write():
        print_warn("No files were written.")
        return 0

    print_header("Writing Node Configuration")

    for key, path in paths.items():
        write_json(
            path=path,
            data=configs[key],
            dry_run=False,
            make_backup=True,
        )

    print_header("Node Configuration Complete")

    print("Next integration target:")
    print("  node/node_main.py")
    print()
    print("Runtime should later load:")
    print("  node/node_config.json")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
