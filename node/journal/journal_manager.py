# ============================================================
# journal_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Journal
#
# Role:
#   Manager
#
# Purpose:
#   Format observed platform events into Journal entries and print the system
#   story according to Journal configuration.
#
# Expected config source:
#   journal_config.py
#
# Expected config section:
#   JOURNAL_CONFIG
#
# Does:
#   - Load Journal configuration defaults
#   - Receive events from JournalDispatcher
#   - Build journal entry dictionaries
#   - Format event timestamp, source, event type, and payload fields
#   - Print journal entries to the terminal when enabled
#
# Does NOT:
#   - Decide event routing
#   - Modify events
#   - Publish events
#   - Subscribe to the event bus
#   - Own Journal subscription registration
#   - Own platform event production
#
# Owner:
#   journal_dispatcher.py
#
# ============================================================

from datetime import datetime

from journal.journal_config import JOURNAL_CONFIG


class JournalManager:

    def __init__(self):

        self.config = JOURNAL_CONFIG

    # ========================================================
    # RECORD EVENT
    # ========================================================

    def record_event(self, event: dict):

        if not self.config.get("enabled", True):
            return

        timestamp = datetime.now().isoformat(timespec="seconds")

        source = event.get("source", "unknown_source")
        event_type = event.get("event_type", "unknown_event")
        payload = event.get("payload", {})

        entry = {
            "timestamp": timestamp,
            "source": source,
            "event_type": event_type,
            "payload": payload,
        }

        self._print_entry(entry)

    # ========================================================
    # PRINT ENTRY
    # ========================================================

    def _print_entry(self, entry: dict):

        if not self.config.get("print_to_terminal", True):
            return

        print("\n[JOURNAL]")
        print(f"Time: {entry['timestamp']}")
        print(f"Source: {entry['source']}")
        print(f"Event: {entry['event_type']}")

        if self.config.get("include_payload", True):
            print(f"Payload: {entry['payload']}")

