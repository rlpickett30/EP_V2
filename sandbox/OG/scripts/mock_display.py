# ============================================================
# MOCK DISPLAY SUBSCRIBER
# ============================================================

class MockDisplay:

    def handle_environment_update(self, payload):

        temperature_c = payload["temperature_c"]

        speed_of_sound = payload["speed_of_sound"]

        print(
            "[DISPLAY] Environment update received."
        )

        print(
            f"[DISPLAY] Temperature: "
            f"{temperature_c:.2f} °C"
        )

        print(
            f"[DISPLAY] Speed of sound: "
            f"{speed_of_sound:.3f} m/s"
        )