# ============================================================
# interface_dispatcher.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Own Interface subsystem
#   - Connect GUI actions to platform events
#   - Route repository updates to viewer
#
# Does NOT:
#   - Publish directly
#   - Store state
#   - Perform business logic
#
# ============================================================

from interface.viewer_manager import (
    ViewerManager
)

from interface.command_manager import (
    CommandManager
)

from interface.interface_event_services import (
    InterfaceEventServices
)


class InterfaceDispatcher:

    def __init__(
        self,
        event_bus
    ):

        self.event_bus = event_bus

        self.viewer = (
            ViewerManager()
        )

        self.commands = (
            CommandManager()
        )

        self.event_services = (
            InterfaceEventServices(
                event_bus=self.event_bus
            )
        )

        self.event_services.register_subscriptions(
            dispatcher=self
        )

        # --------------------------------------------
        # GUI Wiring
        # --------------------------------------------

        self.viewer.test_button.clicked.connect(

            self.handle_enable_wifi

        )

        self.running = False

    # ========================================================
    # START
    # ========================================================

    def start(
        self
    ):

        self.running = True

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self
    ):

        self.running = False

    # ========================================================
    # REPOSITORY UPDATE
    # ========================================================

    def handle_repository_update(
        self,
        event: dict
    ):

        self.viewer.display_event(
            event
        )

    # ========================================================
    # ENABLE WIFI
    # ========================================================

    def handle_enable_wifi(
        self
    ):

        self.event_services.publish_enable_wifi()

    # ========================================================
    # SHOW
    # ========================================================

    def show(
        self
    ):

        self.viewer.show()