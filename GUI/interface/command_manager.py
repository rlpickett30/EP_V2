# ============================================================
# command_manager.py
#
# EnviroPulse V2
#
# Responsibilities:
#   - Convert GUI actions
#     into mode events
#
# ============================================================


class CommandManager:

    def build_enable_wifi(self):

        return {

            "event_type":
                "ENABLE_WIFI"
        }