# ============================================================
# journal_event_services.py
#
# EnviroPulse V2 GUI
#
# Subsystem:
#   Journal
#
# Role:
#   Event Services
#
# Purpose:
#   Document Journal subscriptions and register Journal event
#   visibility with the local GUI event bus.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Document Journal subscriptions
#   - Register Journal subscriptions with the Event Bus
#   - Subscribe Journal to GUI startup events
#   - Subscribe Journal to GUI operator mode-change events
#   - Subscribe Journal to listener events
#   - Subscribe Journal to Communication internal events
#   - Subscribe Journal to Node Repository events
#   - Keep Journal as a terminal observer
#
# Does NOT:
#   - Import other subsystem event services
#   - Publish events
#   - Modify events
#   - Store journal entries
#   - Format journal entries
#   - Make routing decisions
#   - Manage platform state
#
# Owner:
#   journal_dispatcher.py
#
# ============================================================


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class JournalEventServices:

    # ========================================================
    # JOURNAL EVENT INDEX
    # ========================================================
    #
    # Journal is a terminal observer.
    #
    # Journal subscribes to selected platform events for
    # visibility, debugging, and development history.
    #
    # Journal does not publish events.
    #
    # ========================================================

    # ========================================================
    # GUI STARTUP EVENTS
    # ========================================================

    GUI_STARTUP_EVENTS = [

        "GUI_REGISTER"

    ]

    # ========================================================
    # GUI OPERATOR MODE CHANGE EVENTS
    # ========================================================
    #
    # Publisher:
    #   Interface
    #
    # Subscriber:
    #   Journal
    #
    # Purpose:
    #   Record operator mode-change requests before
    #   Communication sends them outward.
    #
    # ========================================================

    GUI_OPERATOR_MODE_CHANGE_EVENTS = [

        "NETWORK_MODE_CHANGE",
        "DETECTION_MODE_CHANGE",
        "FEATURE_MODE_CHANGE"

    ]

    # ========================================================
    # LISTENER EVENTS
    # ========================================================
    #
    # Publisher:
    #   Communication Listener
    #
    # Subscriber:
    #   Journal
    #
    # Purpose:
    #   Record verified inbound server events received by GUI.
    #
    # ========================================================

    LISTENER_EVENTS = [

        "SERVER_GNSS_STATE",
        "SERVER_ENVIRO_STATE",
        "SERVER_DETECTION_EVENT",
        "SERVER_ENVIRO_EVENT",
        "SERVER_TDOA_EVENT",
        "SERVER_GPS_EVENT",
        "SERVER_NODE_REGISTER"

    ]

    # ========================================================
    # COMMUNICATION EVENTS
    # ========================================================
    #
    # Publisher:
    #   Communication Dispatcher
    #
    # Subscriber:
    #   Journal
    #
    # Purpose:
    #   Record Communication subsystem health and send status.
    #
    # ========================================================

    COMMUNICATION_EVENTS = [

        "NETWORK_CONNECTED",
        "NETWORK_DISCONNECTED",

        "EVENT_SENT"

    ]

    # ========================================================
    # NODE REPOSITORY EVENTS
    # ========================================================
    #
    # Publisher:
    #   Node Repository
    #
    # Subscriber:
    #   Journal
    #
    # Purpose:
    #   Record repository updates after inbound server data has
    #   been processed into GUI-owned state.
    #
    # ========================================================

    NODE_REPOSITORY_EVENTS = [

        "REPOSITORY_STATE_UPDATE",
        "REPOSITORY_EVENT_UPDATE",
        "NEW_NODE_REGISTRY"

    ]

    # ========================================================
    # SUBSCRIPTIONS
    # ========================================================

    SUBSCRIPTIONS = (

        GUI_STARTUP_EVENTS
        + GUI_OPERATOR_MODE_CHANGE_EVENTS
        + LISTENER_EVENTS
        + COMMUNICATION_EVENTS
        + NODE_REPOSITORY_EVENTS

    )

    # ========================================================
    # PUBLICATIONS
    # ========================================================

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
