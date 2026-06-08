# ============================================================
# communication_event_services.py
#
# EnviroPulse V2
#
# Subsystem:
#   Communication
#
# Role:
#   Event Services
#
# Purpose:
#   Document GUI Communication event flow, register outbound
#   Communication subscriptions, publish inbound server events,
#   and convert local GUI outbound events into verified GUI_
#   events before they are sent to the server.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   Full communication config
#
# Does:
#   - Document GUI Communication publications and subscriptions
#   - Register Communication sender subscriptions
#   - Publish verified inbound SERVER_ events to the local event bus
#   - Publish internal Communication status events
#   - Convert local GUI outbound events into verified GUI_ events
#   - Maintain one shared SERVER_INBOUND_EVENTS list for listener
#     publications, repository subscriptions, and journal visibility
#
# Does NOT:
#   - Send UDP packets
#   - Receive UDP packets
#   - Decode packet payloads
#   - Store queued messages
#   - Make routing decisions
#   - Manage Communication state
#   - Update GUI display state
#   - Update repository state
#
# Owner:
#   communication_dispatcher.py
#
# ============================================================


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class CommunicationEventServices:

    # ========================================================
    # GUI COMMUNICATION EVENT INDEX
    # ========================================================
    #
    # This file is the event map for the GUI Communication
    # subsystem.
    #
    # The GUI Communication subsystem has four major event groups:
    #
    #   1. SERVER_INBOUND_EVENTS
    #      - Events received from the server by the GUI listener.
    #      - Listener publishes these onto the GUI event bus.
    #      - Repository subscribes to these same events.
    #      - Event Journal may subscribe to these for visibility.
    #
    #   2. COMMUNICATION_INTERNAL_EVENTS
    #      - Events describing Communication subsystem health.
    #
    #   3. INTERFACE_OUTBOUND_EVENTS
    #      - Local GUI events created by interface interaction.
    #      - Communication sender subscribes to these events.
    #
    #   4. GUI_EVENT_MAP
    #      - Converts local interface events into verified GUI_
    #        outbound events before sending them to the server.
    #
    # ========================================================

    # ========================================================
    # SERVER INBOUND EVENTS
    # ========================================================
    #
    # Publisher:
    #   Communication Listener
    #
    # Subscribers:
    #   Node Repository
    #   Interface, only if direct display is required
    #   Event Journal
    #
    # Purpose:
    #   These are verified server-originated events received by
    #   the GUI listener and published onto the local GUI event bus.
    #
    # Notes:
    #   This list is intentionally shared. Do not duplicate these
    #   same event names in a separate repository subscription list.
    #
    # ========================================================

    SERVER_INBOUND_EVENTS = [

        # --------------------------------------------
        # Server state
        # --------------------------------------------

        "SERVER_GNSS_STATE",
        "SERVER_ENVIRO_STATE",
        "SERVER_NODE_STATE",

        # --------------------------------------------
        # Server events
        # --------------------------------------------

        "SERVER_DETECTION_EVENT",
        "SERVER_ENVIRO_EVENT",
        "SERVER_TDOA_EVENT",
        "SERVER_GPS_EVENT",

        # --------------------------------------------
        # Registration
        # --------------------------------------------

        "SERVER_NODE_REGISTER"

    ]

    # ========================================================
    # COMMUNICATION INTERNAL EVENTS
    # ========================================================
    #
    # Publisher:
    #   Communication Dispatcher
    #
    # Subscribers:
    #   Interface
    #   Event Journal
    #
    # Purpose:
    #   These describe Communication subsystem behavior and health.
    #
    # ========================================================

    COMMUNICATION_INTERNAL_EVENTS = [

        "NETWORK_CONNECTED",
        "NETWORK_DISCONNECTED",

        "NETWORK_ENABLED",
        "NETWORK_DISABLED",

        "EVENT_SENT",
        "EVENT_QUEUED",
        "QUEUE_FLUSHED",

        "COMMUNICATION_STATE"

    ]

    # ========================================================
    # REPOSITORY PUBLICATIONS
    # ========================================================
    #
    # Publisher:
    #   Node Repository
    #
    # Subscribers:
    #   Interface
    #   Event Journal
    #
    # Purpose:
    #   These are display-ready repository updates created after
    #   the repository consumes SERVER_INBOUND_EVENTS.
    #
    # Notes:
    #   Communication does not publish these events. They are kept
    #   here as a shared event index so the GUI event structure stays
    #   readable from one location.
    #
    # ========================================================

    REPOSITORY_PUBLICATIONS = [

        "REPOSITORY_GNSS_UPDATE",
        "REPOSITORY_ENVIRO_UPDATE",
        "REPOSITORY_NODE_UPDATE"

    ]

    # ========================================================
    # GUI OUTBOUND EVENTS
    # ========================================================
    #
    # Publisher:
    #   Main
    #   Interface
    #
    # Subscriber:
    #   Communication Sender
    #
    # Purpose:
    #   These are local GUI-originated events that must be sent
    #   outward to the server.
    #
    # ========================================================

    GUI_OUTBOUND_EVENTS = [

        "GUI_REGISTER",

        "NETWORK_MODE_CHANGE",
        "DETECTION_MODE_CHANGE",
        "FEATURE_MODE_CHANGE"

    ]
    # ========================================================
    # JOURNAL SUBSCRIPTIONS
    # ========================================================
    #
    # Publisher:
    #   None
    #
    # Subscribers:
    #   Event Journal
    #
    # Purpose:
    #   This group gives the Event Journal broad visibility without
    #   making it part of workflow ownership.
    #
    # Notes:
    #   Event Journal should observe. It should not make routing or
    #   state decisions.
    #
    # ========================================================

    JOURNAL_SUBSCRIPTIONS = (

        SERVER_INBOUND_EVENTS
        + COMMUNICATION_INTERNAL_EVENTS
        + REPOSITORY_PUBLICATIONS
        + GUI_OUTBOUND_EVENTS

    )
    # ========================================================
    # LISTENER PUBLICATIONS
    # ========================================================
    #
    # Publisher:
    #   Communication Listener
    #
    # Subscribers:
    #   Node Repository
    #   Event Journal
    #
    # Purpose:
    #   These are events the Communication listener is allowed to
    #   publish after receiving and decoding inbound UDP messages.
    #
    # ========================================================

    LISTENER_PUBLICATIONS = (

        SERVER_INBOUND_EVENTS

    )

    # ========================================================
    # INTERNAL PUBLICATIONS
    # ========================================================
    #
    # Publisher:
    #   Communication Dispatcher
    #
    # Subscribers:
    #   Interface
    #   Event Journal
    #
    # Purpose:
    #   These are internal Communication publications.
    #
    # ========================================================

    INTERNAL_PUBLICATIONS = (

        COMMUNICATION_INTERNAL_EVENTS

    )

    # ========================================================
    # SENDER SUBSCRIPTIONS
    # ========================================================
    #
    # Publisher:
    #   Interface
    #
    # Subscriber:
    #   Communication Sender
    #
    # Purpose:
    #   These are local GUI events that must be sent outward to
    #   the server.
    #
    # ========================================================

    SENDER_SUBSCRIPTIONS = (

        GUI_OUTBOUND_EVENTS

    )

    # ========================================================
    # REPOSITORY SUBSCRIPTIONS
    # ========================================================
    #
    # Publisher:
    #   Communication Listener
    #
    # Subscriber:
    #   Node Repository
    #
    # Purpose:
    #   Repository consumes server inbound events and converts them
    #   into repository-owned display state.
    #
    # Notes:
    #   This intentionally reuses SERVER_INBOUND_EVENTS.
    #
    # ========================================================

    REPOSITORY_SUBSCRIPTIONS = (

        SERVER_INBOUND_EVENTS

    )

    # ========================================================
    # INTERFACE SUBSCRIPTIONS
    # ========================================================
    #
    # Publisher:
    #   Node Repository
    #   Communication Dispatcher
    #
    # Subscriber:
    #   Interface
    #
    # Purpose:
    #   Interface should mostly consume repository-ready updates
    #   and Communication health updates instead of raw server data.
    #
    # ========================================================

    INTERFACE_SUBSCRIPTIONS = (

        REPOSITORY_PUBLICATIONS
        + COMMUNICATION_INTERNAL_EVENTS

    )

    # ========================================================
    # VERIFIED GUI EVENT MAP
    # ========================================================
    #
    # These are the events Communication sender converts before
    # sending to the server.
    #
    # Example:
    #
    #   NETWORK_MODE_CHANGE -> GUI_NETWORK_MODE_CHANGE
    #
    # This protects the platform from confusing local interface
    # events with verified GUI-originated communication events.
    #
    # ========================================================

    GUI_EVENT_MAP = {

        "GUI_REGISTER":
            "GUI_REGISTER",

        "NETWORK_MODE_CHANGE":
            "GUI_NETWORK_MODE_CHANGE",

        "DETECTION_MODE_CHANGE":
            "GUI_DETECTION_MODE_CHANGE",

        "FEATURE_MODE_CHANGE":
            "GUI_FEATURE_MODE_CHANGE"

    }
    # ========================================================
    # ALL PUBLICATIONS
    # ========================================================
    #
    # Events this Communication subsystem is allowed to publish.
    #
    # ========================================================

    PUBLICATIONS = (

        LISTENER_PUBLICATIONS
        + INTERNAL_PUBLICATIONS

    )

    # ========================================================
    # ALL SUBSCRIPTIONS
    # ========================================================
    #
    # Events this Communication subsystem subscribes to.
    #
    # ========================================================

    SUBSCRIPTIONS = (

        SENDER_SUBSCRIPTIONS

    )

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
                dispatcher.handle_outbound_event
            )

    # ========================================================
    # CAN PUBLISH
    # ========================================================

    def can_publish(
        self,
        event_name: str
    ) -> bool:

        return event_name in self.PUBLICATIONS

    # ========================================================
    # CAN SEND
    # ========================================================

    def can_send(
        self,
        event_name: str
    ) -> bool:

        return event_name in self.GUI_EVENT_MAP

    # ========================================================
    # GET GUI EVENT TYPE
    # ========================================================

    def get_gui_event_type(
        self,
        event_name: str
    ) -> str:

        return self.GUI_EVENT_MAP.get(
            event_name,
            event_name
        )

    # ========================================================
    # BUILD GUI EVENT
    # ========================================================

    def build_gui_event(
        self,
        event: dict
    ) -> dict:

        event_copy = dict(
            event
        )

        original_event_type = event_copy.get(
            "event_type"
        )

        gui_event_type = (
            self.get_gui_event_type(
                original_event_type
            )
        )

        event_copy[
            "source_event_type"
        ] = original_event_type

        event_copy[
            "event_type"
        ] = gui_event_type

        event_copy[
            "verified_by"
        ] = "gui_communication_sender"

        event_copy[
            "source"
        ] = "gui"

        event_copy[
            "target"
        ] = "server"

        return event_copy

    # ========================================================
    # PUBLISH
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

    # ========================================================
    # PUBLISH LISTENER EVENT
    # ========================================================

    def publish_listener_event(
        self,
        event_name: str,
        event: dict
    ):

        if self.can_publish(
            event_name
        ):

            self.publish(
                event_name,
                event
            )

    # ========================================================
    # PUBLISH NETWORK CONNECTED
    # ========================================================

    def publish_network_connected(
        self,
        event: dict
    ):

        self.publish(
            "NETWORK_CONNECTED",
            event
        )

    # ========================================================
    # PUBLISH NETWORK DISCONNECTED
    # ========================================================

    def publish_network_disconnected(
        self,
        event: dict
    ):

        self.publish(
            "NETWORK_DISCONNECTED",
            event
        )

    # ========================================================
    # PUBLISH NETWORK ENABLED
    # ========================================================

    def publish_network_enabled(
        self,
        event: dict
    ):

        self.publish(
            "NETWORK_ENABLED",
            event
        )

    # ========================================================
    # PUBLISH NETWORK DISABLED
    # ========================================================

    def publish_network_disabled(
        self,
        event: dict
    ):

        self.publish(
            "NETWORK_DISABLED",
            event
        )

    # ========================================================
    # PUBLISH EVENT SENT
    # ========================================================

    def publish_event_sent(
        self,
        event: dict
    ):

        self.publish(
            "EVENT_SENT",
            event
        )

    # ========================================================
    # PUBLISH EVENT QUEUED
    # ========================================================

    def publish_event_queued(
        self,
        event: dict
    ):

        self.publish(
            "EVENT_QUEUED",
            event
        )

    # ========================================================
    # PUBLISH QUEUE FLUSHED
    # ========================================================

    def publish_queue_flushed(
        self,
        event: dict
    ):

        self.publish(
            "QUEUE_FLUSHED",
            event
        )

    # ========================================================
    # PUBLISH COMMUNICATION STATE
    # ========================================================

    def publish_communication_state(
        self,
        state: dict
    ):

        event = {

            "event_type": "COMMUNICATION_STATE",

            "source": "communication",

            "target": "gui",

            "payload": {

                "communication_state": state

            }

        }

        self.publish(
            "COMMUNICATION_STATE",
            event
        )