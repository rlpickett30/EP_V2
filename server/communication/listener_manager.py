# ============================================================
# listener_manager.py
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
#   Own inbound listener work for the Communication subsystem.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["udp"]
#
# Does:
#   - Create and own udp_listener.py
#   - Receive raw packets from udp_listener.py
#   - Decode UTF-8 JSON payloads
#   - Build normalized inbound listener events
#   - Forward decoded events to communication_dispatcher.py
#
# Does NOT:
#   - Route messages
#   - Publish events
#   - Send messages
#   - Store messages
#   - Make communication decisions
#
# Owner:
#   communication_dispatcher.py
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from communication.udp_listener import (
    UDPListener
)

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import json
import logging
import threading


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class ListenerManager:

    def __init__(
        self,
        dispatcher,
        config: dict
    ):

        self.dispatcher = dispatcher
        self.config = config

        udp_config = self.config.get(
            "udp",
            {}
        )

        self.udp_listener = UDPListener(
            host=udp_config.get(
                "listen_host",
                "0.0.0.0"
            ),
            port=udp_config.get(
                "listen_port",
                5005
            ),
            listener_manager=self
        )

        self.listener_thread = None

    # ========================================================
    # START
    # ========================================================

    def start(
        self
    ):

        self.listener_thread = threading.Thread(
            target=self.udp_listener.start,
            daemon=True
        )

        self.listener_thread.start()

        logging.info(
            "[Communication] Listener Manager started."
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self
    ):

        self.udp_listener.stop()

        logging.info(
            "[Communication] Listener Manager stopped."
        )

    # ========================================================
    # HANDLE PACKET
    # ========================================================

    def handle_packet(
        self,
        packet: dict
    ):

        try:

            payload = packet[
                "payload"
            ]

            message = json.loads(
                payload.decode(
                    "utf-8"
                )
            )

            listener_event = {

                "transport": "udp",

                "timestamp": packet.get(
                    "timestamp"
                ),

                "source_ip": packet.get(
                    "source_ip"
                ),

                "source_port": packet.get(
                    "source_port"
                ),

                "message": message

            }

            self.dispatcher.handle_inbound_event(
                listener_event
            )

        except json.JSONDecodeError:

            logging.warning(
                "[Communication] Received invalid JSON packet."
            )

        except Exception as error:

            logging.exception(
                f"[Communication] Listener Manager Error: "
                f"{error}"
            )