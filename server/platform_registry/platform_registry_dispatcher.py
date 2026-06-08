# ============================================================
# platform_registry_dispatcher.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Platform Registry
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own the Platform Registry subsystem workflow.
#   This dispatcher receives raw platform events, coordinates
#   registry managers, and publishes only server-approved events.
#
# Expected config source:
#   platform_registry_config.json
#
# Expected config section:
#   config["platform_registry"]
#
# Does:
#   - Start Platform Registry event subscriptions
#   - Route state events to the state manager
#   - Route platform events to the event manager
#   - Route mode events to the mode manager
#   - Route registration events to the registry manager
#   - Route updated state snapshots to the TDOA manager
#   - Publish server-approved Registry events
#
# Does NOT:
#   - Perform manager work directly
#   - Send UDP messages directly
#   - Solve TDOA
#   - Maintain sensor state internally
#   - Maintain node identity internally
#   - Let raw node events leave Registry as platform truth
#
# Owner:
#   Main / Platform Registry subsystem root
#
# ============================================================


# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from platform_registry.platform_registry_event_services import (
    PlatformRegistryEventServices
)

from platform_registry.platform_registry_registry_manager import (
    PlatformRegistryRegistryManager
)

from platform_registry.platform_registry_state_manager import (
    PlatformRegistryStateManager
)

from platform_registry.platform_registry_mode_manager import (
    PlatformRegistryModeManager
)

from platform_registry.platform_registry_event_manager import (
    PlatformRegistryEventManager
)

from platform_registry.platform_registry_TDOA_manager import (
    PlatformRegistryTDOAManager
)


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import json
import logging
from pathlib import Path


# ============================================================
# PLATFORM REGISTRY DISPATCHER
# ============================================================

