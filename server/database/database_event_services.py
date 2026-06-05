# ============================================================
# database_event_services.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Database
#
# Role:
#   Event Services
#
# Purpose:
#   Connect the database subsystem to the EnviroPulse event bus.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Subscribes the database dispatcher to archive-worthy events
#   - Publishes database status events
#   - Publishes database warning events
#
# Does NOT:
#   - Interpret event payloads
#   - Write database records
#   - Open SQLite connections
#   - Create database tables
#   - Maintain live system state
#
# Owner:
#   database_dispatcher.py
#
# ============================================================

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging
from datetime import datetime, timezone


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class DatabaseEventServices:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        dispatcher,
        debug: bool = False
    ):

        self.event_bus = event_bus
        self.dispatcher = dispatcher
        self.debug = debug

        self.archive_event_names = [
            "node_register",
            "node_registration",
            "node_registry_update",

            "avis_lite",
            "avis_detection",
            "birdnet_detection",

            "gps_coord",

            "weather",
            "weather_event",
            "weather_record",

            "telemetry",
            "telemetry_event",
            "node_health",
            "pps_status",

            "tdoa_calc",
            "tdoa_result",
            "tdoa_candidate",

            "system_log",
            "system_warning",
            "system_error"
        ]

    # ========================================================
    # PUBLIC API
    # ========================================================

    def subscribe_to_events(
        self
    ):
        """
        Subscribes the database dispatcher to archive-worthy events.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        try:

            for event_name in self.archive_event_names:

                self.event_bus.subscribe(
                    event_name,
                    self.dispatcher.handle_event
                )

            result["success"] = True

            result["data"] = {
                "subscribed_events": self.archive_event_names
            }

            if self.debug:
                logging.info(
                    f"Database subscribed to events: {self.archive_event_names}"
                )

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Database event subscription failed: {error}"
            )

        return result

    def publish_database_status(
        self,
        status: str,
        details: dict = None
    ):
        """
        Publishes a database status event.
        """

        event = {
            "event_type": "database_status",
            "source_subsystem": "database",
            "status": status,
            "timestamp_utc": self._utc_now(),
            "payload": {
                "details": details or {}
            }
        }

        return self._publish(
            event_name="database_status",
            event=event
        )

    def publish_database_warning(
        self,
        warning_type: str,
        details=None
    ):
        """
        Publishes a database warning event.
        """

        event = {
            "event_type": "database_warning",
            "source_subsystem": "database",
            "warning_type": warning_type,
            "timestamp_utc": self._utc_now(),
            "payload": {
                "details": details
            }
        }

        return self._publish(
            event_name="database_warning",
            event=event
        )

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _publish(
        self,
        event_name: str,
        event: dict
    ):
        """
        Publishes an event through the event bus.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        try:

            self.event_bus.publish(
                event_name,
                event
            )

            result["success"] = True

            result["data"] = {
                "published_event": event_name
            }

            if self.debug:
                result["debug"] = {
                    "event": event
                }

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Database event publish failed: {error}"
            )

        return result

    def _utc_now(
        self
    ):
        """
        Returns the current UTC time in ISO-8601 format.
        """

        return datetime.now(
            timezone.utc
        ).isoformat()

