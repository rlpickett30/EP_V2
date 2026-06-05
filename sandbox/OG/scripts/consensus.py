# ============================================================
# ENVIROPULSE
# CONSENSUS ALIGNMENT
# ============================================================

"""
Purpose
-------
Compute consensus timing relationships
across matched event groups.

This module:
- compares feature timing across channels
- computes residuals
- computes consensus timing
- measures spread and agreement

This module DOES NOT:
- perform event matching
- perform correlation refinement
- solve localization

Those responsibilities belong to:
    event_matching.py
    TDOA_event_analysis.py
    TDOA_event_solver.py
"""

# ============================================================
# IMPORTS
# ============================================================

import numpy as np

from aligned_feature_manager import (
    AlignedFeatureManager
)


# ============================================================
# CONSENSUS
# ============================================================

class ConsensusAlignment:

    def __init__(

        self,

        debug=False

    ):

        self.debug = debug

        # ====================================================
        # FEATURE MANAGER
        # ====================================================

        self.feature_manager = (
            AlignedFeatureManager()
        )

    # ========================================================
    # COMPUTE CONSENSUS
    # ========================================================

    def compute(

        self,
        matched_groups

    ):

        """
        Compute consensus timing
        for matched event groups.
        """

        result = {

            "success": False,

            "consensus_groups": [],

            "debug": {},

            "errors": []

        }

        try:

            # =================================================
            # VALIDATION
            # =================================================

            if not matched_groups:

                raise ValueError(

                    "No matched groups provided."

                )

            consensus_groups = []

            # =================================================
            # PROCESS GROUPS
            # =================================================

            for group in matched_groups:

                matched_channels = (
                    group["matched_channels"]
                )

                feature_values = {}

                residuals = {}

                # =============================================
                # EXTRACT FEATURES
                # =============================================

                for channel_name, event in (
                    matched_channels.items()
                ):

                    feature_value = (

                        self.feature_manager
                        .extract_feature(
                            event
                        )

                    )

                    feature_values[
                        channel_name
                    ] = feature_value

                # =============================================
                # CONSENSUS VALUE
                # =============================================

                consensus_value = float(

                    np.mean(
                        list(
                            feature_values.values()
                        )
                    )

                )

                # =============================================
                # RESIDUALS
                # =============================================

                for channel_name, value in (
                    feature_values.items()
                ):

                    residuals[
                        channel_name
                    ] = float(

                        value
                        -
                        consensus_value

                    )

                # =============================================
                # SPREAD
                # =============================================

                spread = float(

                    max(
                        feature_values.values()
                    )
                    -
                    min(
                        feature_values.values()
                    )

                )

                # =============================================
                # STANDARD DEVIATION
                # =============================================

                std_deviation = float(

                    np.std(
                        list(
                            feature_values.values()
                        )
                    )

                )

                # =============================================
                # CONSENSUS RECORD
                # =============================================

                consensus_record = {

                    "group_id":
                        group["group_id"],

                    "reference_channel":

                        group[
                            "reference_channel"
                        ],

                    "feature_values":
                        feature_values,

                    "consensus_value":
                        consensus_value,

                    "residuals":
                        residuals,

                    "spread":
                        spread,

                    "std_deviation":
                        std_deviation,

                    "matched_channels":
                        matched_channels

                }

                consensus_groups.append(
                    consensus_record
                )

            # =================================================
            # FINALIZE
            # =================================================

            result["success"] = True

            result["consensus_groups"] = (
                consensus_groups
            )

            # =================================================
            # DEBUG
            # =================================================

            if self.debug:

                result["debug"] = {

                    "active_feature":

                        self.feature_manager
                        .get_active_feature(),

                    "total_groups":

                        len(consensus_groups)

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
