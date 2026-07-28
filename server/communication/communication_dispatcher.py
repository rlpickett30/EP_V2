# ============================================================
# communication_dispatcher.py
#
# EnviroPulse V2
#
# Subsystem:
#   Communication
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own Communication subsystem workflow.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   Full communication config
#
# Does:
#   - Create and own communication_state_manager.py
#   - Create and own communication_event_services.py
#   - Create and own listener_manager.py
#   - Create and own node_route_manager.py
#   - Create and own sender_manager.py
#   - Start inbound Communication listening
#   - Handle inbound decoded events
#   - Learn runtime node routes from NODE_REGISTER source addresses
#   - Publish verified listener events to the local event bus
#   - Handle outbound local events
#   - Convert outbound events to verified server/node/gui events
#   - Resolve TDOA_REQUEST targets and fan out targeted node unicasts
#   - Register expected TDOA uploads before transmitting a request
#   - Start and stop the threaded TDOA HTTP upload receiver
#   - Publish accepted HTTP uploads and validated recording events
#   - Validate and store BirdNET spectrogram HTTP uploads
#   - Serve stored spectrograms to GUI clients through HTTP
#   - Decide when messages should be sent
#   - Decide when messages should be queued
#   - Flush queued messages when communication becomes available
#   - Update Communication state
#
# Does NOT:
#   - Open UDP sockets directly
#   - Send UDP packets directly
#   - Receive UDP packets directly
#   - Decode packet payloads directly
#   - Store queued messages directly
#   - Persist runtime node IP addresses
#   - Select nodes for a TDOA request
#   - Validate multipart metadata or WAV contents directly
#   - Store uploaded WAV bytes directly
#   - Validate or store spectrogram PNG bytes directly
#   - Count TDOA collection quorum
#   - Perform Event Bus delivery logic
#
# Owner:
#   Main / Subsystem root
#
# ============================================================

from communication.communication_state_manager import (
    CommunicationStateManager
)

from communication.communication_event_services import (
    CommunicationEventServices
)

from communication.listener_manager import (
    ListenerManager
)

from communication.node_route_manager import (
    NodeRouteManager
)

from communication.sender_manager import (
    SenderManager
)

from communication.tdoa_upload_manager import (
    TDOAUploadManager
)

from communication.tdoa_upload_server import (
    TDOAUploadServer
)

from communication.spectrogram_upload_manager import (
    SpectrogramUploadManager
)

import copy
import json
import logging
import threading

from datetime import datetime
from datetime import timezone


