# ============================================================
# communication_dispatcher.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Node Communication
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own node Communication workflow.
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
#   - Register Sender subscriptions
#   - Register Listener publications
#   - Send node state and node event messages to the server
#   - Publish inbound TDOA_REQUEST messages to the node bus
#   - Publish EVENT_SENT after successful sends
#   - Track NETWORK_CONNECTED and NETWORK_DISCONNECTED
#   - Handle SEND_NODE_CHANGE_MODE
#   - Switch active outbound transport between Wi-Fi and LoRa
#   - Queue outbound messages when the active transport cannot send
#
# Does NOT:
#   - Open sockets directly
#   - Send UDP packets directly
#   - Receive UDP packets directly
#   - Decode packet payloads directly
#   - Analyze recordings
#   - Own node registration contents
#   - Perform Event Bus delivery logic
#
# Owner:
#   Main / Subsystem root
#
# ============================================================

from __future__ import annotations

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

try:

    from communication.communication_state_manager import (
        CommunicationStateManager
    )

except Exception:

    class CommunicationStateManager:
        """
        Small fallback used only when the real state manager is unavailable.
        """

        def __init__(self):
            self.network_connected = False
            self.server_reachable = False
            self.rx_count = 0
            self.tx_count = 0
            self.rx_errors = 0
            self.tx_errors = 0
            self.last_rx_time = None
            self.last_tx_time = None

        def get_status(self):
            return dict(self.__dict__)


from communication.communication_event_services import (
    CommunicationEventServices,
    PPS_STATE,
    ENVIRO_STATE,
    RTK_STATE,
    GPS_STATE,
    TDOA_RECORDING,
    AVIS_LITE,
    MICROPHONE_SYNCED,
    NODE_REGISTER,
    GPS_COORD,
    ENVIRO_EVENT,
    TDOA_REQUEST,
    NETWORK_CONNECTED,
    NETWORK_DISCONNECTED,
    EVENT_SENT,
    SEND_NODE_CHANGE_MODE,
    OUTBOUND_SEND_EVENTS,
    INBOUND_LISTENER_EVENTS
)

try:

    from communication.listener_manager import (
        ListenerManager
    )

except Exception:

    ListenerManager = None

try:

    from communication.sender_manager import (
        SenderManager
    )

except Exception:

    SenderManager = None


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import json
import logging
import math
import threading
import time

from copy import deepcopy
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


# ============================================================
# CONSTANTS
# ============================================================

WIFI = "wifi"
LORA = "lora"

MODE_ALIASES = {
    "wifi": WIFI,
    "wi-fi": WIFI,
    "udp": WIFI,
    "enable_wifi": WIFI,
    "send_wifi": WIFI,
    "send_via_wifi": WIFI,
    "wifi_on": WIFI,
    "lora": LORA,
    "lorawan": LORA,
    "enable_lora": LORA,
    "send_lora": LORA,
    "send_via_lora": LORA,
    "lora_on": LORA,
}

