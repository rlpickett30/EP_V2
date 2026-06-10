# ============================================================
# platform_registry_registry_manager.py
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
#   Manage known platform identities.
#   This script handles node registration, GUI registration,
#   and basic trust decisions for sources entering the platform.
#
# Expected config source:
#   platform_registry_config.json
#
# Expected config section:
#   config["platform_registry"]["registry"]
#
# Does:
#   - Register field nodes
#   - Register GUI/interface clients
#   - Track known platform identities
#   - Return identity records
#   - Decide whether a source is known or provisionally trusted
#
# Does NOT:
#   - Maintain live node state
#   - Track GPS, PPS, RTK, or sensor status
#   - Publish events directly
#   - Send commands to nodes
#   - Validate mode changes
#   - Perform TDOA readiness checks
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
# PLATFORM REGISTRY REGISTRY MANAGER
# ============================================================

class PlatformRegistryRegistryManager:
    """
    Maintains known platform identities.

    This manager owns the "who exists" and "who may be trusted"
    portion of the Platform Registry subsystem.

    Runtime state belongs to platform_registry_state_manager.py.
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

        self.registry_config = platform_config.get(
            "registry",
            {}
        )

        self.logger = logging.getLogger(self.__class__.__name__)

        self.debug = platform_config.get(
            "debug",
            False
        )

        self.allow_unknown_nodes = self.registry_config.get(
            "allow_unknown_nodes",
            True
        )

        self.allow_unknown_gui_clients = self.registry_config.get(
            "allow_unknown_gui_clients",
            True
        )

        self.require_node_id = self.registry_config.get(
            "require_node_id",
            True
        )

        self.require_gui_id = self.registry_config.get(
            "require_gui_id",
            True
        )

        self.default_node_trust = self.registry_config.get(
            "default_node_trust",
            "provisional"
        )

        self.default_gui_trust = self.registry_config.get(
            "default_gui_trust",
            "provisional"
        )

        self.allowed_node_roles = platform_config.get(
            "allowed_node_roles",
            []
        )

        self.allowed_gui_roles = platform_config.get(
            "allowed_gui_roles",
            []
        )

        self.known_nodes = deepcopy(
            platform_config.get(
                "known_nodes",
                {}
            )
        )

        self.known_gui_clients = deepcopy(
            platform_config.get(
                "known_gui_clients",
                {}
            )
        )

    # ========================================================
    # PUBLIC API: NODE REGISTRATION
    # ========================================================

    def register_node(self, payload):
        """
        Register a node or refresh an existing node record.

        Accepted payload fields:
            node_id
            node_name optional
            node_role optional
            device_id optional
            device_name optional
            device_role optional
            source optional
            capabilities optional
            ip_address optional
            port optional
            software_version optional
            notes optional
        """

        payload = self._unwrap_registration_payload(payload)
        result = self._base_result()

        node_id = (
            payload.get("node_id")
            or payload.get("device_id")
        )

        if self.require_node_id and not node_id:
            return self._fail(
                result,
                "Node registration failed. Missing node_id/device_id.",
                payload
            )

        if not node_id:
            node_id = self._make_generated_id("node")

        device_role = payload.get("device_role")

        if device_role is not None and device_role != "NODE":
            return self._fail(
                result,
                f"Node registration failed. Invalid device_role: {device_role}",
                payload
            )

        node_role = payload.get(
            "node_role",
            "field_node"
        )

        if not self._role_allowed(node_role, self.allowed_node_roles):
            return self._fail(
                result,
                f"Node registration failed. Invalid node role: {node_role}",
                payload
            )

        existing_record = self.known_nodes.get(node_id)

        if existing_record is None and not self.allow_unknown_nodes:
            return self._fail(
                result,
                f"Unknown node rejected: {node_id}",
                payload
            )

        now_utc = self._utc_now()
        action = "created" if existing_record is None else "updated"

        if existing_record is None:
            record = {
                "node_id": node_id,
                "device_id": node_id,
                "device_role": "NODE",
                "node_name": (
                    payload.get("node_name")
                    or payload.get("device_name")
                    or node_id
                ),
                "node_role": node_role,
                "trust": payload.get("trust", self.default_node_trust),
                "source": payload.get("source", "unknown"),
                "capabilities": payload.get("capabilities", {}),
                "ip_address": payload.get("ip_address"),
                "port": payload.get("port"),
                "software_version": payload.get("software_version"),
                "notes": payload.get("notes"),
                "registered_at_utc": now_utc,
                "last_seen_utc": now_utc,
                "registration_count": 1
            }

        else:
            record = deepcopy(existing_record)

            record["device_id"] = node_id
            record["device_role"] = "NODE"
            record["node_name"] = (
                payload.get("node_name")
                or payload.get("device_name")
                or record.get("node_name", node_id)
            )
            record["node_role"] = payload.get(
                "node_role",
                record.get("node_role", node_role)
            )
            record["trust"] = payload.get(
                "trust",
                record.get("trust", self.default_node_trust)
            )
            record["source"] = payload.get(
                "source",
                record.get("source", "unknown")
            )
            record["capabilities"] = payload.get(
                "capabilities",
                record.get("capabilities", {})
            )
            record["ip_address"] = payload.get(
                "ip_address",
                record.get("ip_address")
            )
            record["port"] = payload.get(
                "port",
                record.get("port")
            )
            record["software_version"] = payload.get(
                "software_version",
                record.get("software_version")
            )
            record["notes"] = payload.get(
                "notes",
                record.get("notes")
            )
            record["last_seen_utc"] = now_utc
            record["registration_count"] = record.get(
                "registration_count",
                0
            ) + 1

        self.known_nodes[node_id] = record

        result["success"] = True
        result["action"] = action
        result["identity_type"] = "node"
        result["identity_id"] = node_id
        result["record"] = deepcopy(record)

        self._debug_log(
            f"Node registration {action}: {node_id}"
        )

        return result

    def node_known(self, node_id):
        """
        Return True when node_id exists in the registry.
        """

        return node_id in self.known_nodes

    def get_node_record(self, node_id):
        """
        Return a copy of a node record.
        """

        record = self.known_nodes.get(node_id)

        if record is None:
            return None

        return deepcopy(record)

    def trust_node(self, node_id):
        """
        Promote a node to trusted status.
        """

        result = self._base_result()

        if node_id not in self.known_nodes:
            return self._fail(
                result,
                f"Cannot trust unknown node: {node_id}",
                {
                    "node_id": node_id
                }
            )

        self.known_nodes[node_id]["trust"] = "trusted"
        self.known_nodes[node_id]["trusted_at_utc"] = self._utc_now()

        result["success"] = True
        result["identity_type"] = "node"
        result["identity_id"] = node_id
        result["record"] = deepcopy(self.known_nodes[node_id])

        return result

    # ========================================================
    # PUBLIC API: GUI REGISTRATION
    # ========================================================

    def register_gui(self, payload):
        """
        Register a GUI/interface client or refresh an existing record.

        Accepted GUI contract fields:
            gui_id
            gui_name optional
            gui_version optional
            role optional

        Also supports universal platform fields:
            device_id
            device_name
            device_role
            gui_role
            ip_address
            port
            software_version
            notes
            source
        """

        payload = self._unwrap_registration_payload(payload)
        result = self._base_result()

        gui_id = (
            payload.get("gui_id")
            or payload.get("device_id")
        )

        if self.require_gui_id and not gui_id:
            return self._fail(
                result,
                "GUI registration failed. Missing gui_id/device_id.",
                payload
            )

        if not gui_id:
            gui_id = self._make_generated_id("gui")

        device_role = payload.get("device_role")

        if device_role is not None and device_role != "GUI":
            return self._fail(
                result,
                f"GUI registration failed. Invalid device_role: {device_role}",
                payload
            )

        gui_name = (
            payload.get("gui_name")
            or payload.get("device_name")
            or gui_id
        )

        gui_version = (
            payload.get("gui_version")
            or payload.get("software_version")
        )

        role = payload.get(
            "role",
            payload.get("gui_role", "operator_interface")
        )

        gui_role = payload.get(
            "gui_role",
            "primary_gui"
        )

        if self.allowed_gui_roles:
            role_allowed = self._role_allowed(role, self.allowed_gui_roles)
            gui_role_allowed = self._role_allowed(
                gui_role,
                self.allowed_gui_roles
            )

            if not role_allowed and not gui_role_allowed:
                return self._fail(
                    result,
                    (
                        "GUI registration failed. Invalid role/gui_role: "
                        f"{role}/{gui_role}"
                    ),
                    payload
                )

        existing_record = self.known_gui_clients.get(gui_id)

        if existing_record is None and not self.allow_unknown_gui_clients:
            return self._fail(
                result,
                f"Unknown GUI client rejected: {gui_id}",
                payload
            )

        now_utc = self._utc_now()
        action = "created" if existing_record is None else "updated"

        if existing_record is None:
            record = {
                "gui_id": gui_id,
                "device_id": gui_id,
                "device_role": "GUI",
                "gui_name": gui_name,
                "gui_version": gui_version,
                "role": role,
                "gui_role": gui_role,
                "trust": payload.get("trust", self.default_gui_trust),
                "source": payload.get("source", "unknown"),
                "ip_address": payload.get("ip_address"),
                "port": payload.get("port"),
                "software_version": gui_version,
                "notes": payload.get("notes"),
                "registered_at_utc": now_utc,
                "last_seen_utc": now_utc,
                "registration_count": 1
            }

        else:
            record = deepcopy(existing_record)

            record["device_id"] = gui_id
            record["device_role"] = "GUI"
            record["gui_name"] = gui_name
            record["gui_version"] = gui_version
            record["role"] = role
            record["gui_role"] = payload.get(
                "gui_role",
                record.get("gui_role", gui_role)
            )
            record["trust"] = payload.get(
                "trust",
                record.get("trust", self.default_gui_trust)
            )
            record["source"] = payload.get(
                "source",
                record.get("source", "unknown")
            )
            record["ip_address"] = payload.get(
                "ip_address",
                record.get("ip_address")
            )
            record["port"] = payload.get(
                "port",
                record.get("port")
            )
            record["software_version"] = payload.get(
                "software_version",
                record.get("software_version", gui_version)
            )
            record["notes"] = payload.get(
                "notes",
                record.get("notes")
            )
            record["last_seen_utc"] = now_utc
            record["registration_count"] = record.get(
                "registration_count",
                0
            ) + 1

        self.known_gui_clients[gui_id] = record

        result["success"] = True
        result["action"] = action
        result["identity_type"] = "gui"
        result["identity_id"] = gui_id
        result["record"] = deepcopy(record)

        self._debug_log(
            f"GUI registration {action}: {gui_id}"
        )

        return result

    def gui_known(self, gui_id):
        """
        Return True when gui_id exists in the registry.
        """

        return gui_id in self.known_gui_clients

    def get_gui_record(self, gui_id):
        """
        Return a copy of a GUI record.
        """

        record = self.known_gui_clients.get(gui_id)

        if record is None:
            return None

        return deepcopy(record)

    def trust_gui(self, gui_id):
        """
        Promote a GUI client to trusted status.
        """

        result = self._base_result()

        if gui_id not in self.known_gui_clients:
            return self._fail(
                result,
                f"Cannot trust unknown GUI client: {gui_id}",
                {
                    "gui_id": gui_id
                }
            )

        self.known_gui_clients[gui_id]["trust"] = "trusted"
        self.known_gui_clients[gui_id]["trusted_at_utc"] = self._utc_now()

        result["success"] = True
        result["identity_type"] = "gui"
        result["identity_id"] = gui_id
        result["record"] = deepcopy(self.known_gui_clients[gui_id])

        return result

    # ========================================================
    # PUBLIC API: TRUST CHECKS
    # ========================================================

    def source_allowed(self, source_type, source_id):
        """
        Check whether a source is allowed to interact with Registry.

        source_type:
            node
            gui
        """

        result = self._base_result()

        if source_type == "node":
            record = self.known_nodes.get(source_id)

        elif source_type == "gui":
            record = self.known_gui_clients.get(source_id)

        else:
            return self._fail(
                result,
                f"Unknown source type: {source_type}",
                {
                    "source_type": source_type,
                    "source_id": source_id
                }
            )

        if record is None:
            result["success"] = False
            result["allowed"] = False
            result["reason"] = "source_unknown"
            return result

        trust = record.get("trust", "unknown")

        if trust in ["trusted", "provisional"]:
            result["success"] = True
            result["allowed"] = True
            result["trust"] = trust
            result["record"] = deepcopy(record)
            return result

        result["success"] = False
        result["allowed"] = False
        result["trust"] = trust
        result["reason"] = "source_not_trusted"

        return result

    # ========================================================
    # PUBLIC API: SNAPSHOTS
    # ========================================================

    def get_registry_snapshot(self):
        """
        Return the known identity registry.
        """

        return {
            "nodes": deepcopy(self.known_nodes),
            "gui_clients": deepcopy(self.known_gui_clients),
            "generated_at_utc": self._utc_now()
        }

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _unwrap_registration_payload(self, payload):
        """
        Accept either a direct registration payload or a message envelope.

        Direct GUI payload:
            {"gui_id": "gui_01", ...}

        Envelope GUI payload:
            {
                "event_type": "GUI_REGISTER",
                "source": "gui",
                "payload": {"gui_id": "gui_01", ...}
            }
        """

        if payload is None:
            return {}

        if not isinstance(payload, dict):
            return {}

        inner_payload = payload.get("payload")

        if isinstance(inner_payload, dict):
            clean_payload = deepcopy(inner_payload)

            for metadata_key in [
                "event_type",
                "event_name",
                "incoming_event",
                "source_event_type",
                "source",
                "timestamp",
                "timestamp_utc",
                "verified_by",
                "target"
            ]:
                if metadata_key in payload and metadata_key not in clean_payload:
                    clean_payload[metadata_key] = payload.get(metadata_key)

            clean_payload["message_envelope"] = deepcopy(payload)

            return clean_payload

        return deepcopy(payload)

    def _role_allowed(self, role, allowed_roles):
        """
        Validate a role against the configured role list.
        """

        if not allowed_roles:
            return True

        return role in allowed_roles

    def _base_result(self):
        """
        Create a standard manager result package.
        """

        return {
            "success": False,
            "action": None,
            "identity_type": None,
            "identity_id": None,
            "allowed": None,
            "trust": None,
            "record": None,
            "reason": None,
            "errors": [],
            "debug": {}
        }

    def _fail(self, result, message, payload=None):
        """
        Return a failed result with consistent error formatting.
        """

        result["success"] = False
        result["reason"] = message
        result["errors"].append(message)

        if self.debug:
            result["debug"]["payload"] = deepcopy(payload or {})

        self.logger.warning(message)

        return result

    def _make_generated_id(self, prefix):
        """
        Create a temporary generated ID.

        This should only happen when config allows missing IDs.
        """

        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )

        return f"{prefix}_{timestamp}"

    def _utc_now(self):
        """
        Return current UTC time in ISO format.
        """

        return datetime.now(timezone.utc).isoformat()

    def _debug_log(self, message):
        """
        Emit debug logs when enabled.
        """

        if self.debug:
            self.logger.debug(message)
