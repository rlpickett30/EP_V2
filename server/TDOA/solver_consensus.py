# ============================================================
# solver_consensus.py
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
#   Evaluate one or more TDOA solver results and select a final
#   solver consensus result.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["solver_consensus"]
#
# Does:
#   - Filters invalid solver results
#   - Measures solution spread
#   - Selects best solution
#   - Builds final solver-consensus record
#
# Does NOT:
#   - Detect events
#   - Match events
#   - Compute matching consensus
#   - Solve TDOA geometry directly
#   - Publish events
#   - Own subsystem workflow
#
# Owner:
#   TDOA_manager.py
#
# ============================================================

import numpy as np


class SolverConsensus:
    """
    Helper used by TDOA_manager.py after TDOA_event_solver.py
    generates one or more solver results.
    """

    def __init__(
        self,
        config: dict,
        debug: bool = False
    ):
        self.config = config
        self.debug = debug

        consensus_config = self.config.get(
            "solver_consensus",
            {}
        )

        self.minimum_solutions_required = consensus_config.get(
            "minimum_solutions_required",
            1
        )

        self.max_residual_error = consensus_config.get(
            "max_residual_error",
            1.0
        )

        self.prefer_lowest_residual = consensus_config.get(
            "prefer_lowest_residual",
            True
        )

        self.max_position_spread_meters = consensus_config.get(
            "max_position_spread_meters",
            5.0
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def compute(
        self,
        solver_results: list
    ) -> dict:
        """
        Compute final solver consensus.

        Parameters
        ----------
        solver_results:
            List of result dictionaries returned by
            TDOAEventSolver.solve().

        Returns
        -------
        dict:
            Structured solver consensus result.
        """

        result = {
            "success": False,
            "consensus_solution": {},
            "valid_solutions": [],
            "debug": {},
            "errors": []
        }

        try:
            self._validate_solver_results(
                solver_results
            )

            valid_solutions = self._filter_valid_solutions(
                solver_results
            )

            if len(valid_solutions) < self.minimum_solutions_required:
                result["success"] = True
                result["consensus_solution"] = {
                    "solver_consensus_valid": False,
                    "reason": "Not enough valid solver results.",
                    "valid_solution_count": len(valid_solutions),
                    "minimum_solutions_required": (
                        self.minimum_solutions_required
                    )
                }
                result["valid_solutions"] = valid_solutions
                return result

            position_spread = self._compute_position_spread(
                valid_solutions
            )

            best_solution = self._select_best_solution(
                valid_solutions
            )

            solver_consensus_valid = (
                position_spread
                <= self.max_position_spread_meters
            )

            consensus_position = self._compute_mean_position(
                valid_solutions
            )

            consensus_solution = {
                "solver_consensus_valid": solver_consensus_valid,
                "best_solution": best_solution,
                "consensus_position": consensus_position,
                "position_spread_meters": float(
                    position_spread
                ),
                "valid_solution_count": int(
                    len(valid_solutions)
                ),
                "max_position_spread_meters": float(
                    self.max_position_spread_meters
                )
            }

            result["success"] = True
            result["consensus_solution"] = consensus_solution
            result["valid_solutions"] = valid_solutions

            if self.debug:
                result["debug"] = {
                    "minimum_solutions_required": int(
                        self.minimum_solutions_required
                    ),
                    "max_residual_error": float(
                        self.max_residual_error
                    ),
                    "prefer_lowest_residual": bool(
                        self.prefer_lowest_residual
                    ),
                    "max_position_spread_meters": float(
                        self.max_position_spread_meters
                    ),
                    "input_solution_count": int(
                        len(solver_results)
                    ),
                    "valid_solution_count": int(
                        len(valid_solutions)
                    )
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
    # FILTERING
    # ========================================================

    def _filter_valid_solutions(
        self,
        solver_results: list
    ) -> list:
        """
        Keep only valid solver results.
        """

        valid_solutions = []

        for solver_result in solver_results:

            if not solver_result.get("success", False):
                continue

            solution = solver_result.get(
                "solution",
                {}
            )

            if not solution.get("solver_valid", False):
                continue

            residual_error = solution.get(
                "residual_error"
            )

            if residual_error is None:
                continue

            if residual_error > self.max_residual_error:
                continue

            valid_solutions.append(
                solution
            )

        return valid_solutions

    # ========================================================
    # CONSENSUS MATH
    # ========================================================

    def _compute_position_spread(
        self,
        valid_solutions: list
    ) -> float:
        """
        Compute maximum distance between valid solution positions.

        If there is only one valid solution, spread is zero.
        """

        if len(valid_solutions) <= 1:
            return 0.0

        positions = self._positions_to_array(
            valid_solutions
        )

        max_distance = 0.0

        for i in range(len(positions)):

            for j in range(i + 1, len(positions)):

                distance = float(
                    np.linalg.norm(
                        positions[i]
                        -
                        positions[j]
                    )
                )

                if distance > max_distance:
                    max_distance = distance

        return max_distance

    def _compute_mean_position(
        self,
        valid_solutions: list
    ) -> dict:
        """
        Compute mean position from valid solutions.
        """

        positions = self._positions_to_array(
            valid_solutions
        )

        mean_position = np.mean(
            positions,
            axis=0
        )

        return {
            "x": float(mean_position[0]),
            "y": float(mean_position[1]),
            "z": float(mean_position[2])
        }

    def _select_best_solution(
        self,
        valid_solutions: list
    ) -> dict:
        """
        Select best individual solution.
        """

        if self.prefer_lowest_residual:

            return sorted(
                valid_solutions,
                key=lambda solution: solution.get(
                    "residual_error",
                    float("inf")
                )
            )[0]

        return valid_solutions[0]

    def _positions_to_array(
        self,
        valid_solutions: list
    ) -> np.ndarray:
        """
        Convert solution position dictionaries to Nx3 array.
        """

        positions = []

        for solution in valid_solutions:

            position = solution.get(
                "position",
                {}
            )

            positions.append(
                [
                    position.get("x"),
                    position.get("y"),
                    position.get("z")
                ]
            )

        return np.asarray(
            positions,
            dtype=np.float64
        )

    # ========================================================
    # VALIDATION
    # ========================================================

    def _validate_solver_results(
        self,
        solver_results: list
    ) -> None:
        """
        Validate input result list.
        """

        if solver_results is None:
            raise ValueError(
                "solver_results is None."
            )

        if not isinstance(solver_results, list):
            raise TypeError(
                "solver_results must be a list."
            )