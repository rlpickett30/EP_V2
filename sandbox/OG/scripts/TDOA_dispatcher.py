# ============================================================
# ENVIROPULSE
# TDOA DISPATCHER
# ============================================================

"""
TDOA_dispatcher.py

Master runtime orchestrator for TDOA processing.

Responsibilities:
    - Start watchdog listener
    - Receive completed WAV batches
    - Route batches into TDOA manager
    - Trigger plotting
    - Keep runtime alive

Dispatcher philosophy:
    - Lightweight
    - Event-driven
    - No signal processing logic
    - No TDOA math
    - No detector logic

If processing fails:
    fix manager/subsystems
    NOT dispatcher
"""

# ============================================================
# IMPORTS
# ============================================================

from __future__ import annotations

import logging
import numpy as np
import soundfile as sf
import os

import TDOA_watchdog

from TDOA_manager import (
    TDOAManager
)

from TDOA_plots import (
    TDOAPlots
)

# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "enviropulse.TDOA_dispatcher"
)

# ============================================================
# LOGGING
# ============================================================

def configure_logging():

    logging.basicConfig(

        level=logging.INFO,

        format=(

            "%(asctime)s "
            "[%(levelname)s] "
            "%(name)s: "
            "%(message)s"

        )

    )

# ============================================================
# MANAGER
# ============================================================

tdoa_manager = TDOAManager()

# ============================================================
# PLOTTER
# ============================================================

plotter = TDOAPlots()

# ============================================================
# HANDLE WAV BATCH
# ============================================================

def handle_wav_batch(

    batch_files

):

    """
    Primary TDOA injection point.

    Called by:
        TDOA_watchdog.py
    """

    logger.info(
        "Received WAV batch."
    )

    logger.info(
        "Launching TDOA pipeline..."
    )

    # ========================================================
    # PROCESS
    # ========================================================

    channel_signals = {}

    for file_path in batch_files:

        filename = os.path.basename(
            file_path
        )

        channel_name = (
            filename.split("-")[0]
        )

        signal, sample_rate = sf.read(
            file_path
        )

        channel_signals[
            channel_name
        ] = signal

    result = tdoa_manager.process(

        channel_signals

    )

    # ========================================================
    # FAILURE
    # ========================================================

    if not result["success"]:

        logger.warning(
            "TDOA pipeline failed."
        )

        logger.warning(
            result["errors"]
        )

        return

    logger.info(
        "TDOA pipeline complete."
    )

    # ========================================================
    # PLOT
    # ========================================================

    try:

        plotter.plot_event(
            result
        )

    except Exception as e:

        logger.warning(
            f"Plotting failed: {e}"
        )
        
    solutions = result["solution"]["solutions"]

    print("\n====================================")
    print(" FINAL TDOA SOLUTIONS ")
    print("====================================")

    for i, solution in enumerate(solutions):

        position = solution["solution"]["position"]

        residual = solution["solution"][
            "residual_error"
        ]

        print(
            f"\nSolution {i+1}"
        )

        print(
            f"X: {position['x']:.4f} m"
        )

        print(
            f"Y: {position['y']:.4f} m"
        )

        print(
            f"Z: {position['z']:.4f} m"
        )

        print(
            f"Residual Error: "
            f"{residual:.8f}"
        )
        
    valid_positions = []

    for solution in solutions:

        if not solution["success"]:

            continue

        position = solution["solution"]["position"]

        valid_positions.append([

            position["x"],
            position["y"],
            position["z"]

        ])

    if len(valid_positions) > 0:

        valid_positions = np.array(
            valid_positions
        )

        final_estimate = np.mean(

            valid_positions,

            axis=0

        )

    print(
        "\n===================================="
    )

    print(
        " FINAL CONSENSUS ESTIMATE "
    )

    print(
        "===================================="
    )

    print(
        f"X: {final_estimate[0]:.4f} m"
    )

    print(
        f"Y: {final_estimate[1]:.4f} m"
    )

    print(
        f"Z: {final_estimate[2]:.4f} m"
    )

    print(
        "====================================\n"
    )
    print("\n====================================\n")
    
    
# ============================================================
# MAIN
# ============================================================

def main():

    configure_logging()

    logger.info(
        "====================================="
    )

    logger.info(
        " ENVIROPULSE - TDOA DISPATCHER "
    )

    logger.info(
        "====================================="
    )

    logger.info(
        "Starting TDOA watchdog..."
    )

    # ========================================================
    # START WATCHDOG
    # ========================================================

    TDOA_watchdog.run_with_callback(

        handle_wav_batch

    )

    logger.error(
        "Watchdog exited unexpectedly!"
    )

# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\nTDOA dispatcher stopped "
            "by user.\n"
        )
