# ============================================================
# ENVIROPULSE
# TDOA MANAGER
# ============================================================

"""
Purpose
-------
Primary orchestration layer for the TDOA subsystem.

This manager:
- owns the canonical event object
- controls pipeline flow
- coordinates:
    - detection
    - analysis
    - solving
- handles failures
- returns finalized event package

This is the entry point called by:
    dispatcher.py
"""

# ============================================================
# IMPORTS
# ============================================================

from TDOA_event_detection import (
    TDOAEventDetection
)

from TDOA_event_analysis import (
    TDOAEventAnalysis
)

from TDOA_event_solver import (
    TDOAEventSolver
)


# ============================================================
# MANAGER
# ============================================================

class TDOAManager:

    def __init__(

        self,

        microphone_positions = {

            "CH1": [ 0.0,     0.0,     0.0   ],

            "CH2": [-8.5352,  0.0,     0.2   ],

            "CH3": [-8.5352, -4.8768,  0.4   ],

            "CH4": [ 0.0,    -4.8768,  0.6   ],

            "CH5": [-4.2726, -2.4384,  0.9906]

        },

        sample_rate=96000,

        speed_of_sound=340.0,

        onset_config=None,

        offset_config=None,

        match_tolerance=2000,

        debug=False

    ):

        # ====================================================
        # CONFIGURATION
        # ====================================================
        self.microphone_positions = (
            microphone_positions
        )   
        self.sample_rate = sample_rate

        self.speed_of_sound = (
            speed_of_sound
        )

        self.debug = debug

        # ====================================================
        # DEFAULT CONFIGS
        # ====================================================

        if onset_config is None:

            onset_config = {

                "run_length": 3,

                "max_backtrack": 7

            }

        if offset_config is None:

            offset_config = {

                "noise_sample_count":
                    200000,

                "offset_multiplier":
                    4.0,

                "min_quiet_samples":
                    15000

            }

        # ====================================================
        # DETECTION
        # ====================================================

        self.detector = (

            TDOAEventDetection(

                onset_config=
                    onset_config,

                offset_config=
                    offset_config,

                debug=
                    debug

            )

        )

        # ====================================================
        # ANALYSIS
        # ====================================================

        self.analysis = (

            TDOAEventAnalysis(

                match_tolerance=
                    match_tolerance,

                debug=
                    debug

            )

        )

        # ====================================================
        # SOLVER
        # ====================================================

        self.solver = (

            TDOAEventSolver(

                microphone_positions=
                    self.microphone_positions,

                sample_rate=
                    sample_rate,

                speed_of_sound=
                    speed_of_sound,

                debug=
                    debug

            )

        )

    # ========================================================
    # PROCESS
    # ========================================================

    def process(

        self,

        channel_signals

    ):

        """
        Main TDOA pipeline.

        Input:
            channel_signals = {

                "CH1": signal,
                "CH2": signal,
                ...

            }

        Returns:
            finalized_event
        """

        # ====================================================
        # CANONICAL EVENT OBJECT
        # ====================================================

        event = {

            "success": False,

            "channels": {},

            "analysis": {},

            "solution": {},

            "pipeline_state": {

                "detection_complete":
                    False,

                "analysis_complete":
                    False,

                "solution_complete":
                    False

            },

            "debug": {},

            "errors": []

        }

        try:

            # =================================================
            # DETECTION STAGE
            # =================================================

            channel_events = {}

            for channel_name, signal in (
                channel_signals.items()
            ):

                detection_result = (

                    self.detector.process_channel(

                        signal=
                            signal,

                        sample_rate=
                            self.sample_rate,

                        channel_name=
                            channel_name

                    )

                )

                # =============================================
                # FAILURE
                # =============================================

                if not detection_result["success"]:

                    raise RuntimeError(

                        f"Detection failed "
                        f"for {channel_name}"

                    )

                # =============================================
                # STORE CHANNEL EVENTS
                # =============================================

                channel_events[
                    channel_name
                ] = (

                    detection_result["events"]

                )

                # =============================================
                # STORE RAW DETECTION
                # =============================================

                event["channels"][
                    channel_name
                ] = detection_result

            # =================================================
            # PIPELINE UPDATE
            # =================================================

            event["pipeline_state"][
                "detection_complete"
            ] = True

            # =================================================
            # ANALYSIS STAGE
            # =================================================

            analysis_result = (

                self.analysis.analyze(

                    channel_events

                )

            )

            if not analysis_result["success"]:

                raise RuntimeError(

                    "Analysis stage failed."

                )

            event["analysis"] = (
                analysis_result
            )

            # =================================================
            # PIPELINE UPDATE
            # =================================================

            event["pipeline_state"][
                "analysis_complete"
            ] = True

            # =================================================
            # SOLVER STAGE
            # =================================================

            solutions = []

            analysis_groups = (

                analysis_result[
                    "analysis_groups"
                ]

            )

            for group in analysis_groups:

                solution_result = (

                    self.solver.solve(
                        group
                    )

                )

                if solution_result["success"]:

                    solutions.append(
                        solution_result
                    )

            event["solution"] = {

                "solutions":
                    solutions

            }

            # =================================================
            # PIPELINE UPDATE
            # =================================================

            event["pipeline_state"][
                "solution_complete"
            ] = True

            # =================================================
            # FINALIZE
            # =================================================

            event["success"] = True

            # =================================================
            # DEBUG
            # =================================================

            if self.debug:

                event["debug"] = {

                    "channel_count":

                        len(
                            channel_signals
                        ),

                    "analysis_group_count":

                        len(
                            analysis_groups
                        ),

                    "solution_count":

                        len(
                            solutions
                        )

                }

        # ====================================================
        # ERROR HANDLING
        # ====================================================

        except Exception as e:

            event["errors"].append(
                str(e)
            )

            if self.debug:

                event["debug"][
                    "exception_type"
                ] = type(e).__name__

        return event