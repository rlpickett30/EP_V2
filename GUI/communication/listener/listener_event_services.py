# ============================================================
# listener_event_services.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Publish listener events                      check subscriptions
#
# Does NOT:
#   - Make decisions
#   - Store state
#   - Decode messages
#   - Route messages# ============================================================
# listener_event_services.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Document Listener communication
#   - Register Listener subscriptions
#   - Publish Listener events
#
# Does NOT:
#   - Make decisions
#   - Store state
#   - Decode messages
#   - Route messages
#
# ============================================================


class ListenerEventServices:

    # ========================================================
    # EVENT COMMUNICATION INDEX
    # ========================================================
    #
    # SUBSCRIPTIONS
    #
    # None
    #
    # Listener is primarily a publisher subsystem.
    #
    # ========================================================
    #
    # PUBLICATIONS
    #
    # BMP390_ONLINE
    # BMP390_OFFLINE
    #
    # SHT45_ONLINE
    # SHT45_OFFLINE
    #
    # RTK_ONLINE
    #
    # PPS_LOCK
    # PPS_LOST
    #
    # GPS_LOCK
    # GPS_LOST
    # GPS_COORD
    #
    # NETWORK_CONNECTED
    # NETWORK_DISCONNECTED
    #
    # TDOA_CALC
    # NODE_REGISTER
    # WEATHER
    # AVIS_LITE
    # EVENT_SENT
    #
    # ========================================================

    SUBSCRIPTIONS = []

    PUBLICATIONS = [

        "BMP390_ONLINE",
        "BMP390_OFFLINE",

        "SHT45_ONLINE",
        "SHT45_OFFLINE",

        "RTK_ONLINE",

        "PPS_LOCK",
        "PPS_LOST",

        "GPS_LOCK",
        "GPS_LOST",
        "GPS_COORD",

        "NETWORK_CONNECTED",
        "NETWORK_DISCONNECTED",

        "TDOA_CALC",
        "NODE_REGISTER",
        "WEATHER",
        "AVIS_LITE",
        "EVENT_SENT"

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
    # GENERIC PUBLISH
    # ========================================================

    def publish(
        self,
        event_name: str,
        event: dict
    ):

        self.event_bus.publish(
            event_name,
            event
        )
#
# ============================================================


