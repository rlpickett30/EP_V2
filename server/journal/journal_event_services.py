# ============================================================
# journal_event_services.py
#
# EnviroPulse V2
#
# Subsystem:
#   Journal
#
# Role:
#   Event Services
#
# Purpose:
#   Own Journal event subscriptions.
#
# Does:
#   - Document Journal event communication
#   - Register Journal subscriptions with the Event Bus
#   - Subscribe directly to observed platform events
#
# Does NOT:
#   - Publish events
#   - Make decisions
#   - Store data
#   - Import Communication event services
#   - Perform Event Bus delivery logic
#
# Owner:
#   journal_dispatcher.py
#
# ============================================================


class JournalEventServices:

    # ========================================================
    # EVENT COMMUNICATION INDEX
    # ========================================================
    #
    # SUBSCRIPTIONS
    #
    # GUI_REGISTER
    #
    # Published By:
    #     Communication listener after UDP decode
    #
    # Consumed By:
    #     Journal
    #
    # Purpose:
    #     Prove that the GUI startup registration event crossed
    #     from GUI UDP output into the Server local event bus.
    #
    # --------------------------------------------------------
    #
    # COMMUNICATION_STATE
    #
    # Published By:
    #     Communication dispatcher
    #
    # Consumed By:
    #     Journal
    #
    # Purpose:
    #     Record Communication receive statistics while testing.
    #
    # ========================================================
    #
    # PUBLICATIONS
    #
    # None
    #
    # Journal is a terminal consumer.
    #
    # ========================================================

    SUBSCRIPTIONS = [

        "GUI_REGISTER",
        "COMMUNICATION_STATE"

    ]

    PUBLICATIONS = []

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