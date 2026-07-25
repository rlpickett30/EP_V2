# ============================================================
# TDOA_recording_manager.py
#
# EnviroPulse V2
#
# Subsystem:
#   TDOA
#
# Role:
#   Manager
#
# Purpose:
#   Maintain request-scoped TDOA recording collection transactions.
#
# Expected config source:
#   TDOA_config.json
#
# Expected config section:
#   config["tdoa_recording_manager"]
#
# Does:
#   - Open one transaction for each published TDOA_REQUEST
#   - Track requested nodes and raw node answers separately
#   - Track explicit node failures separately
#   - Count only TDOA_VALID_RECORDING events toward quorum
#   - Track request deadlines
#   - Close all-returned and expired transactions exactly once
#   - Build complete sets from exact validated server WAV references
#   - Build below-quorum failure packages
#
# Does NOT:
#   - Subscribe to the Event Bus
#   - Publish Event Bus events
#   - Start workflow threads
#   - Select TDOA candidates
#   - Send requests to nodes
#   - Validate multipart uploads or WAV contents
#   - Run TDOA calculations
#
# Owner:
#   TDOA_dispatcher.py
#
# ============================================================

from __future__ import annotations

import copy
import threading
import time

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Callable


DEFAULT_MINIMUM_VALID_RECORDINGS = 4
DEFAULT_COLLECTION_TIMEOUT_SECONDS = 15.0
DEFAULT_DEADLINE_POLL_INTERVAL_SECONDS = 0.25
DEFAULT_MAX_CLOSED_REQUESTS = 500


