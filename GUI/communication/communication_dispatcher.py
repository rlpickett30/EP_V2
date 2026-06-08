# ============================================================
# communication_dispatcher.py
#
# EnviroPulse V2 GUI
#
# Subsystem:
#   Communication
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own GUI Communication subsystem workflow.
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
#   - Publish verified inbound listener events to the local event bus
#   - Handle outbound local GUI events
#   - Convert outbound events to verified GUI_ events
#   - Decide when messages should be sent
#   - Decide when messages should be queued
#   - Flush queued messages when communication becomes available
#   - Update Communication state
#   - Publish Communication state events
#
# Does NOT:
#   - Open UDP sockets directly
#   - Send UDP packets directly
#   - Receive UDP packets directly
#   - Decode packet payloads directly
#   - Store queued messages directly
#   - Know Communication helper internals beyond owned managers
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
                self.event_services.build_gui_event(
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
                self._build_internal_event(
                    event_type="EVENT_SENT",
                    payload={
                        "message": message,
                        "tx_count": self.state.tx_count,
                        "tx_errors": self.state.tx_errors,
                        "last_tx_time": self.state.last_tx_time
                    },
                    target="journal"
                )
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

            self.event_services.publish_event_queued(
                self._build_internal_event(
                    event_type="EVENT_QUEUED",
                    payload={
                        "queued": False,
                        "reason": "queue_disabled",
                        "message": message,
                        "queue_size": self.sender_manager.queue_size()
                    },
                    target="journal"
                )
            )

            return

        self.sender_manager.store_message(
            message
        )

        self.event_services.publish_event_queued(
            self._build_internal_event(
                event_type="EVENT_QUEUED",
                payload={
                    "queued": True,
                    "message": message,
                    "queue_size": self.sender_manager.queue_size()
                },
                target="journal"
            )
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
            self._build_internal_event(
                event_type="QUEUE_FLUSHED",
                payload={
                    "sent_count": sent_count,
                    "queue_size": self.sender_manager.queue_size(),
                    "tx_count": self.state.tx_count,
                    "tx_errors": self.state.tx_errors,
                    "last_tx_time": self.state.last_tx_time
                },
                target="journal"
            )
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
                self._build_internal_event(
                    event_type="NETWORK_CONNECTED",
                    payload={
                        "network_connected": True,
                        "source_event": event
                    },
                    target="gui"
                )
            )

            self.flush_queue()

        elif event_type == "NETWORK_DISCONNECTED":

            self.state.network_connected = False

            self.event_services.publish_network_disconnected(
                self._build_internal_event(
                    event_type="NETWORK_DISCONNECTED",
                    payload={
                        "network_connected": False,
                        "source_event": event
                    },
                    target="gui"
                )
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

            self.event_services.publish_network_enabled(
                self._build_internal_event(
                    event_type="NETWORK_ENABLED",
                    payload={
                        "network": "wifi",
                        "enabled": True,
                        "source_event": event
                    },
                    target="gui"
                )
            )

        elif event_type == "DISABLE_WIFI":

            self.wifi_enabled = False

            self.event_services.publish_network_disabled(
                self._build_internal_event(
                    event_type="NETWORK_DISABLED",
                    payload={
                        "network": "wifi",
                        "enabled": False,
                        "source_event": event
                    },
                    target="gui"
                )
            )

        elif event_type == "ENABLE_LORA":

            self.lora_enabled = True

            self.event_services.publish_network_enabled(
                self._build_internal_event(
                    event_type="NETWORK_ENABLED",
                    payload={
                        "network": "lora",
                        "enabled": True,
                        "source_event": event
                    },
                    target="gui"
                )
            )

        elif event_type == "DISABLE_LORA":

            self.lora_enabled = False

            self.event_services.publish_network_disabled(
                self._build_internal_event(
                    event_type="NETWORK_DISABLED",
                    payload={
                        "network": "lora",
                        "enabled": False,
                        "source_event": event
                    },
                    target="gui"
                )
            )

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
            self._build_internal_event(
                event_type="COMMUNICATION_STATE",
                payload={
                    "communication_state": self.state.get_status(),
                    "wifi_enabled": self.wifi_enabled,
                    "lora_enabled": self.lora_enabled,
                    "udp_enabled": self.udp_enabled,
                    "queue_enabled": self.queue_enabled
                },
                target="gui"
            )
        )

    # ========================================================
    # BUILD INTERNAL EVENT
    # ========================================================

    def _build_internal_event(
        self,
        event_type: str,
        payload: dict,
        target: str = "gui"
    ) -> dict:

        return {

            "event_type": event_type,

            "source": "communication",

            "target": target,

            "timestamp": self._utc_now(),

            "payload": payload

        }

    # ========================================================
    # UTC NOW
    # ========================================================

    def _utc_now(
        self
    ) -> str:

        return datetime.utcnow().isoformat()