# ============================================================
# ENVIROPULSE
# TDOA EVENT SOLVER
# ============================================================

"""
Purpose
-------
Solve 3D source location using TDOA analysis.

This module:
- converts TDOA values into distance deltas
- performs least-squares localization
- returns estimated source coordinates

This module DOES NOT:
- detect events
- match events
- perform alignment
- compute consensus

Those responsibilities belong to:
    TDOA_event_detection.py
    TDOA_event_analysis.py
"""

# ============================================================
# IMPORTS
# ============================================================

import numpy as np

from scipy.optimize import minimize


# ============================================================
# SOLVER
# ============================================================

class TDOAEventSolver:

    def __init__(

        self,

        microphone_positions,

        sample_rate=96000,

        speed_of_sound=340.0,

        debug=False

    ):

        # ====================================================
        # CONFIGURATION
        # ====================================================

        self.channel_names = list(
            microphone_positions.keys()
        )

        self.microphone_positions = np.array(

            list(
                microphone_positions.values()
            ),

            dtype=np.float64

        )

        self.sample_rate = sample_rate

        # ====================================================
        # ENVIRONMENTAL
        # ====================================================

        # Future:
        # - dynamic temperature
        # - humidity
        # - pressure
        # - wind correction

        self.speed_of_sound = (
            speed_of_sound
        )

        self.debug = debug

    # ========================================================
    # SOLVE
    # ========================================================

    def solve(

        self,
        analysis_group

    ):

        """
        Solve source position
        from TDOA analysis.
        """

        result = {

            "success": False,

            "solution": {},

            "debug": {},

            "errors": []

        }

        try:

            # =================================================
            # VALIDATION
            # =================================================

            if "tdoa_values" not in (
                analysis_group
            ):

                raise ValueError(

                    "Missing tdoa_values."

                )

            tdoa_values = (
                analysis_group[
                    "tdoa_values"
                ]
            )

            reference_channel = (
                analysis_group[
                    "reference_channel"
                ]
            )

            # =================================================
            # CHANNEL ORDER
            # =================================================

            channel_names = list(
                tdoa_values.keys()
            )

            reference_index = (
                channel_names.index(
                    reference_channel
                )
            )

            # =================================================
            # BUILD SAMPLE OFFSETS
            # =================================================

            sample_offsets = []

            mic_indices = []

            for i, channel_name in enumerate(
                channel_names
            ):

                if channel_name == (
                    reference_channel
                ):

                    continue

                sample_offsets.append(

                    tdoa_values[
                        channel_name
                    ]

                )

                mic_indices.append(i)

            sample_offsets = np.array(
                sample_offsets,
                dtype=np.float64
            )

            # =================================================
            # CONVERT SAMPLES → TIME
            # =================================================

            tdoa_seconds = (

                sample_offsets
                /
                self.sample_rate

            )

            # =================================================
            # CONVERT TIME → DISTANCE
            # =================================================

            delta_distances = (

                self.speed_of_sound
                *
                tdoa_seconds

            )

            # =================================================
            # ERROR FUNCTION
            # =================================================

            def error_function(
                source_position
            ):

                reference_distance = (

                    np.linalg.norm(

                        source_position
                        -
                        self.microphone_positions[
                            reference_index
                        ]

                    )

                )

                error = 0.0

                for i, mic_index in enumerate(
                    mic_indices
                ):

                    current_distance = (

                        np.linalg.norm(

                            source_position
                            -
                            self.microphone_positions[
                                mic_index
                            ]

                        )

                    )

                    predicted_delta = (

                        current_distance
                        -
                        reference_distance

                    )

                    measured_delta = (
                        delta_distances[i]
                    )

                    error += (

                        predicted_delta
                        -
                        measured_delta

                    ) ** 2

                return error

            # =================================================
            # INITIAL GUESS
            # =================================================

            initial_guess = np.mean(

                self.microphone_positions,

                axis=0

            )

            # =================================================
            # SOLVE
            # =================================================

            optimization_result = minimize(

                error_function,

                initial_guess

            )

            estimated_position = (
                optimization_result.x
            )

            # =================================================
            # BUILD SOLUTION
            # =================================================

            solution = {

                "position": {

                    "x": float(
                        estimated_position[0]
                    ),

                    "y": float(
                        estimated_position[1]
                    ),

                    "z": float(
                        estimated_position[2]
                    )

                },

                "residual_error": float(
                    optimization_result.fun
                ),

                "optimization_success":

                    bool(
                        optimization_result.success
                    ),

                "sample_offsets":

                    sample_offsets.tolist(),

                "tdoa_seconds":

                    tdoa_seconds.tolist(),

                "delta_distances":

                    delta_distances.tolist(),

                "speed_of_sound":

                    float(
                        self.speed_of_sound
                    )

            }

            # =================================================
            # FINALIZE
            # =================================================

            result["success"] = True

            result["solution"] = solution

            # =================================================
            # DEBUG
            # =================================================

            if self.debug:

                result["debug"] = {

                    "reference_channel":
                        reference_channel,

                    "reference_index":
                        reference_index,

                    "microphone_count":

                        len(
                            self.microphone_positions
                        ),

                    "initial_guess":

                        initial_guess.tolist()

                }

        # ====================================================
        # ERROR HANDLING
        # ====================================================

        except Exception as e:

            result["errors"].append(
                str(e)
            )

            if self.debug:

                result["debug"][
                    "exception_type"
                ] = type(e).__name__

        return result