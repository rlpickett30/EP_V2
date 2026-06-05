# ============================================================
# communication_state_manager.py
#
# EnviroPulse V2
#
# Communication State
#
# Responsibilities:
#   - Store communication state
#   - Store communication statistics
#   - Provide communication status
#
# Does NOT:
#   - Send messages
#   - Receive messages
#   - Check connectivity
#   - Make decisions
#
# ============================================================


class CommunicationStateManager:

    def __init__(self):

        # --------------------------------------------
        # Connectivity
        # --------------------------------------------

        self.network_connected = False

        self.server_reachable = False

        # --------------------------------------------
        # Statistics
        # --------------------------------------------

        self.rx_count = 0

        self.tx_count = 0

        self.rx_errors = 0

        self.tx_errors = 0

        # --------------------------------------------
        # Activity
        # --------------------------------------------

        self.last_rx_time = None

        self.last_tx_time = None

    # ========================================================
    # STATUS
    # ========================================================

    def get_status(self):

        return {

            "network_connected":
                self.network_connected,

            "server_reachable":
                self.server_reachable,

            "rx_count":
                self.rx_count,

            "tx_count":
                self.tx_count,

            "rx_errors":
                self.rx_errors,

            "tx_errors":
                self.tx_errors,

            "last_rx_time":
                self.last_rx_time,

            "last_tx_time":
                self.last_tx_time
        }