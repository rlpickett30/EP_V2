# ============================================================
# MOCK WEATHER STATION
# ============================================================

import random
import time


class MockWeatherStation:

    def __init__(self, runtime_state):

        self.runtime_state = runtime_state

    def run_test_updates(self, update_count=5, delay_seconds=2):

        for i in range(update_count):

            temperature_c = round(
                random.uniform(0.0, 25.0),
                2
            )

            print(
                "\n[WEATHER] New temperature reading:"
                f" {temperature_c} °C"
            )

            self.runtime_state.update_environment(
                temperature_c=temperature_c
            )

            time.sleep(delay_seconds)