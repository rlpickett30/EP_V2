# ============================================================
# RUNTIME STATE MANAGER SANDBOX
# ============================================================

class RuntimeStateManager:

    def __init__(self):

        self.state = {
            "environment": {}
        }

        self.subscribers = {}

    # ========================================================
    # SUBSCRIBE
    # ========================================================

    def subscribe(self, event_name, callback):

        if event_name not in self.subscribers:
            self.subscribers[event_name] = []

        self.subscribers[event_name].append(callback)

        print(
            f"[STATE] Subscriber added for event: "
            f"{event_name}"
        )

    # ========================================================
    # PUBLISH
    # ========================================================

    def publish(self, event_name, payload):

        print(
            f"[STATE] Publishing event: "
            f"{event_name}"
        )

        listeners = self.subscribers.get(
            event_name,
            []
        )

        for callback in listeners:
            callback(payload)

    # ========================================================
    # UPDATE ENVIRONMENT
    # ========================================================

    def update_environment(self, temperature_c):

        speed_of_sound = (
            331.3
            +
            0.606 * temperature_c
        )

        self.state["environment"] = {
            "temperature_c": temperature_c,
            "speed_of_sound": speed_of_sound
        }

        payload = {
            "temperature_c": temperature_c,
            "speed_of_sound": speed_of_sound
        }

        print(
            "[STATE] Environment state updated."
        )

        self.publish(
            "environment_updated",
            payload
        )

    # ========================================================
    # GET STATE
    # ========================================================

    def get_environment(self):

        return self.state["environment"]

