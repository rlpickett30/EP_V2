"""
sender_event_service.py

Purpose:
    Receive outbound EnviroPulse events
    and forward them to sender_dispatcher.

Acts as Sender's mailbox.

Responsibilities:
    - Subscribe to outbound events
    - Receive events from EventBus
    - Forward events to dispatcher

Not Responsible For:
    - Network decisions
    - Message building
    - Routing logic
    - Database operations
    - State management
"""


class SenderEventService:

    def __init__(
        self,
        event_bus,
        sender_dispatcher
    ):

        self.event_bus = event_bus

        self.sender_dispatcher = (
            sender_dispatcher
        )

        self._register_subscriptions()

    # =====================================================
    # REGISTER SUBSCRIPTIONS
    # =====================================================

    def _register_subscriptions(self):

        subscriptions = [

            # ---------------------------------------------
            # BIRDNET
            # ---------------------------------------------

            "AVIS_LITE",

            # ---------------------------------------------
            # TDOA
            # ---------------------------------------------

            "TDOA_RECORDING",

            # ---------------------------------------------
            # GPS
            # ---------------------------------------------

            "GPS_LOCK",
            "GPS_LOST",
            "GPS_COORD",

            # ---------------------------------------------
            # PPS
            # ---------------------------------------------

            "PPS_LOCK",
            "PPS_LOST",

            # ---------------------------------------------
            # WEATHER
            # ---------------------------------------------

            "WEATHER",

            "SHT45_ONLINE",
            "SHT45_FAILURE",

            "BMP390_ONLINE",
            "BMP390_FAILURE"
        ]

        for event_type in subscriptions:

            self.event_bus.subscribe(

                event_type,

                self.handle_event
            )

    # =====================================================
    # EVENT HANDLER
    # =====================================================

    def handle_event(
        self,
        event
    ):

        self.sender_dispatcher.process(
            event
        )