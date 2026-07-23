# ============================================================
# pps_anchor_journal.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Microphone
#
# Role:
#   Low-level append-only timing evidence writer
#
# Purpose:
#   Persist finalized PPS/sample anchor evidence without blocking
#   the PPS resolver or changing microphone synchronization state.
#
# Does:
#   - Create one session-scoped NDJSON evidence file
#   - Accept finalized anchor records through a bounded queue
#   - Write one compact JSON object per line
#   - Preserve accepted and rejected anchor evidence
#   - Drain queued records during orderly shutdown
#   - Track queued, written, failed, and queue-full counts
#
# Does NOT:
#   - Publish events
#   - Subscribe to the event bus
#   - Fit the microphone sample clock
#   - Declare MICROPHONE_SYNCED
#   - Change recording, BirdNET, or TDOA behavior
#
# Owner:
#   microphone_dispatcher.py
#
# ============================================================

from __future__ import annotations

import copy
import json
import re
import threading

from datetime import datetime
from datetime import timezone
from pathlib import Path
from queue import Empty
from queue import Full
from queue import Queue


class PPSAnchorJournal:

    def __init__(
        self,
        recordings_root,
        node_id,
        queue_capacity=4096,
        debug=True
    ):

        self.recordings_root = Path(recordings_root)
        self.node_id = str(node_id or "unknown_node")
        self.queue_capacity = max(1, int(queue_capacity))
        self.debug = bool(debug)

        session_utc = (
            datetime.now(timezone.utc)
            .strftime("%Y%m%dT%H%M%S.%fZ")
        )

        safe_node_id = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            self.node_id
        ).strip("._")

        if not safe_node_id:
            safe_node_id = "unknown_node"

        self.output_directory = (
            self.recordings_root
            /
            "timing"
        )

        self.output_path = (
            self.output_directory
            /
            (
                f"{safe_node_id}_pps_anchor_evidence_"
                f"{session_utc}.ndjson"
            )
        )

        self._queue = Queue(maxsize=self.queue_capacity)
        self._stop_event = threading.Event()
        self._thread = None
        self._state_lock = threading.Lock()

        self._accepting_records = False
        self._fatal_error = None
        self._unavailable_log_emitted = False

        self.queued_count = 0
        self.written_count = 0
        self.failed_count = 0
        self.queue_full_count = 0

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def log(self, message):

        if self.debug:
            print(f"[PPSAnchorJournal] {message}")

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    def start(self):

        thread = self._thread

        if thread is not None and thread.is_alive():
            return

        self._stop_event.clear()

        with self._state_lock:
            self._accepting_records = True
            self._fatal_error = None
            self._unavailable_log_emitted = False

        self._thread = threading.Thread(
            target=self._writer_worker,
            name="PPSAnchorJournalWriter",
            daemon=True
        )

        self._thread.start()

        self.log(
            (
                "Writer started: "
                f"path={self.output_path} "
                f"queue_capacity={self.queue_capacity}"
            )
        )

    def stop(self, timeout_seconds=5.0):

        with self._state_lock:
            self._accepting_records = False

        self._stop_event.set()

        thread = self._thread

        if thread is None:
            return self.snapshot()

        thread.join(timeout=max(0.0, float(timeout_seconds)))

        if thread.is_alive():
            self.log(
                (
                    "Writer did not stop within "
                    f"{float(timeout_seconds):.1f} seconds; "
                    f"pending={self._queue.qsize()}"
                )
            )
        else:
            self.log(
                (
                    "Writer stopped: "
                    f"queued={self.queued_count} "
                    f"written={self.written_count} "
                    f"failed={self.failed_count} "
                    f"queue_full={self.queue_full_count}"
                )
            )

            self._thread = None

        return self.snapshot()

    # --------------------------------------------------
    # Queue
    # --------------------------------------------------

    def enqueue(self, anchor_record):

        if not isinstance(anchor_record, dict):
            with self._state_lock:
                self.failed_count += 1
            self.log("Rejected non-dictionary anchor record")
            return False

        record_copy = copy.deepcopy(anchor_record)
        should_log_unavailable = False
        queue_full = False
        fatal_error = None

        with self._state_lock:

            fatal_error = self._fatal_error

            if (
                not self._accepting_records
                or
                fatal_error is not None
            ):

                self.failed_count += 1

                if not self._unavailable_log_emitted:
                    self._unavailable_log_emitted = True
                    should_log_unavailable = True

            else:

                try:
                    self._queue.put_nowait(record_copy)

                except Full:
                    self.failed_count += 1
                    self.queue_full_count += 1
                    queue_full = True

                else:
                    self.queued_count += 1
                    return True

        if should_log_unavailable:

            if fatal_error is None:
                reason = "writer_not_accepting_records"
            else:
                reason = (
                    f"{fatal_error['exception_type']}: "
                    f"{fatal_error['exception_message']}"
                )

            self.log(
                (
                    "Anchor evidence not queued: "
                    f"reason={reason}"
                )
            )

        if queue_full:
            self.log(
                (
                    "Anchor evidence queue full: "
                    f"capacity={self.queue_capacity} "
                    f"pps_seq={anchor_record.get('pps_seq')}"
                )
            )

        return False

    # --------------------------------------------------
    # Writer
    # --------------------------------------------------

    def _writer_worker(self):

        output_file = None

        try:
            self.output_directory.mkdir(
                parents=True,
                exist_ok=True
            )

            output_file = open(
                self.output_path,
                "a",
                encoding="utf-8",
                buffering=1
            )

            while True:

                if (
                    self._stop_event.is_set()
                    and
                    self._queue.empty()
                ):
                    return

                try:
                    anchor_record = self._queue.get(
                        timeout=0.1
                    )

                except Empty:
                    continue

                try:
                    line = json.dumps(
                        anchor_record,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False
                    )

                    output_file.write(line)
                    output_file.write("\n")
                    output_file.flush()

                    with self._state_lock:
                        self.written_count += 1

                except Exception as error:

                    with self._state_lock:
                        self.failed_count += 1

                    self.log(
                        (
                            "Anchor evidence write failed: "
                            f"pps_seq={anchor_record.get('pps_seq')} "
                            f"{type(error).__name__}: {error}"
                        )
                    )

                finally:
                    self._queue.task_done()

        except Exception as error:

            fatal_error = {
                "exception_type": type(error).__name__,
                "exception_message": str(error)
            }

            with self._state_lock:
                self._fatal_error = fatal_error
                self._accepting_records = False

            self.log(
                (
                    "Writer unavailable: "
                    f"{fatal_error['exception_type']}: "
                    f"{fatal_error['exception_message']}"
                )
            )

            self._drain_failed_records()

        finally:

            if output_file is not None:
                try:
                    output_file.flush()
                    output_file.close()
                except Exception as error:
                    self.log(
                        (
                            "Writer close failed: "
                            f"{type(error).__name__}: {error}"
                        )
                    )

    def _drain_failed_records(self):

        while True:

            try:
                self._queue.get_nowait()

            except Empty:
                return

            else:

                with self._state_lock:
                    self.failed_count += 1

                self._queue.task_done()

    # --------------------------------------------------
    # Status
    # --------------------------------------------------

    def snapshot(self):

        with self._state_lock:

            fatal_error = (
                copy.deepcopy(self._fatal_error)
                if self._fatal_error is not None
                else None
            )

            return {
                "output_path": str(self.output_path),
                "queue_capacity": self.queue_capacity,
                "queue_size": self._queue.qsize(),
                "accepting_records": self._accepting_records,
                "queued_count": self.queued_count,
                "written_count": self.written_count,
                "failed_count": self.failed_count,
                "queue_full_count": self.queue_full_count,
                "fatal_error": fatal_error
            }
