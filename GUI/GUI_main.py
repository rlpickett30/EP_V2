# ============================================================
# GUI_main.py
#
# EnviroPulse V2 GUI
#
# Responsibilities:
#   - Create Event Bus
#   - Create Subsystems
#   - Start Subsystems
#   - Start Qt Application
#
# Does NOT:
#   - Route events
#   - Manage state
#   - Know subsystem internals
#
# ============================================================

import sys
import logging

from PyQt6.QtWidgets import QApplication

from GUI_event_bus import EventBus

from communication.communication_state_manager import (
    CommunicationStateManager
)


from communication.sender.sender_dispatcher import (
    SenderDispatcher
)

from communication.listener.listener_dispatcher import (
    ListenerDispatcher
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
    # COMMUNICATION STATE
    # --------------------------------------------------------

    communication_state = (
        CommunicationStateManager()
    )

    # --------------------------------------------------------
    # SENDER
    # --------------------------------------------------------

    sender = SenderDispatcher(
    event_bus=event_bus
    )

    # --------------------------------------------------------
    # LISTENER
    # --------------------------------------------------------

    listener = (
        ListenerDispatcher(
            communication_state_manager=
                communication_state,
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

    sender.start()

    listener.start()

    node_repository.start()

    journal.start()

    interface.start()

    # --------------------------------------------------------
    # SHOW GUI
    # --------------------------------------------------------

    interface.show()

    logging.info(
        "EnviroPulse GUI Running"
    )

    sys.exit(
        app.exec()
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    main()