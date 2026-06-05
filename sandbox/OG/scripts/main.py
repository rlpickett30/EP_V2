# ============================================================
# EVENT SYSTEM SANDBOX MAIN
# ============================================================

from runtime_state_manager import RuntimeStateManager
from mock_weather_station import MockWeatherStation
from mock_display import MockDisplay


def main():

    print(
        "\n===================================="
    )

    print(
        " EVENT SYSTEM SANDBOX "
    )

    print(
        "====================================\n"
    )

    runtime_state = RuntimeStateManager()

    display = MockDisplay()

    weather_station = MockWeatherStation(
        runtime_state=runtime_state
    )

    runtime_state.subscribe(
        event_name="environment_updated",
        callback=display.handle_environment_update
    )

    weather_station.run_test_updates(
        update_count=5,
        delay_seconds=2
    )

    print(
        "\n===================================="
    )

    print(
        " FINAL ENVIRONMENT STATE "
    )

    print(
        "===================================="
    )

    print(
        runtime_state.get_environment()
    )


if __name__ == "__main__":

    main()

