# ============================================================
# sender_event_manager.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Own Sender helper scripts
#   - Build outbound messages
#   - Send prepared messages
#   - Store messages
#   - Retrieve messages
#
# Does NOT:
#   - Retry messages
#   - Flush queues
#   - Make decisions
#   - Publish events
#   - Manage state
#
# ============================================================

import json

from typing import Dict
from typing import List

from communication.sender.udp_sender import (
    UDPSender
)

from communication.sender.sender_database import (
    SenderDatabase
)


class SenderEventManager:

    def __init__(
        self
    ):

        self.config = self._load_config()

        self.udp_sender = (
            UDPSender(
                host=self.config[
                    "udp_host"
                ],
                port=self.config[
                    "udp_port"
                ]
            )
        )

        self.sender_database = (
            SenderDatabase(
                queue_file="communication/data/send_queue.json"
            )
        )

    # ========================================================
    # LOAD CONFIG
    # ========================================================

    def _load_config(
        self
    ) -> dict:

        with open(
            "communication/communication_config.json",
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(
                file
            )

    # ========================================================
    # BUILD MESSAGE
    # ========================================================

    def build_message(
        self,
        event: Dict
    ) -> Dict:

        return event

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