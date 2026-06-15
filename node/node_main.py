"""
node_main.py

EnviroPulse V2 Node Runtime

Responsibilities:
- Create EventBus
- Create node subsystems
- Start subsystems
- Keep process alive

Not Responsible For:
- Sensor logic
- Event routing policy
- Business logic
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from node_event_bus import EventBus

from RTK.RTK_dispatcher import RTKDispatcher
from environmental.environmental_dispatcher import EnvironmentalDispatcher
from microphone.microphone_dispatcher import MicrophoneDispatcher
from birdnet.birdnet_dispatcher import BirdNetDispatcher
from communication.communication_dispatcher import CommunicationDispatcher
from journal.journal_dispatcher import JournalDispatcher


def start_dispatcher(name: str, dispatcher):
    def runner():
        try:
            print(f"[MAIN] Starting {name}...")
            dispatcher.start()
        except Exception as error:
            logging.exception("[MAIN] %s crashed: %s", name, error)

    thread = threading.Thread(
        target=runner,
        name=f"{name}Thread",
        daemon=True,
    )
    thread.start()
    return thread


def main():
    base_dir = Path(__file__).resolve().parent
    os.chdir(base_dir)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    print()
    print("=" * 60)
    print("EnviroPulse Node V2 Starting")
    print("=" * 60)

    event_bus = EventBus(debug=True)

    journal = JournalDispatcher(event_bus=event_bus)
    rtk = RTKDispatcher(event_bus=event_bus)
    environmental = EnvironmentalDispatcher(event_bus=event_bus)
    microphone = MicrophoneDispatcher(event_bus=event_bus)
    birdnet = BirdNetDispatcher(event_bus=event_bus)
    communication = CommunicationDispatcher(event_bus=event_bus)

    dispatchers = [
        ("Journal", journal),
        ("RTK", rtk),
        ("Environmental", environmental),
        ("Microphone", microphone),
        ("BirdNET", birdnet),
        ("Communication", communication),
    ]

    threads = []

    for name, dispatcher in dispatchers:
        threads.append(start_dispatcher(name, dispatcher))

    print()
    print("[MAIN] All subsystem start commands issued")
    print("[MAIN] Node runtime is alive")
    print()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print()
        print("[MAIN] Shutdown requested")

    finally:
        for name, dispatcher in dispatchers:
            stop = getattr(dispatcher, "stop", None)
            if callable(stop):
                try:
                    print(f"[MAIN] Stopping {name}...")
                    stop()
                except Exception as error:
                    logging.exception("[MAIN] Stop failed for %s: %s", name, error)

        print("[MAIN] Shutdown complete")


if __name__ == "__main__":
    main()