# ============================================================
# interface_event_services.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Document Interface communication
#   - Register Interface subscriptions
#   - Publish Interface events
#
# Does NOT:
#   - Make decisions
#   - Update GUI
#   - Store state
#
# ============================================================


class InterfaceEventServices:

    # ========================================================
    # EVENT COMMUNICATION INDEX
    # ========================================================
    #
    # SUBSCRIPTIONS
    #
    # GUI_REGISTER
    #
    # Published By:
    #     Node Repository
    #
    # Consumed By:
    #     Interface
    #
    # Purpose:
    #     Update GUI display.
    #
    # ========================================================
    #
    # PUBLICATIONS
    #
    # ENABLE_WIFI
    #
    # Published By:
    #     Interface
    #
    # Consumed By:
    #     Sender
    #
    # Purpose:
    #     Example GUI command.
    #
    # ========================================================

    SUBSCRIPTIONS = [

        "GUI_REGISTER"

    ]

    PUBLICATIONS = [

        "ENABLE_WIFI"

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

        self.event_bus.subscribe(
            "GUI_REGISTER",
            dispatcher.handle_repository_update
        )

    # ========================================================
    # ENABLE WIFI
    # ========================================================

    def publish_enable_wifi(
        self
    ):

        self.event_bus.publish(

            "ENABLE_WIFI",

            {
                "event_type":
                    "ENABLE_WIFI"
            }
        )