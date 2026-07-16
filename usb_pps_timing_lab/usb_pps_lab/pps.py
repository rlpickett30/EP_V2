from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .common import append_ndjson, epoch_ns_to_iso
from .nmea import parse_rmc, rmc_second_utc_ns


@dataclass
class PpsObservation:
    sequence: int
    kernel_realtime_ns: int
    estimated_monotonic_ns: int
    observed_monotonic_ns: int
    observed_realtime_ns: int
    assert_text: str
    utc_ns: int | None = None
    utc_source: str | None = None
    rmc_sentence: str | None = None
    rmc_arrival_delay_ms: float | None = None


def parse_pps_assert(text: str) -> tuple[int, int]:
    """Parse LinuxPPS sysfs form: seconds.nanoseconds#sequence."""
    cleaned = text.strip()
    timestamp_text, sequence_text = cleaned.split("#", 1)
    seconds_text, nanoseconds_text = timestamp_text.split(".", 1)
    nanoseconds_text = (nanoseconds_text + "000000000")[:9]
    epoch_ns = int(seconds_text) * 1_000_000_000 + int(nanoseconds_text)
    return epoch_ns, int(sequence_text)


class PpsGnssMonitor:
    def __init__(
        self,
        assert_path: Path,
        poll_interval_ms: float,
        output_directory: Path,
        gnss_enabled: bool,
        serial_device: str,
        baud: int,
        pairing_window_ms: float,
        allow_system_time_fallback: bool,
        logger: Callable[[str], None] = print,
    ) -> None:
        self.assert_path = assert_path
        self.poll_interval = max(0.0005, poll_interval_ms / 1000.0)
        self.output_directory = output_directory
        self.gnss_enabled = gnss_enabled
        self.serial_device = serial_device
        self.baud = baud
        self.pairing_window_ns = int(pairing_window_ms * 1e6)
        self.allow_system_time_fallback = allow_system_time_fallback
        self.logger = logger

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._observations: list[PpsObservation] = []
        self._last_sequence: int | None = None
        self._threads: list[threading.Thread] = []

        self.observations_path = output_directory / "pps_observations.ndjson"
        self.anchors_path = output_directory / "pps_anchors.ndjson"
        self.nmea_path = output_directory / "nmea_rmc.ndjson"

    def start(self) -> None:
        if not self.assert_path.exists():
            raise FileNotFoundError(f"PPS assert path not found: {self.assert_path}")
        pps_thread = threading.Thread(target=self._pps_loop, name="pps-monitor", daemon=True)
        self._threads.append(pps_thread)
        pps_thread.start()

        if self.gnss_enabled:
            gnss_thread = threading.Thread(target=self._gnss_loop, name="gnss-rmc", daemon=True)
            self._threads.append(gnss_thread)
            gnss_thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=3.0)
        self._finalize_unpaired()

    def snapshot(self) -> list[PpsObservation]:
        with self._lock:
            return list(self._observations)

    def _pps_loop(self) -> None:
        while not self._stop.is_set():
            try:
                assert_text = self.assert_path.read_text(encoding="utf-8").strip()
                kernel_realtime_ns, sequence = parse_pps_assert(assert_text)
                if sequence != self._last_sequence:
                    mono_before = time.monotonic_ns()
                    observed_realtime_ns = time.time_ns()
                    mono_after = time.monotonic_ns()
                    observed_monotonic_ns = (mono_before + mono_after) // 2
                    estimated_monotonic_ns = (
                        observed_monotonic_ns
                        - (observed_realtime_ns - kernel_realtime_ns)
                    )
                    observation = PpsObservation(
                        sequence=sequence,
                        kernel_realtime_ns=kernel_realtime_ns,
                        estimated_monotonic_ns=estimated_monotonic_ns,
                        observed_monotonic_ns=observed_monotonic_ns,
                        observed_realtime_ns=observed_realtime_ns,
                        assert_text=assert_text,
                    )
                    with self._lock:
                        self._observations.append(observation)
                    self._last_sequence = sequence
                    append_ndjson(
                        self.observations_path,
                        {
                            **observation.__dict__,
                            "kernel_realtime_iso": epoch_ns_to_iso(kernel_realtime_ns),
                        },
                    )
            except Exception as error:
                append_ndjson(
                    self.output_directory / "monitor_errors.ndjson",
                    {
                        "source": "pps",
                        "monotonic_ns": time.monotonic_ns(),
                        "error": repr(error),
                    },
                )
            self._stop.wait(self.poll_interval)

    def _gnss_loop(self) -> None:
        try:
            import serial
        except ImportError:
            self.logger("[GNSS] pyserial is unavailable; RMC pairing disabled.")
            return

        try:
            with serial.Serial(self.serial_device, self.baud, timeout=0.5) as port:
                self.logger(f"[GNSS] Reading RMC from {self.serial_device} at {self.baud} baud.")
                while not self._stop.is_set():
                    raw = port.readline()
                    if not raw:
                        continue
                    arrival_monotonic_ns = time.monotonic_ns()
                    try:
                        sentence = raw.decode("ascii", errors="ignore").strip()
                        fix = parse_rmc(sentence)
                    except Exception:
                        fix = None
                    if fix is None:
                        continue
                    append_ndjson(
                        self.nmea_path,
                        {
                            "arrival_monotonic_ns": arrival_monotonic_ns,
                            "utc_ns": fix.utc_ns,
                            "valid": fix.valid,
                            "sentence_type": fix.sentence_type,
                            "raw_sentence": fix.raw_sentence,
                        },
                    )
                    if fix.valid:
                        self._pair_fix(fix, arrival_monotonic_ns)
        except Exception as error:
            append_ndjson(
                self.output_directory / "monitor_errors.ndjson",
                {
                    "source": "gnss",
                    "monotonic_ns": time.monotonic_ns(),
                    "error": repr(error),
                },
            )
            self.logger(f"[GNSS] RMC reader stopped: {error}")

    def _pair_fix(self, fix: Any, arrival_monotonic_ns: int) -> None:
        candidate: PpsObservation | None = None
        with self._lock:
            for observation in reversed(self._observations):
                if observation.utc_ns is not None:
                    continue
                delay = arrival_monotonic_ns - observation.estimated_monotonic_ns
                if 0 <= delay <= self.pairing_window_ns:
                    candidate = observation
                    break
        if candidate is None:
            return

        candidate.utc_ns = rmc_second_utc_ns(fix)
        candidate.utc_source = "gnss_rmc_paired_to_pps"
        candidate.rmc_sentence = fix.raw_sentence
        candidate.rmc_arrival_delay_ms = (
            arrival_monotonic_ns - candidate.estimated_monotonic_ns
        ) / 1e6
        append_ndjson(self.anchors_path, self._anchor_record(candidate))

    def _finalize_unpaired(self) -> None:
        if not self.allow_system_time_fallback:
            return
        with self._lock:
            unpaired = [item for item in self._observations if item.utc_ns is None]
        for observation in unpaired:
            observation.utc_ns = (
                int(round(observation.kernel_realtime_ns / 1e9)) * 1_000_000_000
            )
            observation.utc_source = "system_realtime_fallback"
            append_ndjson(self.anchors_path, self._anchor_record(observation))

    @staticmethod
    def _anchor_record(observation: PpsObservation) -> dict[str, Any]:
        return {
            **observation.__dict__,
            "utc_iso": epoch_ns_to_iso(observation.utc_ns) if observation.utc_ns is not None else None,
        }
