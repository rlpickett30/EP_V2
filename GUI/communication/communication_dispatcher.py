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
#   - Start inbound UDP listening
#   - Handle decoded inbound server events
#   - Publish approved inbound events to the GUI event bus
#   - Handle approved outbound GUI events
#   - Send outbound GUI events through sender_manager.py
#   - Queue outbound messages when sending is unavailable
#   - Update Communication state
#
# Does NOT:
#   - Open UDP sockets directly
#   - Send UDP packets directly
#   - Receive UDP packets directly
#   - Decode packet payloads directly
#   - Store queued messages directly
#   - Perform Event Bus delivery logic
#   - Publish unapproved Communication events
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
    CommunicationEventServices,
    NETWORK_CONNECTED,
    NETWORK_DISCONNECTED,
    EVENT_SENT,
    GUI_REGISTER,
    NETWORK_MODE_CHANGE,
    DETECTION_MODE_CHANGE,
    FEATURE_MODE_CHANGE,
    NODE_STATE_UPDATED,
    NODE_TDOA_STATE,
    SERVER_NODE_REGISTER,
    SERVER_ENVIRO_EVENT,
    SERVER_TDOA_CALC,
    SERVER_GPS_COORD,
    SERVER_AVIS_LITE
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
    """
    Dispatcher for the GUI Communication subsystem.

    Communication receives server events from UDP, publishes approved
    GUI bus events, receives GUI outbound events, and sends those events
    to the configured server destination.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        config_path: str = "communication/communication_config.json"
    ):

        self.event_bus = event_bus
        self.config_path = config_path

        self.config = self._load_config()

        self.debug = self.config.get(
            "debug",
            False
        )

        self.state = CommunicationStateManager()

        self.event_services = CommunicationEventServices(
            event_bus=self.event_bus,
            dispatcher=self,
            debug=self.debug
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

        self.inbound_publish_map = {
            NODE_STATE_UPDATED:
                self.event_services.publish_node_state_updated,

            NODE_TDOA_STATE:
                self.event_services.publish_node_tdoa_state,

            SERVER_NODE_REGISTER:
                self.event_services.publish_server_node_register,

            SERVER_ENVIRO_EVENT:
                self.event_services.publish_server_enviro_event,

            SERVER_TDOA_CALC:
                self.event_services.publish_server_tdoa_calc,

            SERVER_GPS_COORD:
                self.event_services.publish_server_gps_coord,

            SERVER_AVIS_LITE:
                self.event_services.publish_server_avis_lite
        }

        self.outbound_send_events = {
            GUI_REGISTER,
            NETWORK_MODE_CHANGE,
            DETECTION_MODE_CHANGE,
            FEATURE_MODE_CHANGE
        }

        self.event_services.register_subscriptions()

    # ========================================================
    # CONFIG
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

        if self.udp_enabled:

            self.listener_manager.start()

        logging.info(
            "[Communication] Dispatcher ready."
        )

    def stop(
        self
    ):

        self.running = False

        self.listener_manager.stop()

        self.sender_manager.close()

        logging.info(
            "[Communication] Dispatcher stopped."
        )

    # ========================================================
    # EVENT BUS HANDLING
    # ========================================================

    def handle_bus_event(
        self,
        event_name,
        payload=None
    ):
        """
        Handle events received from the GUI event bus.

        Event services only forwards the subscription. Dispatcher decides
        whether the event updates Communication state or should be sent out.
        """

        try:

            if event_name == NETWORK_CONNECTED:

                self._handle_network_connected(
                    payload
                )

                return

            if event_name == NETWORK_DISCONNECTED:

                self._handle_network_disconnected(
                    payload
                )

                return

            if event_name in self.outbound_send_events:

                outbound_event = self._build_outbound_event(
                    event_name=event_name,
                    payload=payload
                )

                self.send_event(
                    outbound_event
                )

                return

            logging.warning(
                "[Communication] Unhandled bus event: %s",
                event_name
            )

        except Exception as error:

            self.state.tx_errors += 1

            logging.exception(
                "[Communication] Bus event handling error: %s",
                error
            )

    # ========================================================
    # INBOUND EVENT HANDLING
    # ========================================================

    def handle_inbound_event(
        self,
        listener_event: dict
    ):
        """
        Handle decoded inbound events from listener_manager.py.
        """

        try:

            self.state.rx_count += 1

            self.state.last_rx_time = listener_event.get(
                "timestamp",
                self._utc_now()
            )

            message = listener_event.get(
                "message",
                {}
            )

            if not isinstance(
                message,
                dict
            ):

                self.state.rx_errors += 1

                logging.warning(
                    "[Communication] Inbound message was not a dictionary."
                )

                return

            event_name = self._extract_event_name(
                message
            )

            if not event_name:

                self.state.rx_errors += 1

                logging.warning(
                    "[Communication] Inbound message missing event_type."
                )

                return

            if event_name == NETWORK_CONNECTED:

                self._handle_network_connected(
                    message
                )

                return

            if event_name == NETWORK_DISCONNECTED:

                self._handle_network_disconnected(
                    message
                )

                return

            publish_method = self.inbound_publish_map.get(
                event_name
            )

            if publish_method is None:

                logging.warning(
                    "[Communication] Unknown inbound event: %s",
                    event_name
                )

                return

            normalized_message = self._build_inbound_bus_payload(
                event_name=event_name,
                message=message,
                listener_event=listener_event
            )

            publish_method(
                normalized_message
            )

        except Exception as error:

            self.state.rx_errors += 1

            logging.exception(
                "[Communication] Inbound dispatcher error: %s",
                error
            )

    # ========================================================
    # OUTBOUND SEND HANDLING
    # ========================================================

    def send_event(
        self,
        event: dict
    ):
        """
        Send or queue an outbound event.
        """

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

            self.state.last_tx_time = self._utc_now()

            self.event_services.publish_event_sent(
                self._build_event_sent_payload(
                    message=message,
                    queued=False
                )
            )

            return

        self.state.tx_errors += 1

        self.queue_event(
            message
        )

    def queue_event(
        self,
        message: dict
    ):
        """
        Store an outbound message when sending is unavailable.
        """

        if not self.queue_enabled:

            logging.warning(
                "[Communication] Queue disabled. Message dropped."
            )

            return

        self.sender_manager.store_message(
            message
        )

        logging.warning(
            "[Communication] Message queued. Queue size: %s",
            self.sender_manager.queue_size()
        )

    def flush_queue(
        self
    ):
        """
        Attempt to send queued messages.
        """

        if not self._can_send_now():

            return

        queued_messages = self.sender_manager.retrieve_queue()

        for message in queued_messages:

            success = self.sender_manager.send_message(
                message
            )

            if not success:

                self.state.tx_errors += 1

                logging.warning(
                    "[Communication] Queue flush stopped after send failure."
                )

                return

            self.sender_manager.remove_message(
                message
            )

            self.state.tx_count += 1

            self.state.last_tx_time = self._utc_now()

            self.event_services.publish_event_sent(
                self._build_event_sent_payload(
                    message=message,
                    queued=True
                )
            )

    # ========================================================
    # NETWORK STATE HANDLING
    # ========================================================

    def _handle_network_connected(
        self,
        payload=None
    ):

        self.state.network_connected = True
        self.state.server_reachable = True

        self.flush_queue()

        if self.debug:

            logging.info(
                "[Communication] Network connected."
            )

    def _handle_network_disconnected(
        self,
        payload=None
    ):

        self.state.network_connected = False
        self.state.server_reachable = False

        if self.debug:

            logging.info(
                "[Communication] Network disconnected."
            )

    # ========================================================
    # VALIDATION / GATES
    # ========================================================

    def _can_send_now(
        self
    ) -> bool:

        if not self.udp_enabled:

            return False

        if not self.wifi_enabled:

            return False

        return True

    def _extract_event_name(
        self,
        message: dict
    ):

        return (
            message.get("event_type")
            or message.get("event_name")
            or message.get("name")
        )

    # ========================================================
    # PAYLOAD BUILDERS
    # ========================================================

    def _build_inbound_bus_payload(
        self,
        event_name: str,
        message: dict,
        listener_event: dict
    ) -> dict:

        payload = dict(
            message
        )

        payload["event_type"] = event_name

        payload["_communication"] = {

            "transport":
                listener_event.get(
                    "transport"
                ),

            "received_timestamp":
                listener_event.get(
                    "timestamp"
                ),

            "source_ip":
                listener_event.get(
                    "source_ip"
                ),

            "source_port":
                listener_event.get(
                    "source_port"
                ),

            "rx_count":
                self.state.rx_count,

            "rx_errors":
                self.state.rx_errors
        }

        return payload

    def _build_outbound_event(
        self,
        event_name: str,
        payload=None
    ) -> dict:

        if payload is None:

            payload = {}

        if not isinstance(
            payload,
            dict
        ):

            payload = {
                "value": payload
            }

        return {

            "event_type":
                event_name,

            "source":
                "gui",

            "target":
                "server",

            "timestamp":
                self._utc_now(),

            "payload":
                payload
        }

    def _build_event_sent_payload(
        self,
        message: dict,
        queued: bool
    ) -> dict:

        return {

            "event_type":
                EVENT_SENT,

            "source":
                "communication",

            "target":
                "journal",

            "timestamp":
                self._utc_now(),

            "payload": {

                "message":
                    message,

                "sent_from_queue":
                    queued,

                "tx_count":
                    self.state.tx_count,

                "tx_errors":
                    self.state.tx_errors,

                "last_tx_time":
                    self.state.last_tx_time,

                "queue_size":
                    self.sender_manager.queue_size()
            }
        }

    # ========================================================
    # STATUS
    # ========================================================

    def get_status(
        self
    ) -> dict:

        return {

            "communication_state":
                self.state.get_status(),

            "wifi_enabled":
                self.wifi_enabled,

            "lora_enabled":
                self.lora_enabled,

            "udp_enabled":
                self.udp_enabled,

            "queue_enabled":
                self.queue_enabled,

            "queue_size":
                self.sender_manager.queue_size(),

            "running":
                self.running
        }

    # ========================================================
    # TIME
    # ========================================================

    def _utc_now(
        self
    ) -> str:

        return datetime.utcnow().isoformat()