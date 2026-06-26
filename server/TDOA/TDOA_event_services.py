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
# Purpose:
#   Connect the TDOA subsystem to the Event Bus.
#
# Owns:
#   - TDOA event-name constants
#   - TDOA Event Bus subscriptions
#   - TDOA Event Bus publications
#   - Inbound Event Bus payload normalization
#
# Does NOT:
#   - Interpret node readiness
#   - Decide TDOA capability
#   - Run candidate filtering
#   - Solve TDOA
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

# Mode events.
TDOA_CHANGE_MODE = "TDOA_CHANGE_MODE"
TDOA_MODE_UPDATED = "TDOA_MODE_UPDATED"

# Registry -> TDOA state events.
NODE_TDOA_STATE = "NODE_TDOA_STATE"
NODE_TDOA_CAPABLE_LOST = "NODE_TDOA_CAPABLE_LOST"

# TDOA -> rest of platform state events.
TDOA_NODE_STATE_UPDATED = "TDOA_NODE_STATE_UPDATED"
TDOA_CAPABLE = "TDOA_CAPABLE"
TDOA_CAPABLE_LOST = "TDOA_CAPABLE_LOST"

# Downstream event names are defined here so the dispatcher can reference
# canonical names without Event Services having to subscribe to them yet.
AVIS_LITE = "AVIS_LITE"
TDOA_RECORDING = "TDOA_RECORDING"
WEATHER_UPDATE = "WEATHER_UPDATE"

TDOA_CANDIDATE_READY = "TDOA_CANDIDATE_READY"
TDOA_CALC_REQUESTED = "TDOA_CALC_REQUESTED"
TDOA_CALC_COMPLETE = "TDOA_CALC_COMPLETE"
TDOA_CALC_FAILED = "TDOA_CALC_FAILED"
TDOA_STATE_UPDATED = "TDOA_STATE_UPDATED"

ENERGY_ONSET_MODE_CHANGED = "ENERGY_ONSET_MODE_CHANGED"
ENERGY_OFFSET_MODE_CHANGED = "ENERGY_OFFSET_MODE_CHANGED"
PATTERN_ONSET_MODE_CHANGED = "PATTERN_ONSET_MODE_CHANGED"
PATTERN_OFFSET_MODE_CHANGED = "PATTERN_OFFSET_MODE_CHANGED"
ONSET_FEATURE_MODE_CHANGED = "ONSET_FEATURE_MODE_CHANGED"
AMP_FEATURE_MODE_CHANGED = "AMP_FEATURE_MODE_CHANGED"


# ============================================================
# TDOA EVENT SERVICES
# ============================================================

