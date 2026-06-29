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
#   Own Communication event names, subscriptions, and publications.
#
# Does:
#   - Document Communication event flow
#   - Register Communication subscriptions with the Event Bus
#   - Publish accepted inbound listener events
#   - Publish internal Communication state events
#   - Keep current GUI and node communication events organized
#
# Does NOT:
#   - Send UDP packets
#   - Receive UDP packets
#   - Decode packets
#   - Store queued messages
#   - Make mode decisions
#   - Apply GUI commands
#   - Manage node registry state
#   - Perform Event Bus delivery logic
#
# Owner:
#   communication_dispatcher.py
#
# ============================================================


class CommunicationEventServices:

    # ========================================================
    # LISTENER PUBLICATIONS
    # ========================================================

    LISTENER_PUBLICATIONS = [

        "GUI_REGISTER",
        "NODE_REGISTER",

        "RTK_STATE",
        "GPS_STATE",
        "PPS_STATE",
        "ENVIRO_STATE",
        "MICROPHONE_SYNCED",

        "AVIS_LITE",
        "TDOA_RECORDING",
        "ENVIRO_EVENT",
        "GPS_COORD",

        "FEATURE_MODE_CHANGE",
        "NETWORK_MODE_CHANGE",
        "DETECTION_MODE_CHANGE"

    ]

    # ========================================================
    # INTERNAL PUBLICATIONS
    # ========================================================

    INTERNAL_PUBLICATIONS = [

        "NETWORK_CONNECTED",
        "NETWORK_DISCONNECTED",

        "COMMUNICATION_STATE",

        "EVENT_SENT",
        "EVENT_QUEUED",
        "QUEUE_FLUSHED"

    ]

    # ========================================================
    # MODE SUBSCRIPTIONS
    # ========================================================

    MODE_SUBSCRIPTIONS = [

        "COMMUNICATION_CHANGE_MODE",
        "SEND_NODE_CHANGE_MODE"

    ]

    # ========================================================
    # SENDER SUBSCRIPTIONS
    # ========================================================

    SENDER_SUBSCRIPTIONS = [

        "SERVER_NODE_REGISTER",
        "NODE_STATE_UPDATED",
        "NODE_TDOA_STATE",

        "SERVER_AVIS_LITE",
        "SERVER_ENVIRO_EVENT",
        "SERVER_GPS_COORD",

        "TDOA_REQUEST"
    ]

    # ========================================================
    # ALL PUBLICATIONS
    # ========================================================

    PUBLICATIONS = (

        LISTENER_PUBLICATIONS
        + INTERNAL_PUBLICATIONS

    )

    # ========================================================
    # ALL SUBSCRIPTIONS
    # ========================================================

    SUBSCRIPTIONS = (

        MODE_SUBSCRIPTIONS
        + SENDER_SUBSCRIPTIONS

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

            if event_name == "COMMUNICATION_CHANGE_MODE":

                self.event_bus.subscribe(
                    event_name,
                    dispatcher.handle_communication_change_mode
                )

            elif event_name == "SEND_NODE_CHANGE_MODE":

                self.event_bus.subscribe(
                    event_name,
                    dispatcher.handle_send_node_change_mode
                )

            elif event_name == "SERVER_NODE_REGISTER":

                self.event_bus.subscribe(
                    event_name,
                    dispatcher.handle_server_node_register
                )

            elif event_name == "NODE_STATE_UPDATED":

                self.event_bus.subscribe(
                    event_name,
                    dispatcher.handle_node_state_updated
                )

            elif event_name == "NODE_TDOA_STATE":

                self.event_bus.subscribe(
                    event_name,
                    dispatcher.handle_node_tdoa_state
                )

            elif event_name == "TDOA_REQUEST":

                self.event_bus.subscribe(
                    event_name,
                    dispatcher.handle_tdoa_request
                )

            elif event_name in [
                "SERVER_AVIS_LITE",
                "SERVER_ENVIRO_EVENT",
                "SERVER_GPS_COORD"
            ]:

                self.event_bus.subscribe(
                    event_name,
                    dispatcher.handle_node_event_to_gui
                )

    # ========================================================
    # CAN PUBLISH / SEND
    # ========================================================

    def can_publish(
        self,
        event_name: str
    ) -> bool:

        return event_name in self.PUBLICATIONS

    def can_send(
        self,
        event_name: str
    ) -> bool:

        return event_name in self.SENDER_SUBSCRIPTIONS

    # ========================================================
    # BUILD SERVER EVENT
    # ========================================================

    def build_server_event(
        self,
        event: dict
    ) -> dict:

        verified_event = dict(
            event
        )

        verified_event.setdefault(
            "source",
            "communication"
        )

        verified_event.setdefault(
            "target",
            "node"
        )

        return verified_event

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
    # PUBLISH COMMUNICATION STATE
    # ========================================================

    def publish_communication_state(
        self,
        state: dict
    ):

        event = {

            "event_type": "COMMUNICATION_STATE",
            "source": "communication",
            "payload": state

        }

        self.publish(
            "COMMUNICATION_STATE",
            event
        )

    # ========================================================
    # PUBLISH EVENT SENT
    # ========================================================

    def publish_event_sent(
        self,
        payload: dict
    ):

        event = {

            "event_type": "EVENT_SENT",
            "source": "communication",
            "payload": payload or {}

        }

        self.publish(
            "EVENT_SENT",
            event
        )

    # ========================================================
    # PUBLISH EVENT QUEUED
    # ========================================================

    def publish_event_queued(
        self,
        payload: dict
    ):

        event = {

            "event_type": "EVENT_QUEUED",
            "source": "communication",
            "payload": payload or {}

        }

        self.publish(
            "EVENT_QUEUED",
            event
        )

    # ========================================================
    # PUBLISH QUEUE FLUSHED
    # ========================================================

    def publish_queue_flushed(
        self,
        payload: dict
    ):

        event = {

            "event_type": "QUEUE_FLUSHED",
            "source": "communication",
            "payload": payload or {}

        }

        self.publish(
            "QUEUE_FLUSHED",
            event
        )
