# ============================================================
# database_event_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Database
#
# Role:
#   Manager
#
# Purpose:
#   Write EnviroPulse event records into the SQLite historical archive.
#
# Expected config source:
#   database_config.py
#
# Expected config section:
#   Module-level constants
#
# Does:
#   - Writes raw events into the master events table
#   - Writes Avis detection records
#   - Writes weather records
#   - Writes telemetry records
#   - Writes node registry archive records
#   - Writes system log records
#
# Does NOT:
#   - Subscribe to the event bus
#   - Decide which events should be archived
#   - Maintain live system state
#   - Create database tables
#   - Drive GUI updates
#
# Owner:
#   database_dispatcher.py
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from database.database_connection_manager import (
    DatabaseConnectionManager
)


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import json
import logging
from datetime import datetime, timezone


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class DatabaseEventManager:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        connection_manager: DatabaseConnectionManager,
        debug: bool = False
    ):

        self.connection_manager = connection_manager
        self.debug = debug

    # ========================================================
    # PUBLIC API
    # ========================================================

    def archive_raw_event(
        self,
        event: dict,
        event_category: str = "general"
    ):
        """
        Archives a raw EnviroPulse event in the master events table.

        This is the primary black-box recorder write path.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        try:

            archived_at_utc = self._utc_now()

            event_id = self._extract_event_id(
                event
            )

            event_type = self._extract_event_type(
                event
            )

            source_subsystem = self._extract_source_subsystem(
                event
            )

            source_node_id = self._extract_node_id(
                event
            )

            received_at_utc = self._extract_received_at_utc(
                event,
                archived_at_utc
            )

            raw_event_json = self._to_json(
                event
            )

            query = """
                INSERT INTO events (
                    event_id,
                    event_type,
                    event_category,
                    source_subsystem,
                    source_node_id,
                    received_at_utc,
                    archived_at_utc,
                    raw_event_json,
                    parsed_successfully,
                    parser_notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """

            values = (
                event_id,
                event_type,
                event_category,
                source_subsystem,
                source_node_id,
                received_at_utc,
                archived_at_utc,
                raw_event_json,
                1,
                None
            )

            write_result = self.connection_manager.execute_write(
                query,
                values
            )

            if not write_result["success"]:

                result["errors"].extend(
                    write_result["errors"]
                )

                return result

            result["success"] = True

            result["data"] = {
                "event_archive_id": write_result["data"]["last_row_id"],
                "event_id": event_id,
                "event_type": event_type,
                "event_category": event_category
            }

            if self.debug:
                result["debug"] = {
                    "raw_event_json": raw_event_json
                }

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Raw event archive failed: {error}"
            )

        return result

    def archive_avis_detection(
        self,
        event: dict,
        event_archive_id: int = None
    ):
        """
        Archives an Avis/BirdNET detection record.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        try:

            payload = self._extract_payload(
                event
            )
            
            avis_payload = payload.get(
                "avis_lite",
                payload
            )            

            query = """
                INSERT INTO avis_detections (
                    event_archive_id,
                    event_id,
                    node_id,
                    detection_time_utc,
                    common_name,
                    scientific_name,
                    confidence,
                    confidence_bin,
                    latitude,
                    longitude,
                    altitude_m,
                    raw_event_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """

            values = (
                event_archive_id,
                self._extract_event_id(event),
                self._extract_node_id(event),
                (
                    avis_payload.get("detection_time_utc")
                    or avis_payload.get("detection_time")
                ),
                (
                    avis_payload.get("common_name")
                    or avis_payload.get("species_common")
                    or avis_payload.get("species")
                ),
                (
                    avis_payload.get("scientific_name")
                    or avis_payload.get("species_scientific")
                ),
                avis_payload.get("confidence"),
                avis_payload.get("confidence_bin"),
                avis_payload.get("latitude"),
                avis_payload.get("longitude"),
                avis_payload.get("altitude_m"),
                self._to_json(event)
            )

            write_result = self.connection_manager.execute_write(
                query,
                values
            )

            if not write_result["success"]:

                result["errors"].extend(
                    write_result["errors"]
                )

                return result

            result["success"] = True

            result["data"] = {
                "avis_detection_id": write_result["data"]["last_row_id"],
                "event_archive_id": event_archive_id
            }

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Avis detection archive failed: {error}"
            )

        return result

    def archive_weather_record(
        self,
        event: dict,
        event_archive_id: int = None
    ):
        """
        Archives a weather record.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        try:

            payload = self._extract_payload(
                event
            )
            
            weather_payload = payload.get(
                "enviro_event",
                payload
            )            

            query = """
                INSERT INTO weather_records (
                    event_archive_id,
                    event_id,
                    node_id,
                    measurement_time_utc,
                    temperature_c,
                    humidity_percent,
                    dew_point_c,
                    pressure_hpa,
                    wind_speed_mps,
                    wind_direction_deg,
                    latitude,
                    longitude,
                    altitude_m,
                    raw_event_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """

            values = (
                event_archive_id,
                self._extract_event_id(event),
                self._extract_node_id(event),
                (
                    weather_payload.get("measurement_time_utc")
                    or weather_payload.get("sample_time_utc")
                    or payload.get("timestamp_utc")
                ),
                weather_payload.get("temperature_c"),
                weather_payload.get("humidity_percent"),
                weather_payload.get("dew_point_c"),
                weather_payload.get("pressure_hpa"),
                weather_payload.get("wind_speed_mps"),
                weather_payload.get("wind_direction_deg"),
                weather_payload.get("latitude"),
                weather_payload.get("longitude"),
                weather_payload.get("altitude_m"),
                self._to_json(event)
            )

            write_result = self.connection_manager.execute_write(
                query,
                values
            )

            if not write_result["success"]:

                result["errors"].extend(
                    write_result["errors"]
                )

                return result

            result["success"] = True

            result["data"] = {
                "weather_record_id": write_result["data"]["last_row_id"],
                "event_archive_id": event_archive_id
            }

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Weather record archive failed: {error}"
            )

        return result

    def archive_telemetry_record(
        self,
        event: dict,
        event_archive_id: int = None
    ):
        """
        Archives a telemetry record.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        try:

            payload = self._extract_payload(
                event
            )

            query = """
                INSERT INTO telemetry_records (
                    event_archive_id,
                    event_id,
                    node_id,
                    telemetry_time_utc,
                    battery_voltage,
                    battery_percent,
                    gps_locked,
                    pps_locked,
                    wifi_connected,
                    lora_connected,
                    cpu_temperature_c,
                    disk_free_mb,
                    memory_free_mb,
                    raw_event_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """

            values = (
                event_archive_id,
                self._extract_event_id(event),
                self._extract_node_id(event),
                payload.get("telemetry_time_utc"),
                payload.get("battery_voltage"),
                payload.get("battery_percent"),
                self._to_int_bool(payload.get("gps_locked")),
                self._to_int_bool(payload.get("pps_locked")),
                self._to_int_bool(payload.get("wifi_connected")),
                self._to_int_bool(payload.get("lora_connected")),
                payload.get("cpu_temperature_c"),
                payload.get("disk_free_mb"),
                payload.get("memory_free_mb"),
                self._to_json(event)
            )

            write_result = self.connection_manager.execute_write(
                query,
                values
            )

            if not write_result["success"]:

                result["errors"].extend(
                    write_result["errors"]
                )

                return result

            result["success"] = True

            result["data"] = {
                "telemetry_record_id": write_result["data"]["last_row_id"],
                "event_archive_id": event_archive_id
            }

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Telemetry record archive failed: {error}"
            )

        return result

    def archive_node_registry_record(
        self,
        event: dict,
        event_archive_id: int = None
    ):
        """
        Archives a node registry change or registration event.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        try:

            payload = self._extract_payload(
                event
            )

            archived_at_utc = self._utc_now()

            query = """
                INSERT INTO node_registry_archive (
                    event_archive_id,
                    event_id,
                    node_id,
                    registry_action,
                    registered_at_utc,
                    archived_at_utc,
                    node_name,
                    node_role,
                    hardware_version,
                    firmware_version,
                    latitude,
                    longitude,
                    altitude_m,
                    raw_event_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """

            values = (
                event_archive_id,
                self._extract_event_id(event),
                self._extract_node_id(event),
                payload.get("registry_action"),
                payload.get("registered_at_utc"),
                archived_at_utc,
                payload.get("node_name"),
                payload.get("node_role"),
                payload.get("hardware_version"),
                payload.get("firmware_version"),
                payload.get("latitude"),
                payload.get("longitude"),
                payload.get("altitude_m"),
                self._to_json(event)
            )

            write_result = self.connection_manager.execute_write(
                query,
                values
            )

            if not write_result["success"]:

                result["errors"].extend(
                    write_result["errors"]
                )

                return result

            result["success"] = True

            result["data"] = {
                "node_registry_archive_id": write_result["data"]["last_row_id"],
                "event_archive_id": event_archive_id
            }

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Node registry archive failed: {error}"
            )

        return result

    def archive_system_log(
        self,
        event: dict,
        event_archive_id: int = None
    ):
        """
        Archives a system log record.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        try:

            payload = self._extract_payload(
                event
            )

            query = """
                INSERT INTO system_logs (
                    event_archive_id,
                    event_id,
                    log_time_utc,
                    level,
                    source_subsystem,
                    message,
                    raw_event_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """

            values = (
                event_archive_id,
                self._extract_event_id(event),
                payload.get(
                    "log_time_utc",
                    self._utc_now()
                ),
                payload.get(
                    "level",
                    "INFO"
                ),
                self._extract_source_subsystem(
                    event
                ),
                payload.get(
                    "message",
                    ""
                ),
                self._to_json(event)
            )

            write_result = self.connection_manager.execute_write(
                query,
                values
            )

            if not write_result["success"]:

                result["errors"].extend(
                    write_result["errors"]
                )

                return result

            result["success"] = True

            result["data"] = {
                "system_log_id": write_result["data"]["last_row_id"],
                "event_archive_id": event_archive_id
            }

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"System log archive failed: {error}"
            )

        return result

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _extract_payload(
        self,
        event: dict
    ):
        """
        Extracts the event payload.

        EnviroPulse events may use either 'payload' or 'message'
        depending on which subsystem produced them.
        """

        if not isinstance(
            event,
            dict
        ):

            return {}

        payload = event.get(
            "payload"
        )

        if isinstance(
            payload,
            dict
        ):

            return payload

        message = event.get(
            "message"
        )

        if isinstance(
            message,
            dict
        ):

            return message

        return {}

    def _extract_event_id(
        self,
        event: dict
    ):
        """
        Attempts to find the event ID from common event locations.
        """

        if not isinstance(
            event,
            dict
        ):

            return None

        if event.get(
            "event_id"
        ) is not None:

            return event.get(
                "event_id"
            )

        payload = self._extract_payload(
            event
        )

        if payload.get(
            "event_id"
        ) is not None:

            return payload.get(
                "event_id"
            )

        return None

    def _extract_event_type(
        self,
        event: dict
    ):
        """
        Extracts the event type from common EnviroPulse event locations.
        """

        if not isinstance(
            event,
            dict
        ):

            return None

        if event.get(
            "event_type"
        ) is not None:

            return event.get(
                "event_type"
            )

        payload = self._extract_payload(
            event
        )

        if payload.get(
            "event_type"
        ) is not None:

            return payload.get(
                "event_type"
            )

        return None

    def _extract_source_subsystem(
        self,
        event: dict
    ):
        """
        Attempts to find the source subsystem from common event locations.
        """

        if not isinstance(
            event,
            dict
        ):

            return None

        if event.get(
            "source_subsystem"
        ) is not None:

            return event.get(
                "source_subsystem"
            )

        payload = self._extract_payload(
            event
        )

        if payload.get(
            "source_subsystem"
        ) is not None:

            return payload.get(
                "source_subsystem"
            )

        return None

    def _extract_node_id(
        self,
        event: dict
    ):
        """
        Attempts to find the node ID from common event locations.
        """

        if not isinstance(
            event,
            dict
        ):

            return None

        if event.get(
            "node_id"
        ) is not None:

            return event.get(
                "node_id"
            )

        if event.get(
            "source_node_id"
        ) is not None:

            return event.get(
                "source_node_id"
            )

        payload = self._extract_payload(
            event
        )

        if payload.get(
            "node_id"
        ) is not None:

            return payload.get(
                "node_id"
            )

        if payload.get(
            "source_node_id"
        ) is not None:

            return payload.get(
                "source_node_id"
            )

        return None

    def _extract_received_at_utc(
        self,
        event: dict,
        fallback_time_utc: str
    ):
        """
        Attempts to find the received timestamp.

        Falls back to the archive timestamp if no received timestamp exists.
        """

        if not isinstance(
            event,
            dict
        ):

            return fallback_time_utc

        if event.get(
            "received_at_utc"
        ) is not None:

            return event.get(
                "received_at_utc"
            )

        if event.get(
            "timestamp_utc"
        ) is not None:

            return event.get(
                "timestamp_utc"
            )

        payload = self._extract_payload(
            event
        )

        if payload.get(
            "received_at_utc"
        ) is not None:

            return payload.get(
                "received_at_utc"
            )

        if payload.get(
            "timestamp_utc"
        ) is not None:

            return payload.get(
                "timestamp_utc"
            )

        return fallback_time_utc

    def _to_json(
        self,
        event: dict
    ):
        """
        Converts event data to stable JSON text.
        """

        return json.dumps(
            event,
            sort_keys=True,
            default=str
        )

    def _to_int_bool(
        self,
        value
    ):
        """
        Converts booleans to SQLite-friendly integer values.

        Returns None if the value is unknown.
        """

        if value is None:

            return None

        if value is True:

            return 1

        if value is False:

            return 0

        if value in [
            1,
            "1",
            "true",
            "True",
            "TRUE",
            "yes",
            "Yes"
        ]:

            return 1

        if value in [
            0,
            "0",
            "false",
            "False",
            "FALSE",
            "no",
            "No"
        ]:

            return 0

        return None

    def _utc_now(
        self
    ):
        """
        Returns the current UTC time in ISO-8601 format.
        """

        return datetime.now(
            timezone.utc
        ).isoformat()