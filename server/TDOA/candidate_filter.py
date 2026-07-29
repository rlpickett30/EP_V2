# ============================================================
# candidate_filter.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Owner:
#   TDOA_dispatcher.py
#
# Purpose:
#   Helper used by the TDOA dispatcher to determine whether
#   TDOA-capable nodes reported the same avis_lite_id within
#   the configured time window.
#
# Does:
#   - Accepts a TDOA capability event/snapshot
#   - Accepts recent avis_lite events
#   - Filters events by TDOA-capable node IDs
#   - Finds matching avis_lite_id groups by recording frame
#   - Returns ranked candidate packages
#
# Does NOT:
#   - Track node capability state
#   - Contact TDOA_manager.py directly
#   - Publish events
#   - Own workflow
#
# ============================================================

import logging
from typing import Dict, List, Optional, Any


class CandidateFilter:

    def __init__(self, config: dict):

        filter_config = config.get(
            "candidate_filter",
            {}
        )

        self.match_window_seconds = filter_config.get(
            "avis_lite_match_window_seconds",
            0.050
        )

        self.min_matching_nodes = filter_config.get(
            "min_matching_nodes",
            4
        )

        self.max_candidate_age_seconds = filter_config.get(
            "max_candidate_age_seconds",
            2.0
        )

        self.prefer_largest_group = filter_config.get(
            "prefer_largest_group",
            True
        )

        self.prefer_smallest_time_spread = filter_config.get(
            "prefer_smallest_time_spread",
            True
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def find_candidate(
        self,
        capability_event: dict,
        recent_avis_lite_events: List[dict]
    ) -> Optional[dict]:
        """
        Find a valid TDOA candidate from recent avis_lite events.

        Parameters
        ----------
        capability_event:
            Event or snapshot from TDOA_state_manager.py.

        recent_avis_lite_events:
            Recent avis_lite detections known by dispatcher/state.

        Returns
        -------
        dict | None:
            Candidate package if matching nodes exist.
            None if no candidate should be sent to TDOA_manager.py.
        """

        candidates = self.find_candidates(
            capability_event=capability_event,
            recent_avis_lite_events=recent_avis_lite_events
        )

        if not candidates:
            return None

        return candidates[0]

    def find_candidates(
        self,
        capability_event: dict,
        recent_avis_lite_events: List[dict]
    ) -> List[dict]:
        """
        Return every valid recording-frame candidate in priority order.

        The dispatcher uses the complete list so an already-consumed frame
        cannot hide a later unprocessed frame.
        """

        if not capability_event.get("candidate_filter_allowed", False):
            return []

        capable_node_ids = capability_event.get(
            "tdoa_capable_node_ids",
            []
        )

        if len(capable_node_ids) < self.min_matching_nodes:
            return []

        eligible_events = self._filter_events_by_capable_nodes(
            recent_avis_lite_events,
            capable_node_ids
        )

        if len(eligible_events) < self.min_matching_nodes:
            return []

        candidates = self._find_matching_event_groups(
            eligible_events
        )

        if not candidates:
            logging.debug(
                "Candidate filter found no matching avis_lite group."
            )

        return candidates

    # ========================================================
    # EVENT FILTERING
    # ========================================================

    def _filter_events_by_capable_nodes(
        self,
        recent_events: List[dict],
        capable_node_ids: List[str]
    ) -> List[dict]:
        """
        Keep only avis_lite events from currently TDOA-capable nodes.
        """

        capable_node_set = set(capable_node_ids)

        filtered_events = []

        for event in recent_events:

            node_id = event.get("node_id")

            if node_id in capable_node_set:
                filtered_events.append(event)

        return filtered_events

    # ========================================================
    # MATCHING LOGIC
    # ========================================================

    def _find_matching_event_groups(
        self,
        events: List[dict]
    ) -> List[dict]:
        """
        Find every recording frame with a matching avis_lite group.
        """

        grouped_events = self._group_events_by_candidate_frame(
            events
        )

        candidates = []

        for group_key, group in grouped_events.items():

            avis_lite_id, frame_key = group_key

            candidate = self._evaluate_group(
                avis_lite_id,
                group
            )

            if candidate is not None:
                candidate["frame_key"] = frame_key
                candidates.append(candidate)

        if not candidates:
            return []

        return self._sort_candidates(
            candidates
        )

    def _group_events_by_candidate_frame(
        self,
        events: List[dict]
    ) -> Dict[tuple, List[dict]]:
        """
        Group events by species identity and source recording frame.

        Recording identity is preferred because it remains stable when a
        fifth node reports after a four-node candidate already launched.
        Events without recording identity use a temporal fallback.
        """

        grouped = {}
        fallback_by_avis_lite_id = {}

        for event in events:

            avis_lite_id = event.get("avis_lite_id")

            if avis_lite_id is None:
                continue

            frame_key = self._event_frame_key(
                event
            )

            if frame_key is None:
                fallback_by_avis_lite_id.setdefault(
                    avis_lite_id,
                    []
                ).append(
                    event
                )
                continue

            grouped.setdefault(
                (
                    avis_lite_id,
                    frame_key
                ),
                []
            ).append(
                event
            )

        for avis_lite_id, fallback_events in (
            fallback_by_avis_lite_id.items()
        ):

            temporal_frames = self._cluster_events_by_time(
                fallback_events
            )

            for frame_events in temporal_frames:

                frame_start = min(
                    event.get("node_time")
                    for event in frame_events
                )

                frame_key = (
                    f"node_time:{float(frame_start):.6f}"
                )

                grouped[
                    (
                        avis_lite_id,
                        frame_key
                    )
                ] = frame_events

        return grouped

    def _event_frame_key(
        self,
        event: dict
    ) -> Optional[str]:
        """
        Return a stable recording-frame identity for one detection.
        """

        payload = event.get(
            "payload",
            {}
        )

        if not isinstance(payload, dict):
            payload = {}

        recording_id = (
            event.get("recording_id")
            or payload.get("recording_id")
        )

        if recording_id not in (
            None,
            ""
        ):
            return f"recording_id:{recording_id}"

        recording_utc = (
            event.get("recording_utc")
            or payload.get("recording_utc")
        )

        if recording_utc not in (
            None,
            ""
        ):
            return f"recording_utc:{recording_utc}"

        return None

    def _cluster_events_by_time(
        self,
        events: List[dict]
    ) -> List[List[dict]]:
        """
        Build temporal frames only when recording identity is unavailable.
        """

        sorted_events = sorted(
            (
                event
                for event in events
                if event.get("node_time") is not None
            ),
            key=lambda event: event.get("node_time")
        )

        frames = []

        for event in sorted_events:

            node_time = float(
                event.get("node_time")
            )

            if not frames:
                frames.append(
                    [event]
                )
                continue

            frame_start = float(
                frames[-1][0].get("node_time")
            )

            if (
                node_time
                -
                frame_start
                >
                self.match_window_seconds
            ):
                frames.append(
                    [event]
                )
                continue

            frames[-1].append(
                event
            )

        return frames

    def _evaluate_group(
        self,
        avis_lite_id: Any,
        events: List[dict]
    ) -> Optional[dict]:
        """
        Determine whether one avis_lite_id group has enough unique
        capable nodes inside the timing window.
        """

        sorted_events = sorted(
            events,
            key=lambda event: event.get("node_time", 0.0)
        )

        candidates = []

        for start_index in range(len(sorted_events)):

            start_event = sorted_events[start_index]
            start_time = start_event.get("node_time")

            if start_time is None:
                continue

            window_events = []
            used_node_ids = set()

            for event in sorted_events[start_index:]:

                node_time = event.get("node_time")
                node_id = event.get("node_id")

                if node_time is None or node_id is None:
                    continue

                if node_time - start_time > self.match_window_seconds:
                    break

                if node_id in used_node_ids:
                    continue

                window_events.append(event)
                used_node_ids.add(node_id)

            if len(used_node_ids) >= self.min_matching_nodes:
                candidates.append(
                    self._build_candidate_package(
                        avis_lite_id,
                        window_events
                    )
                )

        if not candidates:
            return None

        return self._select_best_candidate(
            candidates
        )

    # ========================================================
    # CANDIDATE SELECTION
    # ========================================================

    def _select_best_candidate(
        self,
        candidates: List[dict]
    ) -> dict:
        """
        Select best candidate.

        Current priority:
            1. Highest node count
            2. Smallest time spread
        """

        return self._sort_candidates(
            candidates
        )[0]

    def _sort_candidates(
        self,
        candidates: List[dict]
    ) -> List[dict]:
        """
        Return candidates in deterministic dispatcher priority order.
        """

        return sorted(
            candidates,
            key=lambda candidate: (
                -candidate.get("node_count", 0),
                candidate.get("time_spread_seconds", float("inf")),
                str(candidate.get("frame_key", "")),
                str(candidate.get("avis_lite_id", ""))
            )
        )

    def _build_candidate_package(
        self,
        avis_lite_id: Any,
        events: List[dict]
    ) -> dict:
        """
        Build candidate package for TDOA_dispatcher.py.
        """

        node_times = [
            event.get("node_time")
            for event in events
            if event.get("node_time") is not None
        ]

        return {
            "candidate_valid": True,
            "avis_lite_id": avis_lite_id,
            "node_count": len(events),
            "node_ids": [
                event.get("node_id")
                for event in events
            ],
            "time_spread_seconds": max(node_times) - min(node_times),
            "match_window_seconds": self.match_window_seconds,
            "events": events
        }
