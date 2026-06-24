# ============================================================
# node_repository_dispatcher.py
#
# EnviroPulse V2 GUI
#
# Subsystem:
#   Node Repository
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own GUI-side node repository workflow.
#   Maintain local GUI truth for node registry, node state, and node events.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Create and own node_repository_registry_manager.py
#   - Create and own node_repository_state_manager.py
#   - Create and own node_repository_event_manager.py
#   - Create and own node_repository_event_services.py
#   - Receive approved server events from the GUI event bus
#   - Register new nodes from SERVER_NODE_REGISTER
#   - Update node state from NODE_STATE_UPDATED and SERVER_GPS_COORD
#   - Store node event history
#   - Publish repository updates for the Interface
#
# Does NOT:
#   - Render GUI elements
#   - Receive UDP packets
#   - Send UDP packets
#   - Publish directly to the event bus
#   - Require Main to build repository internals
#
# Owner:
#   Main / Subsystem root
#
# ============================================================


# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from node_repository.node_repository_registry_manager import (
    NodeRepositoryRegistryManager
)

from node_repository.node_repository_state_manager import (
    NodeRepositoryStateManager
)

from node_repository.node_repository_event_manager import (
    NodeRepositoryEventManager
)

from node_repository.node_repository_event_services import (
    NodeRepositoryEventServices,
    NODE_STATE_UPDATED,
    NODE_TDOA_STATE,
    SERVER_NODE_REGISTER,
    SERVER_ENVIRO_EVENT,
    SERVER_TDOA_CALC,
    SERVER_GPS_COORD,
    SERVER_AVIS_LITE,
    REPOSITORY_STATE_UPDATE,
    REPOSITORY_EVENT_UPDATE,
    NEW_NODE_REGISTERED
)


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging

