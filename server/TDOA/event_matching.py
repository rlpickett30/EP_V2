# ============================================================
# event_matching.py
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
#   Match detected event windows across channels using a selected
#   alignment feature.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["event_matching"]
#
# Does:
#   - Groups temporally similar channel events
#   - Uses a configured alignment feature
#   - Builds candidate matched event groups
#
# Does NOT:
#   - Load TDOA_config.json directly
#   - Extract raw signal features
#   - Compute matching consensus
#   - Solve TDOA geometry
#   - Publish events
#   - Own subsystem workflow
#
# Owner:
#   TDOA_event_analysis.py
#
# ============================================================


class EventMatcher:
    """
    Helper used by TDOA_event_analysis.py to group likely matching
    events across multiple channels.
    """

    def __init__(
        self,
        config: dict,
        debug: bool = False
    ):
        self.config = config
        self.debug = debug

        matching_config = self.config.get(
            "event_matching",
            {}
        )

        self.alignment_feature = matching_config.get(
            "alignment_feature",
            "onset_sample"
        )

        self.match_tolerance_samples = matching_config.get(
            "match_tolerance_samples",
            2000
        )

        self.reference_channel_mode = matching_config.get(
            "reference_channel_mode",
            "first"
        )

        self.minimum_channels_required = matching_config.get(
            "minimum_channels_required",
            4
        )

        self.prevent_reuse = matching_config.get(
            "prevent_reuse",
            True
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def match(
        self,
        channel_events: dict
    ) -> dict:
        """
        Match detected events across channels.
        """

        result = {
            "success": False,
            "matched_groups": [],
            "debug": {},
            "errors": []
        }

        try:
            self._validate_channel_events(
                channel_events
            )

            channel_names = list(
                channel_events.keys()
            )

            reference_channel = self._select_reference_channel(
                channel_names=channel_names,
                channel_events=channel_events
            )

            reference_events = channel_events[
                reference_channel
            ]

            used_event_ids = {
                channel_name: set()
                for channel_name in channel_names
            }

            matched_groups = []

            group_id = 0

            for reference_index, reference_event in enumerate(
                reference_events
            ):

                reference_feature = self._extract_alignment_feature(
                    reference_event
                )

                current_group = {
                    "group_id": group_id,
                    "alignment_feature": self.alignment_feature,
                    "reference_channel": reference_channel,
                    "reference_feature": reference_feature,
                    "matched_channels": {
                        reference_channel: reference_event
                    },
                    "match_errors": {
                        reference_channel: 0.0
                    }
                }

                if self.prevent_reuse:
                    used_event_ids[reference_channel].add(
                        reference_index
                    )

                for channel_name in channel_names:

                    if channel_name == reference_channel:
                        continue

                    nearest_match = self._find_nearest_event(
                        reference_feature=reference_feature,
                        candidate_events=channel_events[channel_name],
                        used_indexes=used_event_ids[channel_name]
                    )

                    if nearest_match is None:
                        continue

                    current_group["matched_channels"][channel_name] = (
                        nearest_match["event"]
                    )

                    current_group["match_errors"][channel_name] = (
                        nearest_match["error"]
                    )

                    if self.prevent_reuse:
                        used_event_ids[channel_name].add(
                            nearest_match["index"]
                        )

                if (
                    len(current_group["matched_channels"])
                    >= self.minimum_channels_required
                ):
                    matched_groups.append(
                        current_group
                    )

                    group_id += 1

            result["success"] = True
            result["matched_groups"] = matched_groups

            if self.debug:
                result["debug"] = {
                    "alignment_feature": self.alignment_feature,
                    "match_tolerance_samples": int(
                        self.match_tolerance_samples
                    ),
                    "reference_channel_mode": self.reference_channel_mode,
                    "minimum_channels_required": int(
                        self.minimum_channels_required
                    ),
                    "prevent_reuse": bool(
                        self.prevent_reuse
                    ),
                    "reference_channel": reference_channel,
                    "input_channel_count": int(
                        len(channel_names)
                    ),
                    "total_matched_groups": int(
                        len(matched_groups)
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
    # MATCHING HELPERS
    # ========================================================

    def _find_nearest_event(
        self,
        reference_feature,
        candidate_events: list,
        used_indexes: set
    ) -> dict | None:
        """
        Find nearest candidate event within tolerance.
        """

        nearest_event = None
        nearest_index = None
        nearest_error = float("inf")

        for candidate_index, candidate_event in enumerate(
            candidate_events
        ):

            if (
                self.prevent_reuse
                and
                candidate_index in used_indexes
            ):
                continue

            candidate_feature = self._extract_alignment_feature(
                candidate_event
            )

            error = abs(
                candidate_feature - reference_feature
            )

            if error <= self.match_tolerance_samples:

                if error < nearest_error:
                    nearest_error = error
                    nearest_event = candidate_event
                    nearest_index = candidate_index

        if nearest_event is None:
            return None

        return {
            "event": nearest_event,
            "index": nearest_index,
            "error": float(nearest_error)
        }

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

    def _select_reference_channel(
        self,
        channel_names: list,
        channel_events: dict
    ) -> str:
        """
        Select reference channel for matching.
        """

        if self.reference_channel_mode == "first":
            return channel_names[0]

        if self.reference_channel_mode == "most_events":

            return max(
                channel_names,
                key=lambda channel_name: len(
                    channel_events[channel_name]
                )
            )

        raise ValueError(
            f"Unknown reference_channel_mode: "
            f"{self.reference_channel_mode}"
        )

    # ========================================================
    # VALIDATION
    # ========================================================

    def _validate_channel_events(
        self,
        channel_events: dict
    ) -> None:
        """
        Validate channel event input.
        """

        if channel_events is None:
            raise ValueError(
                "channel_events is None."
            )

        if not isinstance(channel_events, dict):
            raise TypeError(
                "channel_events must be a dictionary."
            )

        if not channel_events:
            raise ValueError(
                "No channel events provided."
            )

        channel_names = list(
            channel_events.keys()
        )

        if len(channel_names) < self.minimum_channels_required:
            raise ValueError(
                "Not enough channels provided for matching. "
                f"Required={self.minimum_channels_required}, "
                f"Available={len(channel_names)}"
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