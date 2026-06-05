# ============================================================
# node_repository_registry_manager.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Register nodes
#   - Track known nodes
#   - Update node metadata
#   - Retrieve node information
#
# Does NOT:
#   - Store node state
#   - Store event history
#   - Publish events
#   - Make routing decisions
#
# ============================================================

import json

from pathlib import Path


class NodeRepositoryRegistryManager:

    def __init__(
        self,
        registry_file: str
    ):

        self.registry_file = Path(
            registry_file
        )

        self.registry_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if not self.registry_file.exists():

            self.registry_file.write_text(
                "{}",
                encoding="utf-8"
            )

    # ========================================================
    # LOAD
    # ========================================================

    def _load(self) -> dict:

        with open(
            self.registry_file,
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
        registry: dict
    ):

        with open(
            self.registry_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                registry,
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

        registry = self._load()

        return node_id in registry

    # ========================================================
    # REGISTER NODE
    # ========================================================

    def register_node(
        self,
        node_info: dict
    ) -> bool:

        node_id = node_info.get(
            "node_id"
        )

        if not node_id:

            return False

        registry = self._load()

        if node_id in registry:

            return False

        registry[node_id] = node_info

        self._save(
            registry
        )

        return True

    # ========================================================
    # GET NODE
    # ========================================================

    def get_node(
        self,
        node_id: str
    ) -> dict:

        registry = self._load()

        return registry.get(
            node_id,
            {}
        )

    # ========================================================
    # GET ALL NODES
    # ========================================================

    def get_all_nodes(
        self
    ) -> dict:

        return self._load()

    # ========================================================
    # UPDATE NODE
    # ========================================================

    def update_node(
        self,
        node_id: str,
        updates: dict
    ) -> bool:

        registry = self._load()

        if node_id not in registry:

            return False

        registry[node_id].update(
            updates
        )

        self._save(
            registry
        )

        return True

    # ========================================================
    # REMOVE NODE
    # ========================================================

    def remove_node(
        self,
        node_id: str
    ) -> bool:

        registry = self._load()

        if node_id not in registry:

            return False

        del registry[node_id]

        self._save(
            registry
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