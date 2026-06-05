# ============================================================
# platform_registry_TDOA_manager.py
#
# EnviroPulse V_2.0
#
# Subsystem:
#   Platform Registry
#
# Role:
#   Manager
#
# Purpose:
#   Evaluate canonical node state and determine whether a node
#   is currently eligible for TDOA calculations.
#
# Expected config source:
#   platform_registry_config.json
#
# Expected config section:
#   config["platform_registry"]["tdoa"]
#
# Does:
#   - Evaluate node TDOA capability
#   - Detect NODE_TDOA_CAPABLE transitions
#   - Detect NODE_TDOA_CAPABLE_LOST transitions
#   - Return server-approved TDOA capability packages
#
# Does NOT:
#   - Publish events directly
#   - Maintain general platform state
#   - Register nodes or GUI clients
#   - Solve TDOA
#   - Request WAV files
#   - Send commands to nodes
#
# Owner:
#   platform_registry_dispatcher.py
#
# ============================================================


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging
from copy import deepcopy
from datetime import datetime, timezone


# ============================================================
# PLATFORM REGISTRY TDOA MANAGER
# ============================================================

class PlatformRegistryTDOAManager:
    """
    Evaluates TDOA capability from canonical node state.

    This manager does not own the state itself. It receives node
    state snapshots from the dispatcher after the state manager has
    updated platform truth.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self, config=None):
        self.config = config or {}

        platform_config = self.config.get(
            "platform_registry",
            {}
        )

        self.tdoa_config = platform_config.get(
            "tdoa",
            {}
        )

        self.tdoa_event_map = platform_config.get(
            "tdoa_event_map",
            {}
        )

        self.debug = platform_config.get(
            "debug",
            False
        )

        self.enabled = self.tdoa_config.get(
            "enabled",
            True
        )

        self.publish_only_on_transition = self.tdoa_config.get(
            "publish_only_on_transition",
            True
        )

        self.minimum_requirements = self.tdoa_config.get(
            "minimum_requirements",
            {}
        )

        self.logger = logging.getLogger(self.__class__.__name__)

        self.node_tdoa_status = {}

    # ========================================================
    # PUBLIC API
    # ========================================================

    def evaluate_node_state(self, node_id, node_state):
        """
        Evaluate one node state snapshot for TDOA capability.

        Expected node_state fields:
            pps_locked
            gps_locked
            gps_coord
            rtk_online optional

        Returns:
            result dictionary
        """

        result = self._base_result()

        if not self.enabled:
            result["success"] = True
            result["publish"] = False
            result["reason"] = "tdoa_manager_disabled"
            return result

        if not node_id:
            return self._fail(
                result,
                "TDOA evaluation rejected. Missing node_id.",
                node_state
            )

        if node_state is None:
            return self._fail(
                result,
                f"TDOA evaluation rejected. Missing node state for {node_id}.",
                {}
            )

        previous_capable = self.node_tdoa_status.get(
            node_id,
            False
        )

        current_capable = self._calculate_tdoa_capable(
            node_state
        )

        self.node_tdoa_status[node_id] = current_capable

        transition = self._get_transition(
            previous_capable=previous_capable,
            current_capable=current_capable
        )

        if transition is None:
            result["success"] = True
            result["publish"] = False
            result["node_id"] = node_id
            result["tdoa_capable"] = current_capable
            result["reason"] = "tdoa_capability_unchanged"
            result["tdoa_snapshot"] = self._build_tdoa_snapshot(
                node_id=node_id,
                node_state=node_state,
                capable=current_capable
            )
            return result

        server_event_key = self.tdoa_event_map.get(transition)

        if server_event_key is None:
            return self._fail(
                result,
                f"TDOA transition has no server event mapping: {transition}",
                node_state
            )

        server_payload = self._build_server_tdoa_payload(
            node_id=node_id,
            transition=transition,
            server_event_key=server_event_key,
            previous_capable=previous_capable,
            current_capable=current_capable,
            node_state=node_state
        )

        result["success"] = True
        result["publish"] = True
        result["node_id"] = node_id
        result["tdoa_capable"] = current_capable
        result["transition"] = transition
        result["server_event_key"] = server_event_key
        result["server_payload"] = server_payload
        result["tdoa_snapshot"] = server_payload.get(
            "tdoa_snapshot"
        )

        return result

    def get_node_tdoa_status(self, node_id):
        """
        Return current TDOA capability for one node.
        """

        return self.node_tdoa_status.get(
            node_id,
            False
        )

    def get_tdoa_status_snapshot(self):
        """
        Return TDOA capability status for all evaluated nodes.
        """

        return {
            "generated_at_utc": self._utc_now(),
            "nodes": deepcopy(self.node_tdoa_status)
        }

    # ========================================================
    # TDOA CAPABILITY LOGIC
    # ========================================================

    def _calculate_tdoa_capable(self, node_state):
        """
        Calculate whether a node currently meets TDOA requirements.
        """

        require_pps_locked = self.minimum_requirements.get(
            "pps_locked",
            True
        )

        require_gps_locked = self.minimum_requirements.get(
            "gps_locked",
            True
        )

        require_gps_coord = self.minimum_requirements.get(
            "gps_coord_required",
            True
        )

        require_rtk_online = self.minimum_requirements.get(
            "rtk_online_required",
            False
        )

        if require_pps_locked and not node_state.get("pps_locked", False):
            return False

        if require_gps_locked and not node_state.get("gps_locked", False):
            return False

        if require_gps_coord and node_state.get("gps_coord") is None:
            return False

        if require_rtk_online and not node_state.get("rtk_online", False):
            return False

        return True

    def _get_transition(self, previous_capable, current_capable):
        """
        Return transition event name when capability changes.
        """

        if previous_capable is False and current_capable is True:
            return "node_tdoa_capable"

        if previous_capable is True and current_capable is False:
            return "node_tdoa_capable_lost"

        return None

    # ========================================================
    # PACKAGE BUILDING
    # ========================================================

    def _build_server_tdoa_payload(
        self,
        node_id,
        transition,
        server_event_key,
        previous_capable,
        current_capable,
        node_state
    ):
        """
        Build server-approved TDOA capability payload.
        """

        return {
            "server_event_key": server_event_key,
            "incoming_event": transition,
            "source_type": "platform_registry",
            "node_id": node_id,
            "previous_tdoa_capable": previous_capable,
            "tdoa_capable": current_capable,
            "timestamp_utc": self._utc_now(),
            "tdoa_snapshot": self._build_tdoa_snapshot(
                node_id=node_id,
                node_state=node_state,
                capable=current_capable
            )
        }

    def _build_tdoa_snapshot(self, node_id, node_state, capable):
        """
        Build compact TDOA readiness snapshot.
        """

        snapshot = {
            "node_id": node_id,
            "tdoa_capable": capable,
            "pps_locked": node_state.get("pps_locked", False),
            "gps_locked": node_state.get("gps_locked", False),
            "gps_coord": deepcopy(node_state.get("gps_coord")),
            "rtk_online": node_state.get("rtk_online", False),
            "generated_at_utc": self._utc_now()
        }

        if self.debug:
            snapshot["debug"] = {
                "full_node_state": deepcopy(node_state),
                "minimum_requirements": deepcopy(
                    self.minimum_requirements
                )
            }

        return snapshot

    # ========================================================
    # RESULT HELPERS
    # ========================================================

    def _base_result(self):
        """
        Create standard result package.
        """

        return {
            "success": False,
            "publish": False,
            "node_id": None,
            "tdoa_capable": None,
            "transition": None,
            "server_event_key": None,
            "server_payload": None,
            "tdoa_snapshot": None,
            "reason": None,
            "errors": [],
            "debug": {}
        }

    def _fail(self, result, message, payload):
        """
        Return failed TDOA-manager result.
        """

        result["success"] = False
        result["publish"] = False
        result["reason"] = message
        result["errors"].append(message)

        if self.debug:
            result["debug"]["payload"] = deepcopy(payload)

        self.logger.warning(message)

        return result

    def _utc_now(self):
        """
        Return current UTC time in ISO format.
        """

        return datetime.now(timezone.utc).isoformat()
