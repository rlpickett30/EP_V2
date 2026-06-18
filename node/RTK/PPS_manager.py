"""
PPS_manager.py

EnviroPulse V2.0
Subsystem: RTK
Role: PPS Manager

Responsibilities:
- Own Raspberry Pi GPIO PPS input.
- Measure PPS pulse edges from the ZED-F9P PPS/timepulse pin.
- Create PPS snapshots for RTKDispatcher.
- Create PPS event IDs.

This module intentionally knows nothing about:
- EventBus
- Dispatchers
- Publishers
- Subscribers
- Microphone recording logic

Notes:
- Use BCM numbering, not physical header numbering.
- BCM GPIO18 is physical pin 12 on the Raspberry Pi header.
- USB serial/NMEA can prove GPS data, but it does not prove that the
  Raspberry Pi measured the PPS edge. PPS truth comes from GPIO here.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import Optional


class PPSManager:

    def __init__(
        self,
        gpio_bcm: int = 18,
        pps_timeout_sec: float = 2.0,
        active_edge: str = "rising",
        pull: str = "down",
        port: Optional[str] = None,
        debug: bool = True
    ):

        self.debug = debug

        # Kept only for backward compatibility with older constructor calls.
        # PPS truth is no longer taken from FP9 USB serial.
        self.port = port

        self.gpio_bcm = int(gpio_bcm)
        self.pps_timeout_sec = float(pps_timeout_sec)
        self.active_edge = str(active_edge).lower()
        self.pull = str(pull).lower()

        self.backend: Optional[str] = None
        self.backend_error: Optional[str] = None

        self.last_pps_epoch: Optional[float] = None
        self.last_pps_monotonic: Optional[float] = None
        self.last_pps_tick: Optional[int] = None
        self.pulse_count = 0

        self.lock = threading.Lock()

        self._lgpio = None
        self._gpio_chip = None
        self._gpio_callback = None
        self._gpiozero_device = None

        self.setup_gpio()

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

        if self.debug:

            print(
                f"[PPSManager] {message}"
            )

    # --------------------------------------------------
    # GPIO Setup
    # --------------------------------------------------

    def setup_gpio(self):

        if self.try_setup_lgpio():
            return

        if self.try_setup_gpiozero():
            return

        self.backend = None

        if self.backend_error is None:
            self.backend_error = (
                "No supported GPIO backend found. Install python3-lgpio "
                "or gpiozero on the Raspberry Pi."
            )

        self.log(self.backend_error)

    def try_setup_lgpio(self) -> bool:

        try:
            import lgpio

            chip = lgpio.gpiochip_open(0)

            flags = self.get_lgpio_pull_flags(lgpio)

            try:
                lgpio.gpio_claim_input(
                    chip,
                    self.gpio_bcm,
                    flags
                )
            except TypeError:
                lgpio.gpio_claim_input(
                    chip,
                    self.gpio_bcm
                )

            edge = self.get_lgpio_edge(lgpio)

            callback = lgpio.callback(
                chip,
                self.gpio_bcm,
                edge,
                self.handle_lgpio_edge
            )

            self._lgpio = lgpio
            self._gpio_chip = chip
            self._gpio_callback = callback
            self.backend = "lgpio"
            self.backend_error = None

            self.log(
                f"Listening for PPS on BCM GPIO{self.gpio_bcm} "
                f"using lgpio ({self.active_edge} edge)"
            )

            return True

        except Exception as error:
            self.backend_error = f"lgpio setup failed: {error}"
            self.log(self.backend_error)
            return False

    def try_setup_gpiozero(self) -> bool:

        try:
            from gpiozero import DigitalInputDevice

            pull_up = None

            if self.pull == "up":
                pull_up = True

            elif self.pull == "down":
                pull_up = False

            device = DigitalInputDevice(
                self.gpio_bcm,
                pull_up=pull_up
            )

            if self.active_edge == "falling":
                device.when_deactivated = self.handle_gpiozero_edge

            elif self.active_edge == "both":
                device.when_activated = self.handle_gpiozero_edge
                device.when_deactivated = self.handle_gpiozero_edge

            else:
                device.when_activated = self.handle_gpiozero_edge

            self._gpiozero_device = device
            self.backend = "gpiozero"
            self.backend_error = None

            self.log(
                f"Listening for PPS on BCM GPIO{self.gpio_bcm} "
                f"using gpiozero ({self.active_edge} edge)"
            )

            return True

        except Exception as error:
            self.backend_error = f"gpiozero setup failed: {error}"
            self.log(self.backend_error)
            return False

    def get_lgpio_pull_flags(self, lgpio_module) -> int:

        if self.pull == "up":
            return getattr(
                lgpio_module,
                "SET_PULL_UP",
                0
            )

        if self.pull == "down":
            return getattr(
                lgpio_module,
                "SET_PULL_DOWN",
                0
            )

        return getattr(
            lgpio_module,
            "SET_PULL_NONE",
            0
        )

    def get_lgpio_edge(self, lgpio_module):

        if self.active_edge == "falling":
            return lgpio_module.FALLING_EDGE

        if self.active_edge == "both":
            return lgpio_module.BOTH_EDGES

        return lgpio_module.RISING_EDGE

    # --------------------------------------------------
    # Edge Capture
    # --------------------------------------------------

    def handle_lgpio_edge(
        self,
        chip,
        gpio,
        level,
        tick
    ):

        self.record_pps_edge(
            tick=tick
        )

    def handle_gpiozero_edge(self, *args):

        self.record_pps_edge()

    def record_pps_edge(
        self,
        tick: Optional[int] = None
    ):

        now_epoch = time.time()
        now_monotonic = time.monotonic()

        with self.lock:

            self.last_pps_epoch = now_epoch
            self.last_pps_monotonic = now_monotonic
            self.last_pps_tick = tick
            self.pulse_count += 1

    # --------------------------------------------------
    # Time Helpers
    # --------------------------------------------------

    def get_utc_timestamp(self) -> str:

        return (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def epoch_to_utc(
        self,
        epoch: Optional[float]
    ) -> Optional[str]:

        if epoch is None:
            return None

        return (
            datetime.fromtimestamp(epoch, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    # --------------------------------------------------
    # GPIO Read Helper
    # --------------------------------------------------

    def read_gpio_level(self) -> Optional[int]:

        try:

            if self.backend == "lgpio" and self._lgpio:
                return int(
                    self._lgpio.gpio_read(
                        self._gpio_chip,
                        self.gpio_bcm
                    )
                )

            if self.backend == "gpiozero" and self._gpiozero_device:
                return int(
                    self._gpiozero_device.value
                )

        except Exception as error:
            self.log(
                f"GPIO read failed: {error}"
            )

        return None

    # --------------------------------------------------
    # Snapshot
    # --------------------------------------------------

    def get_snapshot(self) -> Dict[str, Any]:

        now_epoch = time.time()
        now_monotonic = time.monotonic()
        event_utc = int(now_epoch)

        with self.lock:

            last_pps_epoch = self.last_pps_epoch
            last_pps_monotonic = self.last_pps_monotonic
            last_pps_tick = self.last_pps_tick
            pulse_count = self.pulse_count

        seconds_since_last_pps = None

        if last_pps_monotonic is not None:
            seconds_since_last_pps = (
                now_monotonic
                - last_pps_monotonic
            )

        pps_valid = (
            self.backend is not None
            and seconds_since_last_pps is not None
            and seconds_since_last_pps <= self.pps_timeout_sec
        )

        snapshot = {
            "event_id": f"PPS_{event_utc}",
            "event_utc": event_utc,
            "timestamp": now_epoch,
            "timestamp_utc": self.get_utc_timestamp(),
            "pps_valid": pps_valid,
            "pps_locked": pps_valid,
            "pps_online": pps_valid,
            "state": "LOCKED" if pps_valid else "LOST",
            "pps_source": "gpio",
            "gpio_bcm": self.gpio_bcm,
            "physical_pin": 12 if self.gpio_bcm == 18 else None,
            "pin_numbering": "BCM",
            "active_edge": self.active_edge,
            "pull": self.pull,
            "backend": self.backend,
            "backend_error": self.backend_error,
            "last_pps_epoch": last_pps_epoch,
            "last_pps_utc": self.epoch_to_utc(last_pps_epoch),
            "last_pps_tick": last_pps_tick,
            "seconds_since_last_pps": seconds_since_last_pps,
            "pulse_count": pulse_count,
            "gpio_level": self.read_gpio_level()
        }

        return snapshot

    # --------------------------------------------------
    # Cleanup
    # --------------------------------------------------

    def close(self):

        try:

            if self._gpio_callback is not None:
                self._gpio_callback.cancel()

        except Exception as error:
            self.log(
                f"Callback cleanup failed: {error}"
            )

        try:

            if self._lgpio and self._gpio_chip is not None:
                self._lgpio.gpiochip_close(
                    self._gpio_chip
                )

        except Exception as error:
            self.log(
                f"GPIO chip cleanup failed: {error}"
            )

        try:

            if self._gpiozero_device is not None:
                self._gpiozero_device.close()

        except Exception as error:
            self.log(
                f"gpiozero cleanup failed: {error}"
            )


if __name__ == "__main__":

    manager = PPSManager(
        gpio_bcm=18,
        pps_timeout_sec=2,
        debug=True
    )

    try:

        while True:

            print(
                manager.get_snapshot()
            )

            time.sleep(1)

    except KeyboardInterrupt:

        print()
        print("Shutdown requested")

    finally:

        manager.close()
