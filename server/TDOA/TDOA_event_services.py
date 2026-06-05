# ============================================================
# TDOA_event_services.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Purpose:
#   Event communication layer for the TDOA subsystem.
#
# Owns:
#   - TDOA event subscriptions
#   - TDOA event publishing
#   - TDOA event-name constants
#
# Does NOT:
#   - Inspect payloads
#   - Make routing decisions
#   - Maintain state
#   - Solve TDOA
#   - Call managers directly
#
# Dispatcher owns workflow.
# Event services only connects TDOA to the event bus.
#
# ============================================================

import logging
from typing import Callable, Optional


class TDOAEventServices:
    """
    Event services for the TDOA subsystem.

    The dispatcher owns this class.
    """

    # ========================================================
    # SUBSCRIBED STATE EVENTS
    # ========================================================

    EVENT_NODE_TDOA_CAPABLE = "node_tdoa_capable"
    EVENT_NODE_TDOA_CAPABLE_LOST = "node_tdoa_capable_lost"

    # ========================================================
    # SUBSCRIBED DETECTION / DATA EVENTS
    # ========================================================

    EVENT_AVIS_LITE = "avis_lite"
    EVENT_TDOA_RECORDING = "tdoa_recording"
    EVENT_WEATHER_UPDATE = "weather_update"

    # ========================================================
    # SUBSCRIBED MODE EVENTS
    # ========================================================

    EVENT_ENERGY_ONSET_MODE_CHANGED = "energy_onset_mode_changed"
    EVENT_ENERGY_OFFSET_MODE_CHANGED = "energy_offset_mode_changed"

    EVENT_PATTERN_ONSET_MODE_CHANGED = "pattern_onset_mode_changed"
    EVENT_PATTERN_OFFSET_MODE_CHANGED = "pattern_offset_mode_changed"

    EVENT_ONSET_FEATURE_MODE_CHANGED = "onset_feature_mode_changed"
    EVENT_AMP_FEATURE_MODE_CHANGED = "amp_feature_mode_changed"

    # ========================================================
    # PUBLISHED TDOA EVENTS
    # ========================================================

    EVENT_TDOA_CAPABLE = "tdoa_capable"
    EVENT_TDOA_CAPABLE_LOST = "tdoa_capable_lost"

    EVENT_TDOA_CANDIDATE_READY = "tdoa_candidate_ready"
    EVENT_TDOA_CALC_REQUESTED = "tdoa_calc_requested"
    EVENT_TDOA_CALC_COMPLETE = "tdoa_calc_complete"
    EVENT_TDOA_CALC_FAILED = "tdoa_calc_failed"

    EVENT_TDOA_STATE_UPDATE = "tdoa_state_update"
    EVENT_TDOA_MODE_UPDATE = "tdoa_mode_update"

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus
    ):
        self.event_bus = event_bus

    # ========================================================
    # SUBSCRIPTIONS
    # ========================================================

    def register_subscriptions(
        self,
        callback: Callable[[dict], None]
    ) -> None:
        """
        Register all TDOA subsystem subscriptions.

        The callback should normally be:
            TDOA_dispatcher.handle_event

        Event services does not inspect events.
        It only tells the bus where TDOA receives mail.
        """

        subscribed_events = [
            # State from Registry
            self.EVENT_NODE_TDOA_CAPABLE,
            self.EVENT_NODE_TDOA_CAPABLE_LOST,

            # Detection / data events
            self.EVENT_AVIS_LITE,
            self.EVENT_TDOA_RECORDING,
            self.EVENT_WEATHER_UPDATE,

            # Mode changes
            self.EVENT_ENERGY_ONSET_MODE_CHANGED,
            self.EVENT_ENERGY_OFFSET_MODE_CHANGED,
            self.EVENT_PATTERN_ONSET_MODE_CHANGED,
            self.EVENT_PATTERN_OFFSET_MODE_CHANGED,
            self.EVENT_ONSET_FEATURE_MODE_CHANGED,
            self.EVENT_AMP_FEATURE_MODE_CHANGED
        ]

        for event_name in subscribed_events:
            self.event_bus.subscribe(
                event_name,
                callback
            )

            logging.info(
                f"TDOA subscribed to event: {event_name}"
            )

    # ========================================================
    # STATE PUBLISHERS
    # ========================================================

    def publish_tdoa_state_update(
        self,
        payload: dict
    ) -> None:
        """
        Publish current TDOA state snapshot.
        """

        self._publish(
            event_name=self.EVENT_TDOA_STATE_UPDATE,
            payload=payload
        )

    def publish_tdoa_capable(
        self,
        payload: dict
    ) -> None:
        """
        Publish that TDOA has enough capability to evaluate candidates.
        """

        self._publish(
            event_name=self.EVENT_TDOA_CAPABLE,
            payload=payload
        )

    def publish_tdoa_capable_lost(
        self,
        payload: dict
    ) -> None:
        """
        Publish that TDOA no longer has enough capability.
        """

        self._publish(
            event_name=self.EVENT_TDOA_CAPABLE_LOST,
            payload=payload
        )

    # ========================================================
    # CANDIDATE / CALC PUBLISHERS
    # ========================================================

    def publish_tdoa_candidate_ready(
        self,
        payload: dict
    ) -> None:
        """
        Publish that a valid TDOA candidate group exists.
        """

        self._publish(
            event_name=self.EVENT_TDOA_CANDIDATE_READY,
            payload=payload
        )

    def publish_tdoa_calc_requested(
        self,
        payload: dict
    ) -> None:
        """
        Publish that dispatcher has requested a TDOA calculation.
        """

        self._publish(
            event_name=self.EVENT_TDOA_CALC_REQUESTED,
            payload=payload
        )

    def publish_tdoa_calc_complete(
        self,
        payload: dict
    ) -> None:
        """
        Publish completed TDOA result.
        """

        self._publish(
            event_name=self.EVENT_TDOA_CALC_COMPLETE,
            payload=payload
        )

    def publish_tdoa_calc_failed(
        self,
        payload: dict
    ) -> None:
        """
        Publish failed TDOA calculation.
        """

        self._publish(
            event_name=self.EVENT_TDOA_CALC_FAILED,
            payload=payload
        )

    # ========================================================
    # MODE PUBLISHERS
    # ========================================================

    def publish_tdoa_mode_update(
        self,
        payload: dict
    ) -> None:
        """
        Publish current TDOA mode snapshot.
        """

        self._publish(
            event_name=self.EVENT_TDOA_MODE_UPDATE,
            payload=payload
        )

    # ========================================================
    # INTERNAL PUBLISH WRAPPER
    # ========================================================

    def _publish(
        self,
        event_name: str,
        payload: Optional[dict] = None
    ) -> None:
        """
        Standard publish wrapper.

        Keeps the outbound event shape consistent.
        """

        if payload is None:
            payload = {}

        event = {
            "source": "TDOA",
            "event_type": event_name,
            "payload": payload
        }

        self.event_bus.publish(
            event_name,
            event
        )

        logging.debug(
            f"TDOA published event: {event_name}"
        )