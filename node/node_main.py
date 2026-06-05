"""
node_main.py

EnviroPulse V2

Responsibilities:
    - Create EventBus
    - Create subsystems
    - Start subsystems
    - Keep process alive

Not Responsible For:
    - Sensor logic
    - Event routing
    - Business logic
"""

import time

from node_event_bus import EventBus

from RTK.RTK_dispatcher import RTKDispatcher
from environmental.environmental_dispatcher import EnvironmentalDispatcher
from microphone.microphone_dispatcher import MicrophoneDispatcher
from birdnet.birdnet_dispatcher import BirdNetDispatcher
from sender.sender_dispatcher import SenderDispatcher
from listener.listener_dispatcher import ListenerDispatcher


def main():

    print()
    print("=" * 60)
    print("EnviroPulse Node V2 Starting")
    print("=" * 60)

    # ==================================================
    # EVENT BUS
    # ==================================================

    event_bus = EventBus(
        debug=True
    )

    # ==================================================
    # SUBSYSTEMS
    # ==================================================

    rtk = RTKDispatcher(
        event_bus=event_bus
    )

    environmental = EnvironmentalDispatcher(
        event_bus=event_bus
    )

    microphone = MicrophoneDispatcher(
        event_bus=event_bus
    )

    birdnet = BirdNetDispatcher(
        event_bus=event_bus
    )

    sender = SenderDispatcher(
        event_bus=event_bus
    )

    listener = ListenerDispatcher(
        event_bus=event_bus
    )

    # ==================================================
    # START SUBSYSTEMS
    # ==================================================

    print("[MAIN] Starting RTK...")
    rtk.start()

    print("[MAIN] Starting Environmental...")
    environmental.start()

    print("[MAIN] Starting Microphone...")
    microphone.start()

    print("[MAIN] Starting BirdNET...")
    birdnet.start()

    print("[MAIN] Starting Sender...")
    sender.start()

    print("[MAIN] Starting Listener...")
    listener.start()

    print()
    print("[MAIN] All subsystems started")

    # ==================================================
    # KEEP PROCESS ALIVE
    # ==================================================

    try:

        while True:

            time.sleep(1)

    except KeyboardInterrupt:

        print()
        print("[MAIN] Shutdown requested")

    finally:

        print("[MAIN] Shutdown complete")


if __name__ == "__main__":

    main()