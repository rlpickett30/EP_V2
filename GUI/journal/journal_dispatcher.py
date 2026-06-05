# ============================================================
# journal_dispatcher.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Own Journal subsystem
#   - Receive platform events
#   - Send events to JournalManager
#
# Does NOT:
#   - Interpret events
#   - Modify events
#   - Republish events
#
# ============================================================

import logging

from journal.journal_manager import (
    JournalManager
)

from journal.journal_event_services import (
    JournalEventServices
)


class JournalDispatcher:

    def __init__(
        self,
        event_bus
    ):

        self.event_bus = event_bus

        self.manager = (
            JournalManager()
        )

        self.event_services = (
            JournalEventServices(
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

    def start(
        self
    ):

        self.running = True

        logging.info(
            "[Journal] Ready"
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self
    ):

        self.running = False

        logging.info(
            "[Journal] Stopped"
        )

    # ========================================================
    # HANDLE EVENT
    # ========================================================

    def handle_event(
        self,
        event: dict
    ):

        try:

            self.manager.record_event(
                event
            )

        except Exception as error:

            logging.exception(
                f"[Journal] Dispatcher Error: "
                f"{error}"
            )