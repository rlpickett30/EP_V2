# ============================================================
# node_repository_event_services.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Document Node Repository event communication
#   - Register Node Repository subscriptions
#   - Publish Node Repository events
#
# Does NOT:
#   - Make decisions
#   - Store data
#   - Interpret events
#   - Perform repository logic
#
# ============================================================


class NodeRepositoryEventServices:

    # ========================================================
    # EVENT COMMUNICATION INDEX
    # ========================================================
    #
    # SUBSCRIPTIONS
    #
    # NODE_REGISTER
    #   Published By:
    #       Listener
    #   Consumed By:
    #       Node Repository
    #   Purpose:
    #       Register node metadata and ensure node exists
    #       in repository registry, state, and event history.
    #
    # BMP390_ONLINE
    #   Published By:
    #       Listener
    #   Consumed By:
    #       Node Repository
    #   Purpose:
    #       Mark BMP390 pressure sensor online for a node.
    #
    # BMP390_OFFLINE
    #   Published By:
    #       Listener
    #   Consumed By:
    #       Node Repository
    #   Purpose:
    #       Mark BMP390 pressure sensor offline for a node.
    #
    # SHT45_ONLINE
    #   Published By:
    #       Listener
    #   Consumed By:
    #       Node Repository
    #   Purpose:
    #       Mark SHT45 temperature/humidity sensor online.
    #
    # SHT45_OFFLINE
    #   Published By:
    #       Listener
    #   Consumed By:
    #       Node Repository
    #   Purpose:
    #       Mark SHT45 temperature/humidity sensor offline.
    #
    # GPS_LOCK
    #   Published By:
    #       Listener
    #   Consumed By:
    #       Node Repository
    #   Purpose:
    #       Mark GPS lock active for a node.
    #
    # GPS_LOST
    #   Published By:
    #       Listener
    #   Consumed By:
    #       Node Repository
    #   Purpose:
    #       Mark GPS lock lost for a node.
    #
    # GPS_COORD
    #   Published By:
    #       Listener
    #   Consumed By:
    #       Node Repository
    #   Purpose:
    #       Update known GPS coordinate for a node.
    #
    # PPS_LOCK
    #   Published By:
    #       Listener
    #   Consumed By:
    #       Node Repository
    #   Purpose:
    #       Mark PPS timing lock active for a node.
    #
    # PPS_LOST
    #   Published By:
    #       Listener
    #   Consumed By:
    #       Node Repository
    #   Purpose:
    #       Mark PPS timing lock lost for a node.
    #
    # RTK_ONLINE
    #   Published By:
    #       Listener
    #   Consumed By:
    #       Node Repository
    #   Purpose:
    #       Mark RTK subsystem online for a node.
    #
    # PUBLICATIONS
    #
    # GUI_REGISTER
    #   Published By:
    #       Node Repository
    #   Consumed By:
    #       Interface
    #   Purpose:
    #       Publish a GUI-ready snapshot containing node
    #       registry information, current state, and recent events.
    #
    # ========================================================

    SUBSCRIPTIONS = [

        "NODE_REGISTER",

        "BMP390_ONLINE",

        "BMP390_OFFLINE",

        "SHT45_ONLINE",

        "SHT45_OFFLINE",

        "GPS_LOCK",

        "GPS_LOST",

        "GPS_COORD",

        "PPS_LOCK",

        "PPS_LOST",

        "RTK_ONLINE"

    ]

    PUBLICATIONS = [

        "GUI_REGISTER"

    ]

    def __init__(
        self,
        event_bus
    ):

        self.event_bus = event_bus

    # ========================================================
    # REGISTER SUBSCRIPTIONS
    # ========================================================

    def register_subscriptions(
        self,
        dispatcher
    ):

        for event_name in self.SUBSCRIPTIONS:

            self.event_bus.subscribe(
                event_name,
                dispatcher.handle_event
            )

    # ========================================================
    # PUBLISH GUI REGISTER
    # ========================================================

    def publish_gui_register(
        self,
        event: dict
    ):

        self.event_bus.publish(
            "GUI_REGISTER",
            event
        )