# ============================================================
# node_main.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Node Runtime
#
# Role:
#   Main
#
# Purpose:
#   Start the EnviroPulse node runtime, create subsystem
#   dispatchers, start them, and keep the process alive.
#
# Expected config source:
#   node_config.json
#
# Expected config section:
#   config["node_id"], config["node_name"], config["subsystems"],
#   config["register"], config["debug"]
#
# Does:
#   - Resolve the node runtime directory.
#   - Load central node identity from node_config.json.
#   - Create the EventBus.
#   - Create configured subsystem dispatchers.
#   - Start subsystem dispatchers in daemon threads.
#   - Keep the node process alive.
#   - Stop subsystems during shutdown.
#
# Does NOT:
#   - Own sensor logic.
#   - Own event routing policy.
#   - Own subsystem workflow.
#   - Know manager names.
#   - Know helper script names.
#   - Maintain platform state.
#   - Hard-code real node identity.
#
# Owner:
#   Subsystem root
#
# ============================================================

from __future__ import annotations

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from node_event_bus import EventBus

from RTK.RTK_dispatcher import RTKDispatcher
from environmental.environmental_dispatcher import EnvironmentalDispatcher
from microphone.microphone_dispatcher import MicrophoneDispatcher
from birdnet.birdnet_dispatcher import BirdNetDispatcher
from communication.communication_dispatcher import CommunicationDispatcher
from journal.journal_dispatcher import JournalDispatcher
from node_register import NodeRegister

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import json
import logging
import os
import threading
import time

from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple


# ============================================================
# CONFIG
# ============================================================

def load_node_config(
    base_dir: Path,
) -> Dict[str, Any]:

    config_path = base_dir / "node_config.json"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Missing required node config: {config_path}"
        )

    with config_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        config = json.load(
            file
        )

    if not isinstance(
        config,
        dict,
    ):
        raise ValueError(
            f"node_config.json must contain a JSON object: {config_path}"
        )

    validate_node_config(
        config=config,
        config_path=config_path,
    )

    return config


def validate_node_config(
    config: Dict[str, Any],
    config_path: Path,
) -> None:

    required_keys = [
        "node_id",
        "node_name",
    ]

    missing_keys = [
        key
        for key in required_keys
        if not str(
            config.get(
                key,
                "",
            )
        ).strip()
    ]

    if missing_keys:
        raise ValueError(
            f"Missing required key(s) in {config_path}: {missing_keys}"
        )


def get_subsystem_enabled(
    node_config: Dict[str, Any],
    subsystem_name: str,
    default: bool = True,
) -> bool:

    subsystems = node_config.get(
        "subsystems",
        {},
    )

    if not isinstance(
        subsystems,
        dict,
    ):
        return default

    return bool(
        subsystems.get(
            subsystem_name,
            default,
        )
    )


def get_register_heartbeat_sec(
    node_config: Dict[str, Any],
) -> int:

    register_config = node_config.get(
        "register",
        {},
    )

    if not isinstance(
        register_config,
        dict,
    ):
        return 300

    return int(
        register_config.get(
            "heartbeat_sec",
            300,
        )
    )


# ============================================================
# THREADING
# ============================================================

def start_dispatcher(
    name: str,
    dispatcher,
):

    def runner():

        try:
            print(
                f"[MAIN] Starting {name}..."
            )

            dispatcher.start()

        except Exception as error:
            logging.exception(
                "[MAIN] %s crashed: %s",
                name,
                error,
            )

    thread = threading.Thread(
        target=runner,
        name=f"{name}Thread",
        daemon=True,
    )

    thread.start()

    return thread


# ============================================================
# DISPATCHER CONSTRUCTION
# ============================================================

def add_dispatcher(
    dispatchers: List[Tuple[str, Any]],
    node_config: Dict[str, Any],
    subsystem_name: str,
    display_name: str,
    dispatcher,
) -> None:

    if get_subsystem_enabled(
        node_config=node_config,
        subsystem_name=subsystem_name,
        default=True,
    ):
        dispatchers.append(
            (
                display_name,
                dispatcher,
            )
        )

    else:
        print(
            f"[MAIN] {display_name} disabled by node_config.json"
        )


