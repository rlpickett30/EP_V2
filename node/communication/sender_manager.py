# ============================================================
# sender_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Node Communication
#
# Role:
#   Manager
#
# Purpose:
#   Own outbound sender work for the Communication subsystem. Build prepared
#   outbound messages, send ordinary messages through UDPSender, upload guarded
#   TDOA recordings through TDOAUploadClient, and manage the persistent
#   outbound UDP queue through SenderDatabase.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["udp"], config["queue"]
#
# Does:
#   - Create and own UDPSender
#   - Create and own SenderDatabase
#   - Create and own TDOAUploadClient
#   - Build outbound messages
#   - Send prepared messages over UDP
#   - Upload guarded TDOA WAVs and event metadata through binary HTTP
#   - Store queued messages
#   - Retrieve queued messages
#   - Remove sent messages from the queue
#   - Clear queued messages
#   - Report queue size
#   - Close the UDP sender
#
# Does NOT:
#   - Decide when messages should be sent
#   - Decide when messages should be queued
#   - Flush queues by itself
#   - Publish events
#   - Subscribe to the event bus
#   - Manage Communication state
#   - Switch Wi-Fi or LoRa modes
#   - Receive inbound messages
#   - Decide whether TDOA_RECORDING uses HTTP or UDP
#   - Cache TDOA upload instructions
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

from communication.tdoa_upload_client import (
    TDOAUploadClient
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

        self.tdoa_upload_client = TDOAUploadClient()

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
    # UPLOAD TDOA RECORDING
    # ========================================================

    def upload_tdoa_recording(
        self,
        event_metadata: Dict,
        wav_path,
        upload_instructions: Dict
    ) -> Dict:

        return self.tdoa_upload_client.upload(
            event_metadata=event_metadata,
            wav_path=wav_path,
            upload_instructions=upload_instructions
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
