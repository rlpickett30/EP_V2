# ============================================================
# TDOA_state_manager.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Purpose:
#   Maintain current TDOA node-state and system capability truth.
#
# Owns:
#   - Full TDOA readiness state for known nodes
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
from typing import Dict, Optional, Tuple


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

        # Full accepted NODE_TDOA_STATE history by node.
        # This includes nodes that are not currently ready.
        self.node_tdoa_states: Dict[str, dict] = {}

        # Ready-only view used by candidate filtering.
        self.tdoa_capable_nodes: Dict[str, dict] = {}

        self.last_candidate_ready_state = False

    # ========================================================
    # PUBLIC EVENT INPUT
    # ========================================================

    def handle_node_tdoa_state(
        self,
        event: dict
    ) -> Optional[dict]:
        """
        Accept a registry-owned NODE_TDOA_STATE update.

        NODE_TDOA_STATE is treated as a per-node state report, not as a
        guaranteed capable-node announcement. Ready nodes are added to the
        capable-node set. Not-ready nodes are preserved in the full state
        table and removed from the capable-node set if necessary.

        Expected inbound event:
            {
                "event_type": "NODE_TDOA_STATE",
                "source": "platform_registry",
                "payload": {
                    "node_id": "...",
                    "tdoa_state": {...}
                }
            }
        """

        payload, tdoa_state = self._extract_payload_and_state(
            event
        )

        node_id = self._extract_node_id(
            event=event,
            payload=payload,
            tdoa_state=tdoa_state
        )

        if node_id is None:
            logging.warning(
                "TDOA state rejected NODE_TDOA_STATE event: missing node_id."
            )
            return None

        normalized_state = self._build_normalized_node_state(
            node_id=node_id,
            event=event,
            payload=payload,
            tdoa_state=tdoa_state
        )

        self.node_tdoa_states[node_id] = normalized_state

        if normalized_state.get("tdoa_ready"):
            self.tdoa_capable_nodes[node_id] = normalized_state
        else:
            self.tdoa_capable_nodes.pop(
                node_id,
                None
            )

        logging.info(
            "[TDOA_STATE] Accepted NODE_TDOA_STATE for "
            f"{node_id}: ready={normalized_state.get('tdoa_ready')}"
        )

        return self._build_capability_update()

    def handle_node_tdoa_capable(
        self,
        event: dict
    ) -> Optional[dict]:
        """
        Backward-compatible alias.

        Older dispatcher language treated NODE_TDOA_STATE as a capable-node
        event. The canonical handler now treats it as full node state.
        """

        return self.handle_node_tdoa_state(
            event
        )

    def handle_node_tdoa_lost(
        self,
        event: dict
    ) -> Optional[dict]:
        """
        Remove a node from the TDOA-capable set.

        This does not erase the node from the full state table. It marks the
        node as not ready and preserves the last known state for observability.
        """

        payload = event.get(
            "payload",
            {}
        ) or {}

        node_id = (
            event.get("node_id")
            or payload.get("node_id")
        )

        if node_id is None:
            logging.warning(
                "TDOA state rejected node capability lost event: "
                "missing node_id."
            )
            return None

        self.tdoa_capable_nodes.pop(
            node_id,
            None
        )

        if node_id in self.node_tdoa_states:
            self.node_tdoa_states[node_id]["tdoa_ready"] = False
            self.node_tdoa_states[node_id]["tdoa_capable"] = False
            self.node_tdoa_states[node_id]["last_loss_event"] = event

        return self._build_capability_update()

    # ========================================================
    # PUBLIC SNAPSHOT API
    # ========================================================

    def get_node_tdoa_states(
        self
    ) -> Dict[str, dict]:
        """
        Return full current TDOA node-state dictionary.
        """

        return dict(self.node_tdoa_states)

    def get_node_tdoa_state_ids(
        self
    ) -> list:
        """
        Return all known TDOA node IDs.
        """

        return list(self.node_tdoa_states.keys())

    def get_node_tdoa_state_count(
        self
    ) -> int:
        """
        Return current number of nodes known to the TDOA subsystem.
        """

        return len(self.node_tdoa_states)

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
            "known_node_count": self.get_node_tdoa_state_count(),
            "known_node_ids": self.get_node_tdoa_state_ids(),
            "node_tdoa_states": self.get_node_tdoa_states(),
            "tdoa_capable_node_count": self.get_tdoa_capable_count(),
            "min_tdoa_capable_nodes": self.min_tdoa_capable_nodes,
            "candidate_filter_allowed": self.candidate_filter_allowed(),
            "tdoa_capable_node_ids": self.get_tdoa_capable_node_ids(),
            "tdoa_capable_nodes": self.get_tdoa_capable_nodes()
        }

    # ========================================================
    # INBOUND NORMALIZATION HELPERS
    # ========================================================

    def _extract_payload_and_state(
        self,
        event: dict
    ) -> Tuple[dict, dict]:
        """
        Extract the registry payload and embedded TDOA state.
        """

        payload = event.get(
            "payload",
            {}
        ) or {}

        if not isinstance(payload, dict):
            payload = {
                "value": payload
            }

        nested_payload = payload.get(
            "payload"
        )

        if (
            isinstance(nested_payload, dict)
            and "tdoa_state" not in payload
            and "node_id" not in payload
        ):
            payload = nested_payload

        tdoa_state = payload.get(
            "tdoa_state"
        )

        if not isinstance(tdoa_state, dict):
            # Some senders may publish the TDOA state directly as payload.
            tdoa_state = payload

        return payload, tdoa_state

    def _extract_node_id(
        self,
        event: dict,
        payload: dict,
        tdoa_state: dict
    ) -> Optional[str]:
        """
        Extract node_id from all supported NODE_TDOA_STATE shapes.
        """

        return (
            payload.get("node_id")
            or tdoa_state.get("node_id")
            or event.get("node_id")
        )

    def _build_normalized_node_state(
        self,
        node_id: str,
        event: dict,
        payload: dict,
        tdoa_state: dict
    ) -> dict:
        """
        Build the TDOA-owned node-state record.
        """

        tdoa_ready = self._extract_tdoa_ready(
            tdoa_state=tdoa_state,
            payload=payload
        )

        return {
            "node_id": node_id,
            "node_name": (
                tdoa_state.get("node_name")
                or payload.get("node_name")
                or node_id
            ),
            "node_role": (
                tdoa_state.get("node_role")
                or payload.get("node_role")
            ),
            "tdoa_capable": tdoa_ready,
            "tdoa_ready": tdoa_ready,
            "position": (
                tdoa_state.get("position")
                or payload.get("position")
            ),
            "checks": (
                tdoa_state.get("checks")
                or payload.get("checks")
                or {}
            ),
            "last_update": (
                tdoa_state.get("timestamp_utc")
                or payload.get("timestamp_utc")
                or payload.get("timestamp")
                or event.get("timestamp")
            ),
            "source": event.get("source"),
            "source_event_type": event.get("event_type"),
            "source_event": event
        }

    def _extract_tdoa_ready(
        self,
        tdoa_state: dict,
        payload: dict
    ) -> bool:
        """
        Extract readiness from supported field names.
        """

        for key in (
            "tdoa_ready",
            "tdoa_capable",
            "ready"
        ):
            if key in tdoa_state:
                return bool(tdoa_state.get(key))

            if key in payload:
                return bool(payload.get(key))

        return False

    # ========================================================
    # INTERNAL STATE EVENT BUILDER
    # ========================================================

    def _build_capability_update(
        self
    ) -> Optional[dict]:
        """
        Build a system-level capability update for the dispatcher.

        If publish_capability_changes_only is enabled, this only returns a
        package when the system crosses into or out of candidate-ready status.
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
            "tdoa_capable_nodes": self.get_tdoa_capable_nodes(),
            "known_node_count": self.get_node_tdoa_state_count(),
            "known_node_ids": self.get_node_tdoa_state_ids()
        }
