# ============================================================
# journal_dispatcher.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Journal
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own Journal subsystem workflow and route subscribed platform
#   events to journal storage.
#
# Expected config source:
#   journal_config.json
#
# Expected config section:
#   Full journal config
#
# Does:
#   - Create and own journal_manager.py
#   - Create and own journal_event_services.py
#   - Register Journal event subscriptions
#   - Receive platform events
#   - Send events to Journal Manager
#
# Does NOT:
#   - Interpret event meaning
#   - Modify events
#   - Republish events
#   - Perform Event Bus delivery logic
#
# Owner:
#   Main / Subsystem root
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from journal.journal_manager import (
    JournalManager
)

from journal.journal_event_services import (
    JournalEventServices
)

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class JournalDispatcher:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus
    ):

        self.event_bus = event_bus

        self.manager = JournalManager()

        self.event_services = JournalEventServices(
            event_bus=self.event_bus
        )

        self.running = False
        self.subscribed = False

    # ========================================================
    # START
    # ========================================================

    def start(
        self
    ):

        if not self.subscribed:
            self.event_services.register_subscriptions(
                dispatcher=self
            )

            self.subscribed = True

        self.running = True

        logging.info(
            "[Journal] Dispatcher ready."
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self
    ):

        self.running = False

        logging.info(
            "[Journal] Dispatcher stopped."
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
                f"[Journal] Dispatcher Error: {error}"
            )
