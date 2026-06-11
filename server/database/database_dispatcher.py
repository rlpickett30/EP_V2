# ============================================================
# database_dispatcher.py
#
# EnviroPulse V2
#
# Subsystem:
#   Database
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own the Database subsystem workflow.
#
# Does:
#   - Own Database managers
#   - Initialize the database schema
#   - Register Database event subscriptions through event services
#   - Receive SERVER_NODE_REGISTER
#   - Archive raw events first
#   - Route known event types to specialized archive tables
#
# Does NOT:
#   - Subscribe directly to the Event Bus
#   - Publish database status events
#   - Publish database warning events
#   - Modify registry state
#   - Maintain live GUI state
#   - Perform Event Bus delivery logic
#
# Owner:
#   Main / Subsystem root
#
# Current Scope:
#   SERVER_NODE_REGISTER
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
# EVENT NAMES
# ============================================================

SERVER_NODE_REGISTER = "SERVER_NODE_REGISTER"


# ============================================================
# DATABASE DISPATCHER
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
        self.started = False

        self.logger = logging.getLogger(
            self.__class__.__name__
        )

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
            config={
                "database": {
                    "debug": self.debug
                }
            }
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def start(
        self
    ):
        """
        Start the Database subsystem.

        Current startup responsibilities:
            - Initialize SQLite schema.
            - Register subscriptions declared in database_event_services.py.
        """

        if self.started:

            self._debug_log(
                "Database Dispatcher already started."
            )

            return self._result(
                success=True,
                data={
                    "database_started": True,
                    "already_started": True,
                    "subscribed_events": list(
                        self.event_services.SUBSCRIPTIONS
                    )
                }
            )

        schema_result = self.schema_manager.initialize_schema()

        if not schema_result.get("success"):

            self.logger.error(
                f"Database schema initialization failed: "
                f"{schema_result.get('errors', [])}"
            )

            return schema_result

        self.event_services.register_subscriptions(
            dispatcher=self
        )

        self.started = True

        self._debug_log(
            "Database Dispatcher started."
        )

        return self._result(
            success=True,
            data={
                "database_started": True,
                "schema_initialized": True,
                "subscribed_events": list(
                    self.event_services.SUBSCRIPTIONS
                )
            }
        )

    def stop(
        self
    ):
        """
        Mark the Database dispatcher as stopped.

        The current Event Bus does not expose unsubscribe handling here,
        so this is a local lifecycle marker only.
        """

        self.started = False

        self._debug_log(
            "Database Dispatcher stopped."
        )

        return self._result(
            success=True,
            data={
                "database_started": False
            }
        )

    # ========================================================
    # EVENT HANDLERS
    # ========================================================

    def handle_server_node_register(
        self,
        *args
    ):
        """
        Handle SERVER_NODE_REGISTER.

        Purpose:
            Archive a node identity after the Platform Registry accepts
            or refreshes the node registration.
        """

        event = self._build_event_from_args(
            fallback_event_name=SERVER_NODE_REGISTER,
            args=args
        )

        payload = event.get(
            "payload",
            {}
        )

        if not isinstance(
            payload,
            dict
        ):

            payload = {}

        payload.setdefault(
            "event_type",
            SERVER_NODE_REGISTER
        )

        payload.setdefault(
            "registry_action",
            payload.get("action")
        )

        payload.setdefault(
            "source_subsystem",
            event.get("source")
        )

        event["event_type"] = SERVER_NODE_REGISTER
        event["payload"] = payload

        return self.handle_event(
            event
        )

    def handle_event(
        self,
        event: dict
    ):
        """
        Archive an incoming database-facing event.

        Workflow:
            1. Validate event envelope.
            2. Classify event category.
            3. Archive raw event.
            4. Route to specialized archive table when known.
        """

        result = self._result()

        try:

            if not isinstance(
                event,
                dict
            ):

                return self._fail(
                    result,
                    "Database dispatcher received a non-dictionary event."
                )

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

            if not raw_archive_result.get("success"):

                return self._fail(
                    result,
                    "Raw event archive failed.",
                    raw_archive_result.get("errors", [])
                )

            event_archive_id = raw_archive_result.get(
                "data",
                {}
            ).get(
                "event_archive_id"
            )

            specialized_result = self._archive_specialized_record(
                event=event,
                event_type=event_type,
                event_archive_id=event_archive_id
            )

            result["success"] = True
            result["data"] = {
                "event_archive_id": event_archive_id,
                "event_type": event_type,
                "event_category": event_category,
                "specialized_archive": specialized_result
            }
            
            self.event_services.publish_database_updated(
                {
                    "reason": event_type,
                    "event_archive_id": event_archive_id,
                    "event_type": event_type,
                    "event_category": event_category,
                    "source_node_id": self.event_manager._extract_node_id(
                        event
                    ),
                    "specialized_archive": specialized_result
                }
            )
            
            if self.debug:

                result["debug"] = {
                    "raw_archive_result": raw_archive_result
                }

            if not specialized_result.get("success"):

                result["errors"].extend(
                    specialized_result.get(
                        "errors",
                        []
                    )
                )

                self.logger.warning(
                    f"Database specialized archive failed for {event_type}: "
                    f"{specialized_result.get('errors', [])}"
                )

            self._debug_log(
                f"Archived database event: {event_type}"
            )

        except Exception as error:

            self._fail(
                result,
                f"Database dispatcher failed: {error}"
            )

            self.logger.exception(
                f"Database dispatcher failed: {error}"
            )

        return result

    # ========================================================
    # INTERNAL METHODS: EVENT NORMALIZATION
    # ========================================================

    def _build_event_from_args(
        self,
        fallback_event_name: str,
        args
    ):
        """
        Build a normal event dictionary from common Event Bus
        callback styles.

        Supports:
            handler(payload)
            handler(event_name, payload)
        """

        if len(args) == 2:

            event_name = args[0] or fallback_event_name
            raw_event = args[1] or {}

        elif len(args) == 1:

            event_name = fallback_event_name
            raw_event = args[0] or {}

        else:

            event_name = fallback_event_name
            raw_event = {}

        if not isinstance(
            raw_event,
            dict
        ):

            raw_event = {}

        event = dict(raw_event)

        event.setdefault(
            "event_type",
            event_name
        )

        event.setdefault(
            "source",
            raw_event.get("source", "database_event_bus")
        )

        payload = event.get(
            "payload",
            {}
        )

        if isinstance(
            payload,
            dict
        ):

            payload.setdefault(
                "event_type",
                event.get("event_type", event_name)
            )

            event["payload"] = payload

        return event

    def _extract_event_type(
        self,
        event: dict
    ):
        """
        Extract event type from common EnviroPulse event locations.
        """

        if not isinstance(
            event,
            dict
        ):

            return "unknown"

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

    # ========================================================
    # INTERNAL METHODS: ARCHIVE ROUTING
    # ========================================================

    def _archive_specialized_record(
        self,
        event: dict,
        event_type: str,
        event_archive_id: int
    ):
        """
        Route known event types to specialized archive tables.

        Unknown event types are still preserved in the raw events table.
        """

        normalized_event_type = str(
            event_type or "unknown"
        ).strip().lower()

        if normalized_event_type in [
            "avis_lite",
            "avis_detection",
            "birdnet_detection"
        ]:

            return self.event_manager.archive_avis_detection(
                event=event,
                event_archive_id=event_archive_id
            )

        if normalized_event_type in [
            "weather",
            "weather_event",
            "weather_record",
            "enviro_event"
        ]:

            return self.event_manager.archive_weather_record(
                event=event,
                event_archive_id=event_archive_id
            )

        if normalized_event_type in [
            "telemetry",
            "telemetry_event",
            "node_health",
            "gps_coord",
            "gps_state",
            "pps_status",
            "pps_state",
            "enviro_state"
        ]:

            return self.event_manager.archive_telemetry_record(
                event=event,
                event_archive_id=event_archive_id
            )

        if normalized_event_type in [
            "server_node_register",
            "node_register",
            "node_registration",
            "node_registry_update"
        ]:

            return self.event_manager.archive_node_registry_record(
                event=event,
                event_archive_id=event_archive_id
            )

        if normalized_event_type in [
            "system_log",
            "system_warning",
            "system_error"
        ]:

            return self.event_manager.archive_system_log(
                event=event,
                event_archive_id=event_archive_id
            )

        return self._result(
            success=True,
            data={
                "specialized_archive_skipped": True,
                "reason": "No specialized archive table for this event type."
            }
        )

    def _classify_event_category(
        self,
        event_type: str
    ):
        """
        Assign a broad archive category.
        """

        normalized_event_type = str(
            event_type or "unknown"
        ).strip().lower()

        if normalized_event_type in [
            "avis_lite",
            "avis_detection",
            "birdnet_detection"
        ]:

            return "avis"

        if normalized_event_type in [
            "weather",
            "weather_event",
            "weather_record",
            "enviro_event"
        ]:

            return "weather"

        if normalized_event_type in [
            "telemetry",
            "telemetry_event",
            "node_health",
            "gps_coord",
            "gps_state",
            "pps_status",
            "pps_state",
            "enviro_state"
        ]:

            return "telemetry"

        if normalized_event_type in [
            "server_node_register",
            "node_register",
            "node_registration",
            "node_registry_update"
        ]:

            return "node_registry"

        if normalized_event_type in [
            "tdoa_calc",
            "tdoa_result",
            "tdoa_candidate",
            "tdoa_recording"
        ]:

            return "tdoa"

        if normalized_event_type in [
            "system_log",
            "system_warning",
            "system_error"
        ]:

            return "system"

        return "general"

    # ========================================================
    # INTERNAL METHODS: RESULTS AND DEBUG
    # ========================================================

    def _result(
        self,
        success: bool = False,
        data: dict = None,
        debug: dict = None,
        errors: list = None
    ):
        """
        Return a standard Database dispatcher result.
        """

        return {
            "success": success,
            "data": data or {},
            "debug": debug or {},
            "errors": errors or []
        }

    def _fail(
        self,
        result: dict,
        message: str,
        errors: list = None
    ):
        """
        Add failure information to a result dictionary.
        """

        result["success"] = False
        result["errors"].append(
            message
        )

        if errors:

            result["errors"].extend(
                errors
            )

        self.logger.warning(
            message
        )

        return result

    def _debug_log(
        self,
        message: str
    ):
        """
        Emit debug logs when enabled.
        """

        if self.debug:

            self.logger.debug(
                message
            )
