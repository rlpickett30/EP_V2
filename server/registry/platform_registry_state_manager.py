# ============================================================
# platform_registry_state_manager.py
#
# EnviroPulse V_2.0
#
# Subsystem:
#   Platform Registry
#
# Role:
#   State Manager
#
# Purpose:
#   Maintain canonical platform state for known nodes and return
#   server-approved state event packages to the dispatcher.
#
# Expected config source:
#   platform_registry_config.json
#
# Expected config section:
#   config["platform_registry"]["state"]
#
# Does:
#   - Maintain current node state
#   - Convert accepted node state reports into server state packages
#   - Track previous and current values
#   - Return platform state snapshots
#
# Does NOT:
#   - Publish events directly
#   - Validate node identity
#   - Register nodes or GUI clients
#   - Send updates to GUI
#   - Send commands to field nodes
#   - Solve TDOA
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
# PLATFORM REGISTRY STATE MANAGER
# ============================================================

class PlatformRegistryStateManager:
    """
    Maintains canonical platform state.

    This manager receives already-accepted state events from the
    Platform Registry Dispatcher and returns server-approved state
    event packages.

    The dispatcher publishes the returned package.
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

        self.state_config = platform_config.get(
            "state",
            {}
        )

        self.state_event_map = platform_config.get(
            "state_event_map",
            {}
        )

        self.state_defaults = platform_config.get(
            "state_defaults",
            {}
        )

        self.debug = platform_config.get(
            "debug",
            False
        )

        self.publish_only_on_change = self.state_config.get(
            "publish_only_on_change",
            True
        )

        self.include_previous_value = self.state_config.get(
            "include_previous_value",
            True
        )

        self.include_state_snapshot = self.state_config.get(
            "include_state_snapshot",
            True
        )

        self.default_source_type = self.state_config.get(
            "default_source_type",
            "node"
        )

        self.logger = logging.getLogger(self.__class__.__name__)

        self.node_states = {}

    # ========================================================
    # PUBLIC API
    # ========================================================

    def handle_state_event(self, event_name, payload):
        """
        Update node state and return a server-approved state event.

        Expected payload:
            node_id
            event_type optional
            value optional
            source optional
            timestamp_utc optional

        Returns:
            result dictionary
        """

        result = self._base_result()

        node_id = payload.get("node_id")

        if not node_id:
            return self._fail(
                result,
                "State update rejected. Missing node_id.",
                event_name,
                payload
            )

        server_event_key = self.state_event_map.get(event_name)

        if server_event_key is None:
            return self._fail(
                result,
                f"State update rejected. Unknown state event: {event_name}",
                event_name,
                payload
            )

        self._ensure_node_state(node_id)

        previous_snapshot = deepcopy(self.node_states[node_id])

        update_result = self._apply_state_update(
            node_id=node_id,
            event_name=event_name,
            payload=payload
        )

        if not update_result["success"]:
            return self._fail(
                result,
                update_result["reason"],
                event_name,
                payload
            )

        current_snapshot = deepcopy(self.node_states[node_id])

        changed = previous_snapshot != current_snapshot

        if self.publish_only_on_change and not changed:
            result["success"] = True
            result["publish"] = False
            result["reason"] = "state_unchanged"
            result["node_id"] = node_id
            result["server_event_key"] = server_event_key
            result["state_snapshot"] = current_snapshot
            return result

        server_payload = self._build_server_state_payload(
            node_id=node_id,
            event_name=event_name,
            server_event_key=server_event_key,
            incoming_payload=payload,
            previous_snapshot=previous_snapshot,
            current_snapshot=current_snapshot,
            changed=changed
        )

        result["success"] = True
        result["publish"] = True
        result["node_id"] = node_id
        result["incoming_event"] = event_name
        result["server_event_key"] = server_event_key
        result["server_payload"] = server_payload
        result["state_snapshot"] = current_snapshot

        return result

    def get_node_state(self, node_id):
        """
        Return current state for one node.
        """

        state = self.node_states.get(node_id)

        if state is None:
            return None

        return deepcopy(state)

    def get_platform_state_snapshot(self):
        """
        Return current state for all known nodes.
        """

        return {
            "generated_at_utc": self._utc_now(),
            "nodes": deepcopy(self.node_states)
        }

    # ========================================================
    # STATE UPDATE LOGIC
    # ========================================================

    def _apply_state_update(self, node_id, event_name, payload):
        """
        Apply one accepted state event to canonical node state.
        """

        result = {
            "success": True,
            "reason": None
        }

        state = self.node_states[node_id]
        now_utc = payload.get("timestamp_utc", self._utc_now())

        state["last_state_update_utc"] = now_utc
        state["last_state_event"] = event_name

        if event_name == "bmp390_online":
            state["bmp390_online"] = True

        elif event_name == "bmp390_offline":
            state["bmp390_online"] = False

        elif event_name == "sht45_online":
            state["sht45_online"] = True

        elif event_name == "sht45_offline":
            state["sht45_online"] = False

        elif event_name == "pps_lock":
            state["pps_locked"] = True

        elif event_name == "pps_lost":
            state["pps_locked"] = False

        elif event_name == "gps_lock":
            state["gps_locked"] = True

        elif event_name == "gps_lost":
            state["gps_locked"] = False
            state["gps_coord"] = None

        elif event_name == "gps_coord":
            coord = payload.get("gps_coord")

            if coord is None:
                coord = {
                    "lat": payload.get("lat"),
                    "lon": payload.get("lon"),
                    "alt": payload.get("alt")
                }

            state["gps_coord"] = coord

        elif event_name == "rtk_online":
            state["rtk_online"] = True

        else:
            result["success"] = False
            result["reason"] = f"Unhandled state event: {event_name}"

        state["tdoa_capable"] = self._calculate_tdoa_capable(state)

        return result

    def _calculate_tdoa_capable(self, state):
        """
        Return True if this node currently has minimum TDOA state.
        """

        return (
            state.get("pps_locked", False)
            and state.get("gps_locked", False)
            and state.get("gps_coord") is not None
        )

    # ========================================================
    # PACKAGE BUILDING
    # ========================================================

    def _build_server_state_payload(
        self,
        node_id,
        event_name,
        server_event_key,
        incoming_payload,
        previous_snapshot,
        current_snapshot,
        changed
    ):
        """
        Build server-approved state payload.
        """

        package = {
            "server_event_key": server_event_key,
            "incoming_event": event_name,
            "source_type": self.default_source_type,
            "node_id": node_id,
            "changed": changed,
            "timestamp_utc": self._utc_now(),
            "state": self._get_state_value_for_event(
                event_name,
                current_snapshot
            )
        }

        destination = incoming_payload.get("destination")

        if destination is not None:
            package["destination"] = destination

        if self.include_previous_value:
            package["previous_state"] = self._get_state_value_for_event(
                event_name,
                previous_snapshot
            )

        if self.include_state_snapshot:
            package["node_state_snapshot"] = deepcopy(current_snapshot)

        if self.debug:
            package["debug"] = {
                "incoming_payload": deepcopy(incoming_payload)
            }

        return package

    def _get_state_value_for_event(self, event_name, state):
        """
        Return the relevant state value for a given event.
        """

        if event_name in ["bmp390_online", "bmp390_offline"]:
            return {
                "bmp390_online": state.get("bmp390_online")
            }

        if event_name in ["sht45_online", "sht45_offline"]:
            return {
                "sht45_online": state.get("sht45_online")
            }

        if event_name in ["pps_lock", "pps_lost"]:
            return {
                "pps_locked": state.get("pps_locked")
            }

        if event_name in ["gps_lock", "gps_lost"]:
            return {
                "gps_locked": state.get("gps_locked")
            }

        if event_name == "gps_coord":
            return {
                "gps_coord": state.get("gps_coord")
            }

        if event_name == "rtk_online":
            return {
                "rtk_online": state.get("rtk_online")
            }

        return {}

    # ========================================================
    # NODE STATE SETUP
    # ========================================================

    def _ensure_node_state(self, node_id):
        """
        Create a node state record if it does not exist.
        """

        if node_id in self.node_states:
            return

        self.node_states[node_id] = {
            "node_id": node_id,
            "created_at_utc": self._utc_now(),
            "last_state_update_utc": None,
            "last_state_event": None,
            "bmp390_online": self.state_defaults.get(
                "bmp390_online",
                False
            ),
            "sht45_online": self.state_defaults.get(
                "sht45_online",
                False
            ),
            "pps_locked": self.state_defaults.get(
                "pps_locked",
                False
            ),
            "gps_locked": self.state_defaults.get(
                "gps_locked",
                False
            ),
            "gps_coord": self.state_defaults.get(
                "gps_coord",
                None
            ),
            "rtk_online": self.state_defaults.get(
                "rtk_online",
                False
            ),
            "tdoa_capable": self.state_defaults.get(
                "tdoa_capable",
                False
            )
        }

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
            "incoming_event": None,
            "server_event_key": None,
            "server_payload": None,
            "state_snapshot": None,
            "reason": None,
            "errors": [],
            "debug": {}
        }

    def _fail(self, result, message, event_name, payload):
        """
        Return failed state-manager result.
        """

        result["success"] = False
        result["publish"] = False
        result["incoming_event"] = event_name
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