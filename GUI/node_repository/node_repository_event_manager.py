# ============================================================
# node_repository_event_manager.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Store recent node events
#   - Retrieve node event history
#   - Retrieve recent events
#   - Provide event counts
#
# Does NOT:
#   - Register nodes
#   - Store current node state
#   - Publish events
#   - Make routing decisions
#   - Act as permanent archive
#
# ============================================================

import json

from pathlib import Path


class NodeRepositoryEventManager:

    def __init__(
        self,
        event_file: str,
        max_events_per_node: int = 1000
    ):

        self.event_file = Path(
            event_file
        )

        self.max_events_per_node = (
            max_events_per_node
        )

        self.event_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if not self.event_file.exists():

            self.event_file.write_text(
                "{}",
                encoding="utf-8"
            )

    # ========================================================
    # LOAD
    # ========================================================

    def _load(self) -> dict:

        with open(
            self.event_file,
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
        event_data: dict
    ):

        with open(
            self.event_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                event_data,
                file,
                indent=4
            )

    # ========================================================
    # INITIALIZE NODE
    # ========================================================

    def initialize_node(
        self,
        node_id: str
    ):

        event_data = self._load()

        if node_id not in event_data:

            event_data[node_id] = []

            self._save(
                event_data
            )

    # ========================================================
    # STORE EVENT
    # ========================================================

    def store_event(
        self,
        node_id: str,
        event: dict
    ) -> bool:

        if not node_id:

            return False

        event_data = self._load()

        if node_id not in event_data:

            event_data[node_id] = []

        event_data[node_id].append(
            event
        )

        if len(event_data[node_id]) > self.max_events_per_node:

            event_data[node_id] = event_data[node_id][
                -self.max_events_per_node:
            ]

        self._save(
            event_data
        )

        return True

    # ========================================================
    # GET NODE EVENTS
    # ========================================================

    def get_node_events(
        self,
        node_id: str
    ) -> list:

        event_data = self._load()

        return event_data.get(
            node_id,
            []
        )

    # ========================================================
    # GET RECENT NODE EVENTS
    # ========================================================

    def get_recent_node_events(
        self,
        node_id: str,
        limit: int = 10
    ) -> list:

        events = self.get_node_events(
            node_id
        )

        return events[
            -limit:
        ]

    # ========================================================
    # GET ALL EVENTS
    # ========================================================

    def get_all_events(self) -> dict:

        return self._load()

    # ========================================================
    # CLEAR NODE EVENTS
    # ========================================================

    def clear_node_events(
        self,
        node_id: str
    ) -> bool:

        event_data = self._load()

        if node_id not in event_data:

            return False

        event_data[node_id] = []

        self._save(
            event_data
        )

        return True

    # ========================================================
    # REMOVE NODE
    # ========================================================

    def remove_node(
        self,
        node_id: str
    ) -> bool:

        event_data = self._load()

        if node_id not in event_data:

            return False

        del event_data[node_id]

        self._save(
            event_data
        )

        return True

    # ========================================================
    # CLEAR ALL EVENTS
    # ========================================================

    def clear_all_events(self):

        self._save(
            {}
        )

    # ========================================================
    # COUNT NODE EVENTS
    # ========================================================

    def count_node_events(
        self,
        node_id: str
    ) -> int:

        return len(
            self.get_node_events(
                node_id
            )
        )

    # ========================================================
    # COUNT ALL EVENTS
    # ========================================================

    def count_all_events(self) -> int:

        event_data = self._load()

        return sum(
            len(events)
            for events in event_data.values()
        )