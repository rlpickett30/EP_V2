# ============================================================
# communication_event_services.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Node Communication
#
# Role:
#   Event Services
#
# Purpose:
#   Connect the node Communication subsystem to the local node event bus.
#   Register approved Communication subscriptions and publish approved
#   Communication outputs using canonical node communication event names.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Store canonical Communication event names
#   - Store Sender state subscription groups
#   - Store Sender event subscription groups
#   - Store Communication state subscription groups
#   - Store Communication mode subscription groups
#   - Store Listener publication groups
#   - Register approved local bus subscriptions
#   - Publish approved local bus events
#   - Publish NETWORK_CONNECTED events
#   - Publish NETWORK_DISCONNECTED events
#   - Publish EVENT_SENT events
#   - Publish TDOA_REQUEST events
#   - Publish SEND_NODE_CHANGE_MODE events
#   - Provide event index helper methods
#
# Does NOT:
#   - Send packets
#   - Receive packets
#   - Change Wi-Fi or LoRa modes
#   - Queue messages
#   - Inspect payload contents
#   - Make workflow decisions
#   - Manage Communication state
#   - Perform Event Bus delivery logic
#
# Owner:
#   communication_dispatcher.py
#
# ============================================================

from __future__ import annotations

import logging
from typing import Callable, Iterable


# ============================================================
# EVENT NAME DEFINITIONS
# ============================================================

# ----------------------------
# Sender State Subscriptions
# ----------------------------

PPS_STATE = "PPS_STATE"
ENVIRO_STATE = "ENVIRO_STATE"
RTK_STATE = "RTK_STATE"
GPS_STATE = "GPS_STATE"

# ----------------------------
# Sender Event Subscriptions
# ----------------------------

TDOA_RECORDING = "TDOA_RECORDING"
AVIS_LITE = "AVIS_LITE"
NODE_REGISTER = "NODE_REGISTER"
GPS_COORD = "GPS_COORD"
ENVIRO_EVENT = "ENVIRO_EVENT"
MICROPHONE_SYNCED = "MICROPHONE_SYNCED"
# ----------------------------
# Listener Event Publications
# ----------------------------

TDOA_REQUEST = "TDOA_REQUEST"

# ----------------------------
# Communication State Events
# ----------------------------

NETWORK_CONNECTED = "NETWORK_CONNECTED"
NETWORK_DISCONNECTED = "NETWORK_DISCONNECTED"

# ----------------------------
# Communication Event Events
# ----------------------------

EVENT_SENT = "EVENT_SENT"

# ----------------------------
# Communication / Listener Mode Events
# ----------------------------

SEND_NODE_CHANGE_MODE = "SEND_NODE_CHANGE_MODE"


# ============================================================
# EVENT GROUP DEFINITIONS
# ============================================================

SENDER_STATE_SUBSCRIPTIONS = (
    PPS_STATE,
    ENVIRO_STATE,
    RTK_STATE,
    GPS_STATE,
    MICROPHONE_SYNCED,
)

SENDER_EVENT_SUBSCRIPTIONS = (
    TDOA_RECORDING,
    AVIS_LITE,
    NODE_REGISTER,
    GPS_COORD,
    ENVIRO_EVENT,
)

COMMUNICATION_STATE_SUBSCRIPTIONS = (
    NETWORK_CONNECTED,
    NETWORK_DISCONNECTED,
)

COMMUNICATION_MODE_SUBSCRIPTIONS = (
    SEND_NODE_CHANGE_MODE,
)

COMMUNICATION_SUBSCRIPTIONS = (
    *SENDER_STATE_SUBSCRIPTIONS,
    *SENDER_EVENT_SUBSCRIPTIONS,
    *COMMUNICATION_STATE_SUBSCRIPTIONS,
    *COMMUNICATION_MODE_SUBSCRIPTIONS,
)

LISTENER_PUBLICATIONS = (
    TDOA_REQUEST,
    SEND_NODE_CHANGE_MODE,
)

COMMUNICATION_PUBLICATIONS = (
    NETWORK_CONNECTED,
    NETWORK_DISCONNECTED,
    EVENT_SENT,
    *LISTENER_PUBLICATIONS,
)

OUTBOUND_SEND_EVENTS = (
    *SENDER_STATE_SUBSCRIPTIONS,
    *SENDER_EVENT_SUBSCRIPTIONS,
)

