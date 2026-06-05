"""
node_database.py

Purpose:
    Store outbound messages when network
    delivery is unavailable.

Acts as a simple store-and-forward queue.
"""
import json
from pathlib import Path
from typing import List, Dict


class NodeDatabase:

    def __init__(self, queue_file: str):

        self.queue_file = Path(queue_file)

        self.queue_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if not self.queue_file.exists():

            self.queue_file.write_text(
                "[]",
                encoding="utf-8"
            )

    def _load(self) -> List[Dict]:

        with open(
            self.queue_file,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    def _save(self, data: List[Dict]) -> None:

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

    def store(self, message: Dict) -> None:

        queue = self._load()

        queue.append(message)

        self._save(queue)

    def retrieve_all(self) -> List[Dict]:

        return self._load()

    def clear(self) -> None:

        self._save([])

    def count(self) -> int:

        return len(self._load())