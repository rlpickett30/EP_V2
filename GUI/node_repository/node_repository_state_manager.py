# ============================================================
# node_repository_state_manager.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Store current node state
#   - Update node state
#   - Retrieve node state
#
# Does NOT:
#   - Store event history
#   - Register nodes
#   - Publish events
#   - Make routing decisions
#
# ============================================================

import json

from pathlib import Path


class NodeRepositoryStateManager:

    def __init__(
        self,
        state_file: str
    ):

        self.state_file = Path(
            state_file
        )

        self.state_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if not self.state_file.exists():

            self.state_file.write_text(
                "{}",
                encoding="utf-8"
            )

    # ========================================================
    # LOAD
    # ========================================================

    def _load(self) -> dict:

        with open(
            self.state_file,
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
        state_data: dict
    ):

        with open(
            self.state_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                state_data,
                file,
                indent=4
            )

    # ========================================================
    # NODE EXISTS
    # ========================================================

    def node_exists(
        self,
        node_id: str
    ) -> bool:

        state_data = self._load()

        return node_id in state_data

    # ========================================================
    # INITIALIZE NODE
    # ========================================================

    def initialize_node(
        self,
        node_id: str
    ):

        state_data = self._load()

        if node_id not in state_data:

            state_data[node_id] = {

                "sht45_online": False,
                
                "dps310_online": False,

                "enviro_online": False,

                "microphone_online": False,

                "birdnet_online": False,

                "network_online": False,

                "gps_lock": False,

                "gps_locked": False,

                "pps_lock": False,

                "pps_locked": False,

                "rtk_online": False,

                "tdoa_capable": False,

                "gps_coord": None,

                "last_network_update": None,

                "last_update": None
            }

            self._save(
                state_data
            )

    # ========================================================
    # UPDATE STATE
    # ========================================================

    def update_state(
        self,
        node_id: str,
        updates: dict
    ) -> bool:

        state_data = self._load()

        if node_id not in state_data:

            return False

        state_data[node_id].update(
            updates
        )

        self._save(
            state_data
        )

        return True

    # ========================================================
    # GET NODE STATE
    # ========================================================

    def get_node_state(
        self,
        node_id: str
    ) -> dict:

        state_data = self._load()

        return state_data.get(
            node_id,
            {}
        )

    # ========================================================
    # GET ALL STATES
    # ========================================================

    def get_all_states(
        self
    ) -> dict:

        return self._load()

    # ========================================================
    # REMOVE NODE
    # ========================================================

    def remove_node(
        self,
        node_id: str
    ) -> bool:

        state_data = self._load()

        if node_id not in state_data:

            return False

        del state_data[node_id]

        self._save(
            state_data
        )

        return True

    # ========================================================
    # COUNT
    # ========================================================

    def count(
        self
    ) -> int:

        return len(
            self._load()
        )
