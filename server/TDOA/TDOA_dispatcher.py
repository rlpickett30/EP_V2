# ============================================================
# TDOA_dispatcher.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   TDOA
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own TDOA subsystem workflow.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["tdoa_dispatcher"]
#
# Does:
#   - Create and own TDOA_event_services.py
#   - Create and own TDOA_state_manager.py
#   - Create and own candidate_filter.py
#   - Create and own TDOA_manager.py
#   - Receive subscribed TDOA events
#   - Track recent avis_lite events
#   - Ask candidate_filter.py for valid TDOA candidates
#   - Call TDOA_manager.py only after a valid candidate exists
#   - Publish TDOA state, candidate, result, and failure events
#
# Does NOT:
#   - Solve TDOA directly
#   - Publish directly to Event Bus
#   - Perform candidate filtering internally
#   - Maintain node-state truth directly
#   - Own Platform Registry state
#
# Owner:
#   Main / Subsystem root
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from TDOA.TDOA_event_services import TDOAEventServices
from TDOA.TDOA_state_manager import TDOAStateManager
from TDOA.candidate_filter import CandidateFilter

# Future manager import.
# TDOA_manager.py must provide:
#
#   class TDOAManager:
#       def update_mode(self, mode_name: str, mode_value: Any) -> dict | None:
#           ...
#
#       def update_weather(self, weather_event: dict) -> dict | None:
#           ...
#
#       def store_tdoa_recording(self, recording_event: dict) -> dict | None:
#           ...
#
#       def tdoa_estimate(self, candidate: dict) -> dict:
#           ...
#
from TDOA.TDOA_manager import TDOAManager

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import json
import logging

