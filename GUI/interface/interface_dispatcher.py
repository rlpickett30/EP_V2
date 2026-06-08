# ============================================================
# interface_dispatcher.py
#
# EnviroPulse V2
#
# Subsystem:
#   Interface
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own Interface subsystem workflow and connect GUI actions
#   to platform events.
#
# Does:
#   - Create and own viewer_manager.py
#   - Create and own command_manager.py
#   - Create and own interface_event_services.py
#   - Connect viewer buttons to Interface handlers
#   - Route repository updates to the viewer
#   - Ask Event Services to publish Interface events
#
# Does NOT:
#   - Publish directly
#   - Send UDP packets
#   - Store state
#   - Decide server behavior
#   - Decide node behavior
#   - Perform Event Bus delivery logic
#
# Owner:
#   Main / GUI subsystem root
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
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


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class InterfaceDispatcher:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus
    ):

        self.event_bus = event_bus

        self.viewer = ViewerManager()

        self.commands = CommandManager()

        self.event_services = InterfaceEventServices(
            event_bus=self.event_bus
        )

        self.event_services.register_subscriptions(
            dispatcher=self
        )

        self._wire_gui_actions()

        self.running = False

    # ========================================================
    # WIRE GUI ACTIONS
    # ========================================================

    def _wire_gui_actions(
        self
    ):

        self.viewer.enable_wifi_button.clicked.connect(
            self.handle_enable_wifi
        )

        self.viewer.enable_lora_button.clicked.connect(
            self.handle_enable_lora
        )

        self.viewer.energy_onset_button.clicked.connect(
            self.handle_energy_onset
        )

        self.viewer.pattern_onset_button.clicked.connect(
            self.handle_pattern_onset
        )

        self.viewer.amp_feature_button.clicked.connect(
            self.handle_amp_feature
        )

        self.viewer.onset_feature_button.clicked.connect(
            self.handle_onset_feature
        )

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
    # HANDLE REPOSITORY UPDATE
    # ========================================================

    def handle_repository_update(
        self,
        event: dict
    ):

        self.viewer.display_event(
            event
        )

    # ========================================================
    # HANDLE ENABLE WIFI
    # ========================================================

    def handle_enable_wifi(
        self
    ):

        self.event_services.publish_enable_wifi(
            target_node=self._selected_node()
        )

    # ========================================================
    # HANDLE ENABLE LORA
    # ========================================================

    def handle_enable_lora(
        self
    ):

        self.event_services.publish_enable_lora(
            target_node=self._selected_node()
        )

    # ========================================================
    # HANDLE ENERGY ONSET
    # ========================================================

    def handle_energy_onset(
        self
    ):

        self.event_services.publish_energy_onset(
            target_node=self._selected_node()
        )

    # ========================================================
    # HANDLE PATTERN ONSET
    # ========================================================

    def handle_pattern_onset(
        self
    ):

        self.event_services.publish_pattern_onset(
            target_node=self._selected_node()
        )

    # ========================================================
    # HANDLE AMP FEATURE
    # ========================================================

    def handle_amp_feature(
        self
    ):

        self.event_services.publish_amp_feature(
            target_node=self._selected_node()
        )

    # ========================================================
    # HANDLE ONSET FEATURE
    # ========================================================

    def handle_onset_feature(
        self
    ):

        self.event_services.publish_onset_feature(
            target_node=self._selected_node()
        )

    # ========================================================
    # SELECTED NODE
    # ========================================================

    def _selected_node(
        self
    ) -> str:

        return self.viewer.node_selector.currentText()

    # ========================================================
    # SHOW
    # ========================================================

    def show(
        self
    ):

        self.viewer.show()
