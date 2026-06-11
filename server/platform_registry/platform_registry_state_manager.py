# ============================================================
# platform_registry_state_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Platform Registry
#
# Role:
#   State Manager
#
# Purpose:
#   Maintain canonical platform state for known nodes and return
#   server-approved NODE_STATE_UPDATED payloads to the dispatcher.
#
# Owns:
#   - RTK_STATE
#   - GPS_STATE
#   - PPS_STATE
#   - ENVIRO_STATE
#
# Does:
#   - Maintain current node state
#   - Store raw state blocks from nodes
#   - Derive useful registry flags from those blocks
#   - Track previous and current values
#   - Return server-approved state packages
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
    Maintains canonical platform state for field nodes.

    The dispatcher sends accepted node state events here. This manager
    stores the canonical node snapshot and returns a result package.
    The dispatcher decides whether to publish that result.
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

        configured_state_event_map = platform_config.get(
            "state_event_map",
            {}
        ) or {}

        default_state_event_map = {
            "RTK_STATE": "rtk_state",
            "GPS_STATE": "gps_state",
            "PPS_STATE": "pps_state",
            "ENVIRO_STATE": "enviro_state"
        }

        default_state_event_map.update(
            {
                str(key).strip().upper(): value
                for key, value in configured_state_event_map.items()
            }
        )

        self.state_event_map = default_state_event_map

        self.state_defaults = platform_config.get(
            "state_defaults",
            {}
        )

        self.debug = platform_config.get(
            "debug",
            False
        )

        # Default False while testing node-state flow:
        # every accepted state packet produces NODE_STATE_UPDATED.
        self.publish_only_on_change = self.state_config.get(
            "publish_only_on_change",
            False
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

        self.logger = logging.getLogger(
            self.__class__.__name__
        )

        self.node_states = {}

    # ========================================================
    # PUBLIC API
    # ========================================================

    def handle_state_event(self, event_name, payload):
        """
        Update node state and return a server-approved result package.

        Expected normalized payload:
            {
                "node_id": "...",
                ...state fields...
            }

        Supported event names:
            RTK_STATE
            GPS_STATE
            PPS_STATE
            ENVIRO_STATE
        """

        result = self._base_result()

        event_name = str(
            event_name or ""
        ).strip().upper()

        payload = payload or {}

        if not isinstance(payload, dict):
            return self._fail(
                result,
                "State update rejected. Payload must be a dictionary.",
                event_name,
                {}
            )

        node_id = payload.get(
            "node_id"
        )

        if not node_id:
            return self._fail(
                result,
                "State update rejected. Missing node_id.",
                event_name,
                payload
            )

        server_event_key = self.state_event_map.get(
            event_name
        )

        if server_event_key is None:
            return self._fail(
                result,
                f"State update rejected. Unknown state event: {event_name}",
                event_name,
                payload
            )

        self._ensure_node_state(
            node_id
        )

        previous_snapshot = deepcopy(
            self.node_states[node_id]
        )

        update_result = self._apply_state_update(
            node_id=node_id,
            event_name=event_name,
            payload=payload
        )

        if not update_result.get("success"):
            return self._fail(
                result,
                update_result.get("reason"),
                event_name,
                payload
            )

        current_snapshot = deepcopy(
            self.node_states[node_id]
        )

        changed = self._snapshots_differ(
            previous_snapshot,
            current_snapshot
        )

        if self.publish_only_on_change and not changed:
            result["success"] = True
            result["publish"] = False
            result["reason"] = "state_unchanged"
            result["node_id"] = node_id
            result["incoming_event"] = event_name
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
        result["reason"] = "state_updated"
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

        state = self.node_states.get(
            node_id
        )

        if state is None:
            return None

        return deepcopy(
            state
        )

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
        Apply one accepted aggregate state event to canonical node state.
        """

        result = {
            "success": True,
            "reason": None
        }

        state = self.node_states[node_id]

        now_utc = payload.get(
            "timestamp_utc",
            self._utc_now()
        )

        state["last_state_update_utc"] = now_utc
        state["last_state_event"] = event_name
        state["last_seen_utc"] = now_utc

        if "source" in payload:
            state["last_source"] = payload.get(
                "source"
            )

        if "source_name" in payload:
            state["node_name"] = payload.get(
                "source_name"
            )

        if "simulated" in payload:
            state["simulated"] = payload.get(
                "simulated"
            )

        if event_name == "RTK_STATE":
            self._apply_rtk_state(
                state,
                payload
            )

        elif event_name == "GPS_STATE":
            self._apply_gps_state(
                state,
                payload
            )

        elif event_name == "PPS_STATE":
            self._apply_pps_state(
                state,
                payload
            )

        elif event_name == "ENVIRO_STATE":
            self._apply_enviro_state(
                state,
                payload
            )

        else:
            result["success"] = False
            result["reason"] = f"Unhandled state event: {event_name}"

        state["tdoa_capable"] = self._calculate_tdoa_capable(
            state
        )

        state["rtk_tdoa_capable"] = self._calculate_rtk_tdoa_capable(
            state
        )

        return result

    def _apply_rtk_state(self, state, payload):
        """
        Store RTK state and derive useful RTK flags when present.
        """

        state["rtk_state"] = self._clean_state_payload(
            payload
        )

        rtk_online = self._first_present(
            payload,
            [
                "rtk_online",
                "rtk_ready",
                "rtk_available",
                "online",
                "ready",
                "available",
                "locked",
                "lock"
            ]
        )

        if rtk_online is not None:
            state["rtk_online"] = self._coerce_bool(
                rtk_online,
                default=state.get("rtk_online", False)
            )

        fix_type = self._first_present(
            payload,
            [
                "rtk_fix_type",
                "fix_type",
                "fix",
                "solution"
            ]
        )

        if fix_type is not None:
            state["rtk_fix_type"] = fix_type

            fix_text = str(
                fix_type
            ).strip().lower()

            if fix_text in [
                    "fixed",
                    "rtk_fixed",
                    "float",
                    "rtk_float"
            ]:
                state["rtk_online"] = True

            elif fix_text in [
                    "none",
                    "no_fix",
                    "invalid",
                    "lost",
                    "offline"
            ]:
                state["rtk_online"] = False

    def _apply_gps_state(self, state, payload):
        """
        Store GPS state and derive GPS lock and coordinates when present.
        """

        state["gps_state"] = self._clean_state_payload(
            payload
        )

        gps_locked = self._first_present(
            payload,
            [
                "gps_locked",
                "gps_lock",
                "locked",
                "lock",
                "has_fix",
                "fix",
                "gps_available",
                "available"
            ]
        )

        if gps_locked is not None:
            state["gps_locked"] = self._coerce_bool(
                gps_locked,
                default=state.get("gps_locked", False)
            )

        fix_type = self._first_present(
            payload,
            [
                "gps_fix_type",
                "fix_type",
                "fix_quality",
                "solution"
            ]
        )

        if fix_type is not None:
            state["gps_fix_type"] = fix_type

            fix_text = str(
                fix_type
            ).strip().lower()

            if fix_text in [
                    "2d",
                    "3d",
                    "2d_fix",
                    "3d_fix",
                    "dgps",
                    "rtk_float",
                    "rtk_fixed"
            ]:
                state["gps_locked"] = True

            elif fix_text in [
                    "none",
                    "no_fix",
                    "invalid",
                    "lost"
            ]:
                state["gps_locked"] = False

        gps_coord = self._extract_gps_coord(
            payload
        )

        if gps_coord is not None:
            state["gps_coord"] = gps_coord

        if state.get("gps_locked") is False:
            state["gps_coord"] = None

    def _apply_pps_state(self, state, payload):
        """
        Store PPS state and derive PPS lock when present.
        """

        state["pps_state"] = self._clean_state_payload(
            payload
        )

        pps_locked = self._first_present(
            payload,
            [
                "pps_locked",
                "pps_lock",
                "locked",
                "lock",
                "pps_available",
                "available",
                "ready",
                "online"
            ]
        )

        if pps_locked is not None:
            state["pps_locked"] = self._coerce_bool(
                pps_locked,
                default=state.get("pps_locked", False)
            )

        pps_last_tick_utc = self._first_present(
            payload,
            [
                "pps_last_tick_utc",
                "last_tick_utc",
                "last_pps_utc"
            ]
        )

        if pps_last_tick_utc is not None:
            state["pps_last_tick_utc"] = pps_last_tick_utc

    def _apply_enviro_state(self, state, payload):
        """
        Store environmental state and derive sensor values when present.
        Supports both flat payloads and nested simulator sensor payloads.
        """

        state["enviro_state"] = self._clean_state_payload(
            payload
        )

        sensors = payload.get(
            "sensors",
            {}
        ) or {}

        sht45 = sensors.get(
            "SHT45",
            {}
        ) or {}

        bmp390 = sensors.get(
            "BMP390",
            {}
        ) or {}

        # --------------------------------------------------------
        # Nested simulator format
        # --------------------------------------------------------

        if sht45:
            sht45_available = sht45.get(
                "available",
                False
            )

            sht45_healthy = sht45.get(
                "healthy",
                False
            )

            state["sht45_online"] = (
                bool(sht45_available)
                and bool(sht45_healthy)
            )

        if bmp390:
            bmp390_available = bmp390.get(
                "available",
                False
            )

            bmp390_healthy = bmp390.get(
                "healthy",
                False
            )

            state["bmp390_online"] = (
                bool(bmp390_available)
                and bool(bmp390_healthy)
            )

        # --------------------------------------------------------
        # Flat payload format
        # --------------------------------------------------------
        
        enviro_online = self._first_present(
            payload,
            [
                "enviro_online",
                "environmental_online",
                "environmental_available",
                "online",
                "available",
                "ready"
            ]
        )

        if enviro_online is not None:
            state["enviro_online"] = self._coerce_bool(
                enviro_online,
                default=state.get("enviro_online", False)
            )

        bmp390_online = self._first_present(
            payload,
            [
                "bmp390_online",
                "bmp_online",
                "pressure_sensor_online",
                "pressure_available"
            ]
        )

        if bmp390_online is not None:
            state["bmp390_online"] = self._coerce_bool(
                bmp390_online,
                default=state.get("bmp390_online", False)
            )

        sht45_online = self._first_present(
            payload,
            [
                "sht45_online",
                "sht_online",
                "temp_humidity_sensor_online",
                "environmental_sensor_online",
                "temperature_available",
                "humidity_available"
            ]
        )

        if sht45_online is not None:
            state["sht45_online"] = self._coerce_bool(
                sht45_online,
                default=state.get("sht45_online", False)
            )

        # --------------------------------------------------------
        # Sensor values
        # --------------------------------------------------------

        temperature_c = self._first_present(
            payload,
            [
                "temperature_c",
                "temp_c",
                "temperature"
            ]
        )

        if temperature_c is not None:
            state["temperature_c"] = temperature_c
            state["sht45_online"] = True

        humidity_percent = self._first_present(
            payload,
            [
                "humidity_percent",
                "humidity",
                "relative_humidity"
            ]
        )

        if humidity_percent is not None:
            state["humidity_percent"] = humidity_percent
            state["sht45_online"] = True

        pressure_hpa = self._first_present(
            payload,
            [
                "pressure_hpa",
                "pressure",
                "barometric_pressure"
            ]
        )

        if pressure_hpa is not None:
            state["pressure_hpa"] = pressure_hpa
            state["bmp390_online"] = True

        state["enviro_online"] = (
            state.get("sht45_online", False)
            or state.get("bmp390_online", False)
            or state.get("enviro_online", False)
        )    
    
    def _calculate_tdoa_capable(self, state):
        """
        Return True if this node currently has minimum TDOA state.
        """

        return (
            state.get("pps_locked", False)
            and state.get("gps_locked", False)
            and state.get("gps_coord") is not None
        )

    def _calculate_rtk_tdoa_capable(self, state):
        """
        Return True if this node has RTK-enhanced TDOA state.
        """

        return (
            state.get("tdoa_capable", False)
            and state.get("rtk_online", False)
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
        Build server-approved NODE_STATE_UPDATED payload.
        """

        package = {
            "server_event_key": server_event_key,
            "incoming_event": event_name,
            "source_type": self.default_source_type,
            "node_id": node_id,
            "node_name": current_snapshot.get("node_name"),
            "changed": changed,
            "timestamp_utc": self._utc_now(),
            "state": self._get_state_value_for_event(
                event_name,
                current_snapshot
            )
        }

        destination = incoming_payload.get(
            "destination"
        )

        if destination is not None:
            package["destination"] = destination

        if self.include_previous_value:
            package["previous_state"] = self._get_state_value_for_event(
                event_name,
                previous_snapshot
            )

        if self.include_state_snapshot:
            package["node_state_snapshot"] = deepcopy(
                current_snapshot
            )

        if self.debug:
            package["debug"] = {
                "incoming_payload": deepcopy(incoming_payload)
            }

        return package

    def _get_state_value_for_event(self, event_name, state):
        """
        Return the relevant state value for a given aggregate state event.
        """

        event_name = str(
            event_name or ""
        ).strip().upper()

        if event_name == "RTK_STATE":
            return {
                "rtk_state": state.get("rtk_state"),
                "rtk_online": state.get("rtk_online"),
                "rtk_fix_type": state.get("rtk_fix_type"),
                "rtk_tdoa_capable": state.get("rtk_tdoa_capable")
            }

        if event_name == "GPS_STATE":
            return {
                "gps_state": state.get("gps_state"),
                "gps_locked": state.get("gps_locked"),
                "gps_fix_type": state.get("gps_fix_type"),
                "gps_coord": state.get("gps_coord"),
                "tdoa_capable": state.get("tdoa_capable")
            }

        if event_name == "PPS_STATE":
            return {
                "pps_state": state.get("pps_state"),
                "pps_locked": state.get("pps_locked"),
                "pps_last_tick_utc": state.get("pps_last_tick_utc"),
                "tdoa_capable": state.get("tdoa_capable")
            }

        if event_name == "ENVIRO_STATE":
            return {
                "enviro_state": state.get("enviro_state"),
                "enviro_online": state.get("enviro_online"),
                "bmp390_online": state.get("bmp390_online"),
                "sht45_online": state.get("sht45_online"),
                "temperature_c": state.get("temperature_c"),
                "humidity_percent": state.get("humidity_percent"),
                "pressure_hpa": state.get("pressure_hpa")
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
            "node_name": self.state_defaults.get(
                "node_name",
                node_id
            ),
            "created_at_utc": self._utc_now(),
            "last_seen_utc": None,
            "last_state_update_utc": None,
            "last_state_event": None,
            "last_source": None,
            "simulated": False,

            "rtk_state": deepcopy(
                self.state_defaults.get(
                    "rtk_state",
                    {}
                )
            ),
            "gps_state": deepcopy(
                self.state_defaults.get(
                    "gps_state",
                    {}
                )
            ),
            "pps_state": deepcopy(
                self.state_defaults.get(
                    "pps_state",
                    {}
                )
            ),
            "enviro_state": deepcopy(
                self.state_defaults.get(
                    "enviro_state",
                    {}
                )
            ),

            "rtk_online": self.state_defaults.get(
                "rtk_online",
                False
            ),
            "rtk_fix_type": self.state_defaults.get(
                "rtk_fix_type",
                None
            ),
            "gps_locked": self.state_defaults.get(
                "gps_locked",
                False
            ),
            "gps_fix_type": self.state_defaults.get(
                "gps_fix_type",
                None
            ),
            "gps_coord": deepcopy(
                self.state_defaults.get(
                    "gps_coord",
                    None
                )
            ),
            "pps_locked": self.state_defaults.get(
                "pps_locked",
                False
            ),
            "pps_last_tick_utc": self.state_defaults.get(
                "pps_last_tick_utc",
                None
            ),

            "enviro_online": self.state_defaults.get(
                "enviro_online",
                False
            ),
            "bmp390_online": self.state_defaults.get(
                "bmp390_online",
                False
            ),
            "sht45_online": self.state_defaults.get(
                "sht45_online",
                False
            ),
            "temperature_c": self.state_defaults.get(
                "temperature_c",
                None
            ),
            "humidity_percent": self.state_defaults.get(
                "humidity_percent",
                None
            ),
            "pressure_hpa": self.state_defaults.get(
                "pressure_hpa",
                None
            ),

            "tdoa_capable": self.state_defaults.get(
                "tdoa_capable",
                False
            ),
            "rtk_tdoa_capable": self.state_defaults.get(
                "rtk_tdoa_capable",
                False
            )
        }

    # ========================================================
    # NORMALIZATION HELPERS
    # ========================================================

    def _extract_gps_coord(self, payload):
        """
        Extract a GPS coordinate dictionary from common payload shapes.
        """

        gps_coord = self._first_present(
            payload,
            [
                "gps_coord",
                "coord",
                "coords",
                "coordinate",
                "coordinates",
                "location"
            ]
        )

        if isinstance(gps_coord, dict):
            lat = self._first_present(
                gps_coord,
                [
                    "lat",
                    "latitude"
                ]
            )

            lon = self._first_present(
                gps_coord,
                [
                    "lon",
                    "lng",
                    "longitude"
                ]
            )

            alt = self._first_present(
                gps_coord,
                [
                    "alt",
                    "altitude",
                    "alt_m"
                ]
            )

            if lat is not None and lon is not None:
                return {
                    "lat": lat,
                    "lon": lon,
                    "alt": alt
                }

            return deepcopy(
                gps_coord
            )

        lat = self._first_present(
            payload,
            [
                "lat",
                "latitude"
            ]
        )

        lon = self._first_present(
            payload,
            [
                "lon",
                "lng",
                "longitude"
            ]
        )

        alt = self._first_present(
            payload,
            [
                "alt",
                "altitude",
                "alt_m"
            ]
        )

        if lat is not None and lon is not None:
            return {
                "lat": lat,
                "lon": lon,
                "alt": alt
            }

        return None

    def _first_present(self, payload, keys):
        """
        Return the first present non-None value from payload.
        """

        if not isinstance(payload, dict):
            return None

        for key in keys:
            if key in payload and payload.get(key) is not None:
                return payload.get(key)

        return None

    def _coerce_bool(self, value, default=False):
        """
        Convert common state values into bool.
        """

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return value != 0

        if isinstance(value, str):
            normalized = value.strip().lower()

            if normalized in [
                    "true",
                    "yes",
                    "y",
                    "1",
                    "online",
                    "ready",
                    "locked",
                    "available",
                    "ok",
                    "healthy",
                    "fix",
                    "fixed",
                    "rtk_fixed"
            ]:
                return True

            if normalized in [
                    "false",
                    "no",
                    "n",
                    "0",
                    "offline",
                    "not_ready",
                    "unlocked",
                    "unavailable",
                    "lost",
                    "error",
                    "fail",
                    "failed",
                    "none",
                    "no_fix",
                    "invalid"
            ]:
                return False

            return default

        if value is None:
            return default

        return bool(value)

    def _clean_state_payload(self, payload):
        """
        Store a cleaned copy of the incoming state block.
        """

        return deepcopy(
            payload or {}
        )

    def _snapshots_differ(self, previous_snapshot, current_snapshot):
        """
        Compare snapshots while ignoring registry bookkeeping timestamps.
        """

        previous = deepcopy(
            previous_snapshot or {}
        )

        current = deepcopy(
            current_snapshot or {}
        )

        ignored_keys = [
            "last_seen_utc",
            "last_state_update_utc"
        ]

        for key in ignored_keys:
            previous.pop(
                key,
                None
            )

            current.pop(
                key,
                None
            )

        return previous != current

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
        result["errors"].append(
            message
        )

        if self.debug:
            result["debug"]["payload"] = deepcopy(
                payload
            )

        self.logger.warning(
            message
        )

        return result

    def _utc_now(self):
        """
        Return current UTC time in ISO format.
        """

        return datetime.now(
            timezone.utc
        ).isoformat()