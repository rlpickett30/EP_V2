# ============================================================
# node_event_bus.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Node Runtime
#
# Role:
#   Event Bus
#
# Purpose:
#   Provide the central local publish/subscribe system used for
#   communication between node subsystems.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Register subscribers
#   - Remove subscribers
#   - Publish events
#   - Support event_bus.publish(event)
#   - Support event_bus.publish(event_name, event)
#   - Route events to registered subscribers
#   - Report current subscription mappings
#   - Log subscription and publish activity when debug is enabled
#
# Does NOT:
#   - Create events
#   - Store events
#   - Interpret event meaning
#   - Own subsystem workflow
#   - Own threading
#   - Own queue management
#   - Own transport or network delivery
#
# Owner:
#   node_main.py
#
# ============================================================

from collections import defaultdict
import logging


class EventBus:

    def __init__(self, debug: bool = False):

        self.debug = debug

        self._subscriptions = defaultdict(list)

    # ==================================================
    # SUBSCRIBE
    # ==================================================

    def subscribe(
        self,
        event_name: str,
        callback
    ):

        if callback not in self._subscriptions[event_name]:

            self._subscriptions[event_name].append(
                callback
            )

            if self.debug:

                logging.info(
                    f"[BUS] SUBSCRIBE "
                    f"{event_name} -> "
                    f"{callback.__name__}"
                )

    # ==================================================
    # UNSUBSCRIBE
    # ==================================================

    def unsubscribe(
        self,
        event_name: str,
        callback
    ):

        if callback in self._subscriptions[event_name]:

            self._subscriptions[event_name].remove(
                callback
            )

            if self.debug:

                logging.info(
                    f"[BUS] UNSUBSCRIBE "
                    f"{event_name} -> "
                    f"{callback.__name__}"
                )

    # ==================================================
    # PUBLISH
    # ==================================================
    
    def publish(self, event_name, event=None):
        """
        Supports both forms:

        New/simple form:
            event_bus.publish(event)

        Explicit form:
            event_bus.publish(event_name, event)
        """

        if event is None and isinstance(event_name, dict):
            event = event_name
            event_name = event.get("event_type")

        if not event_name:
            logging.warning("[BUS] PUBLISH skipped because event_type is missing.")
            return

        subscribers = self._subscriptions.get(event_name, [])

        if self.debug:
            logging.info(
                f"[BUS] PUBLISH "
                f"{event_name} "
                f"({len(subscribers)} subscribers)"
            )

        for callback in subscribers:
            try:
                callback(event)

            except Exception as error:
                logging.exception(
                    f"[BUS] ERROR "
                    f"{event_name} -> "
                    f"{callback.__name__}: "
                    f"{error}"
                )
    # ==================================================
    # STATUS
    # ==================================================

    def get_subscriptions(self):

        return {

            event_name: [
                callback.__name__
                for callback
                in callbacks
            ]

            for event_name, callbacks
            in self._subscriptions.items()
        }