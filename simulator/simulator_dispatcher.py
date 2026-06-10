"""
simulator_dispatcher.py

Faux node simulator dispatcher.

Purpose:
- Load simulator_config.json.
- Let the user inject one event at a time.
- Build a pseudo node package.
- Send the package to the server through udp_sender.py.

Modes:
- Manual mode: Choose one event from a menu and send it.
- Cadence mode: Send enabled events according to their individual cadence,
  but still only one event per loop pass.
"""

import copy
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from udp_sender import UDPSender


CONFIG_PATH = Path(__file__).parent / "simulator_config.json"


class SimulatorDispatcher:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = self._load_config()

        network_config = self.config["network"]
        self.sender = UDPSender(
            server_ip=network_config["server_ip"],
            server_port=network_config["server_port"]
        )

        self.last_sent_times = {}

    def _load_config(self) -> dict:
        with open(self.config_path, "r", encoding="utf-8") as file:
            return json.load(file)

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _make_event_id(self, event_type: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        short_uuid = uuid.uuid4().hex[:8].upper()
        return f"SIM_{event_type}_{timestamp}_{short_uuid}"

    def _replace_auto_values(self, payload: dict) -> dict:
        """
        Replaces any payload value of 'AUTO' with current UTC time.
        This keeps config readable while allowing fresh timestamps.
        """
        updated_payload = copy.deepcopy(payload)
        now = self._utc_now()

        for key, value in updated_payload.items():
            if value == "AUTO":
                updated_payload[key] = now

        return updated_payload

    def build_package(self, event_type: str) -> dict | None:
        events = self.config.get("events", {})

        if event_type not in events:
            print(f"[SIM ERROR] Unknown event type: {event_type}")
            return None

        event_config = events[event_type]

        if not event_config.get("enabled", False):
            print(f"[SIM BLOCKED] Event is disabled in config: {event_type}")
            return None

        simulator_config = self.config["simulator"]
        payload = self._replace_auto_values(event_config.get("payload", {}))

        package = {
            "event_id": self._make_event_id(event_type),
            "event_type": event_type,
            "timestamp_utc": self._utc_now(),
            "source": simulator_config.get("node_id", "faux_node"),
            "source_name": simulator_config.get("node_name", "Faux Node"),
            "target": simulator_config.get("target", "server"),
            "simulated": True,
            "payload": payload
        }

        return package

    def send_event(self, event_type: str) -> None:
        package = self.build_package(event_type)

        if package is None:
            return

        print("\n[SIM PACKAGE]")
        print(json.dumps(package, indent=2))

        sent = self.sender.send(package)

        if sent:
            self.last_sent_times[event_type] = time.time()

    def get_enabled_events(self) -> list[str]:
        events = self.config.get("events", {})

        return [
            event_type
            for event_type, event_config in events.items()
            if event_config.get("enabled", False)
        ]

    def manual_menu(self) -> None:
        while True:
            enabled_events = self.get_enabled_events()

            print("\n========== FAUX NODE SIMULATOR ==========")
            print("Choose one event to inject:\n")

            for index, event_type in enumerate(enabled_events, start=1):
                cadence = self.config["events"][event_type].get("cadence_seconds", "None")
                print(f"{index}. {event_type}   cadence={cadence}s")

            print("R. Reload config")
            print("Q. Quit")

            choice = input("\nSelection: ").strip().upper()

            if choice == "Q":
                print("[SIM] Exiting simulator.")
                break

            if choice == "R":
                self.config = self._load_config()
                print("[SIM] Config reloaded.")
                continue

            try:
                selected_index = int(choice) - 1
                selected_event = enabled_events[selected_index]
                self.send_event(selected_event)

            except (ValueError, IndexError):
                print("[SIM ERROR] Invalid selection.")

    def cadence_loop(self) -> None:
        print("[SIM] Starting cadence mode.")
        print("[SIM] Press Ctrl+C to stop.\n")

        try:
            while True:
                self.config = self._load_config()
                enabled_events = self.get_enabled_events()
                now = time.time()

                for event_type in enabled_events:
                    event_config = self.config["events"][event_type]
                    cadence = event_config.get("cadence_seconds", 30)

                    last_sent = self.last_sent_times.get(event_type, 0)
                    due = now - last_sent >= cadence

                    if due:
                        self.send_event(event_type)

                        # Important:
                        # This keeps the simulator from blasting every due event at once.
                        # It sends one event, then restarts the loop.
                        break

                time.sleep(1)

        except KeyboardInterrupt:
            print("\n[SIM] Cadence mode stopped.")


def main():
    dispatcher = SimulatorDispatcher(CONFIG_PATH)

    default_mode = dispatcher.config.get("simulator", {}).get("default_mode", "manual")

    if default_mode == "cadence":
        dispatcher.cadence_loop()
    else:
        dispatcher.manual_menu()


if __name__ == "__main__":
    main()
