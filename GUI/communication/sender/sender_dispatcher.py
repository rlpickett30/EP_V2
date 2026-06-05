# ============================================================
# sender_dispatcher.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Own Sender subsystem
#   - Decide when to send
#   - Decide when to queue
#   - Decide when to flush queue
#   - Maintain sender modes
#   - Update communication state
#
# Does NOT:
#   - Send UDP directly
#   - Store messages directly
#   - Publish directly
#   - Require Main to build sender internals
#
# ============================================================

import logging

from communication.communication_state_manager import (
    CommunicationStateManager
)

from communication.sender.sender_event_manager import (
    SenderEventManager
)

from communication.sender.sender_event_services import (
    SenderEventServices
)


class SenderDispatcher:

    def __init__(
        self,
        event_bus
    ):

        self.event_bus = event_bus

        self.communication_state = (
            CommunicationStateManager()
        )

        self.manager = (
            SenderEventManager()
        )

        self.event_services = (
            SenderEventServices(
                event_bus=self.event_bus
            )
        )

        self.event_services.register_subscriptions(
            dispatcher=self
        )

        self.energy_enabled = True
        self.pattern_enabled = True
        self.onset_enabled = True
        self.amp_enabled = True

        self.wifi_enabled = True
        self.lora_enabled = False

        self.running = False

    # ========================================================
    # START
    # ========================================================

    def start(
        self
    ):

        self.running = True

        logging.info(
            "[Sender] Ready"
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self
    ):

        self.running = False

        logging.info(
            "[Sender] Stopped"
        )

    # ========================================================
    # HANDLE EVENT
    # ========================================================

    def handle_event(
        self,
        event: dict
    ):

        try:

            event_type = event.get(
                "event_type"
            )

            if event_type == "NETWORK_CONNECTED":

                self.communication_state.network_connected = True

                self.event_services.publish_network_connected(
                    event
                )

                self.flush_queue()

            elif event_type == "NETWORK_DISCONNECTED":

                self.communication_state.network_connected = False

                self.event_services.publish_network_disconnected(
                    event
                )

            elif event_type == "ENABLE_WIFI":

                self.wifi_enabled = True

            elif event_type == "DISABLE_WIFI":

                self.wifi_enabled = False

            elif event_type == "ENABLE_LORA":

                self.lora_enabled = True

            elif event_type == "DISABLE_LORA":

                self.lora_enabled = False

            elif event_type == "ENERGY_ONSET":

                self.energy_enabled = True

            elif event_type == "ENERGY_OFFSET":

                self.energy_enabled = False

            elif event_type == "PATTERN_ONSET":

                self.pattern_enabled = True

            elif event_type == "PATTERN_OFFSET":

                self.pattern_enabled = False

            elif event_type == "ONSET_FEATURE":

                self.onset_enabled = True

            elif event_type == "AMP_FEATURE":

                self.amp_enabled = True

            elif event_type == "GUI_REGISTER":

                self.send_event(
                    event
                )

        except Exception as error:

            logging.exception(
                f"[Sender] Dispatcher Error: "
                f"{error}"
            )

    # ========================================================
    # SEND EVENT
    # ========================================================

    def send_event(
        self,
        event: dict
    ):

        message = (
            self.manager.build_message(
                event
            )
        )

        if not self.wifi_enabled:

            self.manager.store_message(
                message
            )

            return

        success = (
            self.manager.send_message(
                message
            )
        )

        if success:

            self.communication_state.tx_count += 1

        else:

            self.communication_state.tx_errors += 1

            self.manager.store_message(
                message
            )

    # ========================================================
    # FLUSH QUEUE
    # ========================================================

    def flush_queue(
        self
    ):

        queued_messages = (
            self.manager.retrieve_queue()
        )

        for message in queued_messages:

            success = (
                self.manager.send_message(
                    message
                )
            )

            if success:

                self.manager.remove_message(
                    message
                )