class TDOARecordingManager:
    """
    Thread-safe bookkeeping for request-scoped recording collection.

    The dispatcher owns workflow and publications. This manager records
    evidence and returns a closure package only when a transaction reaches a
    terminal state.
    """

    def __init__(
        self,
        config: dict | None = None,
        monotonic_now: Callable[[], float] | None = None,
        utc_now: Callable[[], str] | None = None
    ):

        full_config = (
            config
            if isinstance(config, dict)
            else {}
        )

        manager_config = full_config.get(
            "tdoa_recording_manager",
            {}
        )

        self.minimum_valid_recordings = self._positive_int(
            manager_config.get(
                "minimum_valid_recordings",
                full_config.get(
                    "tdoa_subsystem",
                    {}
                ).get(
                    "minimum_tdoa_nodes",
                    DEFAULT_MINIMUM_VALID_RECORDINGS
                )
            ),
            "minimum_valid_recordings"
        )

        self.collection_timeout_seconds = self._positive_float(
            manager_config.get(
                "collection_timeout_seconds",
                DEFAULT_COLLECTION_TIMEOUT_SECONDS
            ),
            "collection_timeout_seconds"
        )

        self.deadline_poll_interval_seconds = self._positive_float(
            manager_config.get(
                "deadline_poll_interval_seconds",
                DEFAULT_DEADLINE_POLL_INTERVAL_SECONDS
            ),
            "deadline_poll_interval_seconds"
        )

        self.max_closed_requests = self._positive_int(
            manager_config.get(
                "max_closed_requests",
                DEFAULT_MAX_CLOSED_REQUESTS
            ),
            "max_closed_requests"
        )

        self._monotonic_now = monotonic_now or time.monotonic
        self._utc_now_callback = utc_now

        self._open_requests = {}
        self._closed_requests = {}
        self._closed_request_order = []
        self._lock = threading.RLock()

    # ========================================================
    # OPEN
    # ========================================================

    def open_request(
        self,
        request: dict,
        candidate: dict | None = None
    ) -> dict:
        """
        Open one collection transaction before TDOA_REQUEST is published.
        """

        if not isinstance(request, dict):
            raise TypeError(
                "TDOA recording transaction request must be a dictionary."
            )

        request_id = self._request_id(
            request
        )

        if request_id is None:
            raise ValueError(
                "TDOA recording transaction requires a request ID."
            )

        requested_node_ids = self._normalize_node_ids(
            request.get("target_nodes")
        )

        if not requested_node_ids:
            raise ValueError(
                "TDOA recording transaction requires target_nodes."
            )

        request_items = request.get(
            "request_items",
            {}
        )

        if not isinstance(request_items, dict):
            raise ValueError(
                "TDOA recording transaction requires request_items."
            )

        opened_monotonic = self._monotonic_now()
        opened_at_utc = self._utc_now()
        deadline_at_utc = self._add_seconds_to_utc(
            opened_at_utc,
            self.collection_timeout_seconds
        )

        transaction = {
            "tdoa_request_id": request_id,
            "request": copy.deepcopy(request),
            "candidate": copy.deepcopy(
                candidate
                if isinstance(candidate, dict)
                else {}
            ),
            "requested_node_ids": set(requested_node_ids),
            "request_items": copy.deepcopy(request_items),
            "node_answers": {},
            "explicit_failures": {},
            "valid_recordings": {},
            "opened_monotonic": opened_monotonic,
            "deadline_monotonic": (
                opened_monotonic
                +
                self.collection_timeout_seconds
            ),
            "opened_at_utc": opened_at_utc,
            "deadline_at_utc": deadline_at_utc,
            "closed": False
        }

        with self._lock:

            if request_id in self._open_requests:
                raise ValueError(
                    f"TDOA recording transaction already open: {request_id}"
                )

            if request_id in self._closed_requests:
                raise ValueError(
                    f"TDOA recording transaction already closed: {request_id}"
                )

            self._open_requests[
                request_id
            ] = transaction

            return self._snapshot_locked(
                transaction
            )

    # ========================================================
    # RAW NODE ANSWERS
    # ========================================================

    def record_node_answer(
        self,
        event: dict
    ) -> dict:
        """
        Record one raw TDOA_RECORDING answer.

        A raw success proves that the node answered, but it does not count
        toward quorum. Only TDOA_VALID_RECORDING adds a valid recording.
        """

        identity = self._event_identity(
            event
        )

        request_id = identity[
            "tdoa_request_id"
        ]

        node_id = identity[
            "node_id"
        ]

        if request_id is None or node_id is None:
            return self._ignored_result(
                request_id=request_id,
                node_id=node_id,
                reason="response_identity_missing"
            )

        with self._lock:

            transaction = self._open_requests.get(
                request_id
            )

            if transaction is None:
                return self._unknown_or_closed_result_locked(
                    request_id=request_id,
                    node_id=node_id
                )

            if node_id not in transaction[
                "requested_node_ids"
            ]:
                return self._ignored_result(
                    request_id=request_id,
                    node_id=node_id,
                    reason="node_not_requested"
                )

            if not self._recording_id_matches(
                transaction=transaction,
                node_id=node_id,
                recording_id=identity["recording_id"]
            ):
                return self._ignored_result(
                    request_id=request_id,
                    node_id=node_id,
                    reason="recording_id_mismatch"
                )

            transaction["node_answers"][
                node_id
            ] = copy.deepcopy(event)

            if identity["status"] in {
                "failure",
                "failed",
                "error",
                "rejected"
            }:

                if node_id not in transaction[
                    "valid_recordings"
                ]:

                    transaction["explicit_failures"][
                        node_id
                    ] = {
                        "node_id": node_id,
                        "recording_id": identity["recording_id"],
                        "failure_reason": identity["failure_reason"],
                        "failure_detail": identity["failure_detail"],
                        "event": copy.deepcopy(event)
                    }

            closure = self._close_if_all_returned_locked(
                transaction
            )

            if closure is not None:
                return closure

            return self._progress_result_locked(
                transaction
            )

    # ========================================================
    # VALID RECORDINGS
    # ========================================================

    def record_valid_recording(
        self,
        event: dict
    ) -> dict:
        """
        Record one Communication-validated server WAV reference.
        """

        identity = self._event_identity(
            event
        )

        request_id = identity[
            "tdoa_request_id"
        ]

        node_id = identity[
            "node_id"
        ]

        if request_id is None or node_id is None:
            return self._ignored_result(
                request_id=request_id,
                node_id=node_id,
                reason="valid_recording_identity_missing"
            )

        payload = self._payload(
            event
        )

        server_wav_path = (
            payload.get("server_wav_path")
            or event.get("server_wav_path")
            or payload.get("wav_path")
            or event.get("wav_path")
        )

        if server_wav_path in (None, ""):
            return self._ignored_result(
                request_id=request_id,
                node_id=node_id,
                reason="server_wav_path_missing"
            )

        with self._lock:

            transaction = self._open_requests.get(
                request_id
            )

            if transaction is None:
                return self._unknown_or_closed_result_locked(
                    request_id=request_id,
                    node_id=node_id
                )

            if node_id not in transaction[
                "requested_node_ids"
            ]:
                return self._ignored_result(
                    request_id=request_id,
                    node_id=node_id,
                    reason="node_not_requested"
                )

            if not self._recording_id_matches(
                transaction=transaction,
                node_id=node_id,
                recording_id=identity["recording_id"]
            ):
                return self._ignored_result(
                    request_id=request_id,
                    node_id=node_id,
                    reason="recording_id_mismatch"
                )

            if node_id in transaction[
                "explicit_failures"
            ]:
                return self._ignored_result(
                    request_id=request_id,
                    node_id=node_id,
                    reason="node_already_failed"
                )

            transaction["node_answers"].setdefault(
                node_id,
                copy.deepcopy(event)
            )

            transaction["valid_recordings"][
                node_id
            ] = self._build_recording_reference(
                event=event,
                identity=identity,
                server_wav_path=str(server_wav_path)
            )

            closure = self._close_if_all_returned_locked(
                transaction
            )

            if closure is not None:
                return closure

            return self._progress_result_locked(
                transaction
            )

    # ========================================================
    # DEADLINES
    # ========================================================

    def close_expired_requests(
        self
    ) -> list:
        """
        Close every transaction whose collection deadline has expired.
        """

        closures = []
        now_monotonic = self._monotonic_now()

        with self._lock:

            expired_request_ids = [
                request_id
                for request_id, transaction
                in self._open_requests.items()
                if (
                    not transaction.get("closed", False)
                    and now_monotonic
                    >= transaction["deadline_monotonic"]
                )
            ]

            for request_id in expired_request_ids:

                transaction = self._open_requests.get(
                    request_id
                )

                if transaction is None:
                    continue

                valid_count = len(
                    transaction["valid_recordings"]
                )

                if valid_count >= self.minimum_valid_recordings:

                    closure = self._close_success_locked(
                        transaction=transaction,
                        closure_reason="timeout_quorum"
                    )

                else:

                    closure = self._close_failure_locked(
                        transaction=transaction,
                        closure_reason="timeout",
                        failure_reason="below_quorum"
                    )

                closures.append(
                    closure
                )

        return closures

    # ========================================================
    # STATUS
    # ========================================================

    def get_status(
        self
    ) -> dict:

        with self._lock:

            return {
                "open_request_count": len(
                    self._open_requests
                ),
                "closed_request_count": len(
                    self._closed_requests
                ),
                "open_request_ids": sorted(
                    self._open_requests.keys()
                ),
                "minimum_valid_recordings":
                    self.minimum_valid_recordings,
                "collection_timeout_seconds":
                    self.collection_timeout_seconds
            }

    # ========================================================
    # CLOSURE
    # ========================================================

    def _close_if_all_returned_locked(
        self,
        transaction: dict
    ) -> dict | None:
        """
        Close when every requested node has a terminal result.

        A raw success is not terminal until Communication publishes the
        corresponding TDOA_VALID_RECORDING. Explicit failures are terminal.
        """

        terminal_node_ids = (
            set(
                transaction["valid_recordings"].keys()
            )
            |
            set(
                transaction["explicit_failures"].keys()
            )
        )

        if not transaction[
            "requested_node_ids"
        ].issubset(
            terminal_node_ids
        ):
            return None

        valid_count = len(
            transaction["valid_recordings"]
        )

        if valid_count >= self.minimum_valid_recordings:

            return self._close_success_locked(
                transaction=transaction,
                closure_reason="all_returned"
            )

        return self._close_failure_locked(
            transaction=transaction,
            closure_reason="all_returned",
            failure_reason="below_quorum"
        )

    def _close_success_locked(
        self,
        transaction: dict,
        closure_reason: str
    ) -> dict:

        payload = self._build_closure_payload_locked(
            transaction=transaction,
            closure_reason=closure_reason
        )

        payload.update({
            "success": True,
            "status": "complete",
            "failure_reason": None,
            "failure_detail": None,
            "recording_references": [
                copy.deepcopy(
                    transaction["valid_recordings"][node_id]
                )
                for node_id in sorted(
                    transaction["valid_recordings"]
                )
            ],
            "recording_events": [
                copy.deepcopy(
                    transaction[
                        "valid_recordings"
                    ][node_id]["event"]
                )
                for node_id in sorted(
                    transaction["valid_recordings"]
                )
            ]
        })

        self._archive_closed_locked(
            transaction=transaction,
            closure_payload=payload
        )

        return {
            "action": "complete",
            "tdoa_request_id": transaction["tdoa_request_id"],
            "payload": payload
        }

    def _close_failure_locked(
        self,
        transaction: dict,
        closure_reason: str,
        failure_reason: str
    ) -> dict:

        payload = self._build_closure_payload_locked(
            transaction=transaction,
            closure_reason=closure_reason
        )

        payload.update({
            "success": False,
            "status": "failed",
            "failure_reason": failure_reason,
            "failure_detail": (
                "TDOA recording collection closed with "
                f"{payload['valid_recording_count']} valid recordings; "
                f"{payload['required_valid_recordings']} are required."
            )
        })

        self._archive_closed_locked(
            transaction=transaction,
            closure_payload=payload
        )

        return {
            "action": "failed",
            "tdoa_request_id": transaction["tdoa_request_id"],
            "payload": payload
        }

    def _build_closure_payload_locked(
        self,
        transaction: dict,
        closure_reason: str
    ) -> dict:

        requested_node_ids = set(
            transaction["requested_node_ids"]
        )

        answered_node_ids = set(
            transaction["node_answers"].keys()
        )

        valid_node_ids = set(
            transaction["valid_recordings"].keys()
        )

        failed_node_ids = set(
            transaction["explicit_failures"].keys()
        )

        terminal_node_ids = (
            valid_node_ids
            |
            failed_node_ids
        )

        return {
            "schema_version": 1,
            "tdoa_request_id": transaction["tdoa_request_id"],
            "request_id": transaction["tdoa_request_id"],
            "candidate_key": transaction[
                "request"
            ].get(
                "candidate_key"
            ),
            "request": copy.deepcopy(
                transaction["request"]
            ),
            "candidate": copy.deepcopy(
                transaction["candidate"]
            ),
            "requested_node_ids": sorted(
                requested_node_ids
            ),
            "answered_node_ids": sorted(
                answered_node_ids
            ),
            "terminal_node_ids": sorted(
                terminal_node_ids
            ),
            "valid_node_ids": sorted(
                valid_node_ids
            ),
            "failed_node_ids": sorted(
                failed_node_ids
            ),
            "missing_node_ids": sorted(
                requested_node_ids
                -
                terminal_node_ids
            ),
            "requested_node_count": len(
                requested_node_ids
            ),
            "answered_node_count": len(
                answered_node_ids
            ),
            "valid_recording_count": len(
                valid_node_ids
            ),
            "explicit_failure_count": len(
                failed_node_ids
            ),
            "required_valid_recordings":
                self.minimum_valid_recordings,
            "explicit_failures": copy.deepcopy(
                transaction["explicit_failures"]
            ),
            "collection_opened_at_utc":
                transaction["opened_at_utc"],
            "collection_deadline_at_utc":
                transaction["deadline_at_utc"],
            "collection_closed_at_utc": self._utc_now(),
            "closure_reason": closure_reason
        }

    def _archive_closed_locked(
        self,
        transaction: dict,
        closure_payload: dict
    ):

        request_id = transaction[
            "tdoa_request_id"
        ]

        transaction["closed"] = True

        self._open_requests.pop(
            request_id,
            None
        )

        self._closed_requests[
            request_id
        ] = copy.deepcopy(
            closure_payload
        )

        self._closed_request_order.append(
            request_id
        )

        while (
            len(self._closed_request_order)
            >
            self.max_closed_requests
        ):

            oldest_request_id = (
                self._closed_request_order.pop(0)
            )

            self._closed_requests.pop(
                oldest_request_id,
                None
            )

    # ========================================================
    # EVENT NORMALIZATION
    # ========================================================

    def _event_identity(
        self,
        event: dict
    ) -> dict:

        if not isinstance(event, dict):
            return {
                "tdoa_request_id": None,
                "node_id": None,
                "recording_id": None,
                "status": "unknown",
                "failure_reason": None,
                "failure_detail": None
            }

        payload = self._payload(
            event
        )

        status = (
            payload.get("status")
            or event.get("status")
            or "unknown"
        )

        return {
            "tdoa_request_id": self._request_id(
                payload,
                fallback=event
            ),
            "node_id": self._clean_identity(
                payload.get("node_id")
                or event.get("node_id")
            ),
            "recording_id": self._clean_identity(
                payload.get("recording_id")
                or event.get("recording_id")
            ),
            "status": str(status).strip().lower(),
            "failure_reason": (
                payload.get("failure_reason")
                or event.get("failure_reason")
            ),
            "failure_detail": (
                payload.get("failure_detail")
                or event.get("failure_detail")
            )
        }

    def _build_recording_reference(
        self,
        event: dict,
        identity: dict,
        server_wav_path: str
    ) -> dict:

        payload = self._payload(
            event
        )

        return {
            "tdoa_request_id": identity["tdoa_request_id"],
            "request_id": identity["tdoa_request_id"],
            "node_id": identity["node_id"],
            "recording_id": identity["recording_id"],
            "server_wav_path": server_wav_path,
            "wav_path": server_wav_path,
            "recording_path": server_wav_path,
            "sample_rate_hz": (
                payload.get("sample_rate_hz")
                or payload.get("sample_rate")
            ),
            "channels": payload.get("channels"),
            "sample_width_bytes": payload.get(
                "sample_width_bytes"
            ),
            "frame_count": payload.get("frame_count"),
            "validation_status": payload.get(
                "validation_status",
                "accepted"
            ),
            "server_validation": copy.deepcopy(
                payload.get(
                    "server_validation",
                    {}
                )
            ),
            "event": copy.deepcopy(event)
        }

    # ========================================================
    # RESULT HELPERS
    # ========================================================

    def _progress_result_locked(
        self,
        transaction: dict
    ) -> dict:

        snapshot = self._snapshot_locked(
            transaction
        )

        return {
            "action": "pending",
            "tdoa_request_id": transaction["tdoa_request_id"],
            "payload": snapshot
        }

    def _snapshot_locked(
        self,
        transaction: dict
    ) -> dict:

        requested_node_ids = set(
            transaction["requested_node_ids"]
        )

        valid_node_ids = set(
            transaction["valid_recordings"].keys()
        )

        failed_node_ids = set(
            transaction["explicit_failures"].keys()
        )

        terminal_node_ids = (
            valid_node_ids
            |
            failed_node_ids
        )

        return {
            "tdoa_request_id": transaction["tdoa_request_id"],
            "requested_node_ids": sorted(
                requested_node_ids
            ),
            "answered_node_ids": sorted(
                transaction["node_answers"].keys()
            ),
            "valid_node_ids": sorted(
                valid_node_ids
            ),
            "failed_node_ids": sorted(
                failed_node_ids
            ),
            "missing_node_ids": sorted(
                requested_node_ids
                -
                terminal_node_ids
            ),
            "requested_node_count": len(
                requested_node_ids
            ),
            "answered_node_count": len(
                transaction["node_answers"]
            ),
            "valid_recording_count": len(
                valid_node_ids
            ),
            "explicit_failure_count": len(
                failed_node_ids
            ),
            "required_valid_recordings":
                self.minimum_valid_recordings,
            "collection_opened_at_utc":
                transaction["opened_at_utc"],
            "collection_deadline_at_utc":
                transaction["deadline_at_utc"]
        }

    def _unknown_or_closed_result_locked(
        self,
        request_id: str,
        node_id: str
    ) -> dict:

        if request_id in self._closed_requests:
            reason = "request_already_closed"
        else:
            reason = "request_unknown"

        return self._ignored_result(
            request_id=request_id,
            node_id=node_id,
            reason=reason
        )

    def _ignored_result(
        self,
        request_id,
        node_id,
        reason: str
    ) -> dict:

        return {
            "action": "ignored",
            "tdoa_request_id": request_id,
            "node_id": node_id,
            "reason": reason,
            "payload": {}
        }

    # ========================================================
    # IDENTITY HELPERS
    # ========================================================

    def _recording_id_matches(
        self,
        transaction: dict,
        node_id: str,
        recording_id
    ) -> bool:

        request_item = transaction[
            "request_items"
        ].get(
            node_id,
            {}
        )

        if not isinstance(request_item, dict):
            return False

        expected_recording_id = self._clean_identity(
            request_item.get("recording_id")
            or request_item.get("source_recording_id")
        )

        if expected_recording_id is None:
            return True

        return (
            self._clean_identity(recording_id)
            ==
            expected_recording_id
        )

    def _request_id(
        self,
        primary: dict,
        fallback: dict | None = None
    ):

        fallback = (
            fallback
            if isinstance(fallback, dict)
            else {}
        )

        return self._clean_identity(
            primary.get("tdoa_request_id")
            or primary.get("request_id")
            or fallback.get("tdoa_request_id")
            or fallback.get("request_id")
        )

    def _normalize_node_ids(
        self,
        raw_node_ids
    ) -> list:

        if isinstance(raw_node_ids, str):
            raw_node_ids = [raw_node_ids]

        if not isinstance(
            raw_node_ids,
            (
                list,
                tuple,
                set
            )
        ):
            return []

        node_ids = []
        seen = set()

        for raw_node_id in raw_node_ids:

            node_id = self._clean_identity(
                raw_node_id
            )

            if node_id is None or node_id in seen:
                continue

            seen.add(
                node_id
            )

            node_ids.append(
                node_id
            )

        return node_ids

    def _payload(
        self,
        event: dict
    ) -> dict:

        payload = event.get(
            "payload"
        )

        if isinstance(payload, dict):
            return payload

        return event

    def _clean_identity(
        self,
        value
    ):

        if value is None:
            return None

        cleaned = str(
            value
        ).strip()

        return cleaned or None

    # ========================================================
    # TIME / CONFIG HELPERS
    # ========================================================

    def _utc_now(
        self
    ) -> str:

        if self._utc_now_callback is not None:
            return str(
                self._utc_now_callback()
            )

        return (
            datetime.now(
                timezone.utc
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z"
            )
        )

    def _add_seconds_to_utc(
        self,
        utc_value: str,
        seconds: float
    ) -> str:

        try:

            parsed = datetime.fromisoformat(
                utc_value.replace(
                    "Z",
                    "+00:00"
                )
            )

            return (
                (
                    parsed
                    +
                    timedelta(seconds=seconds)
                )
                .isoformat()
                .replace(
                    "+00:00",
                    "Z"
                )
            )

        except (TypeError, ValueError):
            return utc_value

    def _positive_int(
        self,
        value,
        field_name: str
    ) -> int:

        parsed = int(
            value
        )

        if parsed < 1:
            raise ValueError(
                f"{field_name} must be positive."
            )

        return parsed

    def _positive_float(
        self,
        value,
        field_name: str
    ) -> float:

        parsed = float(
            value
        )

        if parsed <= 0.0:
            raise ValueError(
                f"{field_name} must be positive."
            )

        return parsed
