# ============================================================
# node_repository_event_services.py
#
# EnviroPulse V2 GUI
#
# Subsystem:
#   Node Repository
#
# Role:
#   Event Services
#
# Purpose:
#   Connect the Node Repository subsystem to the GUI event bus.
#   Register Node Repository subscriptions.
#   Publish repository updates for the Interface.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Register Node Repository subscriptions
#   - Publish approved Node Repository events
#   - Preserve approved EnviroPulse GUI event names
#   - Forward subscribed events to node_repository_dispatcher.py
#
# Does NOT:
#   - Interpret event payloads
#   - Store node data
#   - Update node state
#   - Make repository decisions
#   - Render interface changes
#
# Owner:
#   node_repository_dispatcher.py
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
# Repository State Subscriptions
# ----------------------------

NODE_STATE_UPDATED = "NODE_STATE_UPDATED"

# ----------------------------
# Repository Event Subscriptions
# ----------------------------

SERVER_NODE_REGISTER = "SERVER_NODE_REGISTER"
SERVER_ENVIRO_EVENT = "SERVER_ENVIRO_EVENT"
SERVER_TDOA_CALC = "SERVER_TDOA_CALC"
SERVER_GPS_COORD = "SERVER_GPS_COORD"
SERVER_AVIS_LITE = "SERVER_AVIS_LITE"

# ----------------------------
# Repository State Publications
# ----------------------------

REPOSITORY_STATE_UPDATE = "REPOSITORY_STATE_UPDATE"

# ----------------------------
# Repository Event Publications
# ----------------------------

REPOSITORY_EVENT_UPDATE = "REPOSITORY_EVENT_UPDATE"
NEW_NODE_REGISTERED = "NEW_NODE_REGISTERED"


# ============================================================
# EVENT GROUP DEFINITIONS
# ============================================================

NODE_REPOSITORY_SUBSCRIPTIONS = (
    NODE_STATE_UPDATED,
    SERVER_NODE_REGISTER,
    SERVER_ENVIRO_EVENT,
    SERVER_TDOA_CALC,
    SERVER_GPS_COORD,
    SERVER_AVIS_LITE,
)

NODE_REPOSITORY_PUBLICATIONS = (
    REPOSITORY_STATE_UPDATE,
    REPOSITORY_EVENT_UPDATE,
    NEW_NODE_REGISTERED,
)


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class NodeRepositoryEventServices:
    """
    Event bus connector for the Node Repository subsystem.

    This class only registers subscriptions and publishes approved
    repository events. Repository decisions belong to the dispatcher.
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
        self
    ):
        """
        Register all Node Repository subscriptions with the GUI event bus.
        """

        for event_name in NODE_REPOSITORY_SUBSCRIPTIONS:

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
                "NodeRepositoryEventServices subscribed to %s",
                event_name
            )

    def _build_subscription_callback(
        self,
        event_name
    ):
        """
        Build a callback that forwards the event to the dispatcher.
        """

        def callback(
            payload=None
        ):

            if self.dispatcher is None:

                logging.warning(
                    "NodeRepositoryEventServices received %s but no dispatcher is attached.",
                    event_name
                )

                return

            self.dispatcher.handle_bus_event(
                event_name=event_name,
                payload=payload
            )

        return callback

    # ========================================================
    # GENERIC PUBLICATION
    # ========================================================

    def publish(
        self,
        event_name,
        payload=None
    ):
        """
        Publish an approved Node Repository event to the GUI event bus.
        """

        if event_name not in NODE_REPOSITORY_PUBLICATIONS:

            raise ValueError(
                f"NodeRepositoryEventServices cannot publish unknown event: {event_name}"
            )

        self.event_bus.publish(
            event_name,
            payload
        )

        if self.debug:

            logging.info(
                "NodeRepositoryEventServices published %s",
                event_name
            )

    # ========================================================
    # STATE PUBLICATIONS
    # ========================================================

    def publish_repository_state_update(
        self,
        payload=None
    ):

        self.publish(
            event_name=REPOSITORY_STATE_UPDATE,
            payload=payload
        )

    # ========================================================
    # EVENT PUBLICATIONS
    # ========================================================

    def publish_repository_event_update(
        self,
        payload=None
    ):

        self.publish(
            event_name=REPOSITORY_EVENT_UPDATE,
            payload=payload
        )

    def publish_new_node_registered(
        self,
        payload=None
    ):

        self.publish(
            event_name=NEW_NODE_REGISTERED,
            payload=payload
        )

    # ========================================================
    # EVENT INDEX HELPERS
    # ========================================================

    def get_subscriptions(
        self
    ):

        return list(
            NODE_REPOSITORY_SUBSCRIPTIONS
        )

    def get_publications(
        self
    ):

        return list(
            NODE_REPOSITORY_PUBLICATIONS
        )