# ============================================================
# platform_registry_tdoa_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Platform Registry
#
# Role:
#   TDOA Readiness Manager
#
# Purpose:
#   Determine when a registered node has enough state to participate
#   in TDOA workflows.
#
# Does:
#   - Inspect current node state snapshots
#   - Determine NODE_TDOA_STATE readiness
#   - Publish only on readiness change by default
#
# Does NOT:
#   - Solve TDOA
#   - Request recordings
#   - Manage node registration
#   - Publish directly
#
# Owner:
#   platform_registry_dispatcher.py
#
# ============================================================


from copy import deepcopy
from datetime import datetime, timezone


class PlatformRegistryTDOAManager:
    """
    Evaluates whether a node has enough current state to participate
    in TDOA workflows.
    """

    def __init__(self, config=None):
        self.config = config or {}

        platform_config = self.config.get(
            "platform_registry",
            {}
        )

        self.tdoa_config = platform_config.get(
            "tdoa",
            {}
        )

        self.debug = platform_config.get(
            "debug",
            False
        )

        self.publish_only_on_change = self.tdoa_config.get(
            "publish_only_on_change",
            True
        )

        self.require_rtk = self.tdoa_config.get(
            "require_rtk",
            True
        )

        self.require_enviro = self.tdoa_config.get(
            "require_enviro",
            True
        )

        self.node_tdoa_states = {}

    # ========================================================
    # PUBLIC API
    # ========================================================

    def handle_node_state_snapshot(
        self,
        node_id,
        node_state_snapshot,
        source_event
    ):
        """
        Evaluate one node snapshot and return NODE_TDOA_STATE only when
        the node transitions into TDOA-ready state.
        
        NODE_TDOA_STATE means:
            This node is now TDOA-capable.
            
            It does not publish partial readiness updates.
        """

        result = self._base_result()

        if not node_id:
            result["reason"] = "missing_node_id"
            return result

        if not isinstance(
            node_state_snapshot,
            dict
        ):
            result["reason"] = "missing_node_state_snapshot"
            return result

        previous_tdoa_state = deepcopy(
            self.node_tdoa_states.get(
                node_id,
                {}
            )
        )

        current_tdoa_state = self._build_tdoa_state(
            node_id=node_id,
            node_state_snapshot=node_state_snapshot,
            source_event=source_event
        )

        previous_ready = bool(
            previous_tdoa_state.get(
                "tdoa_ready",
                False
            )
        )

        current_ready = bool(
            current_tdoa_state.get(
                "tdoa_ready",
                False
            )
        )

        self.node_tdoa_states[node_id] = deepcopy(
            current_tdoa_state
        )

        result["success"] = True
        result["node_id"] = node_id
        result["tdoa_state"] = current_tdoa_state
        result["previous_tdoa_state"] = previous_tdoa_state

        if not current_ready:
            result["publish"] = False
            result["reason"] = "node_not_tdoa_ready"
            result["changed"] = previous_ready != current_ready
            return result

        if previous_ready:
            result["publish"] = False
            result["reason"] = "node_already_tdoa_ready"
            result["changed"] = False
            return result

        result["publish"] = True
        result["reason"] = "node_became_tdoa_ready"
        result["changed"] = True

        return result

    def get_node_tdoa_state(self, node_id):
        """
        Return current TDOA state for one node.
        """

        state = self.node_tdoa_states.get(
            node_id
        )

        if state is None:
            return None

        return deepcopy(
            state
        )

    def get_tdoa_snapshot(self):
        """
        Return all known node TDOA readiness states.
        """

        return {
            "generated_at_utc": self._utc_now(),
            "nodes": deepcopy(self.node_tdoa_states)
        }

    # ========================================================
    # TDOA READINESS LOGIC
    # ========================================================

    def _build_tdoa_state(
        self,
        node_id,
        node_state_snapshot,
        source_event
    ):
        """
        Build canonical TDOA readiness state for one node.
        """

        checks = self._build_checks(
            node_state_snapshot
        )

        missing = [
            check_name
            for check_name, passed in checks.items()
            if not passed
        ]

        ready = len(
            missing
        ) == 0

        return {
            "node_id": node_id,
            "node_name": node_state_snapshot.get(
                "node_name",
                node_id
            ),
            "source_event": source_event,
            "tdoa_ready": ready,
            "missing": missing,
            "checks": checks,
            "timestamp_utc": self._utc_now(),
            "position": node_state_snapshot.get(
                "gps_coord"
            ),
            "pps_locked": node_state_snapshot.get(
                "pps_locked",
                False
            ),
            "gps_locked": node_state_snapshot.get(
                "gps_locked",
                False
            ),
            "rtk_online": node_state_snapshot.get(
                "rtk_online",
                False
            ),
            "enviro_online": node_state_snapshot.get(
                "enviro_online",
                False
            ),
            "temperature_c": node_state_snapshot.get(
                "temperature_c"
            ),
            "humidity_percent": node_state_snapshot.get(
                "humidity_percent"
            ),
            "pressure_hpa": node_state_snapshot.get(
                "pressure_hpa"
            )
        }

    def _build_checks(
        self,
        node_state_snapshot
    ):
        """
        Return readiness checks for TDOA participation.
        """

        checks = {
            "pps_locked": bool(
                node_state_snapshot.get(
                    "pps_locked",
                    False
                )
            ),
            "gps_locked": bool(
                node_state_snapshot.get(
                    "gps_locked",
                    False
                )
            ),
            "gps_coord": node_state_snapshot.get(
                "gps_coord"
            ) is not None
        }

        if self.require_rtk:
            checks["rtk_online"] = bool(
                node_state_snapshot.get(
                    "rtk_online",
                    False
                )
            )

        if self.require_enviro:
            checks["enviro_online"] = bool(
                node_state_snapshot.get(
                    "enviro_online",
                    False
                )
            )

        return checks

    # ========================================================
    # RESULT HELPERS
    # ========================================================

    def _base_result(self):
        """
        Create standard result package.
        """

        return {
            "success": False,
            "publish": False,
            "reason": None,
            "node_id": None,
            "tdoa_state": None,
            "previous_tdoa_state": None,
            "changed": False
        }

    def _utc_now(self):
        """
        Return current UTC time in ISO format.
        """

        return datetime.now(
            timezone.utc
        ).isoformat()