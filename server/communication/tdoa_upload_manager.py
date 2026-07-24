# ============================================================
# tdoa_upload_manager.py
#
# EnviroPulse V2
#
# Subsystem:
#   Server Communication
#
# Role:
#   Manager
#
# Purpose:
#   Own request-scoped TDOA upload registration, validation, storage,
#   idempotency, and receipt construction.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["http_upload"]
#
# Does:
#   - Register expected request/node/recording upload identities
#   - Generate and verify per-request upload tokens
#   - Validate multipart metadata and exact WAV bytes
#   - Validate WAV format and required timing-schema presence
#   - Write accepted WAVs through temporary storage and atomic replacement
#   - Return the original receipt for an identical retry
#   - Reject a conflicting retry
#   - Build server-local TDOA_RECORDING and TDOA_VALID_RECORDING events
#
# Does NOT:
#   - Open HTTP sockets
#   - Parse HTTP requests
#   - Publish Event Bus events
#   - Select TDOA nodes
#   - Count collection quorum
#   - Validate clock-model quality
#   - Stretch, compress, or otherwise modify audio
#
# Owner:
#   communication_dispatcher.py
#
# ============================================================

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
import wave

from datetime import datetime
from datetime import timezone
from pathlib import Path


DEFAULT_REQUEST_TTL_SECONDS = 60.0
DEFAULT_MAX_METADATA_BYTES = 256 * 1024
DEFAULT_MAX_WAV_BYTES = 8 * 1024 * 1024

DEFAULT_TIMING_FIELDS = (
    "recording_engine",
    "continuous_stream",
    "timing_state",
    "boundary_utc",
    "boundary_epoch",
    "boundary_sample",
    "guarded_stream_start_sample",
    "guarded_stream_end_sample_exclusive",
    "raw_timing_quality",
    "timing_issues",
)

SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
SAFE_COMPONENT_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


class UploadValidationError(Exception):
    """
    Structured upload rejection that is safe to return to the node.
    """

    def __init__(
        self,
        reason: str,
        detail: str,
        http_status: int = 422
    ):

        super().__init__(detail)

        self.reason = str(reason)
        self.detail = str(detail)
        self.http_status = int(http_status)