from datetime import datetime


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class NodeRepositoryDispatcher:
    """
    Dispatcher for the GUI Node Repository subsystem.

    Node Repository receives server-approved events, maintains local
    GUI-side truth, and publishes repository-ready events to Interface.
    """

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

        self.registry = NodeRepositoryRegistryManager(
            registry_file="node_repository/data/node_registry.json"
        )

        self.state = NodeRepositoryStateManager(
            state_file="node_repository/data/node_state.json"
        )

        self.events = NodeRepositoryEventManager(
            event_file="node_repository/data/node_events.json"
        )

        self.event_services = NodeRepositoryEventServices(
            event_bus=self.event_bus,
            dispatcher=self,
            debug=self.debug
        )

        self.event_services.register_subscriptions()

        self.running = False

        self.state_update_events = {
            NODE_STATE_UPDATED,
            NODE_TDOA_STATE
        }

        self.repository_event_updates = {
            SERVER_ENVIRO_EVENT,
            SERVER_TDOA_CALC,
            SERVER_AVIS_LITE,
            SERVER_GPS_COORD
        }

    # ========================================================
    # START / STOP
    # ========================================================

    def start(
        self
    ):

        self.running = True

        logging.info(
            "[Node Repository] Ready."
        )

    def stop(
        self
    ):

        self.running = False

        logging.info(
            "[Node Repository] Stopped."
        )

    # ========================================================
    # EVENT BUS HANDLING
    # ========================================================

    def handle_bus_event(
        self,
        event_name,
        payload=None
    ):
        """
        Handle events received from the GUI event bus.

        Event services forwards the subscription. Dispatcher decides
        how the repository should update and what should be published.
        """

        try:

            event = self._normalize_payload(
                event_name=event_name,
                payload=payload
            )

            node_id = self._extract_node_id(
                event
            )

            if not node_id:

                logging.warning(
                    "[Node Repository] %s missing node_id.",
                    event_name
                )

                return

            self._ensure_node_storage(
                node_id=node_id
            )

            self.events.store_event(
                node_id,
                event
            )

            if event_name == SERVER_NODE_REGISTER:

                self._handle_server_node_register(
                    node_id=node_id,
                    event=event
                )

                return

            if event_name in self.state_update_events:

                self._handle_state_update(
                    node_id=node_id,
                    event_name=event_name,
                    event=event
                )

                return

            if event_name in self.repository_event_updates:

                self._handle_repository_event_update(
                    node_id=node_id,
                    event_name=event_name,
                    event=event
                )

                return

            logging.warning(
                "[Node Repository] Unhandled repository event: %s",
                event_name
            )

        except Exception as error:

            logging.exception(
                "[Node Repository] Dispatcher error: %s",
                error
            )

    # ========================================================
    # EVENT HANDLERS
    # ========================================================

    def _handle_server_node_register(
        self,
        node_id,
        event
    ):
        """
        Register or update a node and publish NEW_NODE_REGISTERED.
        """

        registry_record = self._extract_registry_record(
            node_id=node_id,
            event=event
        )

        if self.registry.node_exists(
            node_id
        ):

            self.registry.update_node(
                node_id=node_id,
                updates=registry_record
            )

        else:

            self.registry.register_node(
                registry_record
            )

        capabilities = registry_record.get(
            "capabilities",
            {}
        )

        if isinstance(
            capabilities,
            dict
        ) and capabilities:

            self.state.update_state(
                node_id,
                capabilities
            )

        snapshot = self._build_repository_snapshot(
            publication_event_type=NEW_NODE_REGISTERED,
            source_event_type=SERVER_NODE_REGISTER,
            node_id=node_id,
            source_event=event
        )

        self.event_services.publish_new_node_registered(
            snapshot
        )

    def _handle_state_update(
        self,
        node_id,
        event_name,
        event
    ):
        """
        Update node state and publish REPOSITORY_STATE_UPDATE.
        """

        state_update = self._extract_state_update(
            event_name=event_name,
            event=event
        )

        if state_update:

            self.state.update_state(
                node_id,
                state_update
            )

        snapshot = self._build_repository_snapshot(
            publication_event_type=REPOSITORY_STATE_UPDATE,
            source_event_type=event_name,
            node_id=node_id,
            source_event=event
        )

        self.event_services.publish_repository_state_update(
            snapshot
        )

    def _handle_repository_event_update(
        self,
        node_id,
        event_name,
        event
    ):
        """
        Store event history and publish REPOSITORY_EVENT_UPDATE.
        """
        
        derived_state = self._derive_state_from_repository_event(
            event_name=event_name,
            event=event
        )

        if derived_state:

            self.state.update_state(
                node_id,
                derived_state
            )
            
        snapshot = self._build_repository_snapshot(
            publication_event_type=REPOSITORY_EVENT_UPDATE,
            source_event_type=event_name,
            node_id=node_id,
            source_event=event
        )

        self.event_services.publish_repository_event_update(
            snapshot
        )

    # ========================================================
    # STORAGE HELPERS
    # ========================================================

    def _ensure_node_storage(
        self,
        node_id
    ):
        """
        Ensure the node exists in registry, state, and event history.
        """

        if not self.registry.node_exists(
            node_id
        ):

            self.registry.register_node({

                "node_id":
                    node_id,

                "created_by":
                    "node_repository",

                "created_at_utc":
                    self._utc_now()
            })

        if not self.state.node_exists(
            node_id
        ):

            self.state.initialize_node(
                node_id
            )

        self.events.initialize_node(
            node_id
        )

    # ========================================================
    # NORMALIZATION HELPERS
    # ========================================================

    def _normalize_payload(
        self,
        event_name,
        payload
    ) -> dict:

        if payload is None:

            payload = {}

        if not isinstance(
            payload,
            dict
        ):

            payload = {
                "value": payload
            }

        event = dict(
            payload
        )

        event["event_type"] = event_name

        return event

    def _extract_node_id(
        self,
        event
    ):

        # --------------------------------------------
        # Top-level node identity
        # --------------------------------------------

        if event.get(
            "node_id"
        ):

            return event.get(
                "node_id"
            )

        if event.get(
            "device_id"
        ):

            return event.get(
                "device_id"
            )

        # --------------------------------------------
        # First-level payload identity
        # --------------------------------------------

        payload = event.get(
            "payload",
            {}
        )

        if isinstance(
            payload,
            dict
        ):

            if payload.get(
                "node_id"
            ):

                return payload.get(
                    "node_id"
                )

            if payload.get(
                "device_id"
            ):

                return payload.get(
                    "device_id"
                )

            registry_record = payload.get(
                "registry_record",
                {}
            )

            if isinstance(
                registry_record,
                dict
            ) and registry_record.get(
                "node_id"
            ):

                return registry_record.get(
                    "node_id"
                )

            event_record = payload.get(
                "event_record",
                {}
            )

            if isinstance(
                event_record,
                dict
            ) and event_record.get(
                "node_id"
            ):

                return event_record.get(
                    "node_id"
                )

            # --------------------------------------------
            # Nested platform registry node event identity
            # Shape:
            # payload["node_event"]["payload"]["node_id"]
            # --------------------------------------------

            node_event = payload.get(
                "node_event",
                {}
            )

            if isinstance(
                node_event,
                dict
            ):

                if node_event.get(
                    "node_id"
                ):

                    return node_event.get(
                        "node_id"
                    )

                node_event_payload = node_event.get(
                    "payload",
                    {}
                )

                if isinstance(
                    node_event_payload,
                    dict
                ):

                    if node_event_payload.get(
                        "node_id"
                    ):

                        return node_event_payload.get(
                            "node_id"
                        )

                    if node_event_payload.get(
                        "device_id"
                    ):

                        return node_event_payload.get(
                            "device_id"
                        )

                    nested_event_record = node_event_payload.get(
                        "event_record",
                        {}
                    )

                    if isinstance(
                        nested_event_record,
                        dict
                    ) and nested_event_record.get(
                        "node_id"
                    ):

                        return nested_event_record.get(
                            "node_id"
                        )

                    original_payload = node_event_payload.get(
                        "original_payload",
                        {}
                    )

                    if isinstance(
                        original_payload,
                        dict
                    ) and original_payload.get(
                        "node_id"
                    ):

                        return original_payload.get(
                            "node_id"
                        )

        # --------------------------------------------
        # Top-level registry fallback
        # --------------------------------------------

        registry_record = event.get(
            "registry_record",
            {}
        )

        if isinstance(
            registry_record,
            dict
        ) and registry_record.get(
            "node_id"
        ):

            return registry_record.get(
                "node_id"
            )

        return None    

    def _extract_registry_record(
        self,
        node_id,
        event
    ) -> dict:

        registry_record = event.get(
            "registry_record"
        )

        if isinstance(
            registry_record,
            dict
        ):

            record = dict(
                registry_record
            )

        else:

            record = self._strip_internal_fields(
                event
            )

        record["node_id"] = node_id

        return record

    def _extract_state_update(
        self,
        event_name,
        event
    ) -> dict:
        if event_name == NODE_TDOA_STATE:

            tdoa_state = (
                event.get("tdoa_state")
                or event.get("state")
            )

            payload = event.get(
                "payload",
                {}
            )

            if not isinstance(
                tdoa_state,
                dict
            ) and isinstance(
                payload,
                dict
            ):

                tdoa_state = (
                    payload.get("tdoa_state")
                    or payload.get("state")
                )

            if isinstance(
                tdoa_state,
                dict
            ):

                tdoa_ready = bool(
                    tdoa_state.get(
                        "tdoa_ready",
                        False
                    )
                )

                checks = tdoa_state.get(
                    "checks",
                    {}
                )

                update = dict(
                    tdoa_state
                )

                update["tdoa_ready"] = tdoa_ready
                update["tdoa_capable"] = tdoa_ready
                update["rtk_tdoa_capable"] = tdoa_ready
                update["tdoa_missing"] = tdoa_state.get(
                    "missing",
                    []
                )
                update["tdoa_checks"] = checks

                if isinstance(
                    checks,
                    dict
                ):

                    for key, value in checks.items():

                        if isinstance(
                            value,
                            bool
                        ):

                            update[key] = value

                if tdoa_state.get(
                    "microphone_synced"
                ) is True:

                    update["microphone_online"] = True

                return update
            
        if event_name == SERVER_GPS_COORD:

            gps_coord = (
                event.get("gps_coord")
                or event.get("coordinates")
                or event.get("coord")
            )

            if gps_coord is not None:

                return {
                    "gps_coord": gps_coord
                }

            latitude = event.get(
                "latitude"
            )

            longitude = event.get(
                "longitude"
            )

            altitude = event.get(
                "altitude"
            )

            if latitude is not None and longitude is not None:

                return {

                    "gps_coord": {

                        "latitude":
                            latitude,

                        "longitude":
                            longitude,

                        "altitude":
                            altitude
                    }
                }

        node_state = (
            event.get("node_state")
            or event.get("state")
        )

        if isinstance(
            node_state,
            dict
        ):

            return dict(
                node_state
            )

        payload = event.get(
            "payload",
            {}
        )

        if isinstance(
            payload,
            dict
        ):

            nested_state = (
                payload.get("node_state")
                or payload.get("state")
            )

            if isinstance(
                nested_state,
                dict
            ):

                return dict(
                    nested_state
                )

        return self._strip_internal_fields(
            event
        )

    def _derive_state_from_repository_event(
        self,
        event_name,
        event
    ) -> dict:

        state_update = {

            "network_online":
                True,

            "last_network_update":
                self._utc_now()
        }

        if event_name == SERVER_ENVIRO_EVENT:

            state_update.update(
                self._derive_enviro_state(
                    event
                )
            )

        elif event_name == SERVER_AVIS_LITE:

            state_update.update(
                self._derive_avis_lite_state(
                    event
                )
            )

        elif event_name == SERVER_GPS_COORD:

            state_update["gps_locked"] = True
            state_update["gps_lock"] = True

        return state_update

    def _derive_enviro_state(
        self,
        event
    ) -> dict:

        temperature_c = self._find_nested_value(
            event,
            "temperature_c"
        )

        humidity_percent = self._find_nested_value(
            event,
            "humidity_percent"
        )

        pressure_hpa = self._find_nested_value(
            event,
            "pressure_hpa"
        )

        sht45_online = (
            temperature_c is not None
            or humidity_percent is not None
        )

        dps310_online = (
            pressure_hpa is not None
        )

        return {

            "enviro_online":
                sht45_online or dps310_online,

            "sht45_online":
                sht45_online,

            "dps310_online":
                dps310_online,

            "temperature_c":
                temperature_c,

            "humidity_percent":
                humidity_percent,

            "pressure_hpa":
                pressure_hpa
        }

    def _derive_avis_lite_state(
        self,
        event
    ) -> dict:

        audio_path = (
            self._find_nested_value(
                event,
                "audio_path"
            )
            or self._find_nested_value(
                event,
                "recording_path"
            )
        )

        return {

            "birdnet_online":
                True,

            "microphone_online":
                audio_path is not None
        }

    def _find_nested_value(
        self,
        data,
        key_name
    ):

        if isinstance(
            data,
            dict
        ):

            if key_name in data:

                return data[key_name]

            for value in data.values():

                result = self._find_nested_value(
                    value,
                    key_name
                )

                if result is not None:

                    return result

        elif isinstance(
            data,
            list
        ):

            for item in data:

                result = self._find_nested_value(
                    item,
                    key_name
                )

                if result is not None:

                    return result

        return None

    def _strip_internal_fields(
        self,
        event
    ) -> dict:

        skip_keys = {

            "event_type",
            "event_name",
            "name",
            "source",
            "target",
            "timestamp",
            "timestamp_utc",
            "node_id",
            "device_id",
            "payload",
            "registry_record",
            "recent_events",
            "_communication"
        }

        clean_event = {}

        for key, value in event.items():

            if key not in skip_keys:

                clean_event[key] = value

        return clean_event

    # ========================================================
    # SNAPSHOT BUILDER
    # ========================================================

    def _build_repository_snapshot(
        self,
        publication_event_type,
        source_event_type,
        node_id,
        source_event
    ) -> dict:

        return {

            "event_type":
                publication_event_type,

            "source":
                "node_repository",

            "target":
                "interface",

            "timestamp":
                self._utc_now(),

            "node_id":
                node_id,

            "payload": {

                "source_event_type":
                    source_event_type,

                "node_id":
                    node_id,

                "registry":
                    self.registry.get_node(
                        node_id
                    ),

                "state":
                    self.state.get_node_state(
                        node_id
                    ),

                "recent_events":
                    self.events.get_recent_node_events(
                        node_id
                    ),

                "source_event":
                    source_event
            }
        }

    # ========================================================
    # STATUS
    # ========================================================

    def get_status(
        self
    ) -> dict:

        return {

            "running":
                self.running,

            "node_count":
                self.registry.count(),

            "nodes":
                self.registry.get_all_nodes()
        }

    # ========================================================
    # TIME
    # ========================================================

    def _utc_now(
        self
    ) -> str:

        return datetime.utcnow().isoformat()