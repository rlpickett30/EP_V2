# ============================================================
# listener_dispatcher.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Own Listener subsystem
#   - Route listener events
#   - Update communication state
#   - Publish local bus events
#
# Does NOT:
#   - Decode packets
#   - Publish directly
#   - Store state
#
# ============================================================

import logging

from communication.listener.listener_manager import (
    ListenerManager
)

from communication.listener.listener_event_services import (
    ListenerEventServices
)


class ListenerDispatcher:

    def __init__(
        self,
        communication_state_manager,
        event_bus
    ):

        self.event_bus = event_bus

        self.state = (
            communication_state_manager
        )

        self.manager = (
            ListenerManager(
                dispatcher=self
            )
        )

        self.event_services = (
            ListenerEventServices(
                event_bus=self.event_bus
            )
        )

        self.event_services.register_subscriptions(
            dispatcher=self
        )

        self.running = False

    # ========================================================
    # START
    # ========================================================

    def start(self):

        self.running = True

        logging.info(
            "[Listener] Ready"
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(self):

        self.running = False

        logging.info(
            "[Listener] Stopped"
        )

    # ========================================================
    # HANDLE EVENT
    # ========================================================

    def handle_event(
        self,
        event: dict
    ):

        try:

            self.state.rx_count += 1

            self.state.last_rx_time = (
                event.get(
                    "timestamp"
                )
            )

            message = event.get(
                "message",
                {}
            )

            event_type = message.get(
                "event_type"
            )

            # ============================================
            # NETWORK STATE
            # ============================================

            if event_type == "NETWORK_CONNECTED":

                self.state.network_connected = True

            elif event_type == "NETWORK_DISCONNECTED":

                self.state.network_connected = False

            # ============================================
            # PUBLISH EVENT
            # ============================================

            if event_type in (
                self.event_services.PUBLICATIONS
            ):

                self.event_services.publish(
                    event_type,
                    message
                )

            else:

                logging.warning(
                    f"[Listener] Unknown event: "
                    f"{event_type}"
                )

        except Exception as error:

            logging.exception(
                f"[Listener] Dispatcher Error: "
                f"{error}"
            )