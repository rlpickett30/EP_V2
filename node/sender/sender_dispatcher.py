"""
sender_dispatcher.py

Purpose:
    State machine and routing engine for
    the Sender subsystem.

Responsibilities:
    - Evaluate sender state
    - Route outbound events
    - Manage reconnect recovery
    - Execute communication policy

Not Responsible For:
    - Message building
    - UDP transmission
    - Database storage
"""

import time


class SenderDispatcher:

    def __init__(
        self,
        sender_manager,
        network_monitor,
        sender_config
    ):

        self.sender_manager = sender_manager

        self.network_monitor = (
            network_monitor
        )

        self.config = sender_config

        self.previous_online_state = False

    # =====================================================
    # PROCESS EVENT
    # =====================================================

    def process(
        self,
        event
    ):

        # ---------------------------------------------
        # WIFI DISABLED
        # ---------------------------------------------

        if not self.config[
            "wifi_enabled"
        ]:

            if self.config[
                "database_enabled"
            ]:

                self.sender_manager.store_event(
                    event
                )

            return

        # ---------------------------------------------
        # NETWORK OFFLINE
        # ---------------------------------------------

        if not self.network_monitor.is_online():

            if self.config[
                "database_enabled"
            ]:

                self.sender_manager.store_event(
                    event
                )

            return

        # ---------------------------------------------
        # SEND EVENT
        # ---------------------------------------------

        success = (
            self.sender_manager.send_udp(
                event
            )
        )

        # ---------------------------------------------
        # SEND FAILED
        # ---------------------------------------------

        if not success:

            if self.config[
                "database_enabled"
            ]:

                self.sender_manager.store_event(
                    event
                )

    # =====================================================
    # RECONNECT CHECK
    # =====================================================

    def check_reconnect(
        self
    ):

        online = (
            self.network_monitor.is_online()
        )

        if (
            online
            and not self.previous_online_state
        ):

            if self.config[
                "flush_on_reconnect"
            ]:

                flushed = (
                    self.sender_manager
                    .flush_queue()
                )

                if self.config[
                    "debug"
                ]:

                    print(
                        f"[Sender] "
                        f"Flushed "
                        f"{flushed} messages."
                    )

        self.previous_online_state = online

    # =====================================================
    # MAIN LOOP
    # =====================================================

    def run(
        self
    ):

        while True:

            self.check_reconnect()

            time.sleep(5)