# ============================================================
# sender_database.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Persist outbound messages
#   - Retrieve queued messages
#   - Remove sent messages
#   - Provide queue statistics
#
# Does NOT:
#   - Send messages
#   - Retry messages
#   - Make decisions
#   - Publish events
#
# ============================================================

import json

from pathlib import Path

from typing import List
from typing import Dict


class SenderDatabase:

    def __init__(
        self,
        queue_file: str
    ):

        self.queue_file = Path(
            queue_file
        )

        self.queue_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if not self.queue_file.exists():

            self.queue_file.write_text(
                "[]",
                encoding="utf-8"
            )

    # ========================================================
    # LOAD
    # ========================================================

    def _load(
        self
    ) -> List[Dict]:

        with open(
            self.queue_file,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(
                file
            )

    # ========================================================
    # SAVE
    # ========================================================

    def _save(
        self,
        data: List[Dict]
    ):

        with open(
            self.queue_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                indent=4
            )

    # ========================================================
    # STORE
    # ========================================================

    def store(
        self,
        message: Dict
    ):

        queue = self._load()

        queue.append(
            message
        )

        self._save(
            queue
        )

    # ========================================================
    # RETRIEVE
    # ========================================================

    def retrieve_all(
        self
    ) -> List[Dict]:

        return self._load()

    # ========================================================
    # REMOVE MESSAGE
    # ========================================================

    def remove(
        self,
        message: Dict
    ):

        queue = self._load()

        if message in queue:

            queue.remove(
                message
            )

            self._save(
                queue
            )

    # ========================================================
    # CLEAR
    # ========================================================

    def clear(
        self
    ):

        self._save(
            []
        )

    # ========================================================
    # COUNT
    # ========================================================

    def count(
        self
    ) -> int:

        return len(
            self._load()
        )