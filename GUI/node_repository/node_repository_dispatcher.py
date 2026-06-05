# ============================================================
# node_repository_dispatcher.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Own Node Repository subsystem
#   - Maintain repository truth
#   - Update node registry
#   - Update node state
#   - Store node events
#   - Publish GUI updates
#
# Does NOT:
#   - Store data directly
#   - Publish directly
#   - Require Main to build repository internals
#
# ============================================================

import logging

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
    NodeRepositoryEventServices
)


class NodeRepositoryDispatcher:

    def __init__(
        self,
        event_bus
    ):

        self.event_bus = event_bus

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
            event_bus=self.event_bus
        )

        self.event_services.register_subscriptions(
            dispatcher=self
        )

        self.running = False

    # ========================================================
    # START
    # ========================================================

    def start(
        self
    ):

        self.running = True

        logging.info(
            "[Node Repository] Ready"
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self
    ):

        self.running = False

        logging.info(
            "[Node Repository] Stopped"
        )

    # ========================================================
    # HANDLE EVENT
    # ========================================================

    def handle_event(
        self,
        event: dict
    ):

        try:

            event_type = event.get(
                "event_type"
            )

            node_id = event.get(
                "node_id"
            )

            if not node_id:

                logging.warning(
                    "[Node Repository] Event missing node_id"
                )

                return

            # --------------------------------------------
            # Ensure node exists everywhere
            # --------------------------------------------

            if not self.registry.node_exists(
                node_id
            ):

                self.registry.register_node({

                    "node_id": node_id

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

            # --------------------------------------------
            # Store event history
            # --------------------------------------------

            self.events.store_event(
                node_id,
                event
            )

            # --------------------------------------------
            # NODE REGISTER
            # --------------------------------------------

            if event_type == "NODE_REGISTER":

                self.registry.update_node(
                    node_id,
                    event
                )

            # --------------------------------------------
            # BMP390
            # --------------------------------------------

            elif event_type == "BMP390_ONLINE":

                self.state.update_state(
                    node_id,
                    {
                        "bmp390_online": True
                    }
                )

            elif event_type == "BMP390_OFFLINE":

                self.state.update_state(
                    node_id,
                    {
                        "bmp390_online": False
                    }
                )

            # --------------------------------------------
            # SHT45
            # --------------------------------------------

            elif event_type == "SHT45_ONLINE":

                self.state.update_state(
                    node_id,
                    {
                        "sht45_online": True
                    }
                )

            elif event_type == "SHT45_OFFLINE":

                self.state.update_state(
                    node_id,
                    {
                        "sht45_online": False
                    }
                )

            # --------------------------------------------
            # GPS
            # --------------------------------------------

            elif event_type == "GPS_LOCK":

                self.state.update_state(
                    node_id,
                    {
                        "gps_lock": True
                    }
                )

            elif event_type == "GPS_LOST":

                self.state.update_state(
                    node_id,
                    {
                        "gps_lock": False
                    }
                )

            elif event_type == "GPS_COORD":

                self.state.update_state(
                    node_id,
                    {
                        "gps_coord": event.get(
                            "gps_coord"
                        )
                    }
                )

            # --------------------------------------------
            # PPS
            # --------------------------------------------

            elif event_type == "PPS_LOCK":

                self.state.update_state(
                    node_id,
                    {
                        "pps_lock": True
                    }
                )

            elif event_type == "PPS_LOST":

                self.state.update_state(
                    node_id,
                    {
                        "pps_lock": False
                    }
                )

            # --------------------------------------------
            # RTK
            # --------------------------------------------

            elif event_type == "RTK_ONLINE":

                self.state.update_state(
                    node_id,
                    {
                        "rtk_online": True
                    }
                )

            else:

                logging.warning(
                    f"[Node Repository] Unknown event: "
                    f"{event_type}"
                )

            # --------------------------------------------
            # GUI UPDATE
            # --------------------------------------------

            gui_snapshot = {

                "event_type":
                    "GUI_REGISTER",

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
                    )
            }

            self.event_services.publish_gui_register(
                gui_snapshot
            )

        except Exception as error:

            logging.exception(
                f"[Node Repository] Dispatcher Error: "
                f"{error}"
            )