from pathlib import Path
from typing import Optional, List


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class TDOADispatcher:
    """
    Main workflow owner for the TDOA subsystem.
    """

    def __init__(
        self,
        event_bus,
        config_path: Optional[str] = None
    ):

        self.config = self._load_config(config_path)

        dispatcher_config = self.config.get(
            "tdoa_dispatcher",
            {}
        )

        self.enable_candidate_filter = dispatcher_config.get(
            "enable_candidate_filter",
            True
        )

        self.enable_debug_logging = dispatcher_config.get(
            "enable_debug_logging",
            True
        )

        self.max_recent_avis_lite_events = dispatcher_config.get(
            "max_recent_avis_lite_events",
            250
        )

        self.recent_avis_lite_events: List[dict] = []

        self.event_services = TDOAEventServices(
            event_bus=event_bus
        )

        self.state_manager = TDOAStateManager(
            config=self.config
        )

        self.candidate_filter = CandidateFilter(
            config=self.config
        )

        self.manager = TDOAManager(
            config=self.config
        )

        self.running = False
        self.subscribed = False

        logging.info(
            "[TDOA] Dispatcher initialized."
        )

    # ========================================================
    # START
    # ========================================================

    def start(
        self
    ):
        """
        Start TDOA event subscriptions.
        """

        if not self.subscribed:
            self.event_services.register_subscriptions(
                dispatcher=self
            )

            self.subscribed = True

        self.running = True

        logging.info(
            "[TDOA] Dispatcher ready."
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self
    ):
        """
        Stop TDOA dispatcher workflow.
        """

        self.running = False

        logging.info(
            "[TDOA] Dispatcher stopped."
        )

    # ========================================================
    # CONFIG
    # ========================================================

    def _load_config(
        self,
        config_path: Optional[str]
    ) -> dict:
        """
        Load TDOA configuration.

        If no path is provided, use local TDOA_config.json.
        """

        if config_path is None:
            config_path = Path(__file__).with_name(
                "TDOA_config.json"
            )

        config_path = Path(config_path)

        if not config_path.exists():
            logging.warning(
                f"TDOA config not found: {config_path}. "
                "Using empty config."
            )
            return {}

        with open(config_path, "r", encoding="utf-8") as file:
            return json.load(file)

    # ========================================================
    # MAIN EVENT ENTRY
    # ========================================================

    def handle_event(
        self,
        event: dict
    ) -> None:
        """
        Main TDOA event entry point.

        All subscribed events enter here.
        Dispatcher decides what happens next.
        """

        if not isinstance(event, dict):
            logging.warning(
                "TDOA dispatcher rejected non-dict event."
            )
            return

        event_type = event.get("event_type")

        if event_type is None:
            logging.warning(
                "TDOA dispatcher rejected event with missing event_type."
            )
            return

        if self.enable_debug_logging:
            logging.debug(
                f"TDOA dispatcher received event: {event_type}"
            )

        # ----------------------------------------------------
        # Registry / state events
        # ----------------------------------------------------

        if event_type == TDOAEventServices.EVENT_NODE_TDOA_STATE:

            self._handle_node_tdoa_state(
                event
            )
            return

        if event_type == TDOAEventServices.EVENT_NODE_TDOA_CAPABLE_LOST:

            self._handle_node_tdoa_capable_lost(
                event
            )
            return

        # ----------------------------------------------------
        # Detection / data events
        # ----------------------------------------------------

        if event_type == TDOAEventServices.EVENT_AVIS_LITE:

            self._handle_avis_lite(
                event
            )
            return

        if event_type == TDOAEventServices.EVENT_TDOA_RECORDING:

            self._handle_tdoa_recording(
                event
            )
            return

        if event_type == TDOAEventServices.EVENT_WEATHER_UPDATE:

            self._handle_weather_update(
                event
            )
            return

        # ----------------------------------------------------
        # Mode events
        # ----------------------------------------------------

        if event_type in self._mode_event_names():

            self._handle_mode_change(
                event
            )
            return

        logging.warning(
            f"TDOA dispatcher received unknown event_type: {event_type}"
        )
    
    # ========================================================
    # MODE HANDLING
    # ========================================================

    def handle_tdoa_change_mode(self, event):
        """
        Handle Registry-approved TDOA_CHANGE_MODE events.
        
        Expected event shape:
            {
                "event_type": "TDOA_CHANGE_MODE",
                "source": "platform_registry",
                "payload": {
                    "reason": "FEATURE_MODE_CHANGE",
                    "mode_payload": {
                        "incoming_event": "onset_feature",
                        "mode": {
                            "feature_mode": "onset_feature"
                        }
                    }
                }
            }
        """

        payload = event.get("payload", {})

        mode_payload = payload.get("mode_payload", {})

        if not isinstance(mode_payload, dict):
            logging.warning(
                "TDOA_CHANGE_MODE rejected. Missing or invalid mode_payload."
            )
            return

        mode_update = self._extract_mode_update_from_registry_payload(
            mode_payload
        )

        if mode_update is None:
            logging.warning(
                f"TDOA_CHANGE_MODE rejected. No usable mode update found: {mode_payload}"
            )
            return

        mode_name = mode_update.get("mode_name")
        mode_value = mode_update.get("mode_value")

        try:
            result = self.manager.update_mode(
                mode_name=mode_name,
                mode_value=mode_value
            )

            if result is None:
                return

            result["source_event_type"] = event.get("event_type")
            result["source_reason"] = payload.get("reason")
            result["registry_mode_payload"] = mode_payload

            self.event_services.publish_tdoa_mode_update(
                result
            )
        
            logging.info(
                f"[TDOA] Applied mode change: {mode_name} = {mode_value}"
            )

        except Exception as error:
            logging.exception(
                f"TDOA mode update failed: {mode_name}"
            )

        # Keep this simple for now. We can add a real failure publisher later.
        return
    def _extract_mode_update_from_registry_payload(self, mode_payload):
        """
        Convert Registry-approved mode payload into the manager update shape.

        TDOA manager expects:
            mode_name
            mode_value
        """

        mode = mode_payload.get("mode", {})

        if not isinstance(mode, dict):
            return None

        if "onset_method" in mode:
            return {
                "mode_name": mode.get("onset_method"),
                "mode_value": mode.get("onset_method")
            }

        if "offset_method" in mode:
            return {
                "mode_name": mode.get("offset_method"),
                "mode_value": mode.get("offset_method")
            }

        if "feature_mode" in mode:
            return {
                "mode_name": mode.get("feature_mode"),
                "mode_value": mode.get("feature_mode")
            }

        return None

    # ========================================================
    # STATE EVENT HANDLERS
    # ========================================================

    def _handle_node_tdoa_state(
        self,
        event: dict
    ) -> None:
        """
        Handle registry-owned NODE_TDOA_STATE updates.

        NODE_TDOA_STATE is a per-node readiness report. The state manager
        stores the full node state, keeps the capable-node set current, and
        returns a system-level capability update only when the TDOA subsystem
        crosses the candidate-ready threshold.
        """

        capability_update = self.state_manager.handle_node_tdoa_state(
            event
        )

        self._publish_state_snapshot()

        if capability_update is not None:
            self._handle_capability_update(
                capability_update
            )

        self._run_candidate_filter_if_allowed()

    def _handle_node_tdoa_capable(
        self,
        event: dict
    ) -> None:
        """
        Backward-compatible alias for older dispatcher wording.
        """

        self._handle_node_tdoa_state(
            event
        )

    def _handle_node_tdoa_capable_lost(
        self,
        event: dict
    ) -> None:
        """
        Handle registry report that a node lost TDOA capability.
        """

        capability_update = self.state_manager.handle_node_tdoa_lost(
            event
        )

        self._publish_state_snapshot()

        if capability_update is not None:
            self._handle_capability_update(
                capability_update
            )

    def _handle_capability_update(
        self,
        capability_update: dict
    ) -> None:
        """
        Publish high-level TDOA capability status.
        """

        if capability_update.get("candidate_filter_allowed") is True:

            self.event_services.publish_tdoa_capable(
                capability_update
            )

        else:

            self.event_services.publish_tdoa_capable_lost(
                capability_update
            )

    # ========================================================
    # AVIS LITE HANDLING
    # ========================================================

    def _handle_avis_lite(
        self,
        event: dict
    ) -> None:
        """
        Store avis_lite event and check for TDOA candidate.
        """

        self._store_recent_avis_lite_event(
            event
        )

        self._run_candidate_filter_if_allowed()

    def _store_recent_avis_lite_event(
        self,
        event: dict
    ) -> None:
        """
        Maintain bounded recent avis_lite history.
        """

        self.recent_avis_lite_events.append(
            event
        )

        if len(self.recent_avis_lite_events) > self.max_recent_avis_lite_events:

            overflow = (
                len(self.recent_avis_lite_events)
                - self.max_recent_avis_lite_events
            )

            self.recent_avis_lite_events = self.recent_avis_lite_events[
                overflow:
            ]

    # ========================================================
    # CANDIDATE FILTER FLOW
    # ========================================================

    def _run_candidate_filter_if_allowed(
        self
    ) -> None:
        """
        Ask candidate_filter.py whether a valid TDOA candidate exists.

        Dispatcher only calls TDOA_manager.py after candidate_filter.py
        returns a valid candidate.
        """

        if not self.enable_candidate_filter:
            return

        state_snapshot = self.state_manager.get_state_snapshot()

        if not state_snapshot.get("candidate_filter_allowed", False):
            return

        candidate = self.candidate_filter.find_candidate(
            capability_event=state_snapshot,
            recent_avis_lite_events=self.recent_avis_lite_events
        )

        if candidate is None:
            return

        self._handle_candidate_ready(
            candidate
        )

    def _handle_candidate_ready(
        self,
        candidate: dict
    ) -> None:
        """
        Publish candidate and request TDOA estimate from manager.
        """

        self.event_services.publish_tdoa_candidate_ready(
            candidate
        )

        self.event_services.publish_tdoa_calc_requested(
            {
                "avis_lite_id": candidate.get("avis_lite_id"),
                "node_count": candidate.get("node_count"),
                "node_ids": candidate.get("node_ids"),
                "time_spread_seconds": candidate.get(
                    "time_spread_seconds"
                )
            }
        )

        try:

            result = self.manager.tdoa_estimate(
                candidate
            )

            self.event_services.publish_tdoa_calc_complete(
                result
            )

        except Exception as error:

            logging.exception(
                "TDOA estimate failed."
            )

            self.event_services.publish_tdoa_calc_failed(
                {
                    "error": str(error),
                    "candidate": candidate
                }
            )

    # ========================================================
    # RECORDING / WEATHER HANDLING
    # ========================================================

    def _handle_tdoa_recording(
        self,
        event: dict
    ) -> None:
        """
        Forward TDOA recording data to manager.

        Manager may store it, index it, or prepare it for later solve work.
        """

        try:

            result = self.manager.store_tdoa_recording(
                event
            )

            if result is not None:
                self.event_services.publish_tdoa_state_update(
                    result
                )

        except Exception as error:

            logging.exception(
                "TDOA recording handling failed."
            )

            self.event_services.publish_tdoa_calc_failed(
                {
                    "error": str(error),
                    "source_event": event
                }
            )

    def _handle_weather_update(
        self,
        event: dict
    ) -> None:
        """
        Forward weather update to manager.

        Weather may later affect speed-of-sound correction.
        """

        try:

            result = self.manager.update_weather(
                event
            )

            if result is not None:
                self.event_services.publish_tdoa_state_update(
                    result
                )

        except Exception as error:

            logging.exception(
                "TDOA weather update failed."
            )

            self.event_services.publish_tdoa_calc_failed(
                {
                    "error": str(error),
                    "source_event": event
                }
            )

    # ========================================================
    # MODE HANDLING
    # ========================================================

    def _handle_mode_change(
        self,
        event: dict
    ) -> None:
        """
        Inform manager of a mode change.

        Dispatcher decides that this is a mode event.
        Manager applies the change internally.
        """

        event_type = event.get("event_type")
        payload = event.get("payload", {})

        mode_name = self._mode_name_from_event_type(
            event_type
        )

        mode_value = payload.get(
            "mode"
        )

        if mode_value is None:
            mode_value = payload.get(
                "value"
            )

        try:

            result = self.manager.update_mode(
                mode_name=mode_name,
                mode_value=mode_value
            )

            if result is not None:
                self.event_services.publish_tdoa_mode_update(
                    result
                )

        except Exception as error:

            logging.exception(
                f"TDOA mode update failed: {mode_name}"
            )

            self.event_services.publish_tdoa_calc_failed(
                {
                    "error": str(error),
                    "mode_name": mode_name,
                    "source_event": event
                }
            )

    def _mode_event_names(
        self
    ) -> set:
        """
        Return all mode event names subscribed by TDOA.
        """

        return {
            TDOAEventServices.EVENT_ENERGY_ONSET_MODE_CHANGED,
            TDOAEventServices.EVENT_ENERGY_OFFSET_MODE_CHANGED,
            TDOAEventServices.EVENT_PATTERN_ONSET_MODE_CHANGED,
            TDOAEventServices.EVENT_PATTERN_OFFSET_MODE_CHANGED,
            TDOAEventServices.EVENT_ONSET_FEATURE_MODE_CHANGED,
            TDOAEventServices.EVENT_AMP_FEATURE_MODE_CHANGED
        }

    def _mode_name_from_event_type(
        self,
        event_type: str
    ) -> str:
        """
        Convert event_type into internal manager mode name.
        """

        mode_name_map = {
            TDOAEventServices.EVENT_ENERGY_ONSET_MODE_CHANGED:
                "energy_onset",

            TDOAEventServices.EVENT_ENERGY_OFFSET_MODE_CHANGED:
                "energy_offset",

            TDOAEventServices.EVENT_PATTERN_ONSET_MODE_CHANGED:
                "pattern_onset",

            TDOAEventServices.EVENT_PATTERN_OFFSET_MODE_CHANGED:
                "pattern_offset",

            TDOAEventServices.EVENT_ONSET_FEATURE_MODE_CHANGED:
                "onset_feature",

            TDOAEventServices.EVENT_AMP_FEATURE_MODE_CHANGED:
                "amp_feature"
        }

        return mode_name_map.get(
            event_type,
            event_type
        )

    # ========================================================
    # STATE PUBLISHING
    # ========================================================

    def _publish_state_snapshot(
        self
    ) -> None:
        """
        Publish current TDOA node-state snapshot.
        """

        snapshot = self.state_manager.get_state_snapshot()
        
        self.event_services.publish_tdoa_node_state_updated(
            snapshot
        )