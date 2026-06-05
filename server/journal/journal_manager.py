# ============================================================
# journal_manager.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Format journal entries
#   - Print system story events
#
# Does NOT:
#   - Decide routing
#   - Modify events
#   - Publish events
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

