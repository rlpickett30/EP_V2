# ============================================================
# sender_manager.py
#
# EnviroPulse V2
#
# Subsystem:
#   Communication
#
# Role:
#   Manager
#
# Purpose:
#   Own outbound sender work for the Communication subsystem.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["udp"]
#
# Does:
#   - Create and own udp_sender.py
#   - Create and own sender_database.py
#   - Build outbound messages
#   - Send prepared messages
#   - Store queued messages
#   - Retrieve queued messages
#   - Remove sent messages from queue
#   - Report queue size
#
# Does NOT:
#   - Decide when messages should be sent
#   - Decide when messages should be queued
#   - Flush queues by itself
#   - Publish events
#   - Subscribe to the event bus
#   - Manage communication state
#
# Owner:
#   communication_dispatcher.py
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from communication.udp_sender import (
    UDPSender
)

from communication.sender_database import (
    SenderDatabase
)

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

from typing import Dict
from typing import List


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class SenderManager:

    def __init__(
        self,
        config: dict
    ):

        self.config = config

        udp_config = self.config.get(
            "udp",
            {}
        )

        queue_config = self.config.get(
            "queue",
            {}
        )

        self.udp_sender = UDPSender(
            host=udp_config.get(
                "send_host",
                "127.0.0.1"
            ),
            port=udp_config.get(
                "send_port",
                5005
            )
        )

        self.sender_database = SenderDatabase(
            queue_file=queue_config.get(
                "queue_file",
                "communication/data/send_queue.json"
            )
        )

    # ========================================================
    # BUILD MESSAGE
    # ========================================================

    def build_message(
        self,
        event: Dict
    ) -> Dict:

        return dict(
            event
        )

    # ========================================================
    # SEND MESSAGE
    # ========================================================

    def send_message(
        self,
        message: Dict
    ) -> bool:

        return self.udp_sender.send(
            message
        )

    # ========================================================
    # STORE MESSAGE
    # ========================================================

    def store_message(
        self,
        message: Dict
    ):

        self.sender_database.store(
            message
        )

    # ========================================================
    # RETRIEVE QUEUE
    # ========================================================

    def retrieve_queue(
        self
    ) -> List[Dict]:

        return self.sender_database.retrieve_all()

    # ========================================================
    # REMOVE MESSAGE
    # ========================================================

    def remove_message(
        self,
        message: Dict
    ):

        self.sender_database.remove(
            message
        )

    # ========================================================
    # QUEUE SIZE
    # ========================================================

    def queue_size(
        self
    ) -> int:

        return self.sender_database.count()

    # ========================================================
    # CLEAR QUEUE
    # ========================================================

    def clear_queue(
        self
    ):

        self.sender_database.clear()

    # ========================================================
    # CLOSE
    # ========================================================

    def close(
        self
    ):

        self.udp_sender.close()