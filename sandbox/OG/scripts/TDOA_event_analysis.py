# ============================================================
# ENVIROPULSE
# TDOA EVENT ANALYSIS
# ============================================================

"""
Purpose
-------
Main analysis orchestration layer.

This module:
- performs event matching
- performs feature alignment
- computes consensus timing
- prepares timing data for solver stage

This module DOES NOT:
- perform onset/offset detection
- solve localization geometry

Those responsibilities belong to:
    TDOA_event_detection.py
    TDOA_event_solver.py
"""

# ============================================================
# IMPORTS
# ============================================================

from event_matching import (
    EventMatcher
)

from consensus import (
    ConsensusAlignment
)

from aligned_feature_manager import (
    AlignedFeatureManager
)


# ============================================================
# ANALYSIS
# ============================================================

class TDOAEventAnalysis:

    def __init__(

        self,

        match_tolerance=2000,

        debug=False

    ):

        self.debug = debug

        # ====================================================
        # MATCHER
        # ====================================================

        self.event_matcher = EventMatcher(

            match_tolerance=
                match_tolerance,

            debug=
                debug

        )

        # ====================================================
        # CONSENSUS
        # ====================================================

        self.consensus_alignment = (
            ConsensusAlignment(
                debug=debug
            )
        )

        # ====================================================
        # FEATURE MANAGER
        # ====================================================

        self.feature_manager = (
            AlignedFeatureManager()
        )

    # ========================================================
    # ANALYZE
    # ========================================================

    def analyze(

        self,
        channel_events

    ):

        """
        Perform TDOA event analysis.
        """

        result = {

            "success": False,

            "analysis_groups": [],

            "debug": {},

            "errors": []

        }

        try:

            # =================================================
            # EVENT MATCHING
            # =================================================

            matching_result = (

                self.event_matcher.match(

                    channel_events

                )

            )

            if not matching_result["success"]:

                raise RuntimeError(

                    "Event matching failed."

                )

            matched_groups = (

                matching_result[
                    "matched_groups"
                ]

            )

            # =================================================
            # CONSENSUS ALIGNMENT
            # =================================================

            consensus_result = (

                self.consensus_alignment.compute(

                    matched_groups

                )

            )

            if not consensus_result["success"]:

                raise RuntimeError(

                    "Consensus alignment failed."

                )

            consensus_groups = (

                consensus_result[
                    "consensus_groups"
                ]

            )

            # =================================================
            # BUILD ANALYSIS GROUPS
            # =================================================

            analysis_groups = []

            for group in consensus_groups:

                feature_values = (
                    group["feature_values"]
                )

                reference_channel = (
                    group["reference_channel"]
                )

                reference_value = (

                    feature_values[
                        reference_channel
                    ]

                )

                # =============================================
                # COMPUTE TDOA VALUES
                # =============================================

                tdoa_values = {}

                for channel_name, value in (

                    feature_values.items()

                ):

                    tdoa_values[
                        channel_name
                    ] = float(

                        value
                        -
                        reference_value

                    )

                # =============================================
                # ANALYSIS RECORD
                # =============================================

                analysis_record = {

                    "group_id":
                        group["group_id"],

                    "reference_channel":
                        reference_channel,

                    "active_feature":

                        self.feature_manager
                        .get_active_feature(),

                    "feature_values":
                        feature_values,

                    "consensus_value":

                        group[
                            "consensus_value"
                        ],

                    "residuals":
                        group["residuals"],

                    "spread":
                        group["spread"],

                    "std_deviation":

                        group[
                            "std_deviation"
                        ],

                    "tdoa_values":
                        tdoa_values,

                    "matched_channels":

                        group[
                            "matched_channels"
                        ]

                }

                analysis_groups.append(
                    analysis_record
                )

            # =================================================
            # FINALIZE
            # =================================================

            result["success"] = True

            result["analysis_groups"] = (
                analysis_groups
            )

            # =================================================
            # DEBUG
            # =================================================

            if self.debug:

                result["debug"] = {

                    "total_analysis_groups":

                        len(
                            analysis_groups
                        ),

                    "active_feature":

                        self.feature_manager
                        .get_active_feature(),

                    "matching_debug":

                        matching_result[
                            "debug"
                        ],

                    "consensus_debug":

                        consensus_result[
                            "debug"
                        ]

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