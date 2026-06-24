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
    # FEATURE_MODE_CHANGE
    #
    # Published By:
    #     Communication listener after UDP decode
    #
    # Consumed By:
    #     Journal
    #
    # Purpose:
    #     Record GUI feature mode-change commands received by
    #     the Server from the operator interface.
    #
    # --------------------------------------------------------
    #
    # NETWORK_MODE_CHANGE
    #
    # Published By:
    #     Communication listener after UDP decode
    #
    # Consumed By:
    #     Journal
    #
    # Purpose:
    #     Record GUI network mode-change commands received by
    #     the Server from the operator interface.
    #
    # --------------------------------------------------------
    #
    # DETECTION_MODE_CHANGE
    #
    # Published By:
    #     Communication listener after UDP decode
    #
    # Consumed By:
    #     Journal
    #
    # Purpose:
    #     Record GUI detection mode-change commands received by
    #     the Server from the operator interface.
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

        "REGISTRY_UPDATED",
        "SERVER_NODE_REGISTER",
        
        "DATABASE_UPDATED",

        "GUI_REGISTER",
        "NODE_REGISTER",
        "FEATURE_MODE_CHANGE",
        "NETWORK_MODE_CHANGE",
        "DETECTION_MODE_CHANGE",

        "TDOA_CHANGE_MODE",
        "TDOA_MODE_UPDATED",
        "TDOA_NODE_STATE_UPDATED",
        "NODE_STATE_UPDATED",
        "NODE_TDOA_STATE",
        
        "COMMUNICATION_STATE",
        "SEND_NODE_CHANGE_MODE",
        "COMMUNICATION_CHANGE_MODE",
        "EVENT_SENT",
        
        "RTK_STATE",
        "GPS_STATE",
        "PPS_STATE",
        "ENVIRO_STATE",
        "NODE_TDOA_STATE",
        "NODE_STATE_UPDATED",
        
        "AVIS_LITE",
        "EVENT_QUEUED",
        "QUEUE_FLUSHED",

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