# ============================================================
# ENVIROPULSE
# WATCHDOG RUNNER
# ============================================================

"""
Purpose
-------
Watch incoming WAV directory for newly completed
multichannel recordings.

When a complete WAV set is detected:
- group files
- wait for file stability
- send grouped paths to dispatcher

This module DOES NOT:
- load WAVs
- perform TDOA
- plot
- solve localization

Those responsibilities belong to:
    dispatcher.py
"""

# ============================================================
# IMPORTS
# ============================================================

import os

import time

from collections import defaultdict

from watchdog.observers import Observer

from watchdog.events import (
    FileSystemEventHandler
)

# ============================================================
# CONFIGURATION
# ============================================================

WATCH_DIRECTORY = (
    r"D:\EP_V2\scripts\detection_method\Media"
)

EXPECTED_CHANNEL_COUNT = 5

FILE_STABILITY_WAIT = 4

SUPPORTED_EXTENSION = ".wav"

PROCESS_CALLBACK = None

# ============================================================
# DISPATCHER IMPORT
# ============================================================

# dispatcher.py should expose:
#
# handle_wav_batch(batch_files)
#

# ============================================================
# WATCHDOG
# ============================================================

class WAVWatchdogHandler(

    FileSystemEventHandler

):

    def __init__(self):

        super().__init__()

        # ====================================================
        # BATCH STORAGE
        # ====================================================

        self.pending_batches = (
            defaultdict(list)
        )

        self.processed_batches = set()

    # ========================================================
    # FILE CREATED
    # ========================================================

    def on_created(

        self,
        event

    ):

        if event.is_directory:

            return

        file_path = event.src_path

        # ====================================================
        # FILTER EXTENSION
        # ====================================================

        if not file_path.lower().endswith(

            SUPPORTED_EXTENSION

        ):

            return

        print(
            f"[WATCHDOG] New file detected:"
            f" {file_path}"
        )

        # ====================================================
        # WAIT FOR FILE STABILITY
        # ====================================================

        if not self._wait_for_stable_file(

            file_path

        ):

            print(

                f"[WATCHDOG] File unstable:"
                f" {file_path}"

            )

            return

        # ====================================================
        # EXTRACT BATCH ID
        # ====================================================

        filename = os.path.basename(
            file_path
        )

        batch_id = self._extract_batch_id(
            filename
        )

        if batch_id is None:

            print(

                f"[WATCHDOG] Could not extract"
                f" batch ID from: {filename}"

            )

            return

        # ====================================================
        # STORE FILE
        # ====================================================

        self.pending_batches[
            batch_id
        ].append(file_path)

        current_count = len(

            self.pending_batches[
                batch_id
            ]

        )

        print(

            f"[WATCHDOG] Batch {batch_id}: "
            f"{current_count}/"
            f"{EXPECTED_CHANNEL_COUNT}"

        )

        # ====================================================
        # COMPLETE BATCH
        # ====================================================

        if current_count >= (
            EXPECTED_CHANNEL_COUNT
        ):

            if batch_id in (
                self.processed_batches
            ):

                return

            batch_files = sorted(

                self.pending_batches[
                    batch_id
                ]

            )

            print(
                f"[WATCHDOG] Complete batch:"
                f" {batch_id}"
            )

            # ================================================
            # SEND TO DISPATCHER
            # ================================================

            if PROCESS_CALLBACK is not None:

                PROCESS_CALLBACK(
                    batch_files
                )

            # ================================================
            # MARK COMPLETE
            # ================================================

            self.processed_batches.add(
                batch_id
            )

    # ========================================================
    # FILE STABILITY
    # ========================================================

    def _wait_for_stable_file(

        self,
        file_path,

        checks=5

    ):

        previous_size = -1

        for _ in range(checks):

            try:

                current_size = os.path.getsize(
                    file_path
                )

                if current_size == previous_size:

                    return True

                previous_size = current_size

                time.sleep(
                    FILE_STABILITY_WAIT
                )

            except Exception:

                return False

        return False

    # ========================================================
    # BATCH EXTRACTION
    # ========================================================

    def _extract_batch_id(

        self,
        filename

    ):
        
        try:

            name = os.path.splitext(
                filename
            )[0]

            first_split = name.split("-")

            if len(first_split) != 2:

                return None

            batch_id = first_split[1]

            return batch_id

        except Exception:

            return None

# ============================================================
# WATCHDOG RUNTIME
# ============================================================

def run_with_callback(callback):

    global PROCESS_CALLBACK

    PROCESS_CALLBACK = callback

    print(
        "[WATCHDOG] Starting..."
    )

    print(
        f"[WATCHDOG] Watching:"
        f" {WATCH_DIRECTORY}"
    )

    event_handler = WAVWatchdogHandler()

    observer = Observer()

    observer.schedule(

        event_handler,

        WATCH_DIRECTORY,

        recursive=False

    )

    observer.start()

    try:

        while True:

            time.sleep(1)

    except KeyboardInterrupt:

        observer.stop()

    observer.join()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print(
        "[WATCHDOG] Starting..."
    )

    print(
        f"[WATCHDOG] Watching:"
        f" {WATCH_DIRECTORY}"
    )

    event_handler = WAVWatchdogHandler()

    observer = Observer()

    observer.schedule(

        event_handler,

        WATCH_DIRECTORY,

        recursive=False

    )

    observer.start()

    try:

        while True:

            time.sleep(1)

    except KeyboardInterrupt:

        observer.stop()

    observer.join()