def build_dispatchers(
    event_bus: EventBus,
    node_config: Dict[str, Any],
) -> List[Tuple[str, Any]]:

    node_id = str(
        node_config["node_id"]
    )

    node_name = str(
        node_config["node_name"]
    )

    debug = bool(
        node_config.get(
            "debug",
            True,
        )
    )

    register_heartbeat_sec = get_register_heartbeat_sec(
        node_config=node_config,
    )

    dispatchers: List[Tuple[str, Any]] = []

    add_dispatcher(
        dispatchers=dispatchers,
        node_config=node_config,
        subsystem_name="journal",
        display_name="Journal",
        dispatcher=JournalDispatcher(
            event_bus=event_bus,
        ),
    )

    add_dispatcher(
        dispatchers=dispatchers,
        node_config=node_config,
        subsystem_name="node_register",
        display_name="NodeRegister",
        dispatcher=NodeRegister(
            event_bus=event_bus,
            node_id=node_id,
            node_name=node_name,
            register_heartbeat_sec=register_heartbeat_sec,
            debug=debug,
        ),
    )

    add_dispatcher(
        dispatchers=dispatchers,
        node_config=node_config,
        subsystem_name="rtk",
        display_name="RTK",
        dispatcher=RTKDispatcher(
            event_bus=event_bus,
            debug=debug,
        ),
    )

    add_dispatcher(
        dispatchers=dispatchers,
        node_config=node_config,
        subsystem_name="environmental",
        display_name="Environmental",
        dispatcher=EnvironmentalDispatcher(
            event_bus=event_bus,
            node_id=node_id,
            node_name=node_name,
            debug=debug,
        ),
    )

    add_dispatcher(
        dispatchers=dispatchers,
        node_config=node_config,
        subsystem_name="microphone",
        display_name="Microphone",
        dispatcher=MicrophoneDispatcher(
            event_bus=event_bus,
        ),
    )

    add_dispatcher(
        dispatchers=dispatchers,
        node_config=node_config,
        subsystem_name="birdnet",
        display_name="BirdNET",
        dispatcher=BirdNetDispatcher(
            event_bus=event_bus,
        ),
    )

    add_dispatcher(
        dispatchers=dispatchers,
        node_config=node_config,
        subsystem_name="communication",
        display_name="Communication",
        dispatcher=CommunicationDispatcher(
            event_bus=event_bus,
        ),
    )

    return dispatchers


# ============================================================
# DISPLAY
# ============================================================

def print_startup_banner(
    node_config: Dict[str, Any],
) -> None:

    print()
    print(
        "=" * 60
    )
    print(
        "EnviroPulse Node V2 Starting"
    )
    print(
        "=" * 60
    )
    print(
        f"Node ID:   {node_config['node_id']}"
    )
    print(
        f"Node Name: {node_config['node_name']}"
    )
    print(
        "=" * 60
    )
    print()


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    base_dir = Path(
        __file__
    ).resolve().parent

    os.chdir(
        base_dir
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    node_config = load_node_config(
        base_dir=base_dir,
    )

    print_startup_banner(
        node_config=node_config,
    )

    debug = bool(
        node_config.get(
            "debug",
            True,
        )
    )

    event_bus = EventBus(
        debug=debug,
    )

    dispatchers = build_dispatchers(
        event_bus=event_bus,
        node_config=node_config,
    )

    threads = []

    for name, dispatcher in dispatchers:
        threads.append(
            start_dispatcher(
                name=name,
                dispatcher=dispatcher,
            )
        )

    print()
    print(
        "[MAIN] All configured subsystem start commands issued"
    )
    print(
        "[MAIN] Node runtime is alive"
    )
    print()

    try:
        while True:
            time.sleep(
                1
            )

    except KeyboardInterrupt:
        print()
        print(
            "[MAIN] Shutdown requested"
        )

    finally:
        for name, dispatcher in reversed(
            dispatchers
        ):
            stop = getattr(
                dispatcher,
                "stop",
                None,
            )

            if callable(
                stop
            ):
                try:
                    print(
                        f"[MAIN] Stopping {name}..."
                    )

                    stop()

                except Exception as error:
                    logging.exception(
                        "[MAIN] Stop failed for %s: %s",
                        name,
                        error,
                    )

        print(
            "[MAIN] Shutdown complete"
        )


if __name__ == "__main__":
    main()