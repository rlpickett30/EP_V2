# ============================================================
# gui_registration_helper.py
#
# EnviroPulse V2 GUI
#
# Subsystem:
#   Main
#
# Role:
#   Helper Script
#
# Purpose:
#   Build and publish the GUI registration event during platform
#   startup.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Build GUI registration events
#   - Publish GUI_REGISTER to the local event bus
#   - Provide a clean startup registration helper for GUI_main.py
#
# Does NOT:
#   - Send UDP packets
#   - Receive UDP packets
#   - Manage Communication state
#   - Register Communication subscriptions
#   - Know Communication internals
#   - Start subsystems
#
# Owner:
#   GUI_main.py
#
# ============================================================

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

from datetime import datetime
from uuid import uuid4


# ============================================================
# FUNCTION DEFINITIONS
# ============================================================

def build_gui_registration_event() -> dict:

    timestamp = datetime.utcnow().isoformat()

    return {

    "event_type": "GUI_REGISTER",

    "event_id": (
        "GUI_REGISTER_"
        + timestamp.replace(
            ":",
            ""
        ).replace(
            "-",
            ""
        ).replace(
            ".",
            ""
        )
        + "_"
        + str(
            uuid4()
        )[:8]
    ),

    "timestamp": timestamp,

    "source": "gui",

    "target": "server",

    "payload": {

        "gui_id": "gui_01",

        "gui_name": "EnviroPulse GUI",

        "gui_version": "2.0",

        "role": "operator_interface"

    }

}


def publish_gui_registration(
    event_bus
):

    event = build_gui_registration_event()

    event_bus.publish(
        "GUI_REGISTER",
        event
    )

    return event