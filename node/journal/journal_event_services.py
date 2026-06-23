# ============================================================
# journal_event_services.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Journal
#
# Role:
#   Event Services
#
# Purpose:
#   Own Journal event subscriptions for the node platform.
#
# Does:
#   - Document Journal event communication
#   - Register Journal subscriptions with the Event Bus
#   - Subscribe directly to observed node platform events
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

from __future__ import annotations


# ============================================================
# EVENT NAME DEFINITIONS
# ============================================================

# ------------------------------------------------------------
# Mode / command events
# ------------------------------------------------------------

SEND_NODE_CHANGE_MODE = "SEND_NODE_CHANGE_MODE"

# ------------------------------------------------------------
# Recording / TDOA events
# ------------------------------------------------------------

TDOA_RECORDING = "TDOA_RECORDING"
RECORDING_AVAILABLE = "RECORDING_AVAILABLE"
TDOA_REQUEST = "TDOA_REQUEST"
MICROPHONE_SYNCED = "MICROPHONE_SYNCED"

# ------------------------------------------------------------
# Communication state / event publications
# ------------------------------------------------------------

NETWORK_CONNECTED = "NETWORK_CONNECTED"
NETWORK_DISCONNECTED = "NETWORK_DISCONNECTED"
EVENT_SENT = "EVENT_SENT"

# ------------------------------------------------------------
# RTK / GPS / PPS state and coordinate events
# ------------------------------------------------------------

RTK_STATE = "RTK_STATE"
GPS_STATE = "GPS_STATE"
PPS_STATE = "PPS_STATE"
GPS_COORD = "GPS_COORD"

# ------------------------------------------------------------
# Environmental events
# ------------------------------------------------------------

ENVIRO_STATE = "ENVIRO_STATE"
ENVIRO_EVENT = "ENVIRO_EVENT"

# ------------------------------------------------------------
# BirdNET / node events
# ------------------------------------------------------------

AVIS_LITE = "AVIS_LITE"
NODE_REGISTER = "NODE_REGISTER"




# ============================================================
# EVENT GROUP DEFINITIONS
# ============================================================

JOURNAL_SUBSCRIPTIONS = (
    SEND_NODE_CHANGE_MODE,
    TDOA_RECORDING,
    RECORDING_AVAILABLE,
    NETWORK_CONNECTED,
    NETWORK_DISCONNECTED,
    EVENT_SENT,
    RTK_STATE,
    GPS_STATE,
    PPS_STATE,
    GPS_COORD,
    TDOA_REQUEST,
    ENVIRO_STATE,
    ENVIRO_EVENT,
    AVIS_LITE,
    NODE_REGISTER,
)

JOURNAL_PUBLICATIONS = ()


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class JournalEventServices:

    # ========================================================
    # EVENT COMMUNICATION INDEX
    # ========================================================
    #
    # SUBSCRIPTIONS
    #
    # SEND_NODE_CHANGE_MODE
    #     Mode command observed by Communication.
    #
    # TDOA_RECORDING
    #     Microphone publication after a TDOA_REQUEST is accepted.
    #
    # RECORDING_AVAILABLE
    #     Microphone publication after a normal recording is available.
    #
    # NETWORK_CONNECTED
    # NETWORK_DISCONNECTED
    #     Communication state publications.
    #
    # EVENT_SENT
    #     Communication event publication after an outbound message is sent.
    #
    # RTK_STATE
    # GPS_STATE
    # PPS_STATE
    #     RTK subsystem state publications.
    #
    # GPS_COORD
    #     RTK coordinate publication.
    #
    # TDOA_REQUEST
    #     Communication listener publication from the server request.
    #
    # ENVIRO_STATE
    # ENVIRO_EVENT
    #     Environmental subsystem publications.
    #
    # AVIS_LITE
    #     BirdNET detection publication.
    #
    # NODE_REGISTER
    #     Node registration publication.
    #
    # ========================================================
    #
    # PUBLICATIONS
    #
    # None.
    #
    # Journal is a terminal consumer.
    #
    # ========================================================

    SUBSCRIPTIONS = list(
        JOURNAL_SUBSCRIPTIONS
    )

    PUBLICATIONS = list(
        JOURNAL_PUBLICATIONS
    )

    # ========================================================
    # INIT
    # ========================================================

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
    # EVENT INDEX HELPERS
    # ========================================================

    def get_subscriptions(
        self
    ):

        return list(
            self.SUBSCRIPTIONS
        )

    def get_publications(
        self
    ):

        return list(
            self.PUBLICATIONS
        )
