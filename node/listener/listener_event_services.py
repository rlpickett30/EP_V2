# ============================================================
# listener_event_services.py
#
# EnviroPulse V2
#
# Listener Event Services
#
# Responsibilities:
#   - Publish listener-related events
#
# ============================================================

from node_event_bus import EventBus


class ListenerEventServices:

    # ========================================================
    # TDOA REQUEST
    # ========================================================

    @staticmethod
    def publish_tdoa_request(event: dict):

        EventBus.publish(
            "TDOA_REQUEST",
            event
        )