# ============================================================
# server_event_bus.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Platform Core
#
# Role:
#   Event Bus
#
# Purpose:
#   Provide local publish / subscribe event delivery for the
#   EnviroPulse server runtime.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Register event subscribers
#   - Deliver published events to subscribers
#   - Support wildcard subscribers
#   - Protect platform runtime from subscriber exceptions
#   - Track basic publish, delivery, and error counts
#   - Optionally retain bounded event history for debugging
#
# Does NOT:
#   - Own subsystem workflow
#   - Validate event meaning
#   - Convert raw node events into SERVER_ truth
#   - Store permanent event records
#   - Send network messages
#   - Know subsystem helper scripts
#
# Owner:
#   Main / Platform Core
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

# None.

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging
import threading

from collections import defaultdict, deque
from datetime import datetime
from typing import Callable, DefaultDict, Deque, Dict, List, Optional


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class EventBus:
    """
    Local in-process Event Bus.

    Default callback form:
        callback(payload)

    Optional callback form:
        callback(event_name, payload)

    Use include_event_name=True when subscribing if the subscriber needs
    the event name as a separate argument.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        retain_history: bool = True,
        max_history: int = 500,
        debug: bool = False
    ):

        self.retain_history = retain_history
        self.max_history = max_history
        self.debug = debug

        self._subscribers: DefaultDict[str, List[dict]] = defaultdict(list)
        self._history: Deque[dict] = deque(maxlen=max_history)
        self._lock = threading.RLock()

        self.publish_count = 0
        self.delivery_count = 0
        self.error_count = 0

        self.logger = logging.getLogger(self.__class__.__name__)

    # ========================================================
    # SUBSCRIBE
    # ========================================================

    def subscribe(
        self,
        event_name: str,
        callback: Callable,
        include_event_name: bool = False
    ):
        """
        Subscribe a callback to an event name.

        Use event_name="*" for all events.
        """

        if not event_name:
            raise ValueError("Event Bus subscribe requires an event name.")

        if not callable(callback):
            raise TypeError("Event Bus subscriber callback must be callable.")

        subscription = {
            "callback": callback,
            "include_event_name": include_event_name
        }

        with self._lock:
            self._subscribers[event_name].append(subscription)

        if self.debug:
            self.logger.debug(
                f"Subscribed callback to event: {event_name}"
            )

    # ========================================================
    # UNSUBSCRIBE
    # ========================================================

    def unsubscribe(
        self,
        event_name: str,
        callback: Callable
    ):
        """
        Remove a callback from an event name.
        """

        with self._lock:
            subscribers = self._subscribers.get(event_name, [])

            self._subscribers[event_name] = [
                subscriber
                for subscriber in subscribers
                if subscriber["callback"] is not callback
            ]

    # ========================================================
    # PUBLISH
    # ========================================================

    def publish(
        self,
        event_name: str,
        payload: Optional[dict] = None
    ):
        """
        Publish one event to all matching subscribers.
        """

        if not event_name:
            raise ValueError("Event Bus publish requires an event name.")

        if payload is None:
            payload = {}

        if not isinstance(payload, dict):
            payload = {
                "value": payload
            }

        payload = self._prepare_payload(
            event_name=event_name,
            payload=payload
        )

        with self._lock:
            subscribers = list(self._subscribers.get(event_name, []))
            wildcard_subscribers = list(self._subscribers.get("*", []))

        all_subscribers = subscribers + wildcard_subscribers

        self.publish_count += 1

        if self.retain_history:
            self._record_history(
                event_name=event_name,
                payload=payload,
                subscriber_count=len(all_subscribers)
            )

        for subscriber in all_subscribers:
            self._deliver(
                subscriber=subscriber,
                event_name=event_name,
                payload=payload
            )

    # ========================================================
    # CLEAR
    # ========================================================

    def clear(
        self
    ):
        """
        Remove all subscriptions and retained history.
        """

        with self._lock:
            self._subscribers.clear()
            self._history.clear()

    # ========================================================
    # GET STATUS
    # ========================================================

    def get_status(
        self
    ) -> dict:
        """
        Return Event Bus runtime status.
        """

        with self._lock:
            subscriber_counts = {
                event_name: len(subscribers)
                for event_name, subscribers in self._subscribers.items()
            }

        return {
            "publish_count": self.publish_count,
            "delivery_count": self.delivery_count,
            "error_count": self.error_count,
            "subscriber_counts": subscriber_counts,
            "history_size": len(self._history)
        }

    # ========================================================
    # GET HISTORY
    # ========================================================

    def get_history(
        self
    ) -> list:
        """
        Return retained Event Bus history.
        """

        with self._lock:
            return list(self._history)

    # ========================================================
    # PREPARE PAYLOAD
    # ========================================================

    def _prepare_payload(
        self,
        event_name: str,
        payload: dict
    ) -> dict:
        """
        Ensure payload carries its event name.
        """

        if "event_type" not in payload:
            payload["event_type"] = event_name

        if "timestamp" not in payload:
            payload["timestamp"] = self._utc_now()

        return payload

    # ========================================================
    # DELIVER
    # ========================================================

    def _deliver(
        self,
        subscriber: dict,
        event_name: str,
        payload: dict
    ):
        """
        Deliver one event to one subscriber.
        """

        callback = subscriber["callback"]

        try:
            if subscriber["include_event_name"]:
                callback(event_name, payload)
            else:
                callback(payload)

            self.delivery_count += 1

        except Exception as error:
            self.error_count += 1

            logging.exception(
                f"[EventBus] Subscriber failed for {event_name}: {error}"
            )

    # ========================================================
    # RECORD HISTORY
    # ========================================================

    def _record_history(
        self,
        event_name: str,
        payload: dict,
        subscriber_count: int
    ):
        """
        Keep bounded debug history.
        """

        with self._lock:
            self._history.append(
                {
                    "timestamp": self._utc_now(),
                    "event_name": event_name,
                    "payload": payload.copy(),
                    "subscriber_count": subscriber_count
                }
            )

    # ========================================================
    # UTC NOW
    # ========================================================

    def _utc_now(
        self
    ) -> str:
        """
        Return current UTC timestamp.
        """

        return datetime.utcnow().isoformat()
