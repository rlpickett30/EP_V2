# ============================================================
# TDOA_event_services.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   TDOA
#
# Role:
#   Event Services
#
# Current Purpose:
#   Connect the TDOA subsystem to the Event Bus.
#
# Currently Known Events:
#   Subscribes:
#       TDOA_CHANGE_MODE
#
#   Publishes:
#       TDOA_MODE_UPDATE
#
# Philosophy:
#   This file only handles events that are currently implemented.
#   Future events should be added only when they become real.
#
# ============================================================


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging
from typing import Optional


# ============================================================
# EVENT NAMES
# ============================================================

TDOA_CHANGE_MODE = "TDOA_CHANGE_MODE"
TDOA_MODE_UPDATE = "TDOA_MODE_UPDATE"


# ============================================================
# TDOA EVENT SERVICES
# ============================================================

class TDOAEventServices:
    """
    Owns TDOA event bus subscriptions and publications.

    Current responsibility:
        - Subscribe TDOA dispatcher to TDOA_CHANGE_MODE.
        - Publish TDOA_MODE_UPDATE after the TDOA manager applies a mode change.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self, event_bus):
        self.event_bus = event_bus

    # ========================================================
    # SUBSCRIPTIONS
    # ========================================================

    def register_subscriptions(self, dispatcher):
        """
        Register known TDOA subscriptions.
        """

        self.event_bus.subscribe(
            TDOA_CHANGE_MODE,
            lambda payload: dispatcher.handle_tdoa_change_mode(
                self._build_inbound_event(
                    event_name=TDOA_CHANGE_MODE,
                    payload=payload
                )
            )
        )

        logging.info(
            "[TDOA_EVENT_SERVICES] Subscribed to TDOA_CHANGE_MODE"
        )

    # ========================================================
    # PUBLICATIONS
    # ========================================================

    def publish_tdoa_mode_update(self, payload):
        """
        Publish TDOA_MODE_UPDATE after the manager applies a mode change.
        """

        event_package = {
            "source": "tdoa",
            "payload": payload or {}
        }

        self.event_bus.publish(
            TDOA_MODE_UPDATE,
            event_package
        )

        logging.info(
            "[TDOA_EVENT_SERVICES] Published TDOA_MODE_UPDATE"
        )

    # ========================================================
    # INBOUND EVENT NORMALIZATION
    # ========================================================

    def _build_inbound_event(
        self,
        event_name: str,
        payload: Optional[dict] = None
    ):
        """
        Normalize inbound Event Bus payload into a dispatcher event.

        The server Event Bus delivers callback(payload), so Event Services
        restores the event_type before passing it to the dispatcher.
        """

        if payload is None:
            payload = {}

        if not isinstance(payload, dict):
            payload = {
                "payload": payload
            }

        source = payload.get(
            "source",
            "unknown"
        )

        inner_payload = payload.get(
            "payload",
            payload
        )

        return {
            "event_type": event_name,
            "source": source,
            "payload": inner_payload,
            "raw_event": payload
        }