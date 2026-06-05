# ============================================================
# platform_registry_mode_manager.py
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
#   Maintain desired platform/node behavior modes and return
#   server-approved mode command packages to the dispatcher.
#
# Expected config source:
#   platform_registry_config.json
#
# Expected config section:
#   config["platform_registry"]["mode"]
#
# Does:
#   - Validate known mode requests
#   - Maintain desired mode state per node
#   - Convert accepted mode requests into SERVER mode packages
#   - Return mode snapshots for dispatcher publication
#
# Does NOT:
#   - Publish events directly
#   - Send commands directly to nodes
#   - Register nodes or GUI clients
#   - Maintain sensor/GPS/PPS state
#   - Decide network delivery method
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
# PLATFORM REGISTRY MODE MANAGER
# ============================================================

class PlatformRegistryModeManager:
    """
    Maintains desired node/platform mode state.

    This manager receives already-accepted mode events from the
    Platform Registry Dispatcher and returns server-approved mode
    command packages.

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

        self.mode_config = platform_config.get(
            "mode",
            {}
        )

        self.mode_event_map = platform_config.get(
            "mode_event_map",
            {}
        )

        self.mode_defaults = platform_config.get(
            "mode_defaults",
            {}
        )

        self.allowed_modes = platform_config.get(
            "allowed_modes",
            {}
        )

        self.debug = platform_config.get(
            "debug",
            False
        )

        self.publish_only_on_change = self.mode_config.get(
            "publish_only_on_change",
            True
        )

        self.include_previous_value = self.mode_config.get(
            "include_previous_value",
            True
        )

        self.include_mode_snapshot = self.mode_config.get(
            "include_mode_snapshot",
            True
        )

        self.default_target_type = self.mode_config.get(
            "default_target_type",
            "node"
        )

        self.logger = logging.getLogger(self.__class__.__name__)

        self.node_modes = {}

    # ========================================================
    # PUBLIC API
    # ========================================================

    def handle_mode_event(self, event_name, payload):
        """
        Update desired node mode and return a server-approved
        mode package.

        Expected payload:
            node_id
            destination optional
            requested_by optional
            timestamp_utc optional

        Returns:
            result dictionary
        """

        result = self._base_result()

        node_id = payload.get("node_id")

        if not node_id:
            return self._fail(
                result,
                "Mode update rejected. Missing node_id.",
                event_name,
                payload
            )

        server_event_key = self.mode_event_map.get(event_name)

        if server_event_key is None:
            return self._fail(
                result,
                f"Mode update rejected. Unknown mode event: {event_name}",
                event_name,
                payload
            )

        validation = self._validate_mode_event(event_name)

        if not validation["success"]:
            return self._fail(
                result,
                validation["reason"],
                event_name,
                payload
            )

        self._ensure_node_mode(node_id)

        previous_snapshot = deepcopy(self.node_modes[node_id])

        update_result = self._apply_mode_update(
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

        current_snapshot = deepcopy(self.node_modes[node_id])
        changed = previous_snapshot != current_snapshot

        if self.publish_only_on_change and not changed:
            result["success"] = True
            result["publish"] = False
            result["reason"] = "mode_unchanged"
            result["node_id"] = node_id
            result["server_event_key"] = server_event_key
            result["mode_snapshot"] = current_snapshot
            return result

        server_payload = self._build_server_mode_payload(
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
        result["mode_snapshot"] = current_snapshot

        return result

    def get_node_mode(self, node_id):
        """
        Return desired mode state for one node.
        """

        mode = self.node_modes.get(node_id)

        if mode is None:
            return None

        return deepcopy(mode)

    def get_platform_mode_snapshot(self):
        """
        Return desired mode state for all known nodes.
        """

        return {
            "generated_at_utc": self._utc_now(),
            "nodes": deepcopy(self.node_modes)
        }

    # ========================================================
    # MODE UPDATE LOGIC
    # ========================================================

    def _apply_mode_update(self, node_id, event_name, payload):
        """
        Apply one accepted mode request to desired node mode.
        """

        result = {
            "success": True,
            "reason": None
        }

        mode = self.node_modes[node_id]
        now_utc = payload.get("timestamp_utc", self._utc_now())

        mode["last_mode_update_utc"] = now_utc
        mode["last_mode_event"] = event_name
        mode["last_requested_by"] = payload.get(
            "requested_by",
            "unknown"
        )

        if event_name == "energy_onset":
            mode["onset_method"] = "energy_onset"

        elif event_name == "pattern_onset":
            mode["onset_method"] = "pattern_onset"

        elif event_name == "energy_offset":
            mode["offset_method"] = "energy_offset"

        elif event_name == "pattern_offset":
            mode["offset_method"] = "pattern_offset"

        elif event_name == "onset_feature":
            mode["feature_mode"] = "onset_feature"

        elif event_name == "amp_feature":
            mode["feature_mode"] = "amp_feature"

        elif event_name == "enable_wifi":
            mode["wifi_enabled"] = True

        elif event_name == "disable_wifi":
            mode["wifi_enabled"] = False

        elif event_name == "enable_lora":
            mode["lora_enabled"] = True

        elif event_name == "disable_lora":
            mode["lora_enabled"] = False

        else:
            result["success"] = False
            result["reason"] = f"Unhandled mode event: {event_name}"

        return result

    def _validate_mode_event(self, event_name):
        """
        Validate event against allowed mode groups.
        """

        if event_name in self.allowed_modes.get("onset_method", []):
            return {
                "success": True,
                "mode_group": "onset_method",
                "reason": None
            }

        if event_name in self.allowed_modes.get("offset_method", []):
            return {
                "success": True,
                "mode_group": "offset_method",
                "reason": None
            }

        if event_name in self.allowed_modes.get("feature_mode", []):
            return {
                "success": True,
                "mode_group": "feature_mode",
                "reason": None
            }

        if event_name in self.allowed_modes.get("wifi", []):
            return {
                "success": True,
                "mode_group": "wifi",
                "reason": None
            }

        if event_name in self.allowed_modes.get("lora", []):
            return {
                "success": True,
                "mode_group": "lora",
                "reason": None
            }

        return {
            "success": False,
            "mode_group": None,
            "reason": f"Mode event not allowed: {event_name}"
        }

    # ========================================================
    # PACKAGE BUILDING
    # ========================================================

    def _build_server_mode_payload(
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
        Build server-approved mode payload.
        """

        package = {
            "server_event_key": server_event_key,
            "incoming_event": event_name,
            "target_type": self.default_target_type,
            "node_id": node_id,
            "changed": changed,
            "timestamp_utc": self._utc_now(),
            "mode": self._get_mode_value_for_event(
                event_name,
                current_snapshot
            )
        }

        destination = incoming_payload.get("destination")

        if destination is not None:
            package["destination"] = destination

        requested_by = incoming_payload.get("requested_by")

        if requested_by is not None:
            package["requested_by"] = requested_by

        if self.include_previous_value:
            package["previous_mode"] = self._get_mode_value_for_event(
                event_name,
                previous_snapshot
            )

        if self.include_mode_snapshot:
            package["node_mode_snapshot"] = deepcopy(current_snapshot)

        if self.debug:
            package["debug"] = {
                "incoming_payload": deepcopy(incoming_payload)
            }

        return package

    def _get_mode_value_for_event(self, event_name, mode):
        """
        Return relevant mode value for a given event.
        """

        if event_name in ["energy_onset", "pattern_onset"]:
            return {
                "onset_method": mode.get("onset_method")
            }

        if event_name in ["energy_offset", "pattern_offset"]:
            return {
                "offset_method": mode.get("offset_method")
            }

        if event_name in ["onset_feature", "amp_feature"]:
            return {
                "feature_mode": mode.get("feature_mode")
            }

        if event_name in ["enable_wifi", "disable_wifi"]:
            return {
                "wifi_enabled": mode.get("wifi_enabled")
            }

        if event_name in ["enable_lora", "disable_lora"]:
            return {
                "lora_enabled": mode.get("lora_enabled")
            }

        return {}

    # ========================================================
    # NODE MODE SETUP
    # ========================================================

    def _ensure_node_mode(self, node_id):
        """
        Create a node mode record if it does not exist.
        """

        if node_id in self.node_modes:
            return

        self.node_modes[node_id] = {
            "node_id": node_id,
            "created_at_utc": self._utc_now(),
            "last_mode_update_utc": None,
            "last_mode_event": None,
            "last_requested_by": None,
            "onset_method": self.mode_defaults.get(
                "onset_method",
                "energy_onset"
            ),
            "offset_method": self.mode_defaults.get(
                "offset_method",
                "energy_offset"
            ),
            "feature_mode": self.mode_defaults.get(
                "feature_mode",
                "onset_feature"
            ),
            "wifi_enabled": self.mode_defaults.get(
                "wifi_enabled",
                True
            ),
            "lora_enabled": self.mode_defaults.get(
                "lora_enabled",
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
            "mode_snapshot": None,
            "reason": None,
            "errors": [],
            "debug": {}
        }

    def _fail(self, result, message, event_name, payload):
        """
        Return failed mode-manager result.
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