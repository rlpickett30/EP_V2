"""
sender_manager.py

Purpose:
    Execute sender actions requested by
    sender_dispatcher.

Responsibilities:
    - Build outbound UDP messages
    - Send UDP messages
    - Store messages locally
    - Flush queued messages

Not Responsible For:
    - Network decisions
    - Retry logic
    - State management
    - Mode selection
    - Event routing
"""

from typing import Dict, List

from sender.sender.UDP_sender import UDPSender
from sender.sender.node_database import NodeDatabase
from sender.sender.udp_message_builder import UDPMessageBuilder


class SenderManager:

    def __init__(
        self,
        udp_sender: UDPSender,
        node_database: NodeDatabase,
        udp_builder: UDPMessageBuilder
    ):

        self.udp_sender = udp_sender
        self.node_database = node_database
        self.udp_builder = udp_builder

    # =====================================================
    # SEND EVENT
    # =====================================================

    def send_udp(
        self,
        event: Dict
    ) -> bool:

        message = self.udp_builder.build(
            event
        )

        return self.udp_sender.send(
            message
        )

    # =====================================================
    # STORE EVENT
    # =====================================================

    def store_event(
        self,
        event: Dict
    ) -> None:

        message = self.udp_builder.build(
            event
        )

        self.node_database.store(
            message
        )

    # =====================================================
    # RETRIEVE QUEUE
    # =====================================================

    def get_queue(
        self
    ) -> List[Dict]:

        return self.node_database.retrieve_all()

    # =====================================================
    # QUEUE COUNT
    # =====================================================

    def queue_size(
        self
    ) -> int:

        return self.node_database.count()

    # =====================================================
    # CLEAR QUEUE
    # =====================================================

    def clear_queue(
        self
    ) -> None:

        self.node_database.clear()

    # =====================================================
    # FLUSH QUEUE
    # =====================================================

    def flush_queue(
        self
    ) -> int:

        queued_messages = (
            self.node_database.retrieve_all()
        )

        if not queued_messages:

            return 0

        successful_messages = []

        for message in queued_messages:

            success = (
                self.udp_sender.send(
                    message
                )
            )

            if success:

                successful_messages.append(
                    message
                )

        if len(successful_messages) == len(
            queued_messages
        ):

            self.node_database.clear()

        return len(successful_messages)