# ============================================================
# interface_dispatcher.py
#
# EnviroPulse V2 GUI
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
#   - Store node truth
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
    InterfaceEventServices,
    REPOSITORY_STATE_UPDATE,
    REPOSITORY_EVENT_UPDATE,
    NEW_NODE_REGISTERED
)


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class InterfaceDispatcher:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        debug=False
    ):

        self.event_bus = event_bus
        self.debug = debug

        self.viewer = ViewerManager()

        self.commands = CommandManager()

        self.event_services = InterfaceEventServices(
            event_bus=self.event_bus,
            dispatcher=self,
            debug=self.debug
        )

        self.event_services.register_subscriptions()

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

        logging.info(
            "[Interface] Ready."
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self
    ):

        self.running = False

        logging.info(
            "[Interface] Stopped."
        )

    # ========================================================
    # HANDLE BUS EVENT
    # ========================================================

    def handle_bus_event(
        self,
        event_name,
        payload=None
    ):

        event = self._normalize_event(
            event_name=event_name,
            payload=payload
        )

        if event_name == NEW_NODE_REGISTERED:

            self.handle_new_node_registered(
                event
            )

            return

        if event_name == REPOSITORY_STATE_UPDATE:

            self.handle_repository_state_update(
                event
            )

            return

        if event_name == REPOSITORY_EVENT_UPDATE:

            self.handle_repository_event_update(
                event
            )

            return

        logging.warning(
            "[Interface] Unhandled event: %s",
            event_name
        )

    # ========================================================
    # HANDLE NEW NODE REGISTERED
    # ========================================================

    def handle_new_node_registered(
        self,
        event: dict
    ):

        payload = event.get(
            "payload",
            {}
        )

        node_id = payload.get(
            "node_id"
        )

        if node_id:

            self.viewer.add_node(
                node_id
            )

        self.viewer.display_event(
            event
        )

    # ========================================================
    # HANDLE REPOSITORY STATE UPDATE
    # ========================================================

    def handle_repository_state_update(
        self,
        event: dict
    ):

        self.viewer.display_event(
            event
        )

    # ========================================================
    # HANDLE REPOSITORY EVENT UPDATE
    # ========================================================

    def handle_repository_event_update(
        self,
        event: dict
    ):

        self.viewer.display_event(
            event
        )

    # ========================================================
    # LEGACY COMPATIBILITY METHOD
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
    # NORMALIZE EVENT
    # ========================================================

    def _normalize_event(
        self,
        event_name,
        payload
    ) -> dict:

        if payload is None:

            event = {}

        elif isinstance(
            payload,
            dict
        ):

            event = dict(
                payload
            )

        else:

            event = {
                "value": payload
            }

        if not event.get(
            "event_type"
        ):

            event["event_type"] = event_name

        return event

    # ========================================================
    # SHOW
    # ========================================================

    def show(
        self
    ):

        self.viewer.show()