class PlatformRegistryDispatcher:
    """
    Owns Platform Registry workflow.

    Registry is the trust boundary between raw incoming node/interface
    events and server-approved platform truth.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        config_path="platform_registry_config.json",
        config=None
    ):
        self.event_bus = event_bus
        self.config_path = config_path

        self.config = config or self._load_config(config_path)

        platform_config = self.config.get(
            "platform_registry",
            {}
        )

        self.debug = platform_config.get(
            "debug",
            False
        )

        self.logger = logging.getLogger(self.__class__.__name__)

        self.event_services = PlatformRegistryEventServices(
            event_bus=self.event_bus,
            config=self.config
        )

        self.registry_manager = PlatformRegistryRegistryManager(
            config=self.config
        )

        self.state_manager = PlatformRegistryStateManager(
            config=self.config
        )

        self.mode_manager = PlatformRegistryModeManager(
            config=self.config
        )

        self.event_manager = PlatformRegistryEventManager(
            config=self.config
        )

        self.tdoa_manager = PlatformRegistryTDOAManager(
            config=self.config
        )

        self.started = False

    # ========================================================
    # PUBLIC API
    # ========================================================

    def start(self):
        """
        Start Platform Registry event subscriptions.
        """

        self.event_services.register_subscriptions(self)
        self.started = True

        self._debug_log(
            "Platform Registry Dispatcher started."
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(self):
        """
        Mark Platform Registry dispatcher stopped.
        """

        self.started = False

        self._debug_log(
            "Platform Registry Dispatcher stopped."
        )

    def get_platform_snapshot(self):
        """
        Return combined Registry snapshot.
        """

        return {
            "registry": self.registry_manager.get_registry_snapshot(),
            "state": self.state_manager.get_platform_state_snapshot(),
            "mode": self.mode_manager.get_platform_mode_snapshot(),
            "tdoa": self.tdoa_manager.get_tdoa_status_snapshot()
        }

    # ========================================================
    # EVENT HANDLERS
    # ========================================================

    def handle_registry_event(self, *args):
        """
        Handle registration events.

        Expected events:
            node_register
            gui_register
        """

        event_name, payload = self._parse_event_args(args)

        if event_name is None:
            self._publish_validation_failed(
                "Registry event rejected. Missing event name.",
                payload
            )
            return

        if event_name == "node_register":
            result = self.registry_manager.register_node(payload)

            self._publish_manager_result(
                result=result,
                success_event_key="SERVER_NODE_REGISTERED",
                publish_method=self.event_services.publish_registry_event,
                original_payload=payload
            )
            return

        if event_name == "gui_register":
            result = self.registry_manager.register_gui(payload)

            self._publish_manager_result(
                result=result,
                success_event_key="SERVER_GUI_REGISTERED",
                publish_method=self.event_services.publish_registry_event,
                original_payload=payload
            )
            return

        self._publish_validation_failed(
            f"Unknown registry event: {event_name}",
            payload
        )

    def handle_state_event(self, *args):
        """
        Handle state events.

        Raw event enters Registry.
        State Manager updates canonical truth.
        Dispatcher publishes SERVER_* state event.
        Dispatcher then asks TDOA Manager whether capability changed.
        """

        event_name, payload = self._parse_event_args(args)

        if not self._prepare_node_source(event_name, payload):
            return

        state_result = self.state_manager.handle_state_event(
            event_name=event_name,
            payload=payload
        )

        if not state_result["success"]:
            self._publish_validation_failed(
                state_result["reason"],
                payload
            )
            return

        if state_result["publish"]:
            self.event_services.publish_state(
                state_result["server_event_key"],
                state_result["server_payload"]
            )

        self._evaluate_tdoa_after_state_update(state_result)

    def handle_platform_event(self, *args):
        """
        Handle occurrence-based platform events.

        Expected examples:
            weather
            gps_coord
            avis_lite
            tdoa_calc
        """

        event_name, payload = self._parse_event_args(args)

        if not self._prepare_node_source(event_name, payload):
            return

        event_result = self.event_manager.handle_platform_event(
            event_name=event_name,
            payload=payload
        )

        if not event_result["success"]:
            self._publish_validation_failed(
                event_result["reason"],
                payload
            )
            return

        if event_result["publish"]:
            self.event_services.publish_registry_event(
                event_result["server_event_key"],
                event_result["server_payload"]
            )

    def handle_mode_event(self, *args):
        """
        Handle GUI/user requested node behavior changes.

        Mode Manager validates and updates desired node mode.
        Dispatcher publishes SERVER_* command event.
        Sender should subscribe to these command events.
        """

        event_name, payload = self._parse_event_args(args)

        if not self._prepare_node_source(event_name, payload):
            return

        mode_result = self.mode_manager.handle_mode_event(
            event_name=event_name,
            payload=payload
        )

        if not mode_result["success"]:
            self._publish_validation_failed(
                mode_result["reason"],
                payload
            )
            return

        if mode_result["publish"]:
            event_key = self._normalize_mode_event_key(
                mode_result["server_event_key"]
            )

            self.event_services.publish_mode_command(
                event_key,
                mode_result["server_payload"]
            )

    def handle_tdoa_event(self, *args):
        """
        Handle externally published TDOA capability events.

        Most TDOA capability events should be created internally after
        state updates. This method exists because Event Services may also
        subscribe to raw node_tdoa_capable / node_tdoa_capable_lost.
        """

        event_name, payload = self._parse_event_args(args)

        if event_name not in [
            "node_tdoa_capable",
            "node_tdoa_capable_lost"
        ]:
            self._publish_validation_failed(
                f"Unknown TDOA event: {event_name}",
                payload
            )
            return

        self.event_services.publish_tdoa_event(
            self._tdoa_raw_to_server_key(event_name),
            payload
        )

    # ========================================================
    # TDOA WORKFLOW
    # ========================================================

    def _evaluate_tdoa_after_state_update(self, state_result):
        """
        Evaluate whether a state change caused a TDOA capability transition.
        """

        node_id = state_result.get("node_id")
        state_snapshot = state_result.get("state_snapshot")

        if not node_id or state_snapshot is None:
            return

        tdoa_result = self.tdoa_manager.evaluate_node_state(
            node_id=node_id,
            node_state=state_snapshot
        )

        if not tdoa_result["success"]:
            self._publish_validation_failed(
                tdoa_result["reason"],
                state_snapshot
            )
            return

        if tdoa_result["publish"]:
            self.event_services.publish_tdoa_event(
                tdoa_result["server_event_key"],
                tdoa_result["server_payload"]
            )

    # ========================================================
    # SOURCE PREPARATION
    # ========================================================

    def _prepare_node_source(self, event_name, payload):
        """
        Ensure a node source exists before passing event to managers.

        V2.0 behavior:
            If unknown nodes are allowed, create a provisional node record.
            If not allowed, reject the event.
        """

        if payload is None:
            payload = {}

        node_id = payload.get("node_id")

        if not node_id:
            self._publish_validation_failed(
                f"{event_name} rejected. Missing node_id.",
                payload
            )
            return False

        if self.registry_manager.node_known(node_id):
            return True

        register_result = self.registry_manager.register_node(
            {
                "node_id": node_id,
                "node_name": payload.get("node_name", node_id),
                "node_role": payload.get("node_role", "field_node"),
                "source": payload.get("source", "auto_registered"),
                "capabilities": payload.get("capabilities", {})
            }
        )

        if not register_result["success"]:
            self._publish_validation_failed(
                register_result["reason"],
                payload
            )
            return False

        self.event_services.publish_registry_event(
            "SERVER_NODE_REGISTERED",
            register_result
        )

        return True

    # ========================================================
    # RESULT PUBLICATION HELPERS
    # ========================================================

    def _publish_manager_result(
        self,
        result,
        success_event_key,
        publish_method,
        original_payload
    ):
        """
        Publish successful manager result or validation failure.
        """

        if not result["success"]:
            self._publish_validation_failed(
                result["reason"],
                original_payload
            )
            return

        publish_method(
            success_event_key,
            result
        )

    def _publish_validation_failed(self, reason, payload=None):
        """
        Publish validation failure through Event Services.
        """

        self.event_services.publish_validation_failed(
            reason=reason,
            payload=payload or {}
        )

    # ========================================================
    # EVENT ARGUMENT HANDLING
    # ========================================================

    def _parse_event_args(self, args):
        """
        Support both common Event Bus callback styles:

            handler(payload)

        and:

            handler(event_name, payload)

        If only payload is provided, event_name must be inside payload as:
            event_type
            event_name
            incoming_event
        """

        if len(args) == 2:
            event_name = args[0]
            payload = args[1] or {}
            return event_name, payload

        if len(args) == 1:
            payload = args[0] or {}

            event_name = (
                payload.get("event_type")
                or payload.get("event_name")
                or payload.get("incoming_event")
            )

            return event_name, payload

        return None, {}

    def _normalize_mode_event_key(self, event_key):
        """
        Convert mode manager keys to Event Services publication keys.

        Current mode manager returns:
            SERVER_ENERGY_ONSET

        Current Event Services expects:
            SERVER_ENERGY_ONSET_COMMAND
        """

        if event_key in self.event_services.publications:
            return event_key

        command_key = f"{event_key}_COMMAND"

        if command_key in self.event_services.publications:
            return command_key

        return event_key

    def _tdoa_raw_to_server_key(self, event_name):
        """
        Convert raw TDOA event name to server event key.
        """

        if event_name == "node_tdoa_capable":
            return "SERVER_NODE_TDOA_CAPABLE"

        if event_name == "node_tdoa_capable_lost":
            return "SERVER_NODE_TDOA_CAPABLE_LOST"

        return "SERVER_REGISTRY_WARNING"

    # ========================================================
    # CONFIG
    # ========================================================

    def _load_config(self, config_path):
        """
        Load Platform Registry config.

        Note:
            platform_registry_config.json must be one valid JSON object.
            Multiple separate JSON objects in one file will fail.
        """

        path = Path(config_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Platform Registry config not found: {config_path}"
            )

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    # ========================================================
    # DEBUG
    # ========================================================

    def _debug_log(self, message):
        """
        Emit debug logs when enabled.
        """

        if self.debug:
            self.logger.debug(message)