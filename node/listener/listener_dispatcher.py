# ============================================================
# listener_dispatcher.py
# ============================================================

import logging
import json

from listener.listener_event_services import (
    ListenerEventServices
)

from listener.listener_manager import (
    ListenerManager
)


class ListenerDispatcher:

    def __init__(
        self,
        event_bus
    ):

        self.event_bus = event_bus

        self.manager = (
            ListenerManager(
                dispatcher=self
            )
        )

        self.running = False

    # ========================================================
    # START
    # ========================================================

    def start(self):

        self.running = True

        print(
            "[Listener] Ready"
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(self):

        self.running = False

    # ========================================================
    # HANDLE EVENT
    # ========================================================

    def handle_event(
        self,
        event: dict
    ):

        try:

            message = event.get(
                "message",
                {}
            )

            event_type = message.get(
                "event_type"
            )

            if event_type == "tdoa_request":

                ListenerEventServices.publish_tdoa_request(
                    message
                )

            else:

                logging.warning(
                    f"Unknown listener event: "
                    f"{event_type}"
                )

        except Exception as error:

            logging.exception(
                f"Listener Dispatcher Error: "
                f"{error}"
            )