# ============================================================
# journal_event_services.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Document Journal communication
#   - Register Journal subscriptions
#
# Does NOT:
#   - Publish events
#   - Make decisions
#   - Store data
#
# ============================================================


class JournalEventServices:

    # ========================================================
    # EVENT COMMUNICATION INDEX
    # ========================================================
    #
    # SUBSCRIPTIONS
    #
    # ALL PLATFORM EVENTS
    #
    # Published By:
    #     Any subsystem
    #
    # Consumed By:
    #     Journal
    #
    # Purpose:
    #     Record platform history for debugging,
    #     auditing, replay, and analysis.
    #
    # ========================================================
    #
    # PUBLICATIONS
    #
    # None
    #
    # Journal is a terminal consumer.
    #
    # ========================================================

    SUBSCRIPTIONS = [

        "*"

    ]

    PUBLICATIONS = []

    def __init__(
        self,
        event_bus
    ):

        self.event_bus = event_bus

    # ========================================================
    # REGISTER SUBSCRIPTIONS
    # ========================================================

    def register_subscriptions(
        self,
        dispatcher
    ):

        #
        # Depending on how your EventBus evolves:
        #
        # Option 1:
        # subscribe("*", ...)
        #
        # Option 2:
        # manually subscribe every event
        #
        # For now we leave the implementation
        # here so ownership stays with
        # Event Services.
        #

        pass