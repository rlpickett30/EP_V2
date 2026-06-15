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
#   - Create and own sender_manager.py
#   - Start inbound Communication listening
#   - Handle inbound decoded events
#   - Publish verified listener events to the local event bus
#   - Handle outbound local events
#   - Convert outbound events to verified SERVER_ events
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
#   - Know Communication helper scripts
#   - Perform Event Bus delivery logic
#
# Owner:
#   Main / Subsystem root
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
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

from communication.sender_manager import (
    SenderManager
)

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import json
import logging

from datetime import datetime


# ============================================================
# CLASS DEFINITIONS
# ============================================================

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
    # START
    # ========================================================

    def start(
        self
    ):

        self.running = True

        if self.udp_enabled:

            self.listener_manager.start()

        self.publish_communication_state()

        logging.info(
            "[Communication] Dispatcher ready."
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self
    ):

        self.running = False

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
    # HANDLE COMMUNICATION CHANGE MODE
    # ========================================================

    def handle_communication_change_mode(
        self,
        event: dict
    ):
        """
        Handle Registry-approved communication mode changes.
        
        Current inbound event:
            COMMUNICATION_CHANGE_MODE
            
            Expected event shape:
                {
                    "source": "platform_registry",
                    "payload": {
                        "reason": "GUI_NETWORK_MODE_CHANGE",
                        "mode_payload": {
                            "incoming_event": "enable_wifi",
                            "mode": {
                                "wifi_enabled": True
                            }
                        }
                    }
                }
        """

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
        """
        Handle NODE_STATE_UPDATED.

        Purpose:
            Forward accepted node state updates to GUI clients.

        Source:
            Platform Registry

        Expected inbound event:
            {
                "event_type": "NODE_STATE_UPDATED",
                "source": "platform_registry",
                "payload": {
                    ...
                }
            }

        Outbound event:
            {
                "event_type": "NODE_STATE_UPDATED",
                "source": "communication",
                "target": "gui",
                "payload": {
                    ...
                }
            }
        """

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
    # APPLY COMMUNICATION MODE CHANGE
    # ========================================================

    def _apply_communication_mode_change(
        self,
        incoming_event: str,
        mode: dict,
        mode_payload: dict
    ):
        """
        Apply a Registry-approved communication mode change locally.
        """

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
    # QUEUE EVENT
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

    # ========================================================
    # FLUSH QUEUE
    # ========================================================

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
        """
        Handle Registry-approved node mode changes.

        Current inbound event:
            SEND_NODE_CHANGE_MODE

        Purpose:
            Convert approved node mode command into an outbound
            node command package and send it through Communication.
        """

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
        """
        Handle accepted node events that should be visible in GUI.

        Purpose:
            Forward node event traffic to GUI clients after the
            Communication listener has accepted and published it.
        """

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
        """
        Handle SERVER_NODE_REGISTER.

        Purpose:
            Forward accepted node registration updates to GUI clients.
        """

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
        """
        Extract node_id from known NODE_STATE_UPDATED payload shapes.

        Supports:
            - payload["node_id"]
            - payload["state"]["node_id"]
            - payload["node_state_snapshot"]["node_id"]
            - payload["state"]["node_state_snapshot"]["node_id"]
        """

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

        return datetime.utcnow().isoformat()