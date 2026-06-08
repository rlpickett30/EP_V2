# ============================================================
# TDOA_event_analysis.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Role:
#   Specialized helper / analysis orchestrator.
#
# Purpose:
#   Analyze detected channel events by matching events across
#   channels, computing matching consensus, and preparing
#   solver-ready timing groups.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["TDOA_event_analysis"]
#
# Does:
#   - Runs event_matching.py
#   - Runs matching_consensus.py
#   - Builds solver-ready analysis groups
#   - Computes TDOA values relative to a reference channel
#
# Does NOT:
#   - Load TDOA_config.json directly
#   - Detect onsets or offsets
#   - Extract raw signal features
#   - Solve localization geometry
#   - Perform solver consensus
#   - Publish events
#   - Own subsystem workflow
#
# Owner:
#   TDOA_manager.py
#
# ============================================================

from TDOA.event_matching import (
    EventMatcher
)

from TDOA.matching_consensus import (
    MatchingConsensus
)


class TDOAEventAnalysis:
    """
    Helper used by TDOA_manager.py to convert detected channel
    events into solver-ready timing groups.
    """

    def __init__(
        self,
        config: dict,
        debug: bool = False
    ):
        self.config = config
        self.debug = debug

        analysis_config = self.config.get(
            "TDOA_event_analysis",
            {}
        )

        self.minimum_channels_required = analysis_config.get(
            "minimum_channels_required",
            4
        )

        self.use_valid_consensus_only = analysis_config.get(
            "use_valid_consensus_only",
            True
        )

        self.event_matcher = EventMatcher(
            config=self.config,
            debug=self.debug
        )

        self.matching_consensus = MatchingConsensus(
            config=self.config,
            debug=self.debug
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def analyze(
        self,
        channel_events: dict
    ) -> dict:
        """
        Analyze detected channel events.
        """

        result = {
            "success": False,
            "analysis_groups": [],
            "debug": {},
            "errors": []
        }

        try:
            self._validate_channel_events(
                channel_events
            )

            matching_result = self.event_matcher.match(
                channel_events=channel_events
            )

            if not matching_result.get("success", False):
                raise RuntimeError(
                    "Event matching failed."
                )

            matched_groups = matching_result.get(
                "matched_groups",
                []
            )

            if not matched_groups:
                result["success"] = True
                result["analysis_groups"] = []

                if self.debug:
                    result["debug"] = {
                        "message": "No matched groups found.",
                        "matching_debug": matching_result.get(
                            "debug",
                            {}
                        )
                    }

                return result

            consensus_result = self.matching_consensus.compute(
                matched_groups=matched_groups
            )

            if not consensus_result.get("success", False):
                raise RuntimeError(
                    "Matching consensus failed."
                )

            if self.use_valid_consensus_only:
                consensus_groups = consensus_result.get(
                    "valid_consensus_groups",
                    []
                )
            else:
                consensus_groups = consensus_result.get(
                    "consensus_groups",
                    []
                )

            analysis_groups = []

            for group in consensus_groups:

                analysis_record = self._build_analysis_record(
                    group
                )

                if analysis_record is not None:
                    analysis_groups.append(
                        analysis_record
                    )

            result["success"] = True
            result["analysis_groups"] = analysis_groups

            if self.debug:
                result["debug"] = {
                    "minimum_channels_required": int(
                        self.minimum_channels_required
                    ),
                    "use_valid_consensus_only": bool(
                        self.use_valid_consensus_only
                    ),
                    "total_matched_groups": int(
                        len(matched_groups)
                    ),
                    "total_consensus_groups": int(
                        len(
                            consensus_result.get(
                                "consensus_groups",
                                []
                            )
                        )
                    ),
                    "total_valid_consensus_groups": int(
                        len(
                            consensus_result.get(
                                "valid_consensus_groups",
                                []
                            )
                        )
                    ),
                    "total_analysis_groups": int(
                        len(analysis_groups)
                    ),
                    "matching_debug": matching_result.get(
                        "debug",
                        {}
                    ),
                    "consensus_debug": consensus_result.get(
                        "debug",
                        {}
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
    # ANALYSIS RECORD BUILDER
    # ========================================================

    def _build_analysis_record(
        self,
        consensus_group: dict
    ) -> dict | None:
        """
        Convert one consensus group into a solver-ready analysis
        record.
        """

        matched_channels = consensus_group.get(
            "matched_channels",
            {}
        )

        if len(matched_channels) < self.minimum_channels_required:
            return None

        feature_values = consensus_group.get(
            "feature_values",
            {}
        )

        reference_channel = consensus_group.get(
            "reference_channel"
        )

        if reference_channel is None:
            return None

        if reference_channel not in feature_values:
            return None

        reference_value = feature_values[
            reference_channel
        ]

        tdoa_values = self._compute_tdoa_values(
            feature_values=feature_values,
            reference_value=reference_value
        )

        return {
            "group_id": consensus_group.get(
                "group_id"
            ),
            "reference_channel": reference_channel,
            "alignment_feature": consensus_group.get(
                "alignment_feature"
            ),
            "feature_values": feature_values,
            "reference_value": reference_value,
            "tdoa_values": tdoa_values,
            "consensus_value": consensus_group.get(
                "consensus_value"
            ),
            "residuals": consensus_group.get(
                "residuals",
                {}
            ),
            "spread": consensus_group.get(
                "spread"
            ),
            "std_deviation": consensus_group.get(
                "std_deviation"
            ),
            "channel_count": consensus_group.get(
                "channel_count",
                len(matched_channels)
            ),
            "consensus_valid": consensus_group.get(
                "consensus_valid",
                False
            ),
            "matched_channels": matched_channels,
            "match_errors": consensus_group.get(
                "match_errors",
                {}
            )
        }

    def _compute_tdoa_values(
        self,
        feature_values: dict,
        reference_value
    ) -> dict:
        """
        Compute relative TDOA feature differences.

        These are still in the units of the selected alignment
        feature, usually samples at this stage.
        """

        tdoa_values = {}

        for channel_name, value in feature_values.items():

            tdoa_values[channel_name] = float(
                value - reference_value
            )

        return tdoa_values

    # ========================================================
    # VALIDATION
    # ========================================================

    def _validate_channel_events(
        self,
        channel_events: dict
    ) -> None:
        """
        Validate detected channel-event input.
        """

        if channel_events is None:
            raise ValueError(
                "channel_events is None."
            )

        if not isinstance(channel_events, dict):
            raise TypeError(
                "channel_events must be a dictionary."
            )

        if len(channel_events) < self.minimum_channels_required:
            raise ValueError(
                "Not enough channels for TDOA event analysis. "
                f"Required={self.minimum_channels_required}, "
                f"Available={len(channel_events)}"
            )

        for channel_name, events in channel_events.items():

            if events is None:
                raise ValueError(
                    f"Channel has no event list: {channel_name}"
                )

            if not isinstance(events, list):
                raise TypeError(
                    f"Events for {channel_name} must be a list."
                )