# ============================================================
# matching_consensus.py
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
#   Evaluate timing agreement across matched event groups.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["matching_consensus"]
#
# Does:
#   - Computes consensus alignment value
#   - Computes residuals
#   - Computes spread
#   - Computes standard deviation
#   - Marks matched groups as consensus-valid or invalid
#
# Does NOT:
#   - Match events
#   - Extract raw signal features
#   - Solve TDOA geometry
#   - Publish events
#   - Own subsystem workflow
#
# Owner:
#   TDOA_event_analysis.py
#
# ============================================================

import numpy as np


class MatchingConsensus:
    """
    Helper used by TDOA_event_analysis.py to evaluate whether
    matched event groups are internally consistent enough to pass
    forward toward the TDOA solver.
    """

    def __init__(
        self,
        config: dict,
        debug: bool = False
    ):
        self.config = config
        self.debug = debug

        consensus_config = self.config.get(
            "matching_consensus",
            {}
        )

        self.alignment_feature = consensus_config.get(
            "alignment_feature",
            "onset_sample"
        )

        self.max_spread_samples = consensus_config.get(
            "max_spread_samples",
            2000
        )

        self.max_std_deviation_samples = consensus_config.get(
            "max_std_deviation_samples",
            750
        )

        self.minimum_channels_required = consensus_config.get(
            "minimum_channels_required",
            4
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def compute(
        self,
        matched_groups: list
    ) -> dict:
        """
        Compute matching consensus for matched event groups.

        Parameters
        ----------
        matched_groups:
            List of matched groups from event_matching.py.

        Returns
        -------
        dict:
            Structured consensus result.
        """

        result = {
            "success": False,
            "consensus_groups": [],
            "valid_consensus_groups": [],
            "debug": {},
            "errors": []
        }

        try:
            self._validate_matched_groups(
                matched_groups
            )

            consensus_groups = []

            valid_consensus_groups = []

            for group in matched_groups:

                consensus_record = self._compute_group_consensus(
                    group
                )

                consensus_groups.append(
                    consensus_record
                )

                if consensus_record.get("consensus_valid", False):
                    valid_consensus_groups.append(
                        consensus_record
                    )

            result["success"] = True

            result["consensus_groups"] = consensus_groups

            result["valid_consensus_groups"] = valid_consensus_groups

            if self.debug:
                result["debug"] = {
                    "alignment_feature": self.alignment_feature,
                    "max_spread_samples": int(
                        self.max_spread_samples
                    ),
                    "max_std_deviation_samples": int(
                        self.max_std_deviation_samples
                    ),
                    "minimum_channels_required": int(
                        self.minimum_channels_required
                    ),
                    "total_groups": int(
                        len(consensus_groups)
                    ),
                    "valid_groups": int(
                        len(valid_consensus_groups)
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
    # CONSENSUS HELPERS
    # ========================================================

    def _compute_group_consensus(
        self,
        group: dict
    ) -> dict:
        """
        Compute timing consensus for one matched group.
        """

        matched_channels = group.get(
            "matched_channels",
            {}
        )

        feature_values = {}

        for channel_name, event in matched_channels.items():

            feature_values[channel_name] = self._extract_alignment_feature(
                event
            )

        values = list(
            feature_values.values()
        )

        consensus_value = float(
            np.mean(values)
        )

        residuals = {}

        for channel_name, value in feature_values.items():

            residuals[channel_name] = float(
                value - consensus_value
            )

        spread = float(
            max(values) - min(values)
        )

        std_deviation = float(
            np.std(values)
        )

        consensus_valid = self._consensus_is_valid(
            channel_count=len(feature_values),
            spread=spread,
            std_deviation=std_deviation
        )

        return {
            "group_id": group.get("group_id"),
            "alignment_feature": self.alignment_feature,
            "reference_channel": group.get(
                "reference_channel"
            ),
            "feature_values": feature_values,
            "consensus_value": consensus_value,
            "residuals": residuals,
            "spread": spread,
            "std_deviation": std_deviation,
            "channel_count": len(feature_values),
            "consensus_valid": consensus_valid,
            "matched_channels": matched_channels,
            "match_errors": group.get(
                "match_errors",
                {}
            )
        }

    def _consensus_is_valid(
        self,
        channel_count: int,
        spread: float,
        std_deviation: float
    ) -> bool:
        """
        Determine whether matched group passes consensus limits.
        """

        if channel_count < self.minimum_channels_required:
            return False

        if spread > self.max_spread_samples:
            return False

        if std_deviation > self.max_std_deviation_samples:
            return False

        return True

    def _extract_alignment_feature(
        self,
        event: dict
    ):
        """
        Extract selected alignment feature from one detected event.
        """

        if self.alignment_feature in event:
            return event[self.alignment_feature]

        features = event.get(
            "features",
            {}
        )

        if self.alignment_feature in features:
            return features[self.alignment_feature]

        peak_features = features.get(
            "peak_amplitude",
            {}
        )

        if self.alignment_feature in peak_features:
            return peak_features[self.alignment_feature]

        raise KeyError(
            f"Alignment feature not found in event: "
            f"{self.alignment_feature}"
        )

    # ========================================================
    # VALIDATION
    # ========================================================

    def _validate_matched_groups(
        self,
        matched_groups: list
    ) -> None:
        """
        Validate matched group input.
        """

        if matched_groups is None:
            raise ValueError(
                "matched_groups is None."
            )

        if not isinstance(matched_groups, list):
            raise TypeError(
                "matched_groups must be a list."
            )

        if len(matched_groups) == 0:
            raise ValueError(
                "No matched groups provided."
            )