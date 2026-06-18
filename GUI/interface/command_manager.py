# ============================================================
# command_manager.py
#
# EnviroPulse V2 GUI
#
# Subsystem:
#   Interface
#
# Role:
#   Command Manager
#
# Purpose:
#   Convert GUI button actions into canonical mode-change
#   request payloads.
#
# Does:
#   - Own GUI action labels
#   - Build canonical mode-change request dictionaries
#
# Does NOT:
#   - Publish events
#   - Send UDP packets
#   - Decide server behavior
#   - Decide node behavior
#
# Owner:
#   interface_dispatcher.py
#
# ============================================================


# ============================================================
# CANONICAL GUI MODE EVENT NAMES
# ============================================================

NETWORK_MODE_CHANGE = "GUI_NETWORK_MODE_CHANGE"
DETECTION_MODE_CHANGE = "GUI_DETECTION_MODE_CHANGE"
FEATURE_MODE_CHANGE = "GUI_FEATURE_MODE_CHANGE"


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class CommandManager:

    # ========================================================
    # NETWORK MODE REQUESTS
    # ========================================================

    def build_enable_wifi(
        self
    ):

        return self._build_mode_request(
            event_type=NETWORK_MODE_CHANGE,
            mode_category="network",
            requested_mode="enable_wifi",
            target="node"
        )

    def build_enable_lora(
        self
    ):

        return self._build_mode_request(
            event_type=NETWORK_MODE_CHANGE,
            mode_category="network",
            requested_mode="enable_lora",
            target="node"
        )

    # ========================================================
    # DETECTION MODE REQUESTS
    # ========================================================

    def build_energy_onset(
        self
    ):

        return self._build_mode_request(
            event_type=DETECTION_MODE_CHANGE,
            mode_category="detection",
            requested_mode="energy_onset",
            target="server"
        )

    def build_pattern_onset(
        self
    ):

        return self._build_mode_request(
            event_type=DETECTION_MODE_CHANGE,
            mode_category="detection",
            requested_mode="pattern_onset",
            target="server"
        )

    # ========================================================
    # FEATURE MODE REQUESTS
    # ========================================================

    def build_amp_feature(
        self
    ):

        return self._build_mode_request(
            event_type=FEATURE_MODE_CHANGE,
            mode_category="feature",
            requested_mode="amp_feature",
            target="server"
        )

    def build_onset_feature(
        self
    ):

        return self._build_mode_request(
            event_type=FEATURE_MODE_CHANGE,
            mode_category="feature",
            requested_mode="onset_feature",
            target="server"
        )

    # ========================================================
    # BUILD MODE REQUEST
    # ========================================================

    def _build_mode_request(
        self,
        event_type: str,
        mode_category: str,
        requested_mode: str,
        target: str
    ) -> dict:

        return {

            "event_type":
                event_type,

            "mode_category":
                mode_category,

            "requested_mode":
                requested_mode,

            "command":
                requested_mode,

            "target":
                target
        }