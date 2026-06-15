# ============================================================
# database_event_services.py
#
# EnviroPulse V2
#
# Subsystem:
#   Database
#
# Role:
#   Event Services
#
# Purpose:
#   Own Database event names, subscriptions, and publications.
#
# Does:
#   - Document Database event flow
#   - Register Database subscriptions with the Event Bus
#   - Route accepted database events to the Database dispatcher
#
# Does NOT:
#   - Write directly to the database
#   - Decide whether records already exist
#   - Modify registry state
#   - Publish registry events
#   - Perform Event Bus delivery logic
#
# Owner:
#   database_dispatcher.py
#
# Current Scope:
#   Subscribe to SERVER_NODE_REGISTER so the database can create
#   or update known node records.
#
# ============================================================


# ============================================================
# EVENT NAMES
# ============================================================

SERVER_NODE_REGISTER = "SERVER_NODE_REGISTER"

SERVER_AVIS_LITE = "SERVER_AVIS_LITE"
SERVER_ENVIRO_EVENT = "SERVER_ENVIRO_EVENT"
SERVER_GPS_COORD = "SERVER_GPS_COORD"

DATABASE_UPDATED = "DATABASE_UPDATED"

# ============================================================
# DATABASE EVENT SERVICES
# ============================================================

class DatabaseEventServices:
    """
    Owns Database event bus subscriptions and publications.

    Current responsibility:
        - Subscribe dispatcher to SERVER_NODE_REGISTER.
    """

    # ========================================================
    # SUBSCRIPTIONS
    # ========================================================

    SUBSCRIPTIONS = [

        SERVER_NODE_REGISTER,

        SERVER_AVIS_LITE,
        SERVER_ENVIRO_EVENT,
        SERVER_GPS_COORD

    ]

    # ========================================================
    # PUBLICATIONS
    # ========================================================

    PUBLICATIONS = [
        
        DATABASE_UPDATED
    
    ]

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        config=None
    ):

        self.event_bus = event_bus
        self.config = config or {}

        database_config = self.config.get(
            "database",
            {}
        )

        self.debug = database_config.get(
            "debug",
            False
        )

    # ========================================================
    # REGISTER SUBSCRIPTIONS
    # ========================================================

    def register_subscriptions(
        self,
        dispatcher
    ):
        """
        Register known Database subscriptions.
        """

        for event_name in self.SUBSCRIPTIONS:

            if event_name == SERVER_NODE_REGISTER:

                self.event_bus.subscribe(
                    event_name,
                    dispatcher.handle_server_node_register
                )

                self._debug_print(
                    "Subscribed to SERVER_NODE_REGISTER"
                )

            elif event_name in [
                SERVER_AVIS_LITE,
                SERVER_ENVIRO_EVENT,
                SERVER_GPS_COORD
            ]:

                self.event_bus.subscribe(
                    event_name,
                    dispatcher.handle_server_platform_event
                )

                self._debug_print(
                    f"Subscribed to {event_name}"
                )
                
    # ========================================================
    # PUBLISH DATABASE UPDATED
    # ========================================================

    def publish_database_updated(
        self,
        payload: dict
    ):
        """
        Publish DATABASE_UPDATED after the database successfully
        handles an accepted database-facing event.
        """

        event = {
            "event_type": DATABASE_UPDATED,
            "source": "database",
            "payload": payload or {}
        }

        self.event_bus.publish(
            DATABASE_UPDATED,
            event
        )

        self._debug_print(
            "Published DATABASE_UPDATED"
        )

    # ========================================================
    # CAN PUBLISH
    # ========================================================

    def can_publish(
        self,
        event_name: str
    ) -> bool:
        """
        Return True when Database is allowed to publish event_name.
        """

        return event_name in self.PUBLICATIONS

    # ========================================================
    # DEBUG
    # ========================================================

    def _debug_print(
        self,
        message: str
    ):
        """
        Print lightweight debug output when enabled.
        """

        if self.debug:

            print(
                f"[DATABASE_EVENT_SERVICES] {message}"
            )