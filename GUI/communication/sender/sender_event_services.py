# ============================================================
# sender_event_services.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Document Sender communication
#   - Register Sender subscriptions
#   - Publish Sender events
#
# Does NOT:
#   - Make decisions
#   - Store state
#   - Send messages
#   - Manage queues
#
# ============================================================


class SenderEventServices:

    # ========================================================
    # EVENT COMMUNICATION INDEX
    # ========================================================
    #
    # SUBSCRIPTIONS
    #
    # NETWORK_CONNECTED
    # NETWORK_DISCONNECTED
    #
    # ENABLE_WIFI
    # DISABLE_WIFI
    #
    # ENABLE_LORA
    # DISABLE_LORA
    #
    # ENERGY_ONSET
    # ENERGY_OFFSET
    #
    # PATTERN_ONSET
    # PATTERN_OFFSET
    #
    # ONSET_FEATURE
    # AMP_FEATURE
    #
    # GUI_REGISTER
    #
    # ========================================================
    #
    # PUBLICATIONS
    #
    # NETWORK_CONNECTED
    # NETWORK_DISCONNECTED
    #
    # ========================================================

    SUBSCRIPTIONS = [

        "NETWORK_CONNECTED",
        "NETWORK_DISCONNECTED",

        "ENABLE_WIFI",
        "DISABLE_WIFI",

        "ENABLE_LORA",
        "DISABLE_LORA",

        "ENERGY_ONSET",
        "ENERGY_OFFSET",

        "PATTERN_ONSET",
        "PATTERN_OFFSET",

        "ONSET_FEATURE",
        "AMP_FEATURE",

        "GUI_REGISTER"

    ]

    PUBLICATIONS = [

        "NETWORK_CONNECTED",
        "NETWORK_DISCONNECTED"

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
    # NETWORK CONNECTED
    # ========================================================

    def publish_network_connected(
        self,
        event: dict
    ):

        self.event_bus.publish(
            "NETWORK_CONNECTED",
            event
        )

    # ========================================================
    # NETWORK DISCONNECTED
    # ========================================================

    def publish_network_disconnected(
        self,
        event: dict
    ):

        self.event_bus.publish(
            "NETWORK_DISCONNECTED",
            event
        )