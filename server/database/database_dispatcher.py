# ============================================================
# database_dispatcher.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Database
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own the database subsystem workflow and route archive-worthy
#   events to the correct database manager write path.
#
# Expected config source:
#   database_config.py
#
# Expected config section:
#   Module-level constants
#
# Does:
#   - Owns database subsystem components
#   - Initializes the database schema
#   - Receives archive-worthy events
#   - Archives raw events first
#   - Routes known event types to specialized archive tables
#   - Publishes database status and warning events through event services
#
# Does NOT:
#   - Directly talk to SQLite
#   - Maintain live system state
#   - Drive GUI updates
#   - Decide platform behavior outside the database subsystem
#
# Owner:
#   Main / Subsystem root
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from database.database_connection_manager import (
    DatabaseConnectionManager
)

from database.database_schema_manager import (
    DatabaseSchemaManager
)

from database.database_event_manager import (
    DatabaseEventManager
)

from database.database_event_services import (
    DatabaseEventServices
)


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class DatabaseDispatcher:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        debug: bool = False
    ):

        self.event_bus = event_bus
        self.debug = debug

        self.connection_manager = DatabaseConnectionManager(
            debug=self.debug
        )

        self.schema_manager = DatabaseSchemaManager(
            connection_manager=self.connection_manager,
            debug=self.debug
        )

        self.event_manager = DatabaseEventManager(
            connection_manager=self.connection_manager,
            debug=self.debug
        )

        self.event_services = DatabaseEventServices(
            event_bus=self.event_bus,
            dispatcher=self,
            debug=self.debug
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def start(
        self
    ):
        """
        Starts the database subsystem.

        This initializes the schema and subscribes to archive-worthy events.
        """

        schema_result = self.schema_manager.initialize_schema()

        if not schema_result["success"]:

            self.event_services.publish_database_warning(
                warning_type="database_schema_initialization_failed",
                details=schema_result["errors"]
            )

            return schema_result

        self.event_services.publish_database_status(
            status="database_schema_ready",
            details=schema_result["data"]
        )

        subscription_result = self.event_services.subscribe_to_events()

        if not subscription_result["success"]:

            self.event_services.publish_database_warning(
                warning_type="database_subscription_failed",
                details=subscription_result["errors"]
            )

            return subscription_result

        self.event_services.publish_database_status(
            status="database_started",
            details={
                "subscribed_events": subscription_result["data"].get(
                    "subscribed_events",
                    []
                )
            }
        )

        return {
            "success": True,
            "data": {
                "database_started": True,
                "subscribed_events": subscription_result["data"].get(
                    "subscribed_events",
                    []
                )
            },
            "debug": {},
            "errors": []
        }

    def handle_event(
        self,
        event: dict
    ):
        """
        Handles an incoming archive-worthy event.

        The raw event is archived first.
        If the event type is known, a specialized table write is attempted.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        try:

            if not isinstance(
                event,
                dict
            ):

                result["errors"].append(
                    "Database dispatcher received a non-dictionary event."
                )

                self.event_services.publish_database_warning(
                    warning_type="invalid_database_event",
                    details=result["errors"]
                )

                return result

            event_type = self._extract_event_type(
                event
            )

            event_category = self._classify_event_category(
                event_type
            )

            raw_archive_result = self.event_manager.archive_raw_event(
                event=event,
                event_category=event_category
            )

            if not raw_archive_result["success"]:

                result["errors"].extend(
                    raw_archive_result["errors"]
                )

                self.event_services.publish_database_warning(
                    warning_type="raw_event_archive_failed",
                    details=result["errors"]
                )

                return result

            event_archive_id = raw_archive_result["data"].get(
                "event_archive_id"
            )

            specialized_result = self._archive_specialized_record(
                event=event,
                event_type=event_type,
                event_archive_id=event_archive_id
            )

            if not specialized_result["success"]:

                self.event_services.publish_database_warning(
                    warning_type="specialized_archive_failed",
                    details=specialized_result["errors"]
                )

            result["success"] = True

            result["data"] = {
                "event_archive_id": event_archive_id,
                "event_type": event_type,
                "event_category": event_category,
                "specialized_archive": specialized_result
            }

            if self.debug:
                result["debug"] = {
                    "raw_archive_result": raw_archive_result
                }

            self.event_services.publish_database_status(
                status="event_archived",
                details=result["data"]
            )

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Database dispatcher failed: {error}"
            )

            self.event_services.publish_database_warning(
                warning_type="database_dispatcher_failed",
                details=result["errors"]
            )

        return result

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _archive_specialized_record(
        self,
        event: dict,
        event_type: str,
        event_archive_id: int
    ):
        """
        Routes known event types to specialized archive tables.

        Unknown event types are still preserved in the raw events table.
        """

        if event_type in [
            "avis_lite",
            "avis_detection",
            "birdnet_detection"
        ]:

            return self.event_manager.archive_avis_detection(
                event=event,
                event_archive_id=event_archive_id
            )

        if event_type in [
            "weather",
            "weather_event",
            "weather_record"
        ]:

            return self.event_manager.archive_weather_record(
                event=event,
                event_archive_id=event_archive_id
            )

        if event_type in [
            "telemetry",
            "telemetry_event",
            "node_health",
            "gps_coord",
            "pps_status"
        ]:

            return self.event_manager.archive_telemetry_record(
                event=event,
                event_archive_id=event_archive_id
            )

        if event_type in [
            "node_register",
            "node_registration",
            "node_registry_update"
        ]:

            return self.event_manager.archive_node_registry_record(
                event=event,
                event_archive_id=event_archive_id
            )

        if event_type in [
            "system_log",
            "system_warning",
            "system_error"
        ]:

            return self.event_manager.archive_system_log(
                event=event,
                event_archive_id=event_archive_id
            )

        return {
            "success": True,
            "data": {
                "specialized_archive_skipped": True,
                "reason": "No specialized archive table for this event type."
            },
            "debug": {},
            "errors": []
        }

    def _extract_event_type(
        self,
        event: dict
    ):
        """
        Extracts the event type from common EnviroPulse event locations.
        """

        if event.get(
            "event_type"
        ) is not None:

            return event.get(
                "event_type"
            )

        payload = event.get(
            "payload",
            {}
        )

        if isinstance(
            payload,
            dict
        ) and payload.get(
            "event_type"
        ) is not None:

            return payload.get(
                "event_type"
            )

        message = event.get(
            "message",
            {}
        )

        if isinstance(
            message,
            dict
        ) and message.get(
            "event_type"
        ) is not None:

            return message.get(
                "event_type"
            )

        return "unknown"

    def _classify_event_category(
        self,
        event_type: str
    ):
        """
        Assigns a broad archive category.
        """

        if event_type in [
            "avis_lite",
            "avis_detection",
            "birdnet_detection"
        ]:

            return "avis"

        if event_type in [
            "weather",
            "weather_event",
            "weather_record"
        ]:

            return "weather"

        if event_type in [
            "telemetry",
            "telemetry_event",
            "node_health",
            "gps_coord",
            "pps_status"
        ]:

            return "telemetry"

        if event_type in [
            "node_register",
            "node_registration",
            "node_registry_update"
        ]:

            return "node_registry"

        if event_type in [
            "tdoa_calc",
            "tdoa_result",
            "tdoa_candidate"
        ]:

            return "tdoa"

        if event_type in [
            "system_log",
            "system_warning",
            "system_error"
        ]:

            return "system"

        return "general"