INBOUND_LISTENER_EVENTS = (
    TDOA_REQUEST,
    SEND_NODE_CHANGE_MODE,
)


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class CommunicationEventServices:
    """
    Event bus connector for the node Communication subsystem.

    This class only registers subscriptions and publishes approved events.
    Workflow decisions belong to communication_dispatcher.py.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        dispatcher=None,
        debug: bool = False
    ):

        self.event_bus = event_bus
        self.dispatcher = dispatcher
        self.debug = debug

    # ========================================================
    # DEBUG
    # ========================================================

    def log(
        self,
        message: str
    ):

        if self.debug:

            logging.info(
                "[CommunicationEventServices] %s",
                message
            )

    # ========================================================
    # SUBSCRIPTION REGISTRATION
    # ========================================================

    def register_subscriptions(
        self
    ):
        """
        Register all node Communication subscriptions.
        """

        for event_type in COMMUNICATION_SUBSCRIPTIONS:

            self.subscribe(
                event_type=event_type,
                callback=self._build_subscription_callback(
                    event_type
                )
            )

    def subscribe(
        self,
        event_type: str,
        callback: Callable
    ):
        """
        Subscribe to one event on the local node event bus.
        """

        self.event_bus.subscribe(
            event_type,
            callback
        )

        self.log(
            f"Subscribed: {event_type}"
        )

    def _build_subscription_callback(
        self,
        event_type: str
    ):
        """
        Build a callback that forwards the event to the dispatcher.
        """

        def callback(event=None):

            if self.dispatcher is None:

                logging.warning(
                    "CommunicationEventServices received %s but no dispatcher is attached.",
                    event_type
                )

                return

            self.dispatcher.handle_bus_event(
                event_type=event_type,
                event=event
            )

        return callback

    # ========================================================
    # GENERIC PUBLICATION
    # ========================================================

    def publish(
        self,
        event: dict
    ):
        """
        Publish an approved Communication event to the local node event bus.
        """

        if not isinstance(
            event,
            dict
        ):

            raise TypeError(
                "CommunicationEventServices.publish requires an event dictionary."
            )

        event_type = event.get(
            "event_type"
        )

        if event_type not in COMMUNICATION_PUBLICATIONS:

            raise ValueError(
                f"CommunicationEventServices cannot publish unknown event: {event_type}"
            )

        try:

            self.event_bus.publish(
                event
            )

        except TypeError:

            # Compatibility with older buses that use publish(event_type, payload).
            self.event_bus.publish(
                event_type,
                event
            )

        self.log(
            f"Published: {event_type}"
        )

    # ========================================================
    # STATE PUBLICATIONS
    # ========================================================

    def publish_network_connected(
        self,
        event: dict
    ):

        self.publish(
            event
        )

    def publish_network_disconnected(
        self,
        event: dict
    ):

        self.publish(
            event
        )

    # ========================================================
    # EVENT PUBLICATIONS
    # ========================================================

    def publish_event_sent(
        self,
        event: dict
    ):

        self.publish(
            event
        )

    def publish_tdoa_request(
        self,
        event: dict
    ):

        self.publish(
            event
        )

    # ========================================================
    # MODE PUBLICATIONS
    # ========================================================

    def publish_send_node_change_mode(
        self,
        event: dict
    ):

        self.publish(
            event
        )

    # ========================================================
    # EVENT INDEX HELPERS
    # ========================================================

    def get_subscriptions(
        self
    ) -> list[str]:
        """
        Return the Communication subsystem subscription list.
        """

        return list(
            COMMUNICATION_SUBSCRIPTIONS
        )

    def get_publications(
        self
    ) -> list[str]:
        """
        Return the Communication subsystem publication list.
        """

        return list(
            COMMUNICATION_PUBLICATIONS
        )

    def get_outbound_send_events(
        self
    ) -> list[str]:
        """
        Return events the Sender side forwards to the server.
        """

        return list(
            OUTBOUND_SEND_EVENTS
        )

    def get_inbound_listener_events(
        self
    ) -> list[str]:
        """
        Return inbound events the Listener side may publish locally.
        """

        return list(
            INBOUND_LISTENER_EVENTS
        )

    def publish_allowed_events(
        self
    ) -> Iterable[str]:
        """
        Compatibility helper for quick index checks.
        """

        return COMMUNICATION_PUBLICATIONS
