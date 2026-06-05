# ============================================================
# server_main.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Server Root
#
# Role:
#   Main
#
# Purpose:
#   Own server runtime startup, subsystem ownership, shutdown,
#   and shared Event Bus creation.
#
# Expected config source:
#   server_config.json
#
# Expected config section:
#   Full server config
#
# Does:
#   - Create and own the server Event Bus
#   - Create and own server subsystem dispatchers
#   - Start dispatchers in stable runtime order
#   - Stop dispatchers in reverse runtime order
#   - Keep the server process alive
#   - Handle keyboard and termination shutdown
#
# Does NOT:
#   - Perform subsystem workflow directly
#   - Publish subsystem events directly
#   - Open network sockets directly
#   - Write database records directly
#   - Solve TDOA directly
#   - Maintain platform state directly
#
# Owner:
#   Application entry point
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from server_event_bus import EventBus

from communication.communication_dispatcher import (
    CommunicationDispatcher
)

from database.database_dispatcher import (
    DatabaseDispatcher
)

from journal.journal_dispatcher import (
    JournalDispatcher
)

from platform_registry.platform_registry_dispatcher import (
    PlatformRegistryDispatcher
)

from TDOA.TDOA_dispatcher import (
    TDOADispatcher
)

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import json
import logging
import signal
import time

from pathlib import Path
from typing import Dict, Optional


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class ServerMain:
    """
    Server runtime owner.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        config_path: str = "server_config.json"
    ):

        self.config_path = config_path
        self.config = self._load_config(config_path)

        runtime_config = self.config.get(
            "runtime",
            {}
        )

        logging.basicConfig(
            level=self._logging_level(
                runtime_config.get("log_level", "INFO")
            ),
            format="%(asctime)s [%(levelname)s] %(message)s"
        )

        self.running = False

        self.event_bus = EventBus(
            retain_history=runtime_config.get(
                "retain_event_history",
                True
            ),
            max_history=runtime_config.get(
                "max_event_history",
                500
            ),
            debug=runtime_config.get(
                "debug_event_bus",
                False
            )
        )

        self.dispatchers: Dict[str, object] = {}

    # ========================================================
    # BUILD
    # ========================================================

    def build(
        self
    ):
        """
        Create subsystem dispatchers.
        """

        self.dispatchers["journal"] = JournalDispatcher(
            event_bus=self.event_bus
        )

        self.dispatchers["database"] = DatabaseDispatcher(
            event_bus=self.event_bus,
            debug=self.config.get("database", {}).get("debug", False)
        )

        self.dispatchers["platform_registry"] = PlatformRegistryDispatcher(
            event_bus=self.event_bus,
            config_path=self.config.get(
                "platform_registry_config_path",
                "platform_registry/platform_registry_config.json"
            )
        )

        self.dispatchers["tdoa"] = TDOADispatcher(
            event_bus=self.event_bus,
            config_path=self.config.get(
                "tdoa_config_path",
                "TDOA/TDOA_config.json"
            )
        )

        self.dispatchers["communication"] = CommunicationDispatcher(
            event_bus=self.event_bus,
            config_path=self.config.get(
                "communication_config_path",
                "communication/communication_config.json"
            )
        )

    # ========================================================
    # START
    # ========================================================

    def start(
        self
    ):
        """
        Start server runtime.
        """

        if not self.dispatchers:
            self.build()

        self.running = True

        self._start_dispatcher("journal")
        self._start_dispatcher("database")
        self._start_dispatcher("platform_registry")
        self._start_dispatcher("tdoa")
        self._start_dispatcher("communication")

        logging.info(
            "[ServerMain] EnviroPulse server started."
        )

    # ========================================================
    # RUN
    # ========================================================

    def run(
        self
    ):
        """
        Keep server process alive until stopped.
        """

        self.start()

        try:
            while self.running:
                time.sleep(1)

        except KeyboardInterrupt:
            logging.info(
                "[ServerMain] Keyboard shutdown requested."
            )

        finally:
            self.stop()

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self
    ):
        """
        Stop server runtime.
        """

        if not self.running:
            return

        self.running = False

        self._stop_dispatcher("communication")
        self._stop_dispatcher("tdoa")
        self._stop_dispatcher("platform_registry")
        self._stop_dispatcher("database")
        self._stop_dispatcher("journal")

        logging.info(
            "[ServerMain] EnviroPulse server stopped."
        )

    # ========================================================
    # SIGNAL HANDLING
    # ========================================================

    def install_signal_handlers(
        self
    ):
        """
        Register shutdown signal handlers.
        """

        signal.signal(signal.SIGINT, self._handle_shutdown_signal)
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)

    def _handle_shutdown_signal(
        self,
        signum,
        frame
    ):
        """
        Stop runtime after process signal.
        """

        logging.info(
            f"[ServerMain] Shutdown signal received: {signum}"
        )

        self.stop()

    # ========================================================
    # DISPATCHER HELPERS
    # ========================================================

    def _start_dispatcher(
        self,
        name: str
    ):
        """
        Start one dispatcher if it supports start().
        """

        dispatcher = self.dispatchers.get(name)

        if dispatcher is None:
            logging.warning(
                f"[ServerMain] Missing dispatcher: {name}"
            )
            return

        start_method = getattr(dispatcher, "start", None)

        if callable(start_method):
            start_method()

        logging.info(
            f"[ServerMain] Started dispatcher: {name}"
        )

    def _stop_dispatcher(
        self,
        name: str
    ):
        """
        Stop one dispatcher if it supports stop().
        """

        dispatcher = self.dispatchers.get(name)

        if dispatcher is None:
            return

        stop_method = getattr(dispatcher, "stop", None)

        if callable(stop_method):
            try:
                stop_method()
            except Exception as error:
                logging.exception(
                    f"[ServerMain] Failed stopping {name}: {error}"
                )

    # ========================================================
    # CONFIG
    # ========================================================

    def _load_config(
        self,
        config_path: str
    ) -> dict:
        """
        Load server config if present.
        """

        path = Path(config_path)

        if not path.exists():
            return {}

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    # ========================================================
    # LOGGING LEVEL
    # ========================================================

    def _logging_level(
        self,
        level_name: str
    ):
        """
        Convert config log level string to logging level.
        """

        return getattr(
            logging,
            str(level_name).upper(),
            logging.INFO
        )


# ============================================================
# MAIN ENTRY
# ============================================================

def main(
    config_path: Optional[str] = None
):
    """
    Run EnviroPulse server.
    """

    server = ServerMain(
        config_path=config_path or "server_config.json"
    )

    server.install_signal_handlers()
    server.run()


if __name__ == "__main__":
    main()
