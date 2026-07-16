# ============================================================
# birdnet_dispatcher.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   BirdNET
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own the BirdNET subsystem workflow. Receive recording and GPS events,
#   coordinate BirdNetManager analysis, and publish canonical AVIS_LITE
#   events through BirdNetEventServices.
#
# Expected config source:
#   birdnet_config.json
#
# Expected config section:
#   Full file
#
# Does:
#   - Load BirdNET configuration
#   - Start and stop the BirdNET subsystem
#   - Register BirdNET event subscriptions
#   - Track runtime BirdNET location state
#   - Handle GPS_COORD events
#   - Handle RECORDING_AVAILABLE events
#   - Queue recordings for asynchronous BirdNET analysis
#   - Coordinate BirdNetManager
#   - Build canonical AVIS_LITE events
#   - Attach payload-safe spectrogram packages when available
#   - Publish AVIS_LITE events through BirdNetEventServices
#
# Does NOT:
#   - Analyze WAV files directly
#   - Generate spectrograms directly
#   - Subscribe directly to the event bus
#   - Publish directly to the event bus
#   - Rewrite runtime GPS values back into config
#   - Publish state events
#   - Publish mode events
#   - Own node registration
#   - Send AVIS_LITE to the server directly
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
import uuid

from datetime import datetime
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

        self.processed_candidate_keys = set()

        self.processed_candidate_key_order: List[str] = []

        self.max_processed_candidate_keys = dispatcher_config.get(
            "max_processed_candidate_keys",
            500
        )

        self.pending_tdoa_requests = {}

        self.completed_tdoa_requests = set()

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
        Normalize and store bounded recent avis_lite history.

        CandidateFilter expects top-level:
            node_id
            avis_lite_id
            node_time

        Current AVIS_LITE payload provides:
            node_id
            species_code
            recording_utc
            birdnet_start_time
            birdnet_event_id
        """

        payload = event.get(
            "payload",
            event
        )

        if not isinstance(payload, dict):
            logging.warning(
                "[TDOA] Rejected AVIS_LITE event with non-dict payload."
            )
            return

        node_id = payload.get(
            "node_id",
            event.get("node_id")
        )

        species_code = payload.get(
            "species_code"
        )

        species_common = payload.get(
            "species_common"
        )

        birdnet_event_id = payload.get(
            "birdnet_event_id"
        )

        recording_id = payload.get(
            "recording_id"
        )

        recording_utc = payload.get(
            "recording_utc"
        )

        birdnet_start_time = payload.get(
            "birdnet_start_time",
            0.0
        )

        birdnet_event_utc = payload.get(
            "birdnet_event_utc"
        )

        recording_epoch = self._parse_utc_epoch(
            recording_utc
        )

        try:
            birdnet_start_time = float(
                birdnet_start_time
            )
        except (TypeError, ValueError):
            birdnet_start_time = 0.0

        if recording_epoch is not None:
            node_time = (
                recording_epoch
                +
                birdnet_start_time
            )
        else:
            node_time = birdnet_event_utc

        avis_lite_id = species_code

        if avis_lite_id is None:
            avis_lite_id = species_common

        if avis_lite_id is None:
            avis_lite_id = birdnet_event_id

        normalized_event = {
            "event_type": event.get("event_type"),
            "source": event.get("source"),
            "node_id": node_id,
            "avis_lite_id": avis_lite_id,
            "node_time": node_time,
            "species_code": species_code,
            "species_common": species_common,
            "birdnet_event_id": birdnet_event_id,
            "recording_id": recording_id,
            "recording_utc": recording_utc,
            "birdnet_start_time": birdnet_start_time,
            "birdnet_event_utc": birdnet_event_utc,
            "payload": payload,
            "raw_event": event
        }

        self.recent_avis_lite_events.append(
            normalized_event
        )

        logging.info(
            "[TDOA] Stored AVIS_LITE for candidate filter: "
            f"node_id={normalized_event.get('node_id')} "
            f"avis_lite_id={normalized_event.get('avis_lite_id')} "
            f"node_time={normalized_event.get('node_time')} "
            f"species={normalized_event.get('species_common')} "
            f"birdnet_start={normalized_event.get('birdnet_start_time')} "
            f"recording_id={normalized_event.get('recording_id')} "
            f"recent_count={len(self.recent_avis_lite_events)}"
        )

        if len(self.recent_avis_lite_events) > self.max_recent_avis_lite_events:

            overflow = (
                len(self.recent_avis_lite_events)
                -
                self.max_recent_avis_lite_events
            )

            self.recent_avis_lite_events = self.recent_avis_lite_events[
                overflow:
            ]

    def _parse_utc_epoch(
        self,
        utc_value
    ):
        """
        Convert an ISO UTC string into epoch seconds.

        Expected example:
            2026-06-26T18:59:28.001058Z
        """

        if not isinstance(utc_value, str):
            return None

        try:
            normalized_utc = utc_value.replace(
                "Z",
                "+00:00"
            )

            return datetime.fromisoformat(
                normalized_utc
            ).timestamp()

        except (TypeError, ValueError):
            logging.warning(
                f"[TDOA] Could not parse UTC timestamp: {utc_value}"
            )
            return None
    # ========================================================
    # CANDIDATE FILTER FLOW
    # ========================================================

    def _run_candidate_filter_if_allowed(
        self
    ) -> None:
        """
        Ask candidate_filter.py whether a valid TDOA candidate exists.

        Dispatcher only advances a candidate once. Duplicate candidate
        detections are ignored so the same AVIS group does not repeatedly
        trigger downstream workflow.
        """

        if not self.enable_candidate_filter:
            logging.info(
                "[TDOA] Candidate filter skipped: enable_candidate_filter=False"
            )
            return

        state_snapshot = self.state_manager.get_state_snapshot()

        logging.info(
            "[TDOA] Candidate filter check: "
            f"allowed={state_snapshot.get('candidate_filter_allowed')} "
            f"recent_avis={len(self.recent_avis_lite_events)} "
            f"capable_nodes={state_snapshot.get('tdoa_capable_node_ids')}"
        )

        if not state_snapshot.get("candidate_filter_allowed", False):
            return

        candidate = self.candidate_filter.find_candidate(
            capability_event=state_snapshot,
            recent_avis_lite_events=self.recent_avis_lite_events
        )

        if candidate is None:
            logging.info(
                "[TDOA] Candidate filter found no candidate."
            )
            return

        candidate_key = self._build_candidate_key(
            candidate
        )

        if candidate_key in self.processed_candidate_keys:
            logging.info(
                "[TDOA] Duplicate candidate ignored: "
                f"candidate_key={candidate_key}"
            )
            return

        self._mark_candidate_processed(
            candidate_key
        )

        logging.info(
            "[TDOA] Candidate filter found candidate: "
            f"avis_lite_id={candidate.get('avis_lite_id')} "
            f"node_count={candidate.get('node_count')} "
            f"node_ids={candidate.get('node_ids')} "
            f"time_spread={candidate.get('time_spread_seconds')} "
            f"candidate_key={candidate_key}"
        )

        self._handle_candidate_ready(
            candidate
        )

    def _build_candidate_key(
        self,
        candidate: dict
    ) -> str:
        """
        Build a stable duplicate-detection key for one candidate.
        """

        avis_lite_id = candidate.get(
            "avis_lite_id",
            "unknown_avis"
        )

        candidate_events = candidate.get(
            "events",
            []
        )

        event_key_parts = []

        if isinstance(candidate_events, list):

            for candidate_event in candidate_events:

                if not isinstance(candidate_event, dict):
                    continue

                payload = candidate_event.get(
                    "payload",
                    {}
                )

                if not isinstance(payload, dict):
                    payload = {}

                node_id = candidate_event.get(
                    "node_id",
                    payload.get("node_id")
                )

                recording_id = candidate_event.get(
                    "recording_id",
                    payload.get("recording_id")
                )

                node_time = candidate_event.get(
                    "node_time",
                    payload.get("node_time")
                )

                try:
                    node_time_key = round(
                        float(node_time),
                        3
                    )

                except (TypeError, ValueError):
                    node_time_key = node_time

                event_key_parts.append(
                    f"{node_id}:{recording_id}:{node_time_key}"
                )

        if event_key_parts:
            return (
                f"{avis_lite_id}|"
                +
                "|".join(
                    sorted(event_key_parts)
                )
            )

        node_ids = candidate.get(
            "node_ids",
            []
        )

        if isinstance(node_ids, list):
            node_id_key = ",".join(
                sorted(node_ids)
            )
        else:
            node_id_key = str(node_ids)

        return (
            f"{avis_lite_id}|"
            f"{node_id_key}|"
            f"{candidate.get('time_spread_seconds')}"
        )

    def _mark_candidate_processed(
        self,
        candidate_key: str
    ) -> None:
        """
        Store candidate key and keep duplicate tracking bounded.
        """

        self.processed_candidate_keys.add(
            candidate_key
        )

        self.processed_candidate_key_order.append(
            candidate_key
        )

        while (
            len(self.processed_candidate_key_order)
            >
            self.max_processed_candidate_keys
        ):

            oldest_key = self.processed_candidate_key_order.pop(
                0
            )

            self.processed_candidate_keys.discard(
                oldest_key
            )

    def _handle_candidate_ready(
        self,
        candidate: dict
    ) -> None:
        """
        Publish candidate readiness and open the request path.

        The dispatcher owns this workflow step. The manager still does not
        solve until TDOA_RECORDING responses have been received and a
        TDOA_COMPLETE_SET has been assembled.
        """

        self.event_services.publish_tdoa_candidate_ready(
            candidate
        )

        request = self._build_tdoa_request(
            candidate=candidate
        )

        if request is None:
            logging.warning(
                "[TDOA] Candidate ready but no TDOA_REQUEST could be built."
            )
            return

        self.pending_tdoa_requests[request["tdoa_request_id"]] = {
            "request": request,
            "candidate": candidate,
            "required_node_ids": set(request.get("target_nodes", [])),
            "responses": {},
            "complete": False
        }

        self.event_services.publish_tdoa_request(
            request
        )

        logging.info(
            "[TDOA] Published TDOA_REQUEST: "
            f"request_id={request.get('tdoa_request_id')} "
            f"target_nodes={request.get('target_nodes')}"
        )

    def _build_tdoa_request(
        self,
        candidate: dict
    ) -> dict | None:
        """
        Build one broadcast TDOA_REQUEST from a candidate package.

        Each node receives the same request. The node microphone dispatcher
        finds its own request item by node_id and returns the matching
        recording pointer.
        """

        candidate_events = candidate.get(
            "events",
            []
        )

        if not isinstance(candidate_events, list):
            return None

        request_items = {}

        for candidate_event in candidate_events:

            if not isinstance(candidate_event, dict):
                continue

            payload = candidate_event.get(
                "payload",
                {}
            )

            if not isinstance(payload, dict):
                payload = {}

            node_id = (
                candidate_event.get("node_id")
                or payload.get("node_id")
            )

            recording_id = (
                candidate_event.get("recording_id")
                or payload.get("recording_id")
            )

            if node_id is None or recording_id is None:
                continue

            request_items[node_id] = {
                "node_id": node_id,
                "recording_id": recording_id,
                "source_recording_id": recording_id,
                "recording_utc": (
                    candidate_event.get("recording_utc")
                    or payload.get("recording_utc")
                ),
                "birdnet_start_time": (
                    candidate_event.get("birdnet_start_time")
                    or payload.get("birdnet_start_time")
                ),
                "birdnet_event_id": (
                    candidate_event.get("birdnet_event_id")
                    or payload.get("birdnet_event_id")
                ),
                "avis_lite_id": candidate.get("avis_lite_id"),
                "species_code": (
                    candidate_event.get("species_code")
                    or payload.get("species_code")
                ),
                "species_common": (
                    candidate_event.get("species_common")
                    or payload.get("species_common")
                )
            }

        if not request_items:
            return None

        candidate_key = self._build_candidate_key(
            candidate
        )

        request_id = (
            "tdoa_request_"
            + uuid.uuid4().hex[:12]
        )

        return {
            "tdoa_request_id": request_id,
            "request_id": request_id,
            "candidate_key": candidate_key,
            "avis_lite_id": candidate.get("avis_lite_id"),
            "target": "broadcast",
            "target_node_id": "broadcast",
            "target_nodes": sorted(request_items.keys()),
            "required_node_count": len(request_items),
            "request_items": request_items,
            "request_timestamp": datetime.utcnow().isoformat(),
            "request_mode": "existing_recording_pointer",
            "duration_sec": self.config.get(
                "tdoa_manager",
                {}
            ).get(
                "tdoa_recording_duration_sec",
                15
            )
        }        

    # ========================================================
    # RECORDING / WEATHER HANDLING
    # ========================================================

    def _handle_tdoa_recording(
        self,
        event: dict
    ) -> None:
        """
        Store a TDOA_RECORDING response and complete the request when all
        requested nodes have answered.
        """

        try:

            result = self.manager.store_tdoa_recording(
                event
            )

            if result is not None:
                self.event_services.publish_tdoa_state_update(
                    result
                )

            payload = event.get(
                "payload",
                event
            )

            if not isinstance(payload, dict):
                return

            request_id = (
                payload.get("tdoa_request_id")
                or payload.get("request_id")
                or event.get("tdoa_request_id")
                or event.get("request_id")
            )

            node_id = (
                payload.get("node_id")
                or event.get("node_id")
            )

            if request_id is None or node_id is None:
                logging.info(
                    "[TDOA] Stored TDOA_RECORDING without request tracking: "
                    f"request_id={request_id} node_id={node_id}"
                )
                return

            self._store_tdoa_recording_response(
                request_id=request_id,
                node_id=node_id,
                event=event
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

    def _store_tdoa_recording_response(
        self,
        request_id: str,
        node_id: str,
        event: dict
    ) -> None:
        """
        Store one node response and trigger solve when the complete set exists.
        """

        pending = self.pending_tdoa_requests.get(
            request_id
        )

        if pending is None:
            logging.warning(
                "[TDOA] Received TDOA_RECORDING for unknown request: "
                f"request_id={request_id} node_id={node_id}"
            )
            return

        pending["responses"][node_id] = event

        required_node_ids = pending.get(
            "required_node_ids",
            set()
        )

        received_node_ids = set(
            pending["responses"].keys()
        )

        logging.info(
            "[TDOA] TDOA_RECORDING response accepted: "
            f"request_id={request_id} node_id={node_id} "
            f"received={len(received_node_ids)}/{len(required_node_ids)}"
        )

        if pending.get("complete", False):
            return

        if not required_node_ids.issubset(received_node_ids):
            return

        pending["complete"] = True

        complete_set = {
            "tdoa_request_id": request_id,
            "request": pending.get("request"),
            "candidate": pending.get("candidate"),
            "node_ids": sorted(received_node_ids),
            "required_node_ids": sorted(required_node_ids),
            "recording_events": [
                pending["responses"][node_id]
                for node_id in sorted(required_node_ids)
            ],
            "completed_at_utc": datetime.utcnow().isoformat()
        }

        self.event_services.publish_tdoa_complete_set(
            complete_set
        )

        self._handle_tdoa_complete_set(
            complete_set
        )

    def _handle_tdoa_complete_set(
        self,
        complete_set: dict
    ) -> None:
        """
        Invoke the manager once a complete requested recording set exists.
        """

        request_id = complete_set.get(
            "tdoa_request_id"
        )

        candidate = complete_set.get(
            "candidate"
        )

        self.event_services.publish_tdoa_calc_started(
            {
                "tdoa_request_id": request_id,
                "candidate": candidate,
                "node_ids": complete_set.get("node_ids", [])
            }
        )

        self.event_services.publish_tdoa_calc_requested(
            {
                "tdoa_request_id": request_id,
                "candidate": candidate,
                "node_ids": complete_set.get("node_ids", [])
            }
        )

        result = self.manager.tdoa_estimate(
            candidate
        )

        result["tdoa_request_id"] = request_id
        result["complete_set"] = complete_set

        if result.get("success", False):
            self.event_services.publish_tdoa_calc_complete(
                result
            )
        else:
            self.event_services.publish_tdoa_calc_failed(
                result
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