DEFAULT_CONFIG = {
    "debug": True,
    "default_transport": WIFI,
    "wifi_enabled": True,
    "lora_enabled": False,
    "udp": {
        "enabled": True
    },
    "queue": {
        "enabled": True
    },
    "network": {
        "publish_state_on_start": True
    },
    "send_stagger": {
        "enabled": True,
        "auto_node_offset": True,
        "node_offset_seconds": None,
        "node_offset_scale_seconds": 0.1,
        "max_node_offset_seconds": 0.9,
        "align_to_fractional_second": True,
        "event_spacing_seconds": 0.075,
        "event_types": [
            AVIS_LITE,
            TDOA_RECORDING,
            MICROPHONE_SYNCED
        ]
    }
}


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class CommunicationDispatcher:
    """
    Dispatcher for the node Communication subsystem.

    Sender side:
        Local node events and state events are sent to the server.

    Listener side:
        Inbound server commands are normalized and published to the local
        node event bus.

    Communication side:
        Network state and active transport mode are owned here.
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
            True
        )

        self.state = CommunicationStateManager()

        self.event_services = CommunicationEventServices(
            event_bus=self.event_bus,
            dispatcher=self,
            debug=self.debug
        )

        self.listener_manager = self._build_listener_manager()

        self.sender_manager = self._build_sender_manager()

        self.wifi_enabled = self.config.get(
            "wifi_enabled",
            True
        )

        self.lora_enabled = self.config.get(
            "lora_enabled",
            False
        )

        self.udp_enabled = (
            self.config
            .get("udp", {})
            .get("enabled", True)
        )

        self.queue_enabled = (
            self.config
            .get("queue", {})
            .get("enabled", True)
        )

        self.active_transport = self._normalize_transport(
            self.config.get(
                "default_transport",
                WIFI
            )
        )

        if self.active_transport == LORA:

            self.lora_enabled = True

        else:

            self.active_transport = WIFI
            self.wifi_enabled = True

        self.running = False

        self.send_stagger_config = self._build_send_stagger_config()
        self.last_stagger_send_monotonic = 0.0
        self.stagger_lock = threading.Lock()

        self.outbound_send_events = set(
            OUTBOUND_SEND_EVENTS
        )

        self.inbound_publish_map = {
            TDOA_REQUEST:
                self.event_services.publish_tdoa_request,

            SEND_NODE_CHANGE_MODE:
                self.event_services.publish_send_node_change_mode
        }

        self.event_services.register_subscriptions()

    # ========================================================
    # DEBUG
    # ========================================================

    def log(
        self,
        message: str
    ):

        if self.debug:

            logging.info(
                "[CommunicationDispatcher] %s",
                message
            )

    # ========================================================
    # CONFIG
    # ========================================================

    def _load_config(
        self
    ) -> dict:

        config = deepcopy(
            DEFAULT_CONFIG
        )

        path = Path(
            self.config_path
        )

        if not path.exists():

            return config

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as file:

            loaded = json.load(
                file
            )

        self._deep_update(
            config,
            loaded
        )

        return config

    def _deep_update(
        self,
        base: dict,
        updates: dict
    ):

        for key, value in updates.items():

            if (
                isinstance(value, dict)
                and isinstance(base.get(key), dict)
            ):

                self._deep_update(
                    base[key],
                    value
                )

            else:

                base[key] = value

    # ========================================================
    # MANAGER BUILDERS
    # ========================================================

    def _build_listener_manager(
        self
    ):

        if ListenerManager is None:

            return None

        try:

            return ListenerManager(
                dispatcher=self,
                config=self.config
            )

        except TypeError:

            return ListenerManager(
                self,
                self.config
            )

    def _build_sender_manager(
        self
    ):

        if SenderManager is None:

            return None

        try:

            return SenderManager(
                config=self.config
            )

        except TypeError:

            return SenderManager(
                self.config
            )

    # ========================================================
    # START / STOP
    # ========================================================

    def start(
        self
    ):

        self.running = True

        self._start_active_listener()

        if self.config.get(
            "network",
            {}
        ).get(
            "publish_state_on_start",
            True
        ):

            self._publish_network_state(
                connected=self._can_send_now(),
                reason="startup"
            )

        self.log(
            "Communication subsystem started"
        )

    def stop(
        self
    ):

        self.running = False

        self._stop_listener()

        self._close_sender()

        self.log(
            "Communication subsystem stopped"
        )

    # ========================================================
    # EVENT BUS HANDLING
    # ========================================================

    def handle_bus_event(
        self,
        event_type: str,
        event=None
    ):
        """
        Handle events received from the local node event bus.
        """

        try:

            normalized_event = self._normalize_bus_event(
                event_type=event_type,
                event=event
            )

            if event_type == NETWORK_CONNECTED:

                self._handle_network_connected(
                    normalized_event,
                    publish=False
                )

                return

            if event_type == NETWORK_DISCONNECTED:

                self._handle_network_disconnected(
                    normalized_event,
                    publish=False
                )

                return

            if event_type == SEND_NODE_CHANGE_MODE:

                self._handle_send_node_change_mode(
                    normalized_event
                )

                return

            if event_type in self.outbound_send_events:

                outbound_event = self._build_outbound_event(
                    event_type=event_type,
                    event=normalized_event
                )

                self.send_event(
                    outbound_event
                )

                return

            logging.warning(
                "[Communication] Unhandled bus event: %s",
                event_type
            )

        except Exception as error:

            self._increment_state_counter(
                "tx_errors"
            )

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

            self._increment_state_counter(
                "rx_count"
            )

            self._set_state_value(
                "last_rx_time",
                self._utc_now()
            )

            message = self._extract_listener_message(
                listener_event
            )

            if not isinstance(
                message,
                dict
            ):

                self._increment_state_counter(
                    "rx_errors"
                )

                logging.warning(
                    "[Communication] Inbound message was not a dictionary."
                )

                return

            event_type = self._extract_event_type(
                message
            )

            if not event_type:

                self._increment_state_counter(
                    "rx_errors"
                )

                logging.warning(
                    "[Communication] Inbound message missing event_type."
                )

                return

            if event_type == NETWORK_CONNECTED:

                self._handle_network_connected(
                    message,
                    publish=True
                )

                return

            if event_type == NETWORK_DISCONNECTED:

                self._handle_network_disconnected(
                    message,
                    publish=True
                )

                return

            if event_type not in INBOUND_LISTENER_EVENTS:

                logging.warning(
                    "[Communication] Unknown inbound event: %s",
                    event_type
                )

                return

            normalized_event = self._build_inbound_bus_event(
                event_type=event_type,
                message=message,
                listener_event=listener_event
            )

            publish_method = self.inbound_publish_map.get(
                event_type
            )

            if publish_method is None:

                logging.warning(
                    "[Communication] No publish method for inbound event: %s",
                    event_type
                )

                return

            publish_method(
                normalized_event
            )

        except Exception as error:

            self._increment_state_counter(
                "rx_errors"
            )

            logging.exception(
                "[Communication] Inbound dispatcher error: %s",
                error
            )

    # ========================================================
    # SEND STAGGERING
    # ========================================================

    def _build_send_stagger_config(
        self
    ) -> dict:
        """
        Build outbound send-stagger settings.

        This lives in Communication so recording and BirdNET timing remain
        untouched. Only network delivery is delayed.
        """

        config = deepcopy(
            DEFAULT_CONFIG.get(
                "send_stagger",
                {}
            )
        )

        configured = self.config.get(
            "send_stagger",
            {}
        )

        if isinstance(
            configured,
            dict
        ):

            self._deep_update(
                config,
                configured
            )

        return config

    def _message_should_be_staggered(
        self,
        message: dict
    ) -> bool:

        config = self.send_stagger_config

        if not bool(
            config.get(
                "enabled",
                False
            )
        ):

            return False

        event_type = self._extract_event_type(
            message
        )

        configured_events = config.get(
            "event_types",
            []
        )

        if configured_events in (None, "*"):

            return True

        if not isinstance(
            configured_events,
            (list, tuple, set)
        ):

            configured_events = [
                configured_events
            ]

        allowed_events = {
            str(item)
            for item in configured_events
        }

        return (
            "*" in allowed_events
            or event_type in allowed_events
        )

    def _extract_message_node_id(
        self,
        message: dict
    ):

        payload = self._get_payload(
            message
        )

        candidates = [
            payload.get("node_id"),
            message.get("node_id") if isinstance(message, dict) else None,
            self.config.get("node_id"),
            payload.get("node_name"),
            message.get("node_name") if isinstance(message, dict) else None,
            self.config.get("node_name"),
        ]

        for candidate in candidates:

            if candidate not in (None, ""):

                return str(
                    candidate
                )

        return None

    def _extract_node_number(
        self,
        node_id
    ):

        if node_id is None:

            return None

        text = str(
            node_id
        ).strip()

        digits = ""

        for character in reversed(
            text
        ):

            if character.isdigit():

                digits = character + digits
                continue

            if digits:

                break

        if not digits:

            return None

        try:

            return int(
                digits
            )

        except Exception:

            return None

    def _get_node_send_offset_seconds(
        self,
        message: dict
    ) -> float:

        config = self.send_stagger_config

        configured_offset = config.get(
            "node_offset_seconds"
        )

        if configured_offset is not None:

            try:

                offset = float(
                    configured_offset
                )

            except Exception:

                offset = 0.0

        elif bool(
            config.get(
                "auto_node_offset",
                True
            )
        ):

            node_number = self._extract_node_number(
                self._extract_message_node_id(
                    message
                )
            )

            if node_number is None:

                offset = 0.0

            else:

                try:

                    scale = float(
                        config.get(
                            "node_offset_scale_seconds",
                            0.1
                        )
                    )

                except Exception:

                    scale = 0.1

                offset = float(
                    node_number
                ) * scale

        else:

            offset = 0.0

        try:

            max_offset = float(
                config.get(
                    "max_node_offset_seconds",
                    0.9
                )
            )

        except Exception:

            max_offset = 0.9

        max_offset = max(
            0.0,
            max_offset
        )

        return max(
            0.0,
            min(
                offset,
                max_offset
            )
        )

    def _get_event_spacing_seconds(
        self
    ) -> float:

        try:

            return max(
                0.0,
                float(
                    self.send_stagger_config.get(
                        "event_spacing_seconds",
                        0.075
                    )
                )
            )

        except Exception:

            return 0.075

    def _get_fractional_stagger_delay_seconds(
        self,
        offset_seconds: float
    ) -> float:
        """
        Delay until the node's fractional second slot.

        Example:
            node_01 -> 0.1 second mark
            node_05 -> 0.5 second mark
        """

        if not bool(
            self.send_stagger_config.get(
                "align_to_fractional_second",
                True
            )
        ):

            return offset_seconds

        if offset_seconds <= 0.0:

            return 0.0

        now_epoch = time.time()
        base_epoch = math.floor(
            now_epoch
        )
        target_epoch = base_epoch + offset_seconds

        if target_epoch <= now_epoch:

            target_epoch += 1.0

        return max(
            0.0,
            target_epoch - now_epoch
        )

    def apply_send_stagger(
        self,
        message: dict
    ):
        """
        Smooth heavy outbound events after they are built.

        This intentionally does not touch recording timestamps, BirdNET
        detection timestamps, or TDOA timing metadata.
        """

        if not self._message_should_be_staggered(
            message
        ):

            return

        offset_seconds = self._get_node_send_offset_seconds(
            message
        )

        delay_seconds = self._get_fractional_stagger_delay_seconds(
            offset_seconds
        )

        spacing_seconds = self._get_event_spacing_seconds()

        with self.stagger_lock:

            now_monotonic = time.monotonic()
            earliest_by_spacing = (
                self.last_stagger_send_monotonic
                + spacing_seconds
            )

            target_monotonic = max(
                now_monotonic + delay_seconds,
                earliest_by_spacing
            )

            delay_seconds = max(
                0.0,
                target_monotonic - now_monotonic
            )

            self.last_stagger_send_monotonic = target_monotonic

        if delay_seconds <= 0.0:

            return

        event_type = self._extract_event_type(
            message
        )

        self.log(
            (
                f"Staggering outbound {event_type} by "
                f"{delay_seconds:.3f}s"
            )
        )

        time.sleep(
            delay_seconds
        )

    # ========================================================
    # OUTBOUND SEND HANDLING
    # ========================================================

    def send_event(
        self,
        event: dict
    ):
        """
        Send or queue an outbound node event through the active transport.
        """

        message = self._build_sender_message(
            event
        )

        if not self._can_send_now():

            self.queue_event(
                message
            )

            return False

        success = self._send_message_through_active_transport(
            message
        )

        if success:

            self._increment_state_counter(
                "tx_count"
            )

            self._set_state_value(
                "last_tx_time",
                self._utc_now()
            )

            self.event_services.publish_event_sent(
                self._build_event_sent_event(
                    message=message,
                    queued=False
                )
            )

            return True

        self._increment_state_counter(
            "tx_errors"
        )

        self.queue_event(
            message
        )

        return False

    def queue_event(
        self,
        message: dict
    ):
        """
        Store an outbound message when the active transport cannot send.
        """

        if not self.queue_enabled:

            logging.warning(
                "[Communication] Queue disabled. Message dropped."
            )

            return

        if self.sender_manager is None:

            logging.warning(
                "[Communication] No sender manager available. Message dropped."
            )

            return

        if hasattr(
            self.sender_manager,
            "store_message"
        ):

            self.sender_manager.store_message(
                message
            )

        elif hasattr(
            self.sender_manager,
            "queue_message"
        ):

            self.sender_manager.queue_message(
                message
            )

        else:

            logging.warning(
                "[Communication] Sender manager has no queue method. Message dropped."
            )

            return

        logging.warning(
            "[Communication] Message queued. Queue size: %s",
            self._queue_size()
        )

    def flush_queue(
        self
    ):
        """
        Attempt to send queued messages through the active transport.
        """

        if not self._can_send_now():

            return

        if self.sender_manager is None:

            return

        if hasattr(
            self.sender_manager,
            "retrieve_queue"
        ):

            queued_messages = self.sender_manager.retrieve_queue()

        elif hasattr(
            self.sender_manager,
            "get_queue"
        ):

            queued_messages = self.sender_manager.get_queue()

        else:

            return

        for message in list(
            queued_messages
        ):

            success = self._send_message_through_active_transport(
                message
            )

            if not success:

                self._increment_state_counter(
                    "tx_errors"
                )

                logging.warning(
                    "[Communication] Queue flush stopped after send failure."
                )

                return

            self._remove_queued_message(
                message
            )

            self._increment_state_counter(
                "tx_count"
            )

            self._set_state_value(
                "last_tx_time",
                self._utc_now()
            )

            self.event_services.publish_event_sent(
                self._build_event_sent_event(
                    message=message,
                    queued=True
                )
            )

    # ========================================================
    # MODE HANDLING
    # ========================================================

    def _handle_send_node_change_mode(
        self,
        event: dict
    ):
        """
        Switch outbound Communication mode between Wi-Fi and LoRa.
        """

        requested_transport = self._extract_requested_transport(
            event
        )

        if requested_transport is None:

            logging.warning(
                "[Communication] SEND_NODE_CHANGE_MODE missing supported mode."
            )

            return

        previous_transport = self.active_transport

        if requested_transport == WIFI:

            self.active_transport = WIFI
            self.wifi_enabled = True
            self.lora_enabled = False

        elif requested_transport == LORA:

            self.active_transport = LORA
            self.wifi_enabled = False
            self.lora_enabled = True

        else:

            logging.warning(
                "[Communication] Unsupported communication mode: %s",
                requested_transport
            )

            return

        self._apply_transport_change(
            previous_transport=previous_transport,
            requested_transport=requested_transport,
            source_event=event
        )

    def _apply_transport_change(
        self,
        previous_transport: str,
        requested_transport: str,
        source_event: dict
    ):

        if previous_transport != requested_transport:

            self._stop_listener()
            self._start_active_listener()

        connected = self._can_send_now()

        self._publish_network_state(
            connected=connected,
            reason="mode_change",
            source_event=source_event
        )

        if connected:

            self.flush_queue()

        self.log(
            f"Communication mode set to {requested_transport}"
        )

    def _extract_requested_transport(
        self,
        event: dict
    ):

        payload = self._get_payload(
            event
        )

        candidates = [
            event.get("mode") if isinstance(event, dict) else None,
            event.get("network_mode") if isinstance(event, dict) else None,
            event.get("transport") if isinstance(event, dict) else None,
            event.get("command") if isinstance(event, dict) else None,
            event.get("action") if isinstance(event, dict) else None,
            event.get("value") if isinstance(event, dict) else None,
            payload.get("mode"),
            payload.get("network_mode"),
            payload.get("transport"),
            payload.get("command"),
            payload.get("action"),
            payload.get("value"),
        ]

        for candidate in candidates:

            normalized = self._normalize_transport(
                candidate
            )

            if normalized in (WIFI, LORA):

                return normalized

        return None

    def _normalize_transport(
        self,
        value: Any
    ):

        if value is None:

            return None

        text = str(
            value
        ).strip().lower()

        text = text.replace(
            " ",
            "_"
        )

        return MODE_ALIASES.get(
            text,
            text
        )

    # ========================================================
    # NETWORK STATE HANDLING
    # ========================================================

    def _handle_network_connected(
        self,
        event=None,
        publish: bool = False
    ):

        self._set_state_value(
            "network_connected",
            True
        )

        self._set_state_value(
            "server_reachable",
            True
        )

        if publish:

            self._publish_network_state(
                connected=True,
                reason="inbound_network_connected",
                source_event=event
            )

        self.flush_queue()

    def _handle_network_disconnected(
        self,
        event=None,
        publish: bool = False
    ):

        self._set_state_value(
            "network_connected",
            False
        )

        self._set_state_value(
            "server_reachable",
            False
        )

        if publish:

            self._publish_network_state(
                connected=False,
                reason="inbound_network_disconnected",
                source_event=event
            )

    def _publish_network_state(
        self,
        connected: bool,
        reason: str,
        source_event: dict | None = None
    ):

        event_type = (
            NETWORK_CONNECTED
            if connected
            else NETWORK_DISCONNECTED
        )

        event = {
            "event_type": event_type,
            "source": "communication",
            "target": "node",
            "timestamp": self._utc_now(),
            "payload": {
                "active_transport": self.active_transport,
                "wifi_enabled": self.wifi_enabled,
                "lora_enabled": self.lora_enabled,
                "udp_enabled": self.udp_enabled,
                "reason": reason,
                "source_event_type": (
                    source_event.get("event_type")
                    if isinstance(source_event, dict)
                    else None
                )
            }
        }

        if connected:

            self._set_state_value(
                "network_connected",
                True
            )

            self._set_state_value(
                "server_reachable",
                True
            )

            self.event_services.publish_network_connected(
                event
            )

        else:

            self._set_state_value(
                "network_connected",
                False
            )

            self._set_state_value(
                "server_reachable",
                False
            )

            self.event_services.publish_network_disconnected(
                event
            )

    # ========================================================
    # TRANSPORT CONTROL
    # ========================================================

    def _can_send_now(
        self
    ) -> bool:

        if self.active_transport == WIFI:

            return (
                self.wifi_enabled
                and self.udp_enabled
                and self.sender_manager is not None
            )

        if self.active_transport == LORA:

            return (
                self.lora_enabled
                and self.sender_manager is not None
                and self._sender_supports_lora()
            )

        return False

    def _sender_supports_lora(
        self
    ) -> bool:

        if self.sender_manager is None:

            return False

        return any(
            hasattr(self.sender_manager, method_name)
            for method_name in (
                "send_lora_message",
                "send_lora",
                "send_message_lora"
            )
        )

    def _send_message_through_active_transport(
        self,
        message: dict
    ) -> bool:

        if self.sender_manager is None:

            return False

        self.apply_send_stagger(
            message
        )

        if self.active_transport == WIFI:

            return self._send_wifi_message(
                message
            )

        if self.active_transport == LORA:

            return self._send_lora_message(
                message
            )

        return False

    def _send_wifi_message(
        self,
        message: dict
    ) -> bool:

        if hasattr(
            self.sender_manager,
            "send_wifi_message"
        ):

            return bool(
                self.sender_manager.send_wifi_message(
                    message
                )
            )

        if hasattr(
            self.sender_manager,
            "send_udp_message"
        ):

            return bool(
                self.sender_manager.send_udp_message(
                    message
                )
            )

        if hasattr(
            self.sender_manager,
            "send_message"
        ):

            return bool(
                self.sender_manager.send_message(
                    message
                )
            )

        return False

    def _send_lora_message(
        self,
        message: dict
    ) -> bool:

        for method_name in (
            "send_lora_message",
            "send_lora",
            "send_message_lora"
        ):

            method = getattr(
                self.sender_manager,
                method_name,
                None
            )

            if method is None:

                continue

            return bool(
                method(
                    message
                )
            )

        return False

    def _start_active_listener(
        self
    ):

        if self.listener_manager is None:

            return

        if self.active_transport == WIFI:

            self._call_first_available(
                self.listener_manager,
                (
                    "start_wifi",
                    "start_udp",
                    "start"
                )
            )

            return

        if self.active_transport == LORA:

            self._call_first_available(
                self.listener_manager,
                (
                    "start_lora",
                    "start_lorawan"
                )
            )

    def _stop_listener(
        self
    ):

        if self.listener_manager is None:

            return

        self._call_first_available(
            self.listener_manager,
            (
                "stop",
                "stop_wifi",
                "stop_udp",
                "stop_lora"
            )
        )

    def _close_sender(
        self
    ):

        if self.sender_manager is None:

            return

        self._call_first_available(
            self.sender_manager,
            (
                "close",
                "stop",
                "shutdown"
            )
        )

    def _call_first_available(
        self,
        owner,
        method_names
    ):

        for method_name in method_names:

            method = getattr(
                owner,
                method_name,
                None
            )

            if method is None:

                continue

            try:

                return method()

            except TypeError:

                continue

        return None

    # ========================================================
    # PAYLOAD BUILDERS
    # ========================================================

    def _normalize_bus_event(
        self,
        event_type: str,
        event=None
    ) -> dict:

        if isinstance(
            event,
            dict
        ):

            normalized_event = dict(
                event
            )

            normalized_event["event_type"] = (
                normalized_event.get("event_type")
                or event_type
            )

            return normalized_event

        return {
            "event_type": event_type,
            "source": "node",
            "target": "server",
            "timestamp": self._utc_now(),
            "payload": (
                {}
                if event is None
                else event
            )
        }

    def _build_outbound_event(
        self,
        event_type: str,
        event: dict
    ) -> dict:

        outbound_event = dict(
            event
        )

        outbound_event["event_type"] = event_type

        outbound_event.setdefault(
            "source",
            self._get_node_source()
        )

        outbound_event.setdefault(
            "target",
            "server"
        )

        outbound_event.setdefault(
            "timestamp",
            self._utc_now()
        )

        if "payload" not in outbound_event:

            payload = dict(
                outbound_event
            )

            for key in (
                "event_type",
                "source",
                "target",
                "timestamp"
            ):

                payload.pop(
                    key,
                    None
                )

            outbound_event["payload"] = payload

        return outbound_event

    def _build_sender_message(
        self,
        event: dict
    ) -> dict:

        if self.sender_manager is None:

            return event

        build_message = getattr(
            self.sender_manager,
            "build_message",
            None
        )

        if build_message is None:

            return event

        try:

            return build_message(
                event
            )

        except TypeError:

            return build_message(
                event,
                transport=self.active_transport
            )

    def _build_inbound_bus_event(
        self,
        event_type: str,
        message: dict,
        listener_event: dict
    ) -> dict:

        event = dict(
            message
        )

        event["event_type"] = event_type

        event.setdefault(
            "source",
            "server"
        )

        event.setdefault(
            "target",
            self._get_node_source()
        )

        event.setdefault(
            "timestamp",
            self._utc_now()
        )

        payload = self._get_payload(
            event
        )

        payload["_communication"] = {
            "active_transport": self.active_transport,
            "received_timestamp": listener_event.get(
                "timestamp",
                self._utc_now()
            ) if isinstance(listener_event, dict) else self._utc_now(),
            "transport": listener_event.get(
                "transport",
                self.active_transport
            ) if isinstance(listener_event, dict) else self.active_transport,
            "source_ip": listener_event.get(
                "source_ip"
            ) if isinstance(listener_event, dict) else None,
            "source_port": listener_event.get(
                "source_port"
            ) if isinstance(listener_event, dict) else None,
            "rx_count": self._get_state_value(
                "rx_count",
                0
            ),
            "rx_errors": self._get_state_value(
                "rx_errors",
                0
            )
        }

        event["payload"] = payload

        return event

    def _build_event_sent_event(
        self,
        message: dict,
        queued: bool
    ) -> dict:

        return {
            "event_type": EVENT_SENT,
            "source": "communication",
            "target": "journal",
            "timestamp": self._utc_now(),
            "payload": {
                "message": message,
                "active_transport": self.active_transport,
                "sent_from_queue": queued,
                "tx_count": self._get_state_value(
                    "tx_count",
                    0
                ),
                "tx_errors": self._get_state_value(
                    "tx_errors",
                    0
                ),
                "last_tx_time": self._get_state_value(
                    "last_tx_time",
                    None
                ),
                "queue_size": self._queue_size()
            }
        }

    # ========================================================
    # MESSAGE HELPERS
    # ========================================================

    def _extract_listener_message(
        self,
        listener_event: dict
    ):

        if not isinstance(
            listener_event,
            dict
        ):

            return listener_event

        message = listener_event.get(
            "message"
        )

        if isinstance(
            message,
            dict
        ):

            return message

        payload = listener_event.get(
            "payload"
        )

        if isinstance(
            payload,
            dict
        ) and payload.get("event_type"):

            return payload

        return listener_event

    def _extract_event_type(
        self,
        message: dict
    ):

        return (
            message.get("event_type")
            or message.get("event_name")
            or message.get("name")
        )

    def _get_payload(
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

            return dict(
                payload
            )

        return {}

    def _get_node_source(
        self
    ):

        return (
            self.config.get("node_id")
            or self.config.get("node_name")
            or "node"
        )

    # ========================================================
    # QUEUE HELPERS
    # ========================================================

    def _queue_size(
        self
    ) -> int:

        if self.sender_manager is None:

            return 0

        queue_size = getattr(
            self.sender_manager,
            "queue_size",
            None
        )

        if queue_size is None:

            return 0

        try:

            return int(
                queue_size()
            )

        except Exception:

            return 0

    def _remove_queued_message(
        self,
        message: dict
    ):

        if self.sender_manager is None:

            return

        remove_message = getattr(
            self.sender_manager,
            "remove_message",
            None
        )

        if remove_message is not None:

            remove_message(
                message
            )

    # ========================================================
    # STATE HELPERS
    # ========================================================

    def _increment_state_counter(
        self,
        name: str
    ):

        current_value = self._get_state_value(
            name,
            0
        )

        self._set_state_value(
            name,
            current_value + 1
        )

    def _get_state_value(
        self,
        name: str,
        default=None
    ):

        return getattr(
            self.state,
            name,
            default
        )

    def _set_state_value(
        self,
        name: str,
        value
    ):

        try:

            setattr(
                self.state,
                name,
                value
            )

        except Exception:

            pass

    # ========================================================
    # STATUS
    # ========================================================

    def get_status(
        self
    ) -> dict:

        state_status = (
            self.state.get_status()
            if hasattr(self.state, "get_status")
            else dict(getattr(self.state, "__dict__", {}))
        )

        return {
            "communication_state": state_status,
            "active_transport": self.active_transport,
            "wifi_enabled": self.wifi_enabled,
            "lora_enabled": self.lora_enabled,
            "udp_enabled": self.udp_enabled,
            "queue_enabled": self.queue_enabled,
            "queue_size": self._queue_size(),
            "running": self.running
        }

    # ========================================================
    # TIME
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

    def _epoch_now(
        self
    ) -> float:

        return time.time()
