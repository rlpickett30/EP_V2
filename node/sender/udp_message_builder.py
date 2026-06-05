"""
udp_message_builder.py

Purpose:
    Convert EnviroPulse events into a standardized
    outbound UDP message format.

Responsibilities:
    - Add message_id
    - Add node_name
    - Add udp_time
    - Preserve all event payload fields
    - Extract wav_path into attachments

Not Responsible For:
    - Sending messages
    - Network decisions
    - Database storage
    - Event routing
"""

import uuid

from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, Any


class UDPMessageBuilder:

    def __init__(self, node_name: str):

        self.node_name = node_name

    def build(self, event: Dict[str, Any]) -> Dict[str, Any]:

        payload = deepcopy(event)

        attachments = []

        wav_path = payload.pop("wav_path", None)

        if wav_path is not None:

            attachments.append(wav_path)

        message = {

            "message_id": str(uuid.uuid4()),

            "node_name": self.node_name,

            "udp_time": (
                datetime.now(timezone.utc)
                .isoformat()
            ),

            "event_type": payload.get(
                "event_type",
                "unknown"
            ),

            "payload": payload,

            "attachments": attachments
        }

        return message