class CommunicationDispatcher:

    def __init__(
        self,
        event_bus,
        config_path: str = "communication/communication_config.json"
    ):

        self.event_bus = event_bus
        self.config_path = config_path

        self.config = self._load_config()

        self.state = CommunicationStateManager()

        self.event_services = CommunicationEventServices(
            event_bus=self.event_bus
        )

        self.listener_manager = ListenerManager(
            dispatcher=self,
            config=self.config
        )

        self.sender_manager = SenderManager(
            config=self.config
        )

        udp_config = self.config.get(
            "udp",
            {}
        )

        self.node_route_manager = NodeRouteManager(
            node_listener_port=udp_config.get(
                "send_port",
                5006
            )
        )

        http_upload_config = self.config.get(
            "http_upload",
            {}
        )

        self.http_upload_enabled = http_upload_config.get(
            "enabled",
            True
        )

        http_media_config = self.config.get(
            "http_media",
            {}
        )

        self.http_media_enabled = http_media_config.get(
            "enabled",
            True
        )

        self.tdoa_upload_manager = TDOAUploadManager(
            config=http_upload_config
        )

        self.spectrogram_upload_manager = SpectrogramUploadManager(
            config=http_media_config
        )

        http_transfer_config = copy.deepcopy(
            http_upload_config
        )

        http_transfer_config["enabled"] = bool(
            self.http_upload_enabled
            or self.http_media_enabled
        )

        http_transfer_config["spectrogram_enabled"] = (
            self.http_media_enabled
        )

        http_transfer_config["spectrogram_upload_path"] = (
            http_media_config.get(
                "upload_path",
                http_media_config.get(
                    "path",
                    "/media/spectrogram"
                )
            )
        )

        http_transfer_config["spectrogram_download_path"] = (
            http_media_config.get(
                "download_path",
                "/media/spectrogram"
            )
        )

        http_transfer_config["max_spectrogram_upload_bytes"] = (
            http_media_config.get(
                "max_upload_bytes",
                http_media_config.get(
                    "max_image_bytes",
                    4 * 1024 * 1024
                )
            )
        )

        self.tdoa_upload_server = TDOAUploadServer(
            dispatcher=self,
            config=http_transfer_config
        )

        self.tdoa_upload_publish_lock = threading.Lock()

        self.wifi_enabled = self.config.get(
            "wifi_enabled",
            True
        )

        self.lora_enabled = self.config.get(
            "lora_enabled",
            False
        )

        self.udp_enabled = self.config.get(
            "udp",
            {}
        ).get(
            "enabled",
            True
        )

        self.queue_enabled = self.config.get(
            "queue",
            {}
        ).get(
            "enabled",
            True
        )

        self.running = False

        self.event_services.register_subscriptions(
            dispatcher=self
        )

    # ========================================================
    # LOAD CONFIG
    # ========================================================

    def _load_config(
        self
    ) -> dict:

        with open(
            self.config_path,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(
                file
            )

    # ========================================================
    # START / STOP
    # ========================================================

    def start(
        self
    ):

        self.running = True

        if (
            self.http_upload_enabled
            or self.http_media_enabled
        ):

            if self.http_upload_enabled:
                self.tdoa_upload_manager.prepare_storage()

            if self.http_media_enabled:
                self.spectrogram_upload_manager.prepare_storage()

            self.tdoa_upload_server.start()

        if self.udp_enabled:

            self.listener_manager.start()

        self.publish_communication_state()

        logging.info(
            "[Communication] Dispatcher ready."
        )

    def stop(
        self
    ):

        self.running = False

        self.tdoa_upload_server.stop()

        self.listener_manager.stop()

        self.sender_manager.close()

        self.publish_communication_state()

        logging.info(
            "[Communication] Dispatcher stopped."
        )

    # ========================================================
    # HANDLE INBOUND EVENT
    # ========================================================

    def handle_inbound_event(
        self,
        listener_event: dict
    ):

        try:

            self.state.rx_count += 1

            self.state.last_rx_time = listener_event.get(
                "timestamp"
            )

            message = listener_event.get(
                "message",
                {}
            )

            event_type = message.get(
                "event_type"
            )

            if not event_type:

                self.state.rx_errors += 1

                logging.warning(
                    "[Communication] Inbound message missing event_type."
                )

                self.publish_communication_state()

                return

            if event_type == "NODE_REGISTER":

                self._learn_node_route(
                    listener_event=listener_event,
                    message=message
                )

            self._handle_inbound_state_event(
                event_type=event_type,
                event=message
            )

            if self.event_services.can_publish(
                event_type
            ):

                self.event_services.publish_listener_event(
                    event_name=event_type,
                    event=message
                )

            else:

                logging.warning(
                    f"[Communication] Unknown inbound event: "
                    f"{event_type}"
                )

            self.publish_communication_state()

        except Exception as error:

            self.state.rx_errors += 1

            logging.exception(
                f"[Communication] Inbound Dispatcher Error: "
                f"{error}"
            )

            self.publish_communication_state()

    # ========================================================
    # HANDLE OUTBOUND EVENT
    # ========================================================

    def handle_outbound_event(
        self,
        event: dict
    ):

        try:

            event_type = event.get(
                "event_type"
            )

            if not event_type:

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] Outbound event missing event_type."
                )

                self.publish_communication_state()

                return

            self._handle_outbound_mode_event(
                event_type=event_type,
                event=event
            )

            if not self.event_services.can_send(
                event_type
            ):

                logging.warning(
                    f"[Communication] Event is not configured "
                    f"for outbound sending: {event_type}"
                )

                self.publish_communication_state()

                return

            verified_event = (
                self.event_services.build_server_event(
                    event
                )
            )

            self.send_event(
                verified_event
            )

            self.publish_communication_state()

        except Exception as error:

            self.state.tx_errors += 1

            logging.exception(
                f"[Communication] Outbound Dispatcher Error: "
                f"{error}"
            )

            self.publish_communication_state()

    # ========================================================
    # HANDLE TDOA REQUEST
    # ========================================================

    def handle_tdoa_request(
        self,
        event: dict
    ):
        """
        Resolve and unicast one server-local TDOA_REQUEST to each target node.
        """

        try:

            if not isinstance(event, dict):

                self.state.tx_errors += 1
                logging.warning(
                    "[Communication] TDOA_REQUEST was not a dictionary."
                )
                self.publish_communication_state()
                return

            payload = self._extract_payload(
                event
            )

            request_id = (
                payload.get("tdoa_request_id")
                or payload.get("request_id")
                or event.get("tdoa_request_id")
                or event.get("request_id")
            )

            target_nodes = self._extract_target_nodes(
                event=event,
                payload=payload
            )

            if not request_id:

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] TDOA_REQUEST missing request ID."
                )

                self.publish_communication_state()
                return

            if not target_nodes:

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] TDOA_REQUEST has no target_nodes: "
                    f"request_id={request_id}"
                )

                self.publish_communication_state()
                return

            sent_node_ids = []
            missing_node_ids = []
            failed_node_ids = []
            resolved_routes = {}

            for node_id in target_nodes:

                route = self.node_route_manager.resolve_route(
                    node_id
                )

                if route is None:

                    self.state.tx_errors += 1
                    missing_node_ids.append(
                        node_id
                    )

                    logging.warning(
                        "[Communication] TDOA_REQUEST route missing: "
                        f"request_id={request_id} "
                        f"node_id={node_id}"
                    )

                    continue

                resolved_routes[
                    node_id
                ] = route

            if not self.http_upload_enabled:

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] TDOA_REQUEST not sent; "
                    "HTTP upload receiver is disabled: "
                    f"request_id={request_id}"
                )

                self.publish_communication_state()
                return

            if not self.tdoa_upload_server.running:

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] TDOA_REQUEST not sent; "
                    "HTTP upload receiver is not running: "
                    f"request_id={request_id}"
                )

                self.publish_communication_state()
                return

            expected_source_ips = {
                node_id: route.get(
                    "host"
                )
                for node_id, route in resolved_routes.items()
            }

            registration = (
                self.tdoa_upload_manager.register_expected_request(
                    request_id=request_id,
                    target_nodes=target_nodes,
                    request_items=payload.get(
                        "request_items"
                    ),
                    expected_source_ips=expected_source_ips
                )
            )

            upload_instructions = (
                self.tdoa_upload_server.build_upload_instructions(
                    token=registration["token"]
                )
            )

            outbound_event = copy.deepcopy(
                event
            )

            outbound_payload = copy.deepcopy(
                payload
            )

            outbound_payload[
                "upload"
            ] = upload_instructions

            outbound_payload[
                "upload_registered_at_utc"
            ] = registration[
                "created_at_utc"
            ]

            if isinstance(
                outbound_event.get("payload"),
                dict
            ):

                outbound_event[
                    "payload"
                ] = outbound_payload

            else:

                outbound_event.update(
                    outbound_payload
                )

            outbound_event["event_type"] = "TDOA_REQUEST"
            outbound_event.setdefault(
                "source",
                "communication"
            )
            outbound_event.setdefault(
                "target",
                "node"
            )

            logging.info(
                "[Communication] TDOA upload request registered: "
                f"request_id={request_id} "
                f"expected_nodes={target_nodes} "
                f"upload_port={upload_instructions.get('port')} "
                f"upload_path={upload_instructions.get('path')}"
            )

            for node_id, route in resolved_routes.items():

                success = self._send_targeted_event(
                    event=outbound_event,
                    node_id=node_id,
                    destination=route,
                    request_id=request_id
                )

                if success:

                    sent_node_ids.append(
                        node_id
                    )

                else:

                    failed_node_ids.append(
                        node_id
                    )

            logging.info(
                "[Communication] TDOA_REQUEST fan-out complete: "
                f"request_id={request_id} "
                f"targeted={len(target_nodes)} "
                f"sent={len(sent_node_ids)} "
                f"missing_routes={missing_node_ids} "
                f"send_failures={failed_node_ids}"
            )

            self.publish_communication_state()

        except ValueError as error:

            self.state.tx_errors += 1

            logging.warning(
                "[Communication] TDOA_REQUEST registration rejected: "
                f"{error}"
            )

            self.publish_communication_state()

        except Exception as error:

            self.state.tx_errors += 1

            logging.exception(
                f"[Communication] TDOA_REQUEST failed: {error}"
            )

            self.publish_communication_state()

    # ========================================================
    # HANDLE TDOA HTTP UPLOAD
    # ========================================================

    def handle_tdoa_http_upload(
        self,
        transaction: dict
    ) -> dict:
        """
        Validate one HTTP upload and publish accepted server-local events.
        """

        with self.tdoa_upload_publish_lock:

            result = self.tdoa_upload_manager.process_upload(
                transaction
            )

            self.state.rx_count += 1
            self.state.last_rx_time = self._utc_now()

            if not result.get(
                "accepted",
                False
            ):

                self.state.rx_errors += 1

                receipt = result.get(
                    "receipt",
                    {}
                )

                logging.warning(
                    "[Communication] TDOA upload rejected: "
                    f"source_ip={transaction.get('source_ip')} "
                    f"reason={receipt.get('failure_reason')} "
                    f"detail={receipt.get('failure_detail')}"
                )

                self.publish_communication_state()

                return result

            if result.get(
                "publish_events",
                False
            ):

                recording_event = result[
                    "tdoa_recording_event"
                ]

                valid_recording_event = result[
                    "tdoa_valid_recording_event"
                ]

                self.event_services.publish_tdoa_recording(
                    recording_event
                )

                self.event_services.publish_tdoa_valid_recording(
                    valid_recording_event
                )

                receipt = result[
                    "receipt"
                ]

                logging.info(
                    "[Communication] TDOA upload accepted: "
                    f"request_id={receipt.get('tdoa_request_id')} "
                    f"node_id={receipt.get('node_id')} "
                    f"recording_id={receipt.get('recording_id')} "
                    f"bytes={receipt.get('byte_count')} "
                    f"sha256={receipt.get('sha256')}"
                )

            else:

                receipt = result.get(
                    "receipt",
                    {}
                )

                logging.info(
                    "[Communication] TDOA upload retry accepted "
                    "idempotently: "
                    f"request_id={receipt.get('tdoa_request_id')} "
                    f"node_id={receipt.get('node_id')} "
                    f"recording_id={receipt.get('recording_id')}"
                )

            self.publish_communication_state()

            return result

    # ========================================================
    # HANDLE SPECTROGRAM HTTP TRANSFER
    # ========================================================

    def handle_spectrogram_http_upload(
        self,
        transaction: dict
    ) -> dict:

        if not self.http_media_enabled:
            return {
                "accepted": False,
                "success": False,
                "http_status": 503,
                "receipt": {
                    "accepted": False,
                    "status": "rejected",
                    "failure_reason": "spectrogram_upload_disabled",
                    "failure_detail": (
                        "Spectrogram HTTP transfer is disabled."
                    )
                }
            }

        result = self.spectrogram_upload_manager.process_upload(
            transaction
        )

        self.state.rx_count += 1
        self.state.last_rx_time = self._utc_now()

        receipt = result.get(
            "receipt",
            {}
        )

        if result.get(
            "accepted",
            False
        ):

            logging.info(
                "[Communication] Spectrogram upload accepted: "
                f"node_id={receipt.get('node_id')} "
                f"recording_id={receipt.get('recording_id')} "
                f"media_id={receipt.get('media_id')} "
                f"bytes={receipt.get('byte_count')}"
            )

        else:

            self.state.rx_errors += 1

            logging.warning(
                "[Communication] Spectrogram upload rejected: "
                f"source_ip={transaction.get('source_ip')} "
                f"reason={receipt.get('failure_reason')} "
                f"detail={receipt.get('failure_detail')}"
            )

        self.publish_communication_state()

        return result

    def handle_spectrogram_http_download(
        self,
        media_id
    ) -> dict:

        if not self.http_media_enabled:
            return {
                "success": False,
                "http_status": 503,
                "failure_reason": "spectrogram_download_disabled",
                "failure_detail": (
                    "Spectrogram HTTP transfer is disabled."
                )
            }

        return self.spectrogram_upload_manager.get_download(
            media_id
        )

    # ========================================================
    # LEARN NODE ROUTE
    # ========================================================

    def _learn_node_route(
        self,
        listener_event: dict,
        message: dict
    ):
        """
        Learn node_id -> source_ip:node_listener_port from NODE_REGISTER.
        """

        payload = self._extract_payload(
            message
        )

        node_id = (
            payload.get("node_id")
            or message.get("node_id")
            or message.get("source")
        )

        source_ip = listener_event.get(
            "source_ip"
        )

        try:

            result = self.node_route_manager.learn_route(
                node_id=node_id,
                source_ip=source_ip
            )

        except (TypeError, ValueError) as error:

            self.state.rx_errors += 1

            logging.warning(
                "[Communication] NODE_REGISTER route rejected: "
                f"node_id={node_id} "
                f"source_ip={source_ip} "
                f"reason={error}"
            )

            return

        route = result[
            "route"
        ]

        previous_route = result.get(
            "previous_route"
        )

        if (
            result.get("route_changed")
            and previous_route is not None
        ):

            logging.info(
                "[Communication] Node route replaced: "
                f"node_id={route['node_id']} "
                f"old={previous_route.get('host')}:{previous_route.get('port')} "
                f"new={route['host']}:{route['port']}"
            )

        elif result.get(
            "route_changed"
        ):

            logging.info(
                "[Communication] Node route learned: "
                f"node_id={route['node_id']} "
                f"destination={route['host']}:{route['port']}"
            )

        else:

            logging.info(
                "[Communication] Node route refreshed: "
                f"node_id={route['node_id']} "
                f"destination={route['host']}:{route['port']}"
            )

    # ========================================================
    # TARGETED TDOA SEND
    # ========================================================

    def _send_targeted_event(
        self,
        event: dict,
        node_id: str,
        destination: dict,
        request_id: str
    ) -> bool:
        """
        Send one call-specific unicast without entering the generic queue.
        """

        message = self.sender_manager.build_message(
            event
        )

        if not self._can_send_now():

            self.state.tx_errors += 1

            logging.warning(
                "[Communication] TDOA_REQUEST not sent; transport unavailable: "
                f"request_id={request_id} "
                f"node_id={node_id}"
            )

            return False

        success = self.sender_manager.send_message(
            message=message,
            destination=destination
        )

        if not success:

            self.state.tx_errors += 1

            logging.warning(
                "[Communication] TDOA_REQUEST send failed: "
                f"request_id={request_id} "
                f"node_id={node_id} "
                f"destination={destination.get('host')}:{destination.get('port')}"
            )

            return False

        self.state.tx_count += 1
        self.state.last_tx_time = self._utc_now()

        self.event_services.publish_event_sent(
            {
                "event_type": "EVENT_SENT",
                "timestamp": self.state.last_tx_time,
                "message": message,
                "delivery": {
                    "mode": "targeted_unicast",
                    "node_id": node_id,
                    "host": destination.get("host"),
                    "port": destination.get("port")
                },
                "tdoa_request_id": request_id
            }
        )

        logging.info(
            "[Communication] TDOA_REQUEST sent: "
            f"request_id={request_id} "
            f"node_id={node_id} "
            f"destination={destination.get('host')}:{destination.get('port')}"
        )

        return True

    # ========================================================
    # REQUEST HELPERS
    # ========================================================

    def _extract_payload(
        self,
        event: dict
    ) -> dict:

        if not isinstance(
            event,
            dict
        ):

            return {}

        payload = event.get(
            "payload"
        )

        if isinstance(
            payload,
            dict
        ):

            return payload

        return event

    def _extract_target_nodes(
        self,
        event: dict,
        payload: dict
    ) -> list:

        target_nodes = payload.get(
            "target_nodes"
        )

        if target_nodes is None:

            target_nodes = event.get(
                "target_nodes"
            )

        if isinstance(
            target_nodes,
            str
        ):

            raw_node_ids = [
                target_nodes
            ]

        elif isinstance(
            target_nodes,
            (
                list,
                tuple,
                set
            )
        ):

            raw_node_ids = list(
                target_nodes
            )

        else:

            return []

        unique_node_ids = []
        seen_node_ids = set()

        for raw_node_id in raw_node_ids:

            if raw_node_id is None:

                continue

            node_id = str(
                raw_node_id
            ).strip()

            if (
                not node_id
                or node_id in seen_node_ids
            ):

                continue

            seen_node_ids.add(
                node_id
            )

            unique_node_ids.append(
                node_id
            )

        return unique_node_ids

    # ========================================================
    # HANDLE COMMUNICATION CHANGE MODE
    # ========================================================

    def handle_communication_change_mode(
        self,
        event: dict
    ):

        try:

            payload = event.get(
                "payload",
                {}
            )

            mode_payload = payload.get(
                "mode_payload",
                {}
            )

            if not isinstance(
                mode_payload,
                dict
            ):

                self.state.rx_errors += 1

                logging.warning(
                    "[Communication] COMMUNICATION_CHANGE_MODE missing mode_payload."
                )

                self.publish_communication_state()

                return

            incoming_event = mode_payload.get(
                "incoming_event"
            )

            mode = mode_payload.get(
                "mode",
                {}
            )

            if not incoming_event:

                self.state.rx_errors += 1

                logging.warning(
                    "[Communication] COMMUNICATION_CHANGE_MODE missing incoming_event."
                )

                self.publish_communication_state()

                return

            self._apply_communication_mode_change(
                incoming_event=incoming_event,
                mode=mode,
                mode_payload=mode_payload
            )

            self.publish_communication_state()

            logging.info(
                f"[Communication] Applied mode change: {incoming_event}"
            )

        except Exception as error:

            self.state.rx_errors += 1

            logging.exception(
                f"[Communication] COMMUNICATION_CHANGE_MODE failed: {error}"
            )

            self.publish_communication_state()

    # ========================================================
    # HANDLE NODE STATE UPDATED
    # ========================================================

    def handle_node_state_updated(
        self,
        event: dict
    ):

        try:

            payload = event.get(
                "payload",
                {}
            )

            if not isinstance(
                payload,
                dict
            ):

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] NODE_STATE_UPDATED missing payload."
                )

                self.publish_communication_state()

                return

            node_id = self._extract_node_id_from_node_state_payload(
                payload
            )

            if not node_id:

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] NODE_STATE_UPDATED missing node_id."
                )

                self.publish_communication_state()

                return

            outbound_event = {
                "event_type": "NODE_STATE_UPDATED",
                "source": "communication",
                "target": "gui",
                "payload": payload
            }

            self.send_event(
                outbound_event
            )

            self.publish_communication_state()

            logging.info(
                f"[Communication] NODE_STATE_UPDATED sent or queued for GUI: {node_id}"
            )

        except Exception as error:

            self.state.tx_errors += 1

            logging.exception(
                f"[Communication] NODE_STATE_UPDATED failed: {error}"
            )

            self.publish_communication_state()

    # ========================================================
    # HANDLE NODE TDOA STATE
    # ========================================================

    def handle_node_tdoa_state(
        self,
        event: dict
    ):

        try:

            payload = event.get(
                "payload",
                {}
            )

            if not isinstance(
                payload,
                dict
            ):

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] NODE_TDOA_STATE missing payload."
                )

                self.publish_communication_state()

                return

            node_id = (
                payload.get("node_id")
                or self._extract_node_id_from_node_state_payload(
                    payload
                )
            )

            if not node_id:

                tdoa_state = payload.get(
                    "tdoa_state",
                    {}
                )

                if isinstance(
                    tdoa_state,
                    dict
                ):

                    node_id = tdoa_state.get(
                        "node_id"
                    )

            if not node_id:

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] NODE_TDOA_STATE missing node_id."
                )

                self.publish_communication_state()

                return

            outbound_event = {
                "event_type": "NODE_TDOA_STATE",
                "source": "communication",
                "target": "gui",
                "payload": payload
            }

            self.send_event(
                outbound_event
            )

            self.publish_communication_state()

            logging.info(
                f"[Communication] NODE_TDOA_STATE sent or queued for GUI: {node_id}"
            )

        except Exception as error:

            self.state.tx_errors += 1

            logging.exception(
                f"[Communication] NODE_TDOA_STATE failed: {error}"
            )

            self.publish_communication_state()

    # ========================================================
    # APPLY COMMUNICATION MODE CHANGE
    # ========================================================

    def _apply_communication_mode_change(
        self,
        incoming_event: str,
        mode: dict,
        mode_payload: dict
    ):

        if incoming_event == "enable_wifi":

            self.wifi_enabled = True

        elif incoming_event == "disable_wifi":

            self.wifi_enabled = False

        elif incoming_event == "enable_lora":

            self.lora_enabled = True

        elif incoming_event == "disable_lora":

            self.lora_enabled = False

        else:

            raise ValueError(
                f"Unknown communication mode event: {incoming_event}"
            )

        if isinstance(
            mode,
            dict
        ):

            if "wifi_enabled" in mode:

                self.wifi_enabled = bool(
                    mode.get("wifi_enabled")
                )

            if "lora_enabled" in mode:

                self.lora_enabled = bool(
                    mode.get("lora_enabled")
                )

    # ========================================================
    # SEND EVENT
    # ========================================================

    def send_event(
        self,
        event: dict
    ):

        message = self.sender_manager.build_message(
            event
        )

        if not self._can_send_now():

            self.queue_event(
                message
            )

            return

        success = self.sender_manager.send_message(
            message
        )

        if success:

            self.state.tx_count += 1

            self.state.last_tx_time = (
                self._utc_now()
            )

            self.event_services.publish_event_sent(
                {
                    "event_type": "EVENT_SENT",
                    "timestamp": self.state.last_tx_time,
                    "message": message
                }
            )

        else:

            self.state.tx_errors += 1

            self.queue_event(
                message
            )

    # ========================================================
    # QUEUE / FLUSH
    # ========================================================

    def queue_event(
        self,
        message: dict
    ):

        if not self.queue_enabled:

            logging.warning(
                "[Communication] Queue disabled. Message dropped."
            )

            return

        self.sender_manager.store_message(
            message
        )

        self.event_services.publish_event_queued(
            {
                "event_type": "EVENT_QUEUED",
                "timestamp": self._utc_now(),
                "message": message,
                "queue_size": self.sender_manager.queue_size()
            }
        )

    def flush_queue(
        self
    ):

        if not self._can_send_now():

            return

        queued_messages = (
            self.sender_manager.retrieve_queue()
        )

        sent_count = 0

        for message in queued_messages:

            success = self.sender_manager.send_message(
                message
            )

            if success:

                self.sender_manager.remove_message(
                    message
                )

                self.state.tx_count += 1

                self.state.last_tx_time = (
                    self._utc_now()
                )

                sent_count += 1

            else:

                self.state.tx_errors += 1

                break

        self.event_services.publish_queue_flushed(
            {
                "event_type": "QUEUE_FLUSHED",
                "timestamp": self._utc_now(),
                "sent_count": sent_count,
                "queue_size": self.sender_manager.queue_size()
            }
        )

        self.publish_communication_state()

    # ========================================================
    # HANDLE INBOUND STATE EVENT
    # ========================================================

    def _handle_inbound_state_event(
        self,
        event_type: str,
        event: dict
    ):

        if event_type == "NETWORK_CONNECTED":

            self.state.network_connected = True

            self.event_services.publish_network_connected(
                event
            )

            self.flush_queue()

        elif event_type == "NETWORK_DISCONNECTED":

            self.state.network_connected = False

            self.event_services.publish_network_disconnected(
                event
            )

    # ========================================================
    # HANDLE OUTBOUND MODE EVENT
    # ========================================================

    def _handle_outbound_mode_event(
        self,
        event_type: str,
        event: dict
    ):

        if event_type == "ENABLE_WIFI":

            self.wifi_enabled = True

        elif event_type == "DISABLE_WIFI":

            self.wifi_enabled = False

        elif event_type == "ENABLE_LORA":

            self.lora_enabled = True

        elif event_type == "DISABLE_LORA":

            self.lora_enabled = False

    # ========================================================
    # HANDLE SEND NODE CHANGE MODE
    # ========================================================

    def handle_send_node_change_mode(
        self,
        event: dict
    ):

        try:

            payload = event.get(
                "payload",
                {}
            )

            mode_payload = payload.get(
                "mode_payload",
                {}
            )

            if not isinstance(
                mode_payload,
                dict
            ):

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] SEND_NODE_CHANGE_MODE missing mode_payload."
                )

                self.publish_communication_state()

                return

            node_id = mode_payload.get(
                "node_id"
            )

            incoming_event = mode_payload.get(
                "incoming_event"
            )

            mode = mode_payload.get(
                "mode",
                {}
            )

            if not node_id:

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] SEND_NODE_CHANGE_MODE missing node_id."
                )

                self.publish_communication_state()

                return

            if not incoming_event:

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] SEND_NODE_CHANGE_MODE missing incoming_event."
                )

                self.publish_communication_state()

                return

            outbound_event = {
                "event_type": "NODE_CHANGE_MODE",
                "source": "communication",
                "target_node": node_id,
                "command": incoming_event,
                "mode": mode,
                "requested_by": mode_payload.get(
                    "requested_by"
                ),
                "source_event_type": "SEND_NODE_CHANGE_MODE",
                "registry_mode_payload": mode_payload
            }

            self.send_event(
                outbound_event
            )

            self.publish_communication_state()

            logging.info(
                f"[Communication] Node mode command sent or queued: {incoming_event}"
            )

        except Exception as error:

            self.state.tx_errors += 1

            logging.exception(
                f"[Communication] SEND_NODE_CHANGE_MODE failed: {error}"
            )

            self.publish_communication_state()

    # ========================================================
    # HANDLE NODE EVENT TO GUI
    # ========================================================

    def handle_node_event_to_gui(
        self,
        event: dict
    ):

        try:

            event_type = event.get(
                "event_type"
            )

            if not event_type:

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] Node event missing event_type."
                )

                self.publish_communication_state()

                return

            outbound_event = {
                "event_type": event_type,
                "source": "communication",
                "target": "gui",
                "payload": {
                    "node_event": event
                }
            }

            self.send_event(
                outbound_event
            )

            self.publish_communication_state()

            logging.info(
                f"[Communication] {event_type} sent or queued for GUI."
            )

        except Exception as error:

            self.state.tx_errors += 1

            logging.exception(
                f"[Communication] Node event GUI forward failed: {error}"
            )

            self.publish_communication_state()

    # ========================================================
    # HANDLE SERVER NODE REGISTER
    # ========================================================

    def handle_server_node_register(
        self,
        event: dict
    ):

        try:

            payload = event.get(
                "payload",
                {}
            )

            if not isinstance(
                payload,
                dict
            ):

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] SERVER_NODE_REGISTER missing payload."
                )

                self.publish_communication_state()

                return

            outbound_event = {
                "event_type": "SERVER_NODE_REGISTER",
                "source": "communication",
                "target": "gui",
                "payload": payload
            }

            self.send_event(
                outbound_event
            )

            self.publish_communication_state()

            logging.info(
                "[Communication] SERVER_NODE_REGISTER sent or queued for GUI."
            )

        except Exception as error:

            self.state.tx_errors += 1

            logging.exception(
                f"[Communication] SERVER_NODE_REGISTER failed: {error}"
            )

            self.publish_communication_state()

    # ========================================================
    # EXTRACT NODE ID FROM NODE STATE PAYLOAD
    # ========================================================

    def _extract_node_id_from_node_state_payload(
        self,
        payload: dict
    ):

        if not isinstance(
            payload,
            dict
        ):

            return None

        node_id = payload.get(
            "node_id"
        )

        if node_id:

            return node_id

        state = payload.get(
            "state",
            {}
        )

        if isinstance(
            state,
            dict
        ):

            node_id = state.get(
                "node_id"
            )

            if node_id:

                return node_id

            snapshot = state.get(
                "node_state_snapshot",
                {}
            )

            if isinstance(
                snapshot,
                dict
            ):

                node_id = snapshot.get(
                    "node_id"
                )

                if node_id:

                    return node_id

        snapshot = payload.get(
            "node_state_snapshot",
            {}
        )

        if isinstance(
            snapshot,
            dict
        ):

            node_id = snapshot.get(
                "node_id"
            )

            if node_id:

                return node_id

        return None

    # ========================================================
    # CAN SEND NOW
    # ========================================================

    def _can_send_now(
        self
    ) -> bool:

        if not self.udp_enabled:

            return False

        if not self.wifi_enabled:

            return False

        return True

    # ========================================================
    # PUBLISH COMMUNICATION STATE
    # ========================================================

    def publish_communication_state(
        self
    ):

        self.event_services.publish_communication_state(
            self.state.get_status()
        )

    # ========================================================
    # UTC NOW
    # ========================================================

    def _utc_now(
        self
    ) -> str:

        return (
            datetime.now(
                timezone.utc
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z"
            )
        )
