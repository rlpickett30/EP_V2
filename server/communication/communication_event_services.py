# ============================================================
# communication_event_services.py
#
# EnviroPulse V2
#
# Communication Event Services
#
# Owner:
#   - Communication subsystem
#
# Responsibilities:
#   - Document Communication event flow
#   - Register Communication subscriptions
#   - Publish Communication events
#   - Keep listener, sender, and internal communication events organized
#   - Maintain verified SERVER_ event conversion names
#
# Does NOT:
#   - Send UDP packets
#   - Receive UDP packets
#   - Decode packets
#   - Store queued messages
#   - Make routing decisions
#   - Manage communication state
#
# Notes:
#   - Listener events are inbound events received from GUI or node.
#   - Sender events are outbound local requests that become verified SERVER_ events.
#   - Communication internal events describe communication health and transport state.
#   - This file should be updated every time a Communication event is added,
#     removed, or renamed.
#
# ============================================================


class CommunicationEventServices:

    # ========================================================
    # COMMUNICATION EVENT INDEX
    # ========================================================
    #
    # INTERNAL COMMUNICATION EVENTS
    #
    # These events describe Communication subsystem behavior.
    #
    # PUBLICATIONS:
    #
    #   NETWORK_CONNECTED
    #   NETWORK_DISCONNECTED
    #   NETWORK_DISABLED
    #   NETWORK_ENABLED
    #   EVENT_SENT
    #   EVENT_QUEUED
    #   QUEUE_FLUSHED
    #   COMMUNICATION_STATE
    #
    # ========================================================
    #
    # LISTENER EVENTS
    #
    # Listener receives outside messages from GUI or node.
    # Listener publishes the decoded and verified local event name.
    #
    # LISTENER PUBLICATIONS:
    #
    #   BMP390_ONLINE
    #   BMP390_OFFLINE
    #
    #   SHT45_ONLINE
    #   SHT45_OFFLINE
    #
    #   RTK_ONLINE
    #
    #   PPS_LOCK
    #   PPS_LOST
    #
    #   GPS_LOCK
    #   GPS_LOST
    #   GPS_COORD
    #
    #   WEATHER
    #   AVIS_LITE
    #   TDOA_CALC
    #
    #   NODE_REGISTER
    #   GUI_REGISTER
    #
    #   ENABLE_WIFI
    #   DISABLE_WIFI
    #
    #   ENABLE_LORA
    #   DISABLE_LORA
    #
    #   ENERGY_ONSET
    #   ENERGY_OFFSET
    #
    #   PATTERN_ONSET
    #   PATTERN_OFFSET
    #
    #   ONSET_FEATURE
    #   AMP_FEATURE
    #
    # ========================================================
    #
    # SENDER EVENTS
    #
    # Sender receives local events that must be sent outward.
    # Sender converts them into verified SERVER_ events before sending.
    #
    # SENDER SUBSCRIPTIONS:
    #
    #   BMP390_ONLINE
    #   BMP390_OFFLINE
    #
    #   SHT45_ONLINE
    #   SHT45_OFFLINE
    #
    #   RTK_ONLINE
    #
    #   PPS_LOCK
    #   PPS_LOST
    #
    #   GPS_LOCK
    #   GPS_LOST
    #   GPS_COORD
    #
    #   WEATHER
    #   AVIS_LITE
    #   TDOA_CALC
    #
    #   NODE_REGISTER
    #
    # SENDER VERIFIED OUTBOUND EVENTS:
    #
    #   SERVER_BMP390_ONLINE
    #   SERVER_BMP390_OFFLINE
    #
    #   SERVER_SHT45_ONLINE
    #   SERVER_SHT45_OFFLINE
    #
    #   SERVER_RTK_ONLINE
    #
    #   SERVER_PPS_LOCK
    #   SERVER_PPS_LOST
    #
    #   SERVER_GPS_LOCK
    #   SERVER_GPS_LOST
    #   SERVER_GPS_COORD
    #
    #   SERVER_WEATHER
    #   SERVER_AVIS_LITE
    #   SERVER_TDOA_CALC
    #
    #   SERVER_NODE_REGISTER
    #
    # ========================================================
    #
    # MODE EVENTS
    #
    # These are command-style events. Listener may publish them locally
    # when they arrive from GUI. Sender may send them outward if another
    # platform member needs to receive them.
    #
    # MODE EVENTS:
    #
    #   ENABLE_WIFI
    #   DISABLE_WIFI
    #
    #   ENABLE_LORA
    #   DISABLE_LORA
    #
    #   ENERGY_ONSET
    #   ENERGY_OFFSET
    #
    #   PATTERN_ONSET
    #   PATTERN_OFFSET
    #
    #   ONSET_FEATURE
    #   AMP_FEATURE
    #
    # ========================================================

    # ========================================================
    # INTERNAL PUBLICATIONS
    # ========================================================

    INTERNAL_PUBLICATIONS = [

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
    # LISTENER PUBLICATIONS
    # ========================================================

    LISTENER_PUBLICATIONS = [

        # --------------------------------------------
        # State
        # --------------------------------------------

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

        # --------------------------------------------
        # Event
        # --------------------------------------------

        "WEATHER",
        "AVIS_LITE",
        "TDOA_CALC",

        "NODE_REGISTER",
        "GUI_REGISTER",

        # --------------------------------------------
        # Mode
        # --------------------------------------------

        "ENABLE_WIFI",
        "DISABLE_WIFI",

        "ENABLE_LORA",
        "DISABLE_LORA",

        "ENERGY_ONSET",
        "ENERGY_OFFSET",

        "PATTERN_ONSET",
        "PATTERN_OFFSET",

        "ONSET_FEATURE",
        "AMP_FEATURE"

    ]

    # ========================================================
    # SENDER SUBSCRIPTIONS
    # ========================================================

    SENDER_SUBSCRIPTIONS = [

        # --------------------------------------------
        # State
        # --------------------------------------------

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

        # --------------------------------------------
        # Event
        # --------------------------------------------

        "WEATHER",
        "AVIS_LITE",
        "TDOA_CALC",

        "NODE_REGISTER",

        # --------------------------------------------
        # Mode
        # --------------------------------------------

        "ENABLE_WIFI",
        "DISABLE_WIFI",

        "ENABLE_LORA",
        "DISABLE_LORA",

        "ENERGY_ONSET",
        "ENERGY_OFFSET",

        "PATTERN_ONSET",
        "PATTERN_OFFSET",

        "ONSET_FEATURE",
        "AMP_FEATURE"

    ]

    # ========================================================
    # VERIFIED SERVER EVENT MAP
    # ========================================================
    #
    # These are the events that sender converts before sending.
    #
    # Example:
    #
    #   GPS_LOCK  -> SERVER_GPS_LOCK
    #
    # This protects the rest of the platform from confusing raw local
    # events with verified server-bound communication events.
    #
    # ========================================================

    SERVER_EVENT_MAP = {

        # --------------------------------------------
        # State
        # --------------------------------------------

        "BMP390_ONLINE":
            "SERVER_BMP390_ONLINE",

        "BMP390_OFFLINE":
            "SERVER_BMP390_OFFLINE",

        "SHT45_ONLINE":
            "SERVER_SHT45_ONLINE",

        "SHT45_OFFLINE":
            "SERVER_SHT45_OFFLINE",

        "RTK_ONLINE":
            "SERVER_RTK_ONLINE",

        "PPS_LOCK":
            "SERVER_PPS_LOCK",

        "PPS_LOST":
            "SERVER_PPS_LOST",

        "GPS_LOCK":
            "SERVER_GPS_LOCK",

        "GPS_LOST":
            "SERVER_GPS_LOST",

        "GPS_COORD":
            "SERVER_GPS_COORD",

        # --------------------------------------------
        # Event
        # --------------------------------------------

        "WEATHER":
            "SERVER_WEATHER",

        "AVIS_LITE":
            "SERVER_AVIS_LITE",

        "TDOA_CALC":
            "SERVER_TDOA_CALC",

        "NODE_REGISTER":
            "SERVER_NODE_REGISTER",

        # --------------------------------------------
        # Mode
        # --------------------------------------------

        "ENABLE_WIFI":
            "SERVER_ENABLE_WIFI",

        "DISABLE_WIFI":
            "SERVER_DISABLE_WIFI",

        "ENABLE_LORA":
            "SERVER_ENABLE_LORA",

        "DISABLE_LORA":
            "SERVER_DISABLE_LORA",

        "ENERGY_ONSET":
            "SERVER_ENERGY_ONSET",

        "ENERGY_OFFSET":
            "SERVER_ENERGY_OFFSET",

        "PATTERN_ONSET":
            "SERVER_PATTERN_ONSET",

        "PATTERN_OFFSET":
            "SERVER_PATTERN_OFFSET",

        "ONSET_FEATURE":
            "SERVER_ONSET_FEATURE",

        "AMP_FEATURE":
            "SERVER_AMP_FEATURE"

    }

    # ========================================================
    # ALL PUBLICATIONS
    # ========================================================

    PUBLICATIONS = (

        INTERNAL_PUBLICATIONS
        + LISTENER_PUBLICATIONS

    )

    # ========================================================
    # ALL SUBSCRIPTIONS
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

        return event_name in self.SERVER_EVENT_MAP

    # ========================================================
    # GET SERVER EVENT TYPE
    # ========================================================

    def get_server_event_type(
        self,
        event_name: str
    ) -> str:

        return self.SERVER_EVENT_MAP.get(
            event_name,
            event_name
        )

    # ========================================================
    # BUILD SERVER EVENT
    # ========================================================

    def build_server_event(
        self,
        event: dict
    ) -> dict:

        event_copy = dict(
            event
        )

        original_event_type = event_copy.get(
            "event_type"
        )

        server_event_type = (
            self.get_server_event_type(
                original_event_type
            )
        )

        event_copy[
            "source_event_type"
        ] = original_event_type

        event_copy[
            "event_type"
        ] = server_event_type

        event_copy[
            "verified_by"
        ] = "communication_sender"

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
            "communication_state": state

        }

        self.publish(
            "COMMUNICATION_STATE",
            event
        )