# ============================================================
# ENVIROPULSE
# TDOA PLOTS
# ============================================================

"""
Purpose
-------
Visualization layer for TDOA results.

This module:
- plots microphone geometry
- plots estimated source locations
- visualizes solver results
- provides debugging visuals

This module DOES NOT:
- perform detection
- perform analysis
- perform solving
- manage events

Those responsibilities belong to:
    TDOA_manager.py
"""

# ============================================================
# IMPORTS
# ============================================================

import numpy as np

import matplotlib.pyplot as plt

from mpl_toolkits.mplot3d import (
    Axes3D
)


# ============================================================
# PLOTTER
# ============================================================

class TDOAPlots:

    def __init__(

        self,

        microphone_positions = np.array([

            [ 0.0,     0.0,     0.0   ],   # Mic 0 (reference)

            [-8.5352,  0.0,     0.2   ],   # Mic 1

            [-8.5352, -4.8768,  0.4   ],   # Mic 2

            [ 0.0,    -4.8768,  0.6   ],   # Mic 3

            [-4.2726, -2.4384,  0.9906]    # Mic 4 (raised center)

        ]),

        debug=False

    ):

        self.microphone_positions = (
            np.array(
                microphone_positions,
                dtype=np.float64
            )
        )

        self.debug = debug

    # ========================================================
    # PLOT EVENT
    # ========================================================

    def plot_event(

        self,

        event,

        show=True

    ):

        """
        Plot finalized TDOA event.
        """

        try:

            if not event["success"]:

                print(
                    "Cannot plot failed event."
                )

                return

            solutions = (

                event["solution"][
                    "solutions"
                ]

            )

            if len(solutions) == 0:

                print(
                    "No solutions available."
                )

                return

            # =================================================
            # FIGURE
            # =================================================

            fig = plt.figure(
                figsize=(10, 8)
            )

            ax = fig.add_subplot(

                111,

                projection="3d"

            )

            # =================================================
            # MICROPHONES
            # =================================================

            ax.scatter(

                self.microphone_positions[:, 0],

                self.microphone_positions[:, 1],

                self.microphone_positions[:, 2],

                s=120,

                marker="o",

                label="Microphones"

            )

            # =================================================
            # LABEL MICROPHONES
            # =================================================

            for i, mic in enumerate(

                self.microphone_positions

            ):

                ax.text(

                    mic[0],

                    mic[1],

                    mic[2],

                    f"Mic {i}",

                    fontsize=10

                )

            # =================================================
            # PLOT SOLUTIONS
            # =================================================

            for i, solution in enumerate(
                solutions
            ):

                if not solution["success"]:

                    continue

                position = (

                    solution["solution"][
                        "position"
                    ]

                )

                x = position["x"]

                y = position["y"]

                z = position["z"]

                ax.scatter(

                    x,
                    y,
                    z,

                    s=200,

                    marker="*",

                    label=f"Solution {i}"

                )

                # =============================================
                # LABEL SOLUTION
                # =============================================

                ax.text(

                    x,
                    y,
                    z,

                    f"S{i}",

                    fontsize=10

                )

            # =================================================
            # AXIS LABELS
            # =================================================

            ax.set_xlabel(
                "X Position (m)"
            )

            ax.set_ylabel(
                "Y Position (m)"
            )

            ax.set_zlabel(
                "Z Position (m)"
            )

            ax.set_title(
                "3D TDOA Localization"
            )

            ax.legend()

            ax.grid(True)

            # =================================================
            # DISPLAY
            # =================================================

            if show:

                plt.show()

            return fig, ax

        # ====================================================
        # ERROR HANDLING
        # ====================================================

        except Exception as e:

            print(
                f"Plotting Error: {e}"
            )

    # ========================================================
    # PLOT TDOA MATRIX
    # ========================================================

    def plot_tdoa_matrix(

        self,

        analysis_group,

        show=True

    ):

        """
        Plot TDOA values by channel.
        """

        try:

            tdoa_values = (

                analysis_group[
                    "tdoa_values"
                ]

            )

            channels = list(
                tdoa_values.keys()
            )

            values = list(
                tdoa_values.values()
            )

            fig = plt.figure(
                figsize=(8, 5)
            )

            ax = fig.add_subplot(111)

            ax.bar(
                channels,
                values
            )

            ax.set_title(
                "TDOA Sample Offsets"
            )

            ax.set_xlabel(
                "Channel"
            )

            ax.set_ylabel(
                "Sample Offset"
            )

            ax.grid(True)

            if show:

                plt.show()

            return fig, ax

        except Exception as e:

            print(
                f"TDOA Matrix Plot Error: {e}"
            )

    # ========================================================
    # PLOT RESIDUALS
    # ========================================================

    def plot_residuals(

        self,

        analysis_group,

        show=True

    ):

        """
        Plot consensus residuals.
        """

        try:

            residuals = (

                analysis_group[
                    "residuals"
                ]

            )

            channels = list(
                residuals.keys()
            )

            values = list(
                residuals.values()
            )

            fig = plt.figure(
                figsize=(8, 5)
            )

            ax = fig.add_subplot(111)

            ax.bar(
                channels,
                values
            )

            ax.set_title(
                "Consensus Residuals"
            )

            ax.set_xlabel(
                "Channel"
            )

            ax.set_ylabel(
                "Residual"
            )

            ax.grid(True)

            if show:

                plt.show()

            return fig, ax

        except Exception as e:

            print(
                f"Residual Plot Error: {e}"
            )
