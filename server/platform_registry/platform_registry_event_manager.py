# ============================================================
# platform_registry_event_manager.py
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
#   Validate accepted platform events and convert them into
#   server-approved event packages for dispatcher publication.
#
# Expected config source:
#   platform_registry_config.json
#
# Expected config section:
#   config["platform_registry"]["event"]
#
# Does:
#   - Validate known platform event types
#   - Convert raw event names into SERVER event keys
#   - Build server-approved event payloads
#   - Preserve original event payloads when configured
#
# Does NOT:
#   - Publish events directly
#   - Maintain live platform state
#   - Register nodes or GUI clients
#   - Validate mode changes
#   - Send commands to nodes
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
# PLATFORM REGISTRY EVENT MANAGER
# ============================================================

class PlatformRegistryEventManager:
    """
    Validates and converts platform events.

    This manager handles occurrence-based events, not state and
    not mode commands.

    Examples:
        weather
        gps_coord
        avis_lite
        tdoa_calc

    The dispatcher publishes the returned SERVER event package.
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

        self.event_config = platform_config.get(
            "event",
            {}
        )

        self.platform_event_map = platform_config.get(
            "platform_event_map",
            {}
        )

        self.required_event_fields = platform_config.get(
            "required_event_fields",
            {}
        )

        self.debug = platform_config.get(
            "debug",
            False
        )

        self.publish_all_valid_events = self.event_config.get(
            "publish_all_valid_events",
            True
        )

        self.include_original_payload = self.event_config.get(
            "include_original_payload",
            True
        )

        self.include_event_snapshot = self.event_config.get(
            "include_event_snapshot",
            True
        )

        self.default_source_type = self.event_config.get(
            "default_source_type",
            "node"
        )

        self.logger = logging.getLogger(self.__class__.__name__)

        self.event_history = []

    # ========================================================
    # PUBLIC API
    # ========================================================

    def handle_platform_event(self, event_name, payload):
        """
        Validate and convert an accepted platform event.

        Expected payload:
            node_id
            event_id optional
            timestamp_utc optional
            destination optional
            event-specific fields

        Returns:
            result dictionary
        """

        result = self._base_result()

        server_event_key = self.platform_event_map.get(event_name)

        if server_event_key is None:
            return self._fail(
                result,
                f"Platform event rejected. Unknown event: {event_name}",
                event_name,
                payload
            )

        validation = self._validate_required_fields(
            event_name=event_name,
            payload=payload
        )

        if not validation["success"]:
            return self._fail(
                result,
                validation["reason"],
                event_name,
                payload
            )

        event_record = self._build_event_record(
            event_name=event_name,
            server_event_key=server_event_key,
            payload=payload
        )

        self.event_history.append(event_record)

        server_payload = self._build_server_event_payload(
            event_name=event_name,
            server_event_key=server_event_key,
            incoming_payload=payload,
            event_record=event_record
        )

        result["success"] = True
        result["publish"] = self.publish_all_valid_events
        result["incoming_event"] = event_name
        result["server_event_key"] = server_event_key
        result["server_payload"] = server_payload
        result["event_record"] = deepcopy(event_record)

        return result

    def get_event_history(self):
        """
        Return a copy of event history.
        """

        return deepcopy(self.event_history)

    def get_recent_events(self, limit=25):
        """
        Return the most recent event records.
        """

        if limit <= 0:
            return []

        return deepcopy(self.event_history[-limit:])

    # ========================================================
    # VALIDATION
    # ========================================================

    def _validate_required_fields(self, event_name, payload):
        """
        Check required fields for a given platform event.
        """

        required_fields = self.required_event_fields.get(
            event_name,
            []
        )

        missing_fields = []

        for field_name in required_fields:
            if payload.get(field_name) is None:
                missing_fields.append(field_name)

        if missing_fields:
            return {
                "success": False,
                "reason": (
                    f"Platform event rejected. Missing fields for "
                    f"{event_name}: {missing_fields}"
                )
            }

        return {
            "success": True,
            "reason": None
        }

    # ========================================================
    # EVENT RECORD BUILDING
    # ========================================================

    def _build_event_record(
        self,
        event_name,
        server_event_key,
        payload
    ):
        """
        Build internal event record.
        """

        timestamp_utc = payload.get(
            "timestamp_utc",
            self._utc_now()
        )

        event_id = payload.get(
            "event_id",
            self._make_generated_event_id(event_name)
        )

        record = {
            "event_id": event_id,
            "incoming_event": event_name,
            "server_event_key": server_event_key,
            "node_id": payload.get("node_id"),
            "timestamp_utc": timestamp_utc,
            "received_at_utc": self._utc_now()
        }

        if event_name == "weather":
            record["weather"] = self._extract_weather(payload)

        elif event_name == "gps_coord":
            record["gps_coord"] = self._extract_gps_coord(payload)

        elif event_name == "avis_lite":
            record["avis_lite"] = self._extract_avis_lite(payload)

        elif event_name == "tdoa_calc":
            record["tdoa_calc"] = self._extract_tdoa_calc(payload)

        if self.include_original_payload:
            record["original_payload"] = deepcopy(payload)

        return record

    def _build_server_event_payload(
        self,
        event_name,
        server_event_key,
        incoming_payload,
        event_record
    ):
        """
        Build server-approved event payload.
        """

        package = {
            "server_event_key": server_event_key,
            "incoming_event": event_name,
            "source_type": self.default_source_type,
            "node_id": incoming_payload.get("node_id"),
            "event_id": event_record.get("event_id"),
            "timestamp_utc": self._utc_now()
        }

        destination = incoming_payload.get("destination")

        if destination is not None:
            package["destination"] = destination

        if event_name == "weather":
            package["weather"] = event_record.get("weather", {})

        elif event_name == "gps_coord":
            package["gps_coord"] = event_record.get("gps_coord", {})

        elif event_name == "avis_lite":
            package["avis_lite"] = event_record.get("avis_lite", {})

        elif event_name == "tdoa_calc":
            package["tdoa_calc"] = event_record.get("tdoa_calc", {})

        if self.include_event_snapshot:
            package["event_record"] = deepcopy(event_record)

        if self.debug:
            package["debug"] = {
                "incoming_payload": deepcopy(incoming_payload)
            }

        return package

    # ========================================================
    # EVENT-SPECIFIC EXTRACTORS
    # ========================================================

    def _extract_weather(self, payload):
        """
        Extract weather/environment fields.
        """

        return {
            "temperature_c": payload.get("temperature_c"),
            "humidity_percent": payload.get("humidity_percent"),
            "pressure_hpa": payload.get("pressure_hpa")
        }

    def _extract_gps_coord(self, payload):
        """
        Extract GPS coordinate fields.
        """

        coord = payload.get("gps_coord")

        if coord is not None:
            return deepcopy(coord)

        return {
            "lat": payload.get("lat"),
            "lon": payload.get("lon"),
            "alt": payload.get("alt")
        }

    def _extract_avis_lite(self, payload):
        """
        Extract Avis Lite detection fields.
        """

        return {
            "species": payload.get("species"),
            "common_name": payload.get("common_name"),
            "scientific_name": payload.get("scientific_name"),
            "confidence": payload.get("confidence"),
            "detection_time": payload.get("detection_time"),
            "audio_path": payload.get("audio_path")
        }

    def _extract_tdoa_calc(self, payload):
        """
        Extract TDOA calculation fields.
        """

        return {
            "tdoa_event_id": payload.get("tdoa_event_id"),
            "position": payload.get("position"),
            "uncertainty": payload.get("uncertainty"),
            "participating_nodes": payload.get("participating_nodes"),
            "solver_status": payload.get("solver_status")
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
            "incoming_event": None,
            "server_event_key": None,
            "server_payload": None,
            "event_record": None,
            "reason": None,
            "errors": [],
            "debug": {}
        }

    def _fail(self, result, message, event_name, payload):
        """
        Return failed event-manager result.
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

    def _make_generated_event_id(self, event_name):
        """
        Create generated event ID when source did not provide one.
        """

        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )

        return f"{event_name}_{timestamp}"

    def _utc_now(self):
        """
        Return current UTC time in ISO format.
        """

        return datetime.now(timezone.utc).isoformat()
