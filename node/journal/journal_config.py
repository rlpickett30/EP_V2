# ============================================================
# journal_config.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Journal
#
# Role:
#   Helper Script
#
# Purpose:
#   Store default Journal configuration values used by JournalManager.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Store Journal default settings
#   - Enable or disable Journal output
#   - Control terminal printing
#   - Control whether source, event type, and payload fields are included
#
# Does NOT:
#   - Publish events
#   - Subscribe to the event bus
#   - Record events directly
#   - Format journal entries
#   - Own Journal workflow
#
# Owner:
#   journal_manager.py
#
# ============================================================


JOURNAL_CONFIG = {

    "enabled": True,

    "print_to_terminal": True,

    "include_source": True,

    "include_event_type": True,

    "include_payload": True,
}