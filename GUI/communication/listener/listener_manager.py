# ============================================================
# listener_manager.py
#
# EnviroPulse V2
#
# Listener Manager
#
# Responsibilities:
#   - Receive raw packets
#   - Decode payloads
#   - Build normalized listener events
#   - Forward events to dispatcher
#
# Does NOT:
#   - Route messages
#   - Publish events
#   - Make decisions
#
# ============================================================

import json
import logging


class ListenerManager:

    def __init__(self, dispatcher):

        self.dispatcher = dispatcher

    # ========================================================
    # Handle Incoming Packet
    # ========================================================

    def handle_packet(self, packet):

        try:

            payload = packet["payload"]

            # --------------------------------------------
            # Decode UTF-8 JSON payload
            # --------------------------------------------

            message = json.loads(
                payload.decode("utf-8")
            )

            # --------------------------------------------
            # Build normalized event
            # --------------------------------------------

            event = {
                "transport": "udp",
                "timestamp": packet["timestamp"],
                "source_ip": packet["source_ip"],
                "source_port": packet["source_port"],
                "message": message
            }

            self.dispatcher.handle_event(event)

        except json.JSONDecodeError:

            logging.warning(
                "Received invalid JSON packet."
            )

        except Exception as error:

            logging.exception(
                f"Listener Manager Error: {error}"
            )