class TDOAUploadManager:
    """
    Validate and accept one request-scoped guarded WAV upload.
    """

    def __init__(
        self,
        config: dict | None = None
    ):

        self.config = (
            dict(config)
            if isinstance(config, dict)
            else {}
        )

        self.storage_dir = Path(
            self.config.get(
                "storage_dir",
                "TDOA/uploads"
            )
        ).expanduser().resolve()

        self.temp_dir = Path(
            self.config.get(
                "temp_dir",
                "TDOA/uploads/.incoming"
            )
        ).expanduser().resolve()

        self.request_ttl_seconds = self._positive_float(
            self.config.get(
                "request_ttl_seconds",
                DEFAULT_REQUEST_TTL_SECONDS
            ),
            "request_ttl_seconds"
        )

        self.max_metadata_bytes = self._positive_int(
            self.config.get(
                "max_metadata_bytes",
                DEFAULT_MAX_METADATA_BYTES
            ),
            "max_metadata_bytes"
        )

        self.max_wav_bytes = self._positive_int(
            self.config.get(
                "max_wav_bytes",
                DEFAULT_MAX_WAV_BYTES
            ),
            "max_wav_bytes"
        )

        self.allowed_channels = self._positive_int_set(
            self.config.get(
                "allowed_channels",
                [1]
            ),
            "allowed_channels"
        )

        self.allowed_sample_width_bytes = self._positive_int_set(
            self.config.get(
                "allowed_sample_width_bytes",
                [2]
            ),
            "allowed_sample_width_bytes"
        )

        self.allowed_sample_rates_hz = self._positive_int_set(
            self.config.get(
                "allowed_sample_rates_hz",
                [44100, 48000, 96000, 192000]
            ),
            "allowed_sample_rates_hz"
        )

        timing_fields = self.config.get(
            "required_timing_fields",
            DEFAULT_TIMING_FIELDS
        )

        if not isinstance(timing_fields, (list, tuple)):
            raise ValueError(
                "required_timing_fields must be a list."
            )

        self.required_timing_fields = tuple(
            str(field_name).strip()
            for field_name in timing_fields
            if str(field_name).strip()
        )

        self.enforce_source_ip = bool(
            self.config.get(
                "enforce_source_ip",
                True
            )
        )

        self._requests = {}
        self._accepted_uploads = {}
        self._lock = threading.RLock()

    # ========================================================
    # RUNTIME STORAGE
    # ========================================================

    def prepare_storage(
        self
    ):

        self.storage_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        self.temp_dir.mkdir(
            parents=True,
            exist_ok=True
        )

    # ========================================================
    # REQUEST REGISTRATION
    # ========================================================

    def register_expected_request(
        self,
        request_id,
        target_nodes,
        request_items,
        expected_source_ips: dict | None = None
    ) -> dict:
        """
        Register every expected node/recording before request transmission.
        """

        normalized_request_id = self._required_identity(
            request_id,
            "tdoa_request_id"
        )

        normalized_nodes = self._normalize_target_nodes(
            target_nodes
        )

        if not normalized_nodes:
            raise ValueError(
                "TDOA upload registration requires target_nodes."
            )

        if not isinstance(request_items, dict):
            raise ValueError(
                "TDOA upload registration requires request_items."
            )

        source_ips = (
            expected_source_ips
            if isinstance(expected_source_ips, dict)
            else {}
        )

        expected = {}

        for node_id in normalized_nodes:

            item = request_items.get(
                node_id
            )

            if not isinstance(item, dict):
                raise ValueError(
                    "TDOA upload registration has no request item for "
                    f"{node_id!r}."
                )

            item_node_id = self._required_identity(
                item.get("node_id", node_id),
                "request_item.node_id"
            )

            if item_node_id != node_id:
                raise ValueError(
                    "TDOA request item node mismatch: "
                    f"target={node_id!r} item={item_node_id!r}."
                )

            recording_id = self._required_identity(
                (
                    item.get("recording_id")
                    or item.get("source_recording_id")
                ),
                "request_item.recording_id"
            )

            source_ip = source_ips.get(
                node_id
            )

            expected[node_id] = {
                "node_id": node_id,
                "recording_id": recording_id,
                "source_ip": (
                    str(source_ip).strip()
                    if source_ip not in (None, "")
                    else None
                )
            }

        signature = tuple(
            (
                node_id,
                expected[node_id]["recording_id"],
                expected[node_id]["source_ip"]
            )
            for node_id in normalized_nodes
        )

        now_monotonic = time.monotonic()

        with self._lock:

            self._prune_expired_locked(
                now_monotonic
            )

            existing = self._requests.get(
                normalized_request_id
            )

            if existing is not None:

                if existing["signature"] != signature:
                    raise ValueError(
                        "Conflicting registration for existing "
                        f"TDOA request {normalized_request_id!r}."
                    )

                return self._registration_result(
                    existing,
                    duplicate=True
                )

            token = secrets.token_urlsafe(
                32
            )

            request = {
                "tdoa_request_id": normalized_request_id,
                "token": token,
                "expected": expected,
                "target_nodes": tuple(normalized_nodes),
                "signature": signature,
                "created_monotonic": now_monotonic,
                "expires_monotonic": (
                    now_monotonic
                    + self.request_ttl_seconds
                ),
                "created_at_utc": self._utc_now()
            }

            self._requests[
                normalized_request_id
            ] = request

            return self._registration_result(
                request,
                duplicate=False
            )

    # ========================================================
    # UPLOAD PROCESSING
    # ========================================================

    def process_upload(
        self,
        transaction: dict
    ) -> dict:
        """
        Validate, store, and build events for one HTTP upload.
        """

        try:

            if not isinstance(transaction, dict):
                raise UploadValidationError(
                    "upload_transaction_invalid",
                    "Upload transaction is not a dictionary.",
                    400
                )

            with self._lock:

                return self._process_upload_locked(
                    transaction
                )

        except UploadValidationError as error:

            return self._rejection(
                error.reason,
                error.detail,
                error.http_status
            )

        except Exception as error:

            logging.exception(
                "[TDOAUploadManager] Unexpected upload failure."
            )

            return self._rejection(
                "upload_server_failure",
                str(error),
                500
            )

    def _process_upload_locked(
        self,
        transaction: dict
    ) -> dict:

        metadata_bytes = transaction.get(
            "metadata_bytes"
        )

        wav_bytes = transaction.get(
            "wav_bytes"
        )

        if not isinstance(metadata_bytes, bytes):
            raise UploadValidationError(
                "upload_metadata_invalid",
                "Multipart metadata part is missing.",
                400
            )

        if len(metadata_bytes) > self.max_metadata_bytes:
            raise UploadValidationError(
                "upload_metadata_too_large",
                "Multipart metadata exceeds the configured limit.",
                413
            )

        if not isinstance(wav_bytes, bytes):
            raise UploadValidationError(
                "upload_wav_missing",
                "Multipart WAV part is missing.",
                400
            )

        if len(wav_bytes) > self.max_wav_bytes:
            raise UploadValidationError(
                "upload_wav_too_large",
                "WAV bytes exceed the configured limit.",
                413
            )

        metadata = self._decode_metadata(
            metadata_bytes
        )

        payload = metadata.get(
            "payload"
        )

        if not isinstance(payload, dict):
            raise UploadValidationError(
                "upload_metadata_invalid",
                "TDOA_RECORDING payload is missing.",
                422
            )

        identity = self._extract_identity(
            metadata,
            payload
        )

        request = self._get_active_request(
            identity["tdoa_request_id"]
        )

        self._validate_token(
            request=request,
            token=transaction.get("token")
        )

        expected = self._validate_expected_identity(
            request=request,
            identity=identity,
            source_ip=transaction.get("source_ip")
        )

        manifest = self._validate_manifest(
            metadata=metadata,
            payload=payload,
            identity=identity,
            wav_filename=transaction.get("wav_filename")
        )

        actual_byte_count = len(
            wav_bytes
        )

        actual_sha256 = hashlib.sha256(
            wav_bytes
        ).hexdigest()

        if manifest["byte_count"] != actual_byte_count:
            raise UploadValidationError(
                "upload_byte_count_mismatch",
                "Manifest byte_count does not match received WAV bytes.",
                422
            )

        if not secrets.compare_digest(
            manifest["sha256"],
            actual_sha256
        ):
            raise UploadValidationError(
                "upload_checksum_mismatch",
                "Manifest SHA-256 does not match received WAV bytes.",
                422
            )

        upload_key = (
            identity["tdoa_request_id"],
            identity["node_id"],
            identity["recording_id"]
        )

        existing = self._accepted_uploads.get(
            upload_key
        )

        if existing is not None:

            if (
                existing["byte_count"] == actual_byte_count
                and secrets.compare_digest(
                    existing["sha256"],
                    actual_sha256
                )
            ):

                return {
                    "accepted": True,
                    "success": True,
                    "idempotent": True,
                    "publish_events": False,
                    "http_status": 200,
                    "receipt": copy.deepcopy(
                        existing["receipt"]
                    )
                }

            raise UploadValidationError(
                "upload_conflicting_retry",
                (
                    "The request/node/recording identity was already "
                    "accepted with different WAV bytes."
                ),
                409
            )

        self._validate_recording_event(
            metadata=metadata,
            payload=payload,
            expected=expected
        )

        self._validate_timing_schema(
            payload
        )

        self.prepare_storage()

        temporary_path = self._write_temporary_wav(
            wav_bytes=wav_bytes,
            identity=identity
        )

        try:

            wav_properties = self._validate_wav_file(
                wav_path=temporary_path,
                payload=payload
            )

            accepted_path = self._accepted_path(
                identity
            )

            accepted_path.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            if accepted_path.exists():
                raise UploadValidationError(
                    "upload_storage_conflict",
                    (
                        "The accepted server WAV path already exists "
                        "without a matching runtime receipt."
                    ),
                    409
                )

            os.replace(
                temporary_path,
                accepted_path
            )

        finally:

            if temporary_path.exists():

                try:
                    temporary_path.unlink()
                except OSError:
                    logging.exception(
                        "[TDOAUploadManager] Failed removing temporary WAV."
                    )

        validated_at_utc = self._utc_now()

        receipt = self._build_receipt(
            identity=identity,
            byte_count=actual_byte_count,
            sha256=actual_sha256,
            accepted_path=accepted_path,
            wav_properties=wav_properties,
            validated_at_utc=validated_at_utc
        )

        tdoa_recording_event = self._build_server_recording_event(
            metadata=metadata,
            payload=payload,
            identity=identity,
            accepted_path=accepted_path,
            byte_count=actual_byte_count,
            sha256=actual_sha256,
            wav_properties=wav_properties,
            validated_at_utc=validated_at_utc
        )

        valid_recording_event = copy.deepcopy(
            tdoa_recording_event
        )

        valid_recording_event[
            "event_type"
        ] = "TDOA_VALID_RECORDING"

        valid_recording_event[
            "source"
        ] = "communication"

        valid_recording_event[
            "target"
        ] = "tdoa"

        valid_payload = valid_recording_event[
            "payload"
        ]

        valid_payload[
            "validation_status"
        ] = "accepted"

        valid_payload[
            "original_event_type"
        ] = "TDOA_RECORDING"

        accepted_record = {
            "byte_count": actual_byte_count,
            "sha256": actual_sha256,
            "receipt": copy.deepcopy(receipt),
            "server_wav_path": str(accepted_path),
            "accepted_at_utc": validated_at_utc
        }

        self._accepted_uploads[
            upload_key
        ] = accepted_record

        return {
            "accepted": True,
            "success": True,
            "idempotent": False,
            "publish_events": True,
            "http_status": 201,
            "receipt": receipt,
            "tdoa_recording_event": tdoa_recording_event,
            "tdoa_valid_recording_event": valid_recording_event
        }

    # ========================================================
    # REQUEST AND IDENTITY VALIDATION
    # ========================================================

    def _get_active_request(
        self,
        request_id: str
    ) -> dict:

        request = self._requests.get(
            request_id
        )

        if request is None:
            raise UploadValidationError(
                "upload_request_unknown",
                f"No active upload request exists for {request_id!r}.",
                403
            )

        if time.monotonic() > request["expires_monotonic"]:

            self._remove_request_locked(
                request_id
            )

            raise UploadValidationError(
                "upload_request_expired",
                f"Upload request {request_id!r} has expired.",
                410
            )

        return request

    def _validate_token(
        self,
        request: dict,
        token
    ):

        if not isinstance(token, str):
            raise UploadValidationError(
                "upload_token_invalid",
                "Upload token is missing.",
                403
            )

        if not secrets.compare_digest(
            request["token"],
            token
        ):
            raise UploadValidationError(
                "upload_token_invalid",
                "Upload token is not valid for this request.",
                403
            )

    def _validate_expected_identity(
        self,
        request: dict,
        identity: dict,
        source_ip
    ) -> dict:

        node_id = identity[
            "node_id"
        ]

        expected = request[
            "expected"
        ].get(
            node_id
        )

        if expected is None:
            raise UploadValidationError(
                "upload_node_not_requested",
                f"Node {node_id!r} was not requested.",
                403
            )

        if identity["recording_id"] != expected["recording_id"]:
            raise UploadValidationError(
                "upload_recording_not_requested",
                (
                    f"Expected recording {expected['recording_id']!r} "
                    f"from {node_id!r}; received "
                    f"{identity['recording_id']!r}."
                ),
                422
            )

        expected_source_ip = expected.get(
            "source_ip"
        )

        if (
            self.enforce_source_ip
            and expected_source_ip
            and str(source_ip).strip() != expected_source_ip
        ):
            raise UploadValidationError(
                "upload_source_ip_mismatch",
                (
                    f"Node {node_id!r} registered from "
                    f"{expected_source_ip!r}, but the upload arrived "
                    f"from {source_ip!r}."
                ),
                403
            )

        return expected

    # ========================================================
    # METADATA AND MANIFEST VALIDATION
    # ========================================================

    def _decode_metadata(
        self,
        metadata_bytes: bytes
    ) -> dict:

        try:

            metadata = json.loads(
                metadata_bytes.decode(
                    "utf-8"
                )
            )

        except (
            UnicodeDecodeError,
            json.JSONDecodeError
        ) as error:

            raise UploadValidationError(
                "upload_metadata_invalid",
                f"Metadata is not valid UTF-8 JSON: {error}.",
                400
            ) from error

        if not isinstance(metadata, dict):
            raise UploadValidationError(
                "upload_metadata_invalid",
                "Metadata JSON is not an object.",
                400
            )

        return metadata

    def _extract_identity(
        self,
        metadata: dict,
        payload: dict
    ) -> dict:

        return {
            "tdoa_request_id": self._required_identity(
                (
                    payload.get("tdoa_request_id")
                    or payload.get("request_id")
                    or metadata.get("tdoa_request_id")
                    or metadata.get("request_id")
                ),
                "tdoa_request_id",
                UploadValidationError
            ),
            "node_id": self._required_identity(
                (
                    payload.get("node_id")
                    or metadata.get("node_id")
                ),
                "node_id",
                UploadValidationError
            ),
            "recording_id": self._required_identity(
                (
                    payload.get("recording_id")
                    or metadata.get("recording_id")
                ),
                "recording_id",
                UploadValidationError
            )
        }

    def _validate_manifest(
        self,
        metadata: dict,
        payload: dict,
        identity: dict,
        wav_filename
    ) -> dict:

        manifest = payload.get(
            "upload_manifest"
        )

        if not isinstance(manifest, dict):
            raise UploadValidationError(
                "upload_manifest_missing",
                "payload.upload_manifest is missing.",
                422
            )

        top_level_manifest = metadata.get(
            "upload_manifest"
        )

        if (
            top_level_manifest is not None
            and top_level_manifest != manifest
        ):
            raise UploadValidationError(
                "upload_manifest_conflict",
                "Top-level and payload upload manifests differ.",
                422
            )

        for field_name, expected_value in (
            ("schema_version", 1),
            ("transport", "http_multipart"),
            ("field_name", "wav"),
            ("content_type", "audio/wav"),
        ):

            if manifest.get(field_name) != expected_value:
                raise UploadValidationError(
                    "upload_manifest_invalid",
                    (
                        f"Manifest {field_name} must be "
                        f"{expected_value!r}."
                    ),
                    422
                )

        for field_name in (
            "tdoa_request_id",
            "node_id",
            "recording_id",
        ):

            if str(manifest.get(field_name, "")).strip() != identity[field_name]:
                raise UploadValidationError(
                    "upload_manifest_identity_mismatch",
                    f"Manifest {field_name} does not match metadata.",
                    422
                )

        filename = self._required_identity(
            manifest.get("filename"),
            "upload_manifest.filename",
            UploadValidationError
        )

        if wav_filename and filename != str(wav_filename):
            raise UploadValidationError(
                "upload_filename_mismatch",
                "Manifest filename does not match the multipart WAV filename.",
                422
            )

        byte_count = self._strict_int(
            manifest.get("byte_count"),
            "upload_manifest.byte_count"
        )

        if byte_count < 1 or byte_count > self.max_wav_bytes:
            raise UploadValidationError(
                "upload_byte_count_invalid",
                "Manifest byte_count is outside the configured WAV limit.",
                422
            )

        sha256 = str(
            manifest.get(
                "sha256",
                ""
            )
        ).strip().lower()

        if not SHA256_PATTERN.fullmatch(sha256):
            raise UploadValidationError(
                "upload_checksum_invalid",
                "Manifest sha256 is not a 64-character hexadecimal digest.",
                422
            )

        return {
            "byte_count": byte_count,
            "sha256": sha256,
            "filename": filename
        }

    def _validate_recording_event(
        self,
        metadata: dict,
        payload: dict,
        expected: dict
    ):

        if metadata.get("event_type") != "TDOA_RECORDING":
            raise UploadValidationError(
                "upload_event_type_invalid",
                "Uploaded metadata event_type must be TDOA_RECORDING.",
                422
            )

        status = str(
            (
                payload.get("status")
                or metadata.get("status")
                or ""
            )
        ).strip().lower()

        if status != "success":
            raise UploadValidationError(
                "upload_recording_status_invalid",
                "Only successful TDOA_RECORDING metadata may upload a WAV.",
                422
            )

        requested_recording_id = payload.get(
            "requested_recording_id"
        )

        if (
            requested_recording_id not in (None, "")
            and str(requested_recording_id) != expected["recording_id"]
        ):
            raise UploadValidationError(
                "upload_requested_recording_mismatch",
                "requested_recording_id does not match the request.",
                422
            )

    def _validate_timing_schema(
        self,
        payload: dict
    ):

        missing_fields = [
            field_name
            for field_name in self.required_timing_fields
            if field_name not in payload
        ]

        if missing_fields:
            raise UploadValidationError(
                "upload_timing_schema_missing",
                (
                    "TDOA recording timing fields are missing: "
                    + ", ".join(missing_fields)
                ),
                422
            )

        if not isinstance(
            payload.get("continuous_stream"),
            bool
        ):
            raise UploadValidationError(
                "upload_timing_schema_invalid",
                "continuous_stream must be boolean.",
                422
            )

        if not str(
            payload.get("recording_engine") or ""
        ).strip():
            raise UploadValidationError(
                "upload_timing_schema_invalid",
                "recording_engine is empty.",
                422
            )

        if not str(
            payload.get("timing_state") or ""
        ).strip():
            raise UploadValidationError(
                "upload_timing_schema_invalid",
                "timing_state is empty.",
                422
            )

        if not str(
            payload.get("raw_timing_quality") or ""
        ).strip():
            raise UploadValidationError(
                "upload_timing_schema_invalid",
                "raw_timing_quality is empty.",
                422
            )

        if not isinstance(
            payload.get("timing_issues"),
            list
        ):
            raise UploadValidationError(
                "upload_timing_schema_invalid",
                "timing_issues must be a list.",
                422
            )

    # ========================================================
    # WAV VALIDATION AND STORAGE
    # ========================================================

    def _write_temporary_wav(
        self,
        wav_bytes: bytes,
        identity: dict
    ) -> Path:

        temporary_name = (
            self._safe_component(identity["tdoa_request_id"])
            + "_"
            + self._safe_component(identity["node_id"])
            + "_"
            + uuid.uuid4().hex
            + ".part"
        )

        temporary_path = self.temp_dir / temporary_name

        with temporary_path.open(
            "xb"
        ) as file:

            file.write(
                wav_bytes
            )

            file.flush()
            os.fsync(
                file.fileno()
            )

        return temporary_path

    def _validate_wav_file(
        self,
        wav_path: Path,
        payload: dict
    ) -> dict:

        try:

            with wave.open(
                str(wav_path),
                "rb"
            ) as wav_file:

                channels = wav_file.getnchannels()
                sample_width_bytes = wav_file.getsampwidth()
                sample_rate_hz = wav_file.getframerate()
                frame_count = wav_file.getnframes()
                compression_type = wav_file.getcomptype()

                expected_pcm_bytes = (
                    frame_count
                    * channels
                    * sample_width_bytes
                )

                actual_pcm_bytes = 0

                while True:

                    frames = wav_file.readframes(
                        65536
                    )

                    if not frames:
                        break

                    actual_pcm_bytes += len(
                        frames
                    )

        except (
            EOFError,
            wave.Error
        ) as error:

            raise UploadValidationError(
                "upload_wav_malformed",
                f"WAV is not readable: {error}.",
                422
            ) from error

        if compression_type != "NONE":
            raise UploadValidationError(
                "upload_wav_compression_invalid",
                "WAV must contain uncompressed PCM audio.",
                422
            )

        if channels not in self.allowed_channels:
            raise UploadValidationError(
                "upload_wav_channels_invalid",
                f"WAV channels are not allowed: {channels}.",
                422
            )

        if sample_width_bytes not in self.allowed_sample_width_bytes:
            raise UploadValidationError(
                "upload_wav_sample_width_invalid",
                (
                    "WAV sample width is not allowed: "
                    f"{sample_width_bytes} bytes."
                ),
                422
            )

        if sample_rate_hz not in self.allowed_sample_rates_hz:
            raise UploadValidationError(
                "upload_wav_sample_rate_invalid",
                f"WAV sample rate is not allowed: {sample_rate_hz} Hz.",
                422
            )

        if frame_count < 1:
            raise UploadValidationError(
                "upload_wav_frame_count_invalid",
                "WAV contains no audio frames.",
                422
            )

        if actual_pcm_bytes != expected_pcm_bytes:
            raise UploadValidationError(
                "upload_wav_truncated",
                (
                    f"WAV declared {expected_pcm_bytes} PCM bytes but "
                    f"contained {actual_pcm_bytes}."
                ),
                422
            )

        metadata_channels = self._strict_int(
            payload.get("channels"),
            "payload.channels"
        )

        metadata_sample_rate = self._strict_int(
            payload.get("sample_rate"),
            "payload.sample_rate"
        )

        metadata_frame_count = payload.get(
            "frame_count"
        )

        if metadata_frame_count is None:
            metadata_frame_count = payload.get(
                "guarded_frame_count"
            )

        metadata_frame_count = self._strict_int(
            metadata_frame_count,
            "payload.frame_count"
        )

        if metadata_channels != channels:
            raise UploadValidationError(
                "upload_wav_channels_mismatch",
                "Metadata channels do not match the WAV header.",
                422
            )

        if metadata_sample_rate != sample_rate_hz:
            raise UploadValidationError(
                "upload_wav_sample_rate_mismatch",
                "Metadata sample_rate does not match the WAV header.",
                422
            )

        if metadata_frame_count != frame_count:
            raise UploadValidationError(
                "upload_wav_frame_count_mismatch",
                "Metadata frame_count does not match the WAV header.",
                422
            )

        guarded_frame_count = payload.get(
            "guarded_frame_count"
        )

        if (
            guarded_frame_count is not None
            and self._strict_int(
                guarded_frame_count,
                "payload.guarded_frame_count"
            ) != frame_count
        ):
            raise UploadValidationError(
                "upload_wav_guarded_frame_count_mismatch",
                "guarded_frame_count does not match the WAV header.",
                422
            )

        guarded_start = self._strict_int(
            payload.get(
                "guarded_stream_start_sample"
            ),
            "payload.guarded_stream_start_sample"
        )

        guarded_end = self._strict_int(
            payload.get(
                "guarded_stream_end_sample_exclusive"
            ),
            "payload.guarded_stream_end_sample_exclusive"
        )

        if guarded_end - guarded_start != frame_count:
            raise UploadValidationError(
                "upload_timing_frame_range_mismatch",
                (
                    "Guarded stream sample range does not equal the "
                    "WAV frame count."
                ),
                422
            )

        return {
            "channels": channels,
            "sample_width_bytes": sample_width_bytes,
            "sample_rate_hz": sample_rate_hz,
            "frame_count": frame_count,
            "duration_seconds": (
                frame_count
                / float(sample_rate_hz)
            ),
            "compression_type": compression_type
        }

    def _accepted_path(
        self,
        identity: dict
    ) -> Path:

        return (
            self.storage_dir
            / self._safe_component(
                identity["tdoa_request_id"]
            )
            / self._safe_component(
                identity["node_id"]
            )
            / (
                self._safe_component(
                    identity["recording_id"]
                )
                + ".wav"
            )
        )

    # ========================================================
    # RECEIPT AND EVENT BUILDING
    # ========================================================

    def _build_receipt(
        self,
        identity: dict,
        byte_count: int,
        sha256: str,
        accepted_path: Path,
        wav_properties: dict,
        validated_at_utc: str
    ) -> dict:

        return {
            "accepted": True,
            "status": "accepted",
            "schema_version": 1,
            "tdoa_request_id": identity["tdoa_request_id"],
            "request_id": identity["tdoa_request_id"],
            "node_id": identity["node_id"],
            "recording_id": identity["recording_id"],
            "byte_count": byte_count,
            "wav_byte_count": byte_count,
            "sha256": sha256,
            "wav_sha256": sha256,
            "server_wav_path": str(accepted_path),
            "sample_rate_hz": wav_properties["sample_rate_hz"],
            "channels": wav_properties["channels"],
            "sample_width_bytes": wav_properties[
                "sample_width_bytes"
            ],
            "frame_count": wav_properties["frame_count"],
            "validated_at_utc": validated_at_utc
        }

    def _build_server_recording_event(
        self,
        metadata: dict,
        payload: dict,
        identity: dict,
        accepted_path: Path,
        byte_count: int,
        sha256: str,
        wav_properties: dict,
        validated_at_utc: str
    ) -> dict:

        event = copy.deepcopy(
            metadata
        )

        server_path = str(
            accepted_path
        )

        server_payload = copy.deepcopy(
            payload
        )

        node_file_references = {
            field_name: server_payload.get(
                field_name
            )
            for field_name in (
                "recording_path",
                "wav_path",
                "guarded_wav_path",
                "selected_wav_path",
                "core_wav_path",
                "metadata_path",
            )
            if server_payload.get(field_name) not in (None, "")
        }

        server_payload.update({
            "status": "success",
            "failure_reason": None,
            "failure_detail": None,
            "recording_path": server_path,
            "wav_path": server_path,
            "guarded_wav_path": server_path,
            "selected_wav_path": server_path,
            "server_wav_path": server_path,
            "node_file_references": node_file_references,
            "server_validation": {
                "schema_version": 1,
                "validated_at_utc": validated_at_utc,
                "byte_count": byte_count,
                "sha256": sha256,
                "wav": copy.deepcopy(wav_properties),
                "timing_schema_present": True
            }
        })

        event.update({
            "event_type": "TDOA_RECORDING",
            "target": "tdoa",
            "status": "success",
            "failure_reason": None,
            "tdoa_request_id": identity["tdoa_request_id"],
            "request_id": identity["tdoa_request_id"],
            "node_id": identity["node_id"],
            "recording_id": identity["recording_id"],
            "recording_path": server_path,
            "wav_path": server_path,
            "guarded_wav_path": server_path,
            "selected_wav_path": server_path,
            "server_wav_path": server_path,
            "payload": server_payload
        })

        return event

    # ========================================================
    # HELPERS
    # ========================================================

    def _registration_result(
        self,
        request: dict,
        duplicate: bool
    ) -> dict:

        return {
            "tdoa_request_id": request["tdoa_request_id"],
            "token": request["token"],
            "target_nodes": list(
                request["target_nodes"]
            ),
            "created_at_utc": request["created_at_utc"],
            "expires_in_seconds": max(
                0.0,
                request["expires_monotonic"]
                - time.monotonic()
            ),
            "duplicate": bool(duplicate)
        }

    def _prune_expired_locked(
        self,
        now_monotonic: float
    ):

        expired_request_ids = [
            request_id
            for request_id, request in self._requests.items()
            if now_monotonic > request["expires_monotonic"]
        ]

        for request_id in expired_request_ids:
            self._remove_request_locked(
                request_id
            )

    def _remove_request_locked(
        self,
        request_id: str
    ):

        self._requests.pop(
            request_id,
            None
        )

        accepted_keys = [
            upload_key
            for upload_key in self._accepted_uploads
            if upload_key[0] == request_id
        ]

        for upload_key in accepted_keys:
            self._accepted_uploads.pop(
                upload_key,
                None
            )

    def _normalize_target_nodes(
        self,
        target_nodes
    ) -> list:

        if isinstance(target_nodes, str):
            raw_nodes = [target_nodes]
        elif isinstance(target_nodes, (list, tuple, set)):
            raw_nodes = list(target_nodes)
        else:
            return []

        normalized = []
        seen = set()

        for raw_node_id in raw_nodes:

            node_id = str(
                raw_node_id
            ).strip()

            if not node_id or node_id in seen:
                continue

            seen.add(
                node_id
            )

            normalized.append(
                node_id
            )

        return normalized

    def _required_identity(
        self,
        value,
        field_name: str,
        error_class=ValueError
    ) -> str:

        if value is None:

            if error_class is UploadValidationError:
                raise error_class(
                    "upload_identity_missing",
                    f"{field_name} is missing.",
                    422
                )

            raise error_class(
                f"{field_name} is missing."
            )

        normalized = str(
            value
        ).strip()

        if not normalized:

            if error_class is UploadValidationError:
                raise error_class(
                    "upload_identity_missing",
                    f"{field_name} is empty.",
                    422
                )

            raise error_class(
                f"{field_name} is empty."
            )

        if len(normalized) > 256:

            if error_class is UploadValidationError:
                raise error_class(
                    "upload_identity_invalid",
                    f"{field_name} is too long.",
                    422
                )

            raise error_class(
                f"{field_name} is too long."
            )

        return normalized

    def _strict_int(
        self,
        value,
        field_name: str
    ) -> int:

        if isinstance(value, bool):
            raise UploadValidationError(
                "upload_metadata_invalid",
                f"{field_name} must be an integer.",
                422
            )

        try:
            converted = int(value)
        except (TypeError, ValueError) as error:
            raise UploadValidationError(
                "upload_metadata_invalid",
                f"{field_name} must be an integer.",
                422
            ) from error

        return converted

    def _positive_int(
        self,
        value,
        field_name: str
    ) -> int:

        converted = int(
            value
        )

        if converted < 1:
            raise ValueError(
                f"{field_name} must be greater than zero."
            )

        return converted

    def _positive_float(
        self,
        value,
        field_name: str
    ) -> float:

        converted = float(
            value
        )

        if converted <= 0.0:
            raise ValueError(
                f"{field_name} must be greater than zero."
            )

        return converted

    def _positive_int_set(
        self,
        values,
        field_name: str
    ) -> set:

        if not isinstance(values, (list, tuple, set)):
            raise ValueError(
                f"{field_name} must be a list."
            )

        normalized = {
            self._positive_int(
                value,
                field_name
            )
            for value in values
        }

        if not normalized:
            raise ValueError(
                f"{field_name} must not be empty."
            )

        return normalized

    def _safe_component(
        self,
        value: str
    ) -> str:

        original = str(
            value
        )

        safe = SAFE_COMPONENT_PATTERN.sub(
            "_",
            original
        ).strip(
            "._"
        )

        if not safe:
            safe = "identity"

        if safe != original or len(safe) > 96:

            digest = hashlib.sha256(
                original.encode(
                    "utf-8"
                )
            ).hexdigest()[:12]

            safe = (
                safe[:80]
                + "_"
                + digest
            )

        return safe

    def _rejection(
        self,
        reason: str,
        detail: str,
        http_status: int
    ) -> dict:

        receipt = {
            "accepted": False,
            "status": "rejected",
            "schema_version": 1,
            "failure_reason": str(reason),
            "failure_detail": str(detail)
        }

        return {
            "accepted": False,
            "success": False,
            "idempotent": False,
            "publish_events": False,
            "http_status": int(http_status),
            "receipt": receipt
        }

    def _utc_now(
        self
    ) -> str:

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
