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
#   Own the Journal subsystem workflow and route subscribed node platform
#   events to JournalManager.
#
# Expected config source:
#   journal_config.py
#
# Expected config section:
#   JOURNAL_CONFIG
#
# Does:
#   - Create and own JournalManager
#   - Create and own JournalEventServices
#   - Register Journal event subscriptions
#   - Receive subscribed platform events
#   - Send received events to JournalManager
#   - Start and stop Journal dispatcher state
#
# Does NOT:
#   - Interpret event meaning
#   - Modify events
#   - Republish events
#   - Perform Event Bus delivery logic
#   - Format journal entries directly
#   - Own subsystem event producers
#
# Owner:
#   Main / Subsystem root
#
# ============================================================

from __future__ import annotations


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
