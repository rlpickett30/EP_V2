# ============================================================
# TDOA_event_solver.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Role:
#   Helper script.
#
# Purpose:
#   Solve source position from one solver-ready TDOA analysis
#   group.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["TDOA_event_solver"]
#
# Does:
#   - Converts sample offsets to time offsets
#   - Converts time offsets to distance deltas
#   - Runs least-squares 3D localization
#   - Returns structured solver result
#
# Does NOT:
#   - Load TDOA_config.json directly
#   - Detect events
#   - Match events
#   - Compute matching consensus
#   - Compute solver consensus
#   - Publish events
#   - Own subsystem workflow
#
# Owner:
#   TDOA_manager.py
#
# ============================================================

import numpy as np

from scipy.optimize import minimize


class TDOAEventSolver:
    """
    Helper used by TDOA_manager.py to solve one TDOA analysis group.
    """

    def __init__(
        self,
        config: dict,
        microphone_positions: dict,
        debug: bool = False
    ):
        self.config = config
        self.debug = debug

        solver_config = self.config.get(
            "TDOA_event_solver",
            {}
        )

        self.sample_rate_hz = solver_config.get(
            "sample_rate_hz",
            96000
        )

        self.speed_of_sound_mps = solver_config.get(
            "speed_of_sound_mps",
            340.0
        )

        self.minimum_channels_required = solver_config.get(
            "minimum_channels_required",
            4
        )

        self.solver_method = solver_config.get(
            "solver_method",
            "least_squares"
        )

        self.max_residual_error = solver_config.get(
            "max_residual_error",
            1.0
        )

        self.microphone_positions = self._normalize_microphone_positions(
            microphone_positions
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def solve(
        self,
        analysis_group: dict
    ) -> dict:
        """
        Solve one analysis group.

        Parameters
        ----------
        analysis_group:
            Solver-ready group from TDOA_event_analysis.py.

        Returns
        -------
        dict:
            Structured solver result.
        """

        result = {
            "success": False,
            "solution": {},
            "debug": {},
            "errors": []
        }

        try:
            self._validate_analysis_group(
                analysis_group
            )

            reference_channel = analysis_group.get(
                "reference_channel"
            )

            tdoa_values = analysis_group.get(
                "tdoa_values",
                {}
            )

            channel_names = list(
                tdoa_values.keys()
            )

            solve_package = self._build_solve_package(
                channel_names=channel_names,
                reference_channel=reference_channel,
                tdoa_values=tdoa_values
            )

            optimization_result = self._solve_least_squares(
                solve_package=solve_package
            )

            solution = self._build_solution_record(
                analysis_group=analysis_group,
                solve_package=solve_package,
                optimization_result=optimization_result
            )

            result["success"] = True
            result["solution"] = solution

            if self.debug:
                result["debug"] = {
                    "solver_method": self.solver_method,
                    "reference_channel": reference_channel,
                    "channel_names": channel_names,
                    "sample_rate_hz": float(
                        self.sample_rate_hz
                    ),
                    "speed_of_sound_mps": float(
                        self.speed_of_sound_mps
                    ),
                    "minimum_channels_required": int(
                        self.minimum_channels_required
                    ),
                    "initial_guess": solve_package[
                        "initial_guess"
                    ].tolist()
                }

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            if self.debug:
                result["debug"]["exception_type"] = (
                    type(error).__name__
                )

        return result

    # ========================================================
    # SOLVE PACKAGE
    # ========================================================

    def _build_solve_package(
        self,
        channel_names: list,
        reference_channel: str,
        tdoa_values: dict
    ) -> dict:
        """
        Build numeric arrays required for solving.
        """

        reference_position = self.microphone_positions[
            reference_channel
        ]

        solve_channels = []
        solve_positions = []
        sample_offsets = []

        for channel_name in channel_names:

            if channel_name == reference_channel:
                continue

            if channel_name not in self.microphone_positions:
                raise KeyError(
                    f"Missing microphone position for channel: "
                    f"{channel_name}"
                )

            solve_channels.append(
                channel_name
            )

            solve_positions.append(
                self.microphone_positions[channel_name]
            )

            sample_offsets.append(
                tdoa_values[channel_name]
            )

        sample_offsets = np.asarray(
            sample_offsets,
            dtype=np.float64
        )

        tdoa_seconds = (
            sample_offsets
            /
            self.sample_rate_hz
        )

        delta_distances = (
            self.speed_of_sound_mps
            *
            tdoa_seconds
        )

        all_positions = np.asarray(
            list(self.microphone_positions.values()),
            dtype=np.float64
        )

        initial_guess = np.mean(
            all_positions,
            axis=0
        )

        return {
            "reference_channel": reference_channel,
            "reference_position": reference_position,
            "solve_channels": solve_channels,
            "solve_positions": np.asarray(
                solve_positions,
                dtype=np.float64
            ),
            "sample_offsets": sample_offsets,
            "tdoa_seconds": tdoa_seconds,
            "delta_distances": delta_distances,
            "initial_guess": initial_guess
        }

    # ========================================================
    # LEAST-SQUARES SOLVER
    # ========================================================

    def _solve_least_squares(
        self,
        solve_package: dict
    ):
        """
        Run least-squares TDOA solve.
        """

        reference_position = solve_package[
            "reference_position"
        ]

        solve_positions = solve_package[
            "solve_positions"
        ]

        delta_distances = solve_package[
            "delta_distances"
        ]

        def error_function(source_position):

            reference_distance = np.linalg.norm(
                source_position
                -
                reference_position
            )

            total_error = 0.0

            for index, microphone_position in enumerate(
                solve_positions
            ):

                current_distance = np.linalg.norm(
                    source_position
                    -
                    microphone_position
                )

                predicted_delta = (
                    current_distance
                    -
                    reference_distance
                )

                measured_delta = delta_distances[
                    index
                ]

                total_error += (
                    predicted_delta
                    -
                    measured_delta
                ) ** 2

            return total_error

        return minimize(
            error_function,
            solve_package["initial_guess"]
        )

    # ========================================================
    # SOLUTION RECORD
    # ========================================================

    def _build_solution_record(
        self,
        analysis_group: dict,
        solve_package: dict,
        optimization_result
    ) -> dict:
        """
        Build structured solver output.
        """

        estimated_position = optimization_result.x

        residual_error = float(
            optimization_result.fun
        )

        solver_valid = (
            bool(optimization_result.success)
            and
            residual_error <= self.max_residual_error
        )

        return {
            "group_id": analysis_group.get(
                "group_id"
            ),
            "solver_valid": solver_valid,
            "position": {
                "x": float(estimated_position[0]),
                "y": float(estimated_position[1]),
                "z": float(estimated_position[2])
            },
            "residual_error": residual_error,
            "optimization_success": bool(
                optimization_result.success
            ),
            "reference_channel": solve_package.get(
                "reference_channel"
            ),
            "solve_channels": solve_package.get(
                "solve_channels",
                []
            ),
            "sample_offsets": solve_package[
                "sample_offsets"
            ].tolist(),
            "tdoa_seconds": solve_package[
                "tdoa_seconds"
            ].tolist(),
            "delta_distances": solve_package[
                "delta_distances"
            ].tolist(),
            "sample_rate_hz": float(
                self.sample_rate_hz
            ),
            "speed_of_sound_mps": float(
                self.speed_of_sound_mps
            ),
            "analysis_group": analysis_group
        }

    # ========================================================
    # VALIDATION
    # ========================================================

    def _validate_analysis_group(
        self,
        analysis_group: dict
    ) -> None:
        """
        Validate solver input.
        """

        if analysis_group is None:
            raise ValueError(
                "analysis_group is None."
            )

        if not isinstance(analysis_group, dict):
            raise TypeError(
                "analysis_group must be a dictionary."
            )

        if "tdoa_values" not in analysis_group:
            raise ValueError(
                "Missing tdoa_values."
            )

        if "reference_channel" not in analysis_group:
            raise ValueError(
                "Missing reference_channel."
            )

        tdoa_values = analysis_group.get(
            "tdoa_values",
            {}
        )

        if not isinstance(tdoa_values, dict):
            raise TypeError(
                "tdoa_values must be a dictionary."
            )

        if len(tdoa_values) < self.minimum_channels_required:
            raise ValueError(
                "Not enough channels for TDOA solve. "
                f"Required={self.minimum_channels_required}, "
                f"Available={len(tdoa_values)}"
            )

        reference_channel = analysis_group.get(
            "reference_channel"
        )

        if reference_channel not in tdoa_values:
            raise ValueError(
                "reference_channel missing from tdoa_values."
            )

    def _normalize_microphone_positions(
        self,
        microphone_positions: dict
    ) -> dict:
        """
        Convert microphone position dictionary into clean numpy arrays.

        Expected shape:
            {
                "CH1": [0.0, 0.0, 0.0],
                "CH2": [1.0, 0.0, 0.0],
                "CH3": [0.0, 1.0, 0.0],
                "CH4": [0.0, 0.0, 1.0]
            }
        """

        if microphone_positions is None:
            raise ValueError(
                "microphone_positions is None."
            )

        if not isinstance(microphone_positions, dict):
            raise TypeError(
                "microphone_positions must be a dictionary."
            )

        normalized = {}

        for channel_name, position in microphone_positions.items():

            position_array = np.asarray(
                position,
                dtype=np.float64
            )

            if position_array.shape != (3,):
                raise ValueError(
                    "Microphone position must contain exactly "
                    f"three coordinates for channel: {channel_name}"
                )

            normalized[channel_name] = position_array

        if len(normalized) < self.minimum_channels_required:
            raise ValueError(
                "Not enough microphone positions. "
                f"Required={self.minimum_channels_required}, "
                f"Available={len(normalized)}"
            )

        return normalized