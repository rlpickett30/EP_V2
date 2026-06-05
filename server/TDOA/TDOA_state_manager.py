# ============================================================
# TDOA_state_manager.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Purpose:
#   Maintains current TDOA capability truth.
#
# Owns:
#   - Which nodes are currently TDOA-capable
#   - Current capable node count
#   - Whether TDOA candidate filtering is allowed
#
# Does NOT:
#   - Match avis_lite events
#   - Call TDOA_manager.py
#   - Solve TDOA
#   - Publish directly to the event bus
#
# ============================================================

import logging
from typing import Dict, Optional


class TDOAStateManager:

    def __init__(self, config: dict):

        state_config = config.get(
            "tdoa_state_manager",
            {}
        )

        self.min_tdoa_capable_nodes = state_config.get(
            "min_tdoa_capable_nodes",
            4
        )

        self.publish_capability_changes_only = state_config.get(
            "publish_capability_changes_only",
            True
        )

        self.tdoa_capable_nodes: Dict[str, dict] = {}

        self.last_candidate_ready_state = False

    # ========================================================
    # PUBLIC EVENT INPUT
    # ========================================================

    def handle_node_tdoa_capable(
        self,
        event: dict
    ) -> Optional[dict]:
        """
        Register or refresh a node as TDOA-capable.

        Expected event shape:
            {
                "event_type": "node_tdoa_capable",
                "node_id": "node_01",
                "timestamp": "...",
                "payload": {...}
            }
        """

        node_id = event.get("node_id")

        if node_id is None:
            logging.warning(
                "TDOA state rejected node_tdoa_capable event: "
                "missing node_id."
            )
            return None

        self.tdoa_capable_nodes[node_id] = {
            "node_id": node_id,
            "tdoa_capable": True,
            "last_update": event.get("timestamp"),
            "source_event": event
        }

        return self._build_capability_update()

    def handle_node_tdoa_lost(
        self,
        event: dict
    ) -> Optional[dict]:
        """
        Remove a node from the TDOA-capable set.

        Expected event shape:
            {
                "event_type": "node_tdoa_lost",
                "node_id": "node_01",
                "timestamp": "...",
                "payload": {...}
            }
        """

        node_id = event.get("node_id")

        if node_id is None:
            logging.warning(
                "TDOA state rejected node_tdoa_lost event: "
                "missing node_id."
            )
            return None

        if node_id in self.tdoa_capable_nodes:
            del self.tdoa_capable_nodes[node_id]

        return self._build_capability_update()

    # ========================================================
    # PUBLIC SNAPSHOT API
    # ========================================================

    def get_tdoa_capable_nodes(
        self
    ) -> Dict[str, dict]:
        """
        Return current TDOA-capable node dictionary.
        """

        return dict(self.tdoa_capable_nodes)

    def get_tdoa_capable_node_ids(
        self
    ) -> list:
        """
        Return current TDOA-capable node IDs.
        """

        return list(self.tdoa_capable_nodes.keys())

    def get_tdoa_capable_count(
        self
    ) -> int:
        """
        Return current number of TDOA-capable nodes.
        """

        return len(self.tdoa_capable_nodes)

    def candidate_filter_allowed(
        self
    ) -> bool:
        """
        Return True when enough nodes are available for candidate filtering.
        """

        return (
            self.get_tdoa_capable_count()
            >= self.min_tdoa_capable_nodes
        )

    def get_state_snapshot(
        self
    ) -> dict:
        """
        Return full current TDOA state snapshot.
        """

        return {
            "tdoa_capable_node_count": self.get_tdoa_capable_count(),
            "min_tdoa_capable_nodes": self.min_tdoa_capable_nodes,
            "candidate_filter_allowed": self.candidate_filter_allowed(),
            "tdoa_capable_node_ids": self.get_tdoa_capable_node_ids(),
            "tdoa_capable_nodes": self.get_tdoa_capable_nodes()
        }

    # ========================================================
    # INTERNAL STATE EVENT BUILDER
    # ========================================================

    def _build_capability_update(
        self
    ) -> Optional[dict]:
        """
        Build a state update for the dispatcher.

        If publish_capability_changes_only is enabled, this only returns
        a package when the system crosses into or out of candidate-ready
        status.
        """

        candidate_ready = self.candidate_filter_allowed()

        if self.publish_capability_changes_only:

            if candidate_ready == self.last_candidate_ready_state:
                return None

        self.last_candidate_ready_state = candidate_ready

        return {
            "event_type": "tdoa_capability_update",
            "candidate_filter_allowed": candidate_ready,
            "tdoa_capable_node_count": self.get_tdoa_capable_count(),
            "min_tdoa_capable_nodes": self.min_tdoa_capable_nodes,
            "tdoa_capable_node_ids": self.get_tdoa_capable_node_ids(),
            "tdoa_capable_nodes": self.get_tdoa_capable_nodes()
        }
