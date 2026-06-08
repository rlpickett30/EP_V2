# ============================================================
# GUI_main.py
#
# EnviroPulse V2 GUI
#
# Subsystem:
#   Main
#
# Role:
#   Startup Script
#
# Purpose:
#   Start the EnviroPulse GUI platform.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Create Qt Application
#   - Create Event Bus
#   - Create top-level GUI subsystems
#   - Start top-level GUI subsystems
#   - Start Qt event loop
#
# Does NOT:
#   - Route events
#   - Manage state
#   - Know subsystem managers
#   - Know helper scripts
#   - Know Communication sender internals
#   - Know Communication listener internals
#   - Manage subsystem workflow
#
# Owner:
#   Platform entry point
#
# ============================================================

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import sys
import logging

from PyQt6.QtWidgets import QApplication

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from GUI_event_bus import EventBus

from gui_registration_helper import (
    publish_gui_registration
)

from communication.communication_dispatcher import (
    CommunicationDispatcher
)

from node_repository.node_repository_dispatcher import (
    NodeRepositoryDispatcher
)

from journal.journal_dispatcher import (
    JournalDispatcher
)

from interface.interface_dispatcher import (
    InterfaceDispatcher
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(

    level=logging.INFO,

    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    )
)


# ============================================================
# MAIN
# ============================================================

def main():

    logging.info(
        "Starting EnviroPulse GUI..."
    )

    # --------------------------------------------------------
    # QT APPLICATION
    # --------------------------------------------------------

    app = QApplication(
        sys.argv
    )

    # --------------------------------------------------------
    # EVENT BUS
    # --------------------------------------------------------

    event_bus = EventBus()

    # --------------------------------------------------------
    # COMMUNICATION
    # --------------------------------------------------------

    communication = (
        CommunicationDispatcher(
            event_bus=event_bus
        )
    )

    # --------------------------------------------------------
    # NODE REPOSITORY
    # --------------------------------------------------------

    node_repository = (
        NodeRepositoryDispatcher(
            event_bus=event_bus
        )
    )

    # --------------------------------------------------------
    # JOURNAL
    # --------------------------------------------------------

    journal = (
        JournalDispatcher(
            event_bus=event_bus
        )
    )

    # --------------------------------------------------------
    # INTERFACE
    # --------------------------------------------------------

    interface = (
        InterfaceDispatcher(
            event_bus=event_bus
        )
    )

        # --------------------------------------------------------
    # START SUBSYSTEMS
    # --------------------------------------------------------

    communication.start()

    node_repository.start()

    journal.start()

    interface.start()

    # --------------------------------------------------------
    # GUI REGISTRATION
    # --------------------------------------------------------

    publish_gui_registration(
        event_bus=event_bus
    )

    # --------------------------------------------------------
    # SHOW GUI
    # --------------------------------------------------------

    interface.show()

    logging.info(
        "EnviroPulse GUI Running"
    )

    # --------------------------------------------------------
    # START QT EVENT LOOP
    # --------------------------------------------------------

    sys.exit(
        app.exec()
    )
# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    main()