class TDOAEventServices:
    """
    Own TDOA event bus subscriptions and publications.

    Current real subscriptions:
        - TDOA_CHANGE_MODE
        - NODE_TDOA_STATE

    Current real publications:
        - TDOA_MODE_UPDATED
        - TDOA_NODE_STATE_UPDATED
        - TDOA_CAPABLE
        - TDOA_CAPABLE_LOST
    """

    EVENT_TDOA_CHANGE_MODE = TDOA_CHANGE_MODE
    EVENT_TDOA_MODE_UPDATED = TDOA_MODE_UPDATED

    EVENT_NODE_TDOA_STATE = NODE_TDOA_STATE

    # Backward-compatible alias for older dispatcher wording.
    # NODE_TDOA_STATE is a state update, not only a "capable" event.
    EVENT_NODE_TDOA_CAPABLE = NODE_TDOA_STATE
    EVENT_NODE_TDOA_CAPABLE_LOST = NODE_TDOA_CAPABLE_LOST

    EVENT_TDOA_NODE_STATE_UPDATED = TDOA_NODE_STATE_UPDATED
    EVENT_TDOA_CAPABLE = TDOA_CAPABLE
    EVENT_TDOA_CAPABLE_LOST = TDOA_CAPABLE_LOST

    EVENT_AVIS_LITE = AVIS_LITE
    EVENT_TDOA_RECORDING = TDOA_RECORDING
    EVENT_WEATHER_UPDATE = WEATHER_UPDATE

    EVENT_TDOA_CANDIDATE_READY = TDOA_CANDIDATE_READY
    EVENT_TDOA_CALC_REQUESTED = TDOA_CALC_REQUESTED
    EVENT_TDOA_CALC_COMPLETE = TDOA_CALC_COMPLETE
    EVENT_TDOA_CALC_FAILED = TDOA_CALC_FAILED
    EVENT_TDOA_STATE_UPDATED = TDOA_STATE_UPDATED

    EVENT_ENERGY_ONSET_MODE_CHANGED = ENERGY_ONSET_MODE_CHANGED
    EVENT_ENERGY_OFFSET_MODE_CHANGED = ENERGY_OFFSET_MODE_CHANGED
    EVENT_PATTERN_ONSET_MODE_CHANGED = PATTERN_ONSET_MODE_CHANGED
    EVENT_PATTERN_OFFSET_MODE_CHANGED = PATTERN_OFFSET_MODE_CHANGED
    EVENT_ONSET_FEATURE_MODE_CHANGED = ONSET_FEATURE_MODE_CHANGED
    EVENT_AMP_FEATURE_MODE_CHANGED = AMP_FEATURE_MODE_CHANGED

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
        Register currently implemented TDOA subscriptions.
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

        self.event_bus.subscribe(
            NODE_TDOA_STATE,
            lambda payload: dispatcher.handle_event(
                self._build_inbound_event(
                    event_name=NODE_TDOA_STATE,
                    payload=payload
                )
            )
        )

        logging.info(
            "[TDOA_EVENT_SERVICES] Subscribed to NODE_TDOA_STATE"
        )
        
        self.event_bus.subscribe(
            AVIS_LITE,
            lambda payload: dispatcher.handle_event(
                self._build_inbound_event(
                    event_name=AVIS_LITE,
                    payload=payload
                )
            )
        )
        
        self.event_bus.subscribe(
            TDOA_RECORDING,
            lambda payload: dispatcher.handle_event(
                self._build_inbound_event(
                    event_name=TDOA_RECORDING,
                    payload=payload
                )
            )
        )
        
        self.event_bus.subscribe(
            WEATHER_UPDATE,
            lambda payload: dispatcher.handle_event(
                self._build_inbound_event(
                    event_name=WEATHER_UPDATE,
                    payload=payload
                )
            )
        )
        
    # ========================================================
    # PUBLICATIONS
    # ========================================================

    def publish_tdoa_mode_update(self, payload):
        """
        Publish TDOA_MODE_UPDATED after the manager applies a mode change.
        """

        self._publish(
            event_name=TDOA_MODE_UPDATED,
            payload=payload
        )

    def publish_tdoa_node_state_updated(self, payload):
        """
        Publish TDOA_NODE_STATE_UPDATED after TDOA accepts a
        registry-owned NODE_TDOA_STATE update into its own state model.
        """

        self._publish(
            event_name=TDOA_NODE_STATE_UPDATED,
            payload=payload
        )

    def publish_tdoa_capable(self, payload):
        """
        Publish TDOA_CAPABLE when the TDOA subsystem crosses into
        system-level candidate-ready status.
        """

        self._publish(
            event_name=TDOA_CAPABLE,
            payload=payload
        )

    def publish_tdoa_capable_lost(self, payload):
        """
        Publish TDOA_CAPABLE_LOST when the TDOA subsystem crosses out of
        system-level candidate-ready status.
        """

        self._publish(
            event_name=TDOA_CAPABLE_LOST,
            payload=payload
        )

    # --------------------------------------------------------
    # Downstream publisher placeholders.
    # These keep dispatcher ownership intact while downstream TDOA
    # events are wired in later passes.
    # --------------------------------------------------------

    def publish_tdoa_candidate_ready(self, payload):
        self._publish(
            event_name=TDOA_CANDIDATE_READY,
            payload=payload
        )

    def publish_tdoa_calc_requested(self, payload):
        self._publish(
            event_name=TDOA_CALC_REQUESTED,
            payload=payload
        )

    def publish_tdoa_calc_complete(self, payload):
        self._publish(
            event_name=TDOA_CALC_COMPLETE,
            payload=payload
        )

    def publish_tdoa_calc_failed(self, payload):
        self._publish(
            event_name=TDOA_CALC_FAILED,
            payload=payload
        )

    def publish_tdoa_state_update(self, payload):
        self._publish(
            event_name=TDOA_STATE_UPDATED,
            payload=payload
        )

    # ========================================================
    # INTERNAL PUBLICATION SUPPORT
    # ========================================================

    def _publish(self, event_name: str, payload):
        """
        Publish a normalized TDOA event package.
        """

        event_package = {
            "event_type": event_name,
            "source": "tdoa",
            "payload": payload or {}
        }

        self.event_bus.publish(
            event_name,
            event_package
        )

        logging.info(
            f"[TDOA_EVENT_SERVICES] Published {event_name}"
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
