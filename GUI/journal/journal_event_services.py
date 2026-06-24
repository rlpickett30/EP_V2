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
#   Connect the Journal subsystem to the GUI event bus.
#   Register Journal subscriptions for current GUI architecture events.
#   Keep Journal as a terminal observer for development visibility.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Register Journal subscriptions with the GUI event bus
#   - Subscribe Journal to GUI startup events
#   - Subscribe Journal to GUI operator mode-change events
#   - Subscribe Journal to listener events
#   - Subscribe Journal to Communication events
#   - Subscribe Journal to Node Repository events
#   - Forward observed events to journal_dispatcher.py
#
# Does NOT:
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
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging


# ============================================================
# EVENT NAME DEFINITIONS
# ============================================================

# ----------------------------
# GUI Startup Events
# ----------------------------

GUI_REGISTER = "GUI_REGISTER"

# ----------------------------
# Interface Mode Events
# ----------------------------

NETWORK_MODE_CHANGE = "NETWORK_MODE_CHANGE"
DETECTION_MODE_CHANGE = "DETECTION_MODE_CHANGE"
FEATURE_MODE_CHANGE = "FEATURE_MODE_CHANGE"

# ----------------------------
# Listener State Events
# ----------------------------

NODE_STATE_UPDATED = "NODE_STATE_UPDATED"
NODE_TDOA_STATE = "NODE_TDOA_STATE"

# ----------------------------
# Listener Event Events
# ----------------------------

SERVER_NODE_REGISTER = "SERVER_NODE_REGISTER"
SERVER_AVIS_LITE = "SERVER_AVIS_LITE"
SERVER_ENVIRO_EVENT = "SERVER_ENVIRO_EVENT"
SERVER_TDOA_CALC = "SERVER_TDOA_CALC"
SERVER_GPS_COORD = "SERVER_GPS_COORD"

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
# Node Repository State Events
# ----------------------------

REPOSITORY_STATE_UPDATE = "REPOSITORY_STATE_UPDATE"

# ----------------------------
# Node Repository Event Events
# ----------------------------

REPOSITORY_EVENT_UPDATE = "REPOSITORY_EVENT_UPDATE"
NEW_NODE_REGISTERED = "NEW_NODE_REGISTERED"


# ============================================================
# EVENT GROUP DEFINITIONS
# ============================================================

GUI_STARTUP_EVENTS = (
    GUI_REGISTER,
)

GUI_OPERATOR_MODE_CHANGE_EVENTS = (
    NETWORK_MODE_CHANGE,
    DETECTION_MODE_CHANGE,
    FEATURE_MODE_CHANGE,
)

LISTENER_EVENTS = (
    NODE_STATE_UPDATED,
    SERVER_NODE_REGISTER,
    SERVER_AVIS_LITE,
    SERVER_ENVIRO_EVENT,
    SERVER_TDOA_CALC,
    SERVER_GPS_COORD,
)

COMMUNICATION_EVENTS = (
    NETWORK_CONNECTED,
    NETWORK_DISCONNECTED,
    EVENT_SENT,
)

NODE_REPOSITORY_EVENTS = (
    REPOSITORY_STATE_UPDATE,
    REPOSITORY_EVENT_UPDATE,
    NEW_NODE_REGISTERED,
)

JOURNAL_SUBSCRIPTIONS = (
    GUI_STARTUP_EVENTS
    + GUI_OPERATOR_MODE_CHANGE_EVENTS
    + LISTENER_EVENTS
    + COMMUNICATION_EVENTS
    + NODE_REPOSITORY_EVENTS
)

JOURNAL_PUBLICATIONS = ()


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class JournalEventServices:
    """
    Event bus connector for the Journal subsystem.

    Journal is a terminal observer. It subscribes to approved platform
    events for visibility and forwards them to journal_dispatcher.py.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        dispatcher=None,
        debug=False
    ):

        self.event_bus = event_bus
        self.dispatcher = dispatcher
        self.debug = debug

    # ========================================================
    # SUBSCRIPTION REGISTRATION
    # ========================================================

    def register_subscriptions(
        self,
        dispatcher=None
    ):
        """
        Register all Journal subscriptions with the GUI event bus.
        """

        if dispatcher is not None:

            self.dispatcher = dispatcher

        for event_name in JOURNAL_SUBSCRIPTIONS:

            self._subscribe(
                event_name=event_name,
                callback=self._build_subscription_callback(
                    event_name
                )
            )

    def _subscribe(
        self,
        event_name,
        callback
    ):
        """
        Subscribe to one event on the GUI event bus.
        """

        self.event_bus.subscribe(
            event_name,
            callback
        )

        if self.debug:

            logging.info(
                "JournalEventServices subscribed to %s",
                event_name
            )

    def _build_subscription_callback(
        self,
        event_name
    ):
        """
        Build a callback that preserves the observed event name
        before forwarding the event to journal_dispatcher.py.
        """

        def callback(
            payload=None
        ):

            if self.dispatcher is None:

                logging.warning(
                    "JournalEventServices received %s but no dispatcher is attached.",
                    event_name
                )

                return

            event = self._normalize_journal_event(
                event_name=event_name,
                payload=payload
            )

            self.dispatcher.handle_event(
                event
            )

        return callback

    # ========================================================
    # NORMALIZATION
    # ========================================================

    def _normalize_journal_event(
        self,
        event_name,
        payload
    ) -> dict:
        """
        Ensure Journal receives a dictionary with event_type present.
        """

        if payload is None:

            event = {}

        elif isinstance(
            payload,
            dict
        ):

            event = dict(
                payload
            )

        else:

            event = {
                "value": payload
            }

        if not event.get(
            "event_type"
        ):

            event["event_type"] = event_name

        return event

    # ========================================================
    # EVENT INDEX HELPERS
    # ========================================================

    def get_subscriptions(
        self
    ):

        return list(
            JOURNAL_SUBSCRIPTIONS
        )

    def get_publications(
        self
    ):

        return list(
            JOURNAL_PUBLICATIONS
        )