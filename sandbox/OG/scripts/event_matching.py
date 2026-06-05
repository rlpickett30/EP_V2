# ============================================================
# ENVIROPULSE
# EVENT MATCHING
# ============================================================

"""
Purpose
-------
Match temporally similar events across channels.

This module:
- groups events across channels
- compares selected alignment features
- builds candidate event groups

This module DOES NOT:
- perform feature extraction logic
- perform correlation refinement
- compute consensus
- solve localization

Those responsibilities belong to:
    aligned_feature_manager.py
    consensus.py
    TDOA_event_analysis.py
"""

# ============================================================
# IMPORTS
# ============================================================

from aligned_feature_manager import (
    AlignedFeatureManager
)


# ============================================================
# EVENT MATCHER
# ============================================================

class EventMatcher:

    def __init__(

        self,

        match_tolerance=2000,

        debug=False

    ):

        self.match_tolerance = (
            match_tolerance
        )

        self.debug = debug

        # ====================================================
        # FEATURE MANAGER
        # ====================================================

        self.feature_manager = (
            AlignedFeatureManager()
        )

    # ========================================================
    # MATCH EVENTS
    # ========================================================

    def match(

        self,
        channel_events

    ):

        """
        Match events across channels
        using the active alignment feature.
        """

        result = {

            "success": False,

            "matched_groups": [],

            "debug": {},

            "errors": []

        }

        try:

            # =================================================
            # VALIDATION
            # =================================================

            if not channel_events:

                raise ValueError(

                    "No channel events provided."

                )

            channel_names = list(
                channel_events.keys()
            )

            if len(channel_names) < 2:

                raise ValueError(

                    "At least two channels required."

                )

            # =================================================
            # REFERENCE CHANNEL
            # =================================================

            reference_channel = (
                channel_names[0]
            )

            reference_events = (
                channel_events[
                    reference_channel
                ]
            )

            matched_groups = []

            group_id = 0

            # =================================================
            # MATCH REFERENCE EVENTS
            # =================================================

            for ref_event in reference_events:

                # =============================================
                # EXTRACT FEATURE
                # =============================================

                ref_feature = (

                    self.feature_manager
                    .extract_feature(
                        ref_event
                    )

                )

                current_group = {

                    "group_id":
                        group_id,

                    "reference_channel":
                        reference_channel,

                    "reference_feature":
                        ref_feature,

                    "matched_channels": {

                        reference_channel:
                            ref_event

                    }

                }

                valid_group = True

                # =============================================
                # SEARCH OTHER CHANNELS
                # =============================================

                for channel in channel_names[1:]:

                    nearest_event = None

                    nearest_error = float(
                        "inf"
                    )

                    candidate_events = (
                        channel_events[
                            channel
                        ]
                    )

                    # =========================================
                    # SEARCH CANDIDATES
                    # =========================================

                    for candidate in candidate_events:

                        candidate_feature = (

                            self.feature_manager
                            .extract_feature(
                                candidate
                            )

                        )

                        error = abs(

                            candidate_feature
                            -
                            ref_feature

                        )

                        if error < (
                            self.match_tolerance
                        ):

                            if error < nearest_error:

                                nearest_error = (
                                    error
                                )

                                nearest_event = (
                                    candidate
                                )

                    # =========================================
                    # FAILED MATCH
                    # =========================================

                    if nearest_event is None:

                        valid_group = False

                        break

                    # =========================================
                    # STORE MATCH
                    # =========================================

                    current_group[
                        "matched_channels"
                    ][channel] = (
                        nearest_event
                    )

                # =============================================
                # STORE VALID GROUP
                # =============================================

                if valid_group:

                    matched_groups.append(

                        current_group

                    )

                    group_id += 1

            # =================================================
            # FINALIZE
            # =================================================

            result["success"] = True

            result["matched_groups"] = (
                matched_groups
            )

            # =================================================
            # DEBUG
            # =================================================

            if self.debug:

                result["debug"] = {

                    "reference_channel":
                        reference_channel,

                    "match_tolerance":
                        self.match_tolerance,

                    "active_feature":

                        self.feature_manager
                        .get_active_feature(),

                    "total_groups":

                        len(matched_groups)

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
