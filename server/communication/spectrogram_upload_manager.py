# ============================================================
# spectrogram_upload_manager.py
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
#   Validate, store, and retrieve BirdNET spectrogram PNG files transferred
#   through the Communication HTTP server.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["http_media"]
#
# Does:
#   - Validate AVIS_LITE lineage and upload manifests
#   - Verify PNG signature, byte count, and SHA-256
#   - Store PNG and metadata files atomically
#   - Accept identical retries idempotently
#   - Resolve safe media IDs for HTTP download
#   - Build structured upload receipts
#
# Does NOT:
#   - Open HTTP sockets
#   - Parse multipart bodies
#   - Publish events
#   - Promote AVIS_LITE events
#   - Generate spectrograms
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
import threading
import uuid

from datetime import datetime
from datetime import timezone
from pathlib import Path


DEFAULT_STORAGE_DIR = "media/spectrograms"
DEFAULT_MAX_METADATA_BYTES = 256 * 1024
DEFAULT_MAX_IMAGE_BYTES = 4 * 1024 * 1024

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
SAFE_COMPONENT_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
SAFE_MEDIA_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,240}$")


class SpectrogramUploadError(Exception):

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


class SpectrogramUploadManager:

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
                DEFAULT_STORAGE_DIR
            )
        ).expanduser().resolve()

        self.max_metadata_bytes = self._positive_int(
            self.config.get(
                "max_metadata_bytes",
                DEFAULT_MAX_METADATA_BYTES
            ),
            "max_metadata_bytes"
        )

        self.max_image_bytes = self._positive_int(
            self.config.get(
                "max_image_bytes",
                DEFAULT_MAX_IMAGE_BYTES
            ),
            "max_image_bytes"
        )

        self._lock = threading.RLock()

    # ========================================================
    # STORAGE
    # ========================================================

    def prepare_storage(
        self
    ):

        self.storage_dir.mkdir(
            parents=True,
            exist_ok=True
        )

    # ========================================================
    # UPLOAD
    # ========================================================

    def process_upload(
        self,
        transaction: dict
    ) -> dict:

        try:

            if not isinstance(transaction, dict):
                raise SpectrogramUploadError(
                    "spectrogram_upload_transaction_invalid",
                    "Upload transaction is not a dictionary.",
                    400
                )

            with self._lock:
                return self._process_upload_locked(
                    transaction
                )

        except SpectrogramUploadError as error:

            return self._rejection(
                reason=error.reason,
                detail=error.detail,
                http_status=error.http_status
            )

        except Exception as error:

            logging.exception(
                "[SpectrogramUploadManager] Unexpected upload failure."
            )

            return self._rejection(
                reason="spectrogram_upload_server_failure",
                detail=str(error),
                http_status=500
            )

    def _process_upload_locked(
        self,
        transaction: dict
    ) -> dict:

        metadata_bytes = transaction.get(
            "metadata_bytes"
        )

        image_bytes = transaction.get(
            "image_bytes"
        )

        if not isinstance(metadata_bytes, bytes):
            raise SpectrogramUploadError(
                "spectrogram_metadata_invalid",
                "Multipart metadata part is missing.",
                400
            )

        if len(metadata_bytes) > self.max_metadata_bytes:
            raise SpectrogramUploadError(
                "spectrogram_metadata_too_large",
                "Multipart metadata exceeds the configured limit.",
                413
            )

        if not isinstance(image_bytes, bytes):
            raise SpectrogramUploadError(
                "spectrogram_image_missing",
                "Multipart image part is missing.",
                400
            )

        if not image_bytes:
            raise SpectrogramUploadError(
                "spectrogram_image_missing",
                "Multipart image is empty.",
                400
            )

        if len(image_bytes) > self.max_image_bytes:
            raise SpectrogramUploadError(
                "spectrogram_image_too_large",
                "Spectrogram PNG exceeds the configured limit.",
                413
            )

        if not image_bytes.startswith(
            PNG_SIGNATURE
        ):
            raise SpectrogramUploadError(
                "spectrogram_image_invalid",
                "Uploaded image does not have a PNG signature.",
                415
            )

        metadata = self._decode_metadata(
            metadata_bytes
        )

        payload = metadata.get(
            "payload"
        )

        if not isinstance(payload, dict):
            raise SpectrogramUploadError(
                "spectrogram_metadata_invalid",
                "AVIS_LITE payload is missing.",
                422
            )

        if metadata.get("event_type") != "AVIS_LITE":
            raise SpectrogramUploadError(
                "spectrogram_event_type_invalid",
                "Uploaded metadata event_type must be AVIS_LITE.",
                422
            )

        identity = self._extract_identity(
            metadata=metadata,
            payload=payload
        )

        manifest = self._validate_manifest(
            metadata=metadata,
            payload=payload,
            identity=identity,
            image_filename=transaction.get(
                "image_filename"
            )
        )

        actual_byte_count = len(
            image_bytes
        )

        actual_sha256 = hashlib.sha256(
            image_bytes
        ).hexdigest()

        if manifest["byte_count"] != actual_byte_count:
            raise SpectrogramUploadError(
                "spectrogram_byte_count_mismatch",
                "Manifest byte_count does not match received PNG bytes.",
                422
            )

        if manifest["sha256"] != actual_sha256:
            raise SpectrogramUploadError(
                "spectrogram_checksum_mismatch",
                "Manifest SHA-256 does not match received PNG bytes.",
                422
            )

        media_id = self._build_media_id(
            identity=identity,
            sha256=actual_sha256
        )

        self.prepare_storage()

        image_path = self.storage_dir / (
            media_id + ".png"
        )

        metadata_path = self.storage_dir / (
            media_id + ".json"
        )

        if image_path.exists():

            existing_sha256 = hashlib.sha256(
                image_path.read_bytes()
            ).hexdigest()

            if existing_sha256 != actual_sha256:
                raise SpectrogramUploadError(
                    "spectrogram_storage_conflict",
                    "Existing media ID contains different PNG bytes.",
                    409
                )

            receipt = self._build_receipt(
                identity=identity,
                media_id=media_id,
                image_path=image_path,
                byte_count=actual_byte_count,
                sha256=actual_sha256,
                accepted_at_utc=self._utc_now(),
                idempotent=True
            )

            return {
                "accepted": True,
                "success": True,
                "idempotent": True,
                "http_status": 200,
                "receipt": receipt
            }

        temporary_image_path = self.storage_dir / (
            "." + media_id + "." + uuid.uuid4().hex + ".tmp"
        )

        temporary_metadata_path = self.storage_dir / (
            "." + media_id + "." + uuid.uuid4().hex + ".json.tmp"
        )

        accepted_at_utc = self._utc_now()

        stored_metadata = copy.deepcopy(
            metadata
        )

        stored_metadata["_spectrogram_storage"] = {
            "media_id": media_id,
            "source_ip": transaction.get(
                "source_ip"
            ),
            "byte_count": actual_byte_count,
            "sha256": actual_sha256,
            "accepted_at_utc": accepted_at_utc
        }

        try:

            temporary_image_path.write_bytes(
                image_bytes
            )

            temporary_metadata_path.write_text(
                json.dumps(
                    stored_metadata,
                    indent=4,
                    sort_keys=True
                ),
                encoding="utf-8"
            )

            os.replace(
                temporary_image_path,
                image_path
            )

            os.replace(
                temporary_metadata_path,
                metadata_path
            )

        finally:

            for temporary_path in (
                temporary_image_path,
                temporary_metadata_path,
            ):

                if temporary_path.exists():

                    try:
                        temporary_path.unlink()
                    except OSError:
                        logging.exception(
                            "[SpectrogramUploadManager] "
                            "Failed removing temporary file."
                        )

        receipt = self._build_receipt(
            identity=identity,
            media_id=media_id,
            image_path=image_path,
            byte_count=actual_byte_count,
            sha256=actual_sha256,
            accepted_at_utc=accepted_at_utc,
            idempotent=False
        )

        return {
            "accepted": True,
            "success": True,
            "idempotent": False,
            "http_status": 201,
            "receipt": receipt
        }

    # ========================================================
    # DOWNLOAD
    # ========================================================

    def get_download(
        self,
        media_id
    ) -> dict:

        normalized_media_id = str(
            media_id or ""
        ).strip()

        if not SAFE_MEDIA_ID_PATTERN.fullmatch(
            normalized_media_id
        ):
            return {
                "success": False,
                "http_status": 404,
                "failure_reason": "spectrogram_not_found",
                "failure_detail": "Spectrogram media ID is invalid."
            }

        image_path = self.storage_dir / (
            normalized_media_id + ".png"
        )

        if not image_path.is_file():
            return {
                "success": False,
                "http_status": 404,
                "failure_reason": "spectrogram_not_found",
                "failure_detail": "Spectrogram image does not exist."
            }

        try:
            image_bytes = image_path.read_bytes()
        except OSError as error:
            return {
                "success": False,
                "http_status": 500,
                "failure_reason": "spectrogram_read_failed",
                "failure_detail": str(error)
            }

        if (
            not image_bytes.startswith(PNG_SIGNATURE)
            or len(image_bytes) > self.max_image_bytes
        ):
            return {
                "success": False,
                "http_status": 500,
                "failure_reason": "spectrogram_storage_invalid",
                "failure_detail": "Stored spectrogram failed validation."
            }

        return {
            "success": True,
            "http_status": 200,
            "content_type": "image/png",
            "content": image_bytes,
            "filename": image_path.name,
            "byte_count": len(image_bytes),
            "sha256": hashlib.sha256(
                image_bytes
            ).hexdigest()
        }

    # ========================================================
    # METADATA VALIDATION
    # ========================================================

    def _decode_metadata(
        self,
        metadata_bytes: bytes
    ) -> dict:

        try:
            metadata = json.loads(
                metadata_bytes.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError
        ) as error:
            raise SpectrogramUploadError(
                "spectrogram_metadata_invalid",
                f"Metadata is not valid UTF-8 JSON: {error}.",
                400
            ) from error

        if not isinstance(metadata, dict):
            raise SpectrogramUploadError(
                "spectrogram_metadata_invalid",
                "Metadata JSON is not an object.",
                400
            )

        return metadata

    def _extract_identity(
        self,
        metadata: dict,
        payload: dict
    ) -> dict:

        identity = {
            "node_id": (
                payload.get("node_id")
                or metadata.get("node_id")
                or metadata.get("source")
            ),
            "recording_id": (
                payload.get("recording_id")
                or metadata.get("recording_id")
            ),
            "birdnet_event_id": (
                payload.get("birdnet_event_id")
                or metadata.get("birdnet_event_id")
            )
        }

        for field_name, value in identity.items():

            if value in (None, ""):
                raise SpectrogramUploadError(
                    "spectrogram_identity_missing",
                    f"AVIS_LITE is missing {field_name}.",
                    422
                )

            identity[field_name] = str(
                value
            )

        return identity

    def _validate_manifest(
        self,
        metadata: dict,
        payload: dict,
        identity: dict,
        image_filename
    ) -> dict:

        spectrogram = payload.get(
            "spectrogram"
        )

        if not isinstance(spectrogram, dict):
            raise SpectrogramUploadError(
                "spectrogram_metadata_invalid",
                "payload.spectrogram is missing.",
                422
            )

        manifest = spectrogram.get(
            "upload_manifest"
        )

        if not isinstance(manifest, dict):
            raise SpectrogramUploadError(
                "spectrogram_manifest_missing",
                "payload.spectrogram.upload_manifest is missing.",
                422
            )

        top_level_manifest = metadata.get(
            "spectrogram_upload_manifest"
        )

        if (
            top_level_manifest is not None
            and top_level_manifest != manifest
        ):
            raise SpectrogramUploadError(
                "spectrogram_manifest_conflict",
                "Top-level and payload spectrogram manifests differ.",
                422
            )

        for field_name, expected_value in (
            ("schema_version", 1),
            ("transport", "http_multipart"),
            ("field_name", "image"),
            ("content_type", "image/png"),
        ):

            if manifest.get(field_name) != expected_value:
                raise SpectrogramUploadError(
                    "spectrogram_manifest_invalid",
                    (
                        f"Manifest {field_name} must be "
                        f"{expected_value!r}."
                    ),
                    422
                )

        for field_name, expected_value in identity.items():

            if str(
                manifest.get(field_name, "")
            ) != expected_value:
                raise SpectrogramUploadError(
                    "spectrogram_manifest_identity_mismatch",
                    f"Manifest {field_name} does not match AVIS_LITE.",
                    422
                )

        filename = str(
            manifest.get(
                "filename",
                ""
            )
        ).strip()

        if not filename:
            raise SpectrogramUploadError(
                "spectrogram_filename_missing",
                "Manifest filename is missing.",
                422
            )

        if (
            image_filename
            and filename != str(image_filename)
        ):
            raise SpectrogramUploadError(
                "spectrogram_filename_mismatch",
                "Manifest filename does not match multipart image filename.",
                422
            )

        try:
            byte_count = int(
                manifest.get("byte_count")
            )
        except (
            TypeError,
            ValueError
        ) as error:
            raise SpectrogramUploadError(
                "spectrogram_byte_count_invalid",
                "Manifest byte_count is invalid.",
                422
            ) from error

        if not 1 <= byte_count <= self.max_image_bytes:
            raise SpectrogramUploadError(
                "spectrogram_byte_count_invalid",
                "Manifest byte_count is outside the configured limit.",
                422
            )

        sha256 = str(
            manifest.get(
                "sha256",
                ""
            )
        ).strip().lower()

        if not SHA256_PATTERN.fullmatch(
            sha256
        ):
            raise SpectrogramUploadError(
                "spectrogram_checksum_invalid",
                "Manifest SHA-256 is invalid.",
                422
            )

        return {
            "filename": filename,
            "byte_count": byte_count,
            "sha256": sha256
        }

    # ========================================================
    # RECEIPTS AND HELPERS
    # ========================================================

    def _build_media_id(
        self,
        identity: dict,
        sha256: str
    ) -> str:

        components = (
            self._safe_component(
                identity["node_id"],
                max_length=48
            ),
            self._safe_component(
                identity["birdnet_event_id"],
                max_length=140
            ),
            sha256[:16]
        )

        return "--".join(
            components
        )

    def _build_receipt(
        self,
        identity: dict,
        media_id: str,
        image_path: Path,
        byte_count: int,
        sha256: str,
        accepted_at_utc: str,
        idempotent: bool
    ) -> dict:

        return {
            "accepted": True,
            "status": "accepted",
            "schema_version": 1,
            "media_type": "spectrogram",
            "media_id": media_id,
            "node_id": identity["node_id"],
            "recording_id": identity["recording_id"],
            "birdnet_event_id": identity["birdnet_event_id"],
            "filename": image_path.name,
            "content_type": "image/png",
            "byte_count": byte_count,
            "sha256": sha256,
            "accepted_at_utc": accepted_at_utc,
            "idempotent": bool(idempotent)
        }

    def _rejection(
        self,
        reason: str,
        detail: str,
        http_status: int
    ) -> dict:

        return {
            "accepted": False,
            "success": False,
            "http_status": int(http_status),
            "receipt": {
                "accepted": False,
                "status": "rejected",
                "schema_version": 1,
                "media_type": "spectrogram",
                "failure_reason": str(reason),
                "failure_detail": str(detail)
            }
        }

    def _safe_component(
        self,
        value,
        max_length: int
    ) -> str:

        safe = SAFE_COMPONENT_PATTERN.sub(
            "_",
            str(value)
        ).strip("._-")

        if not safe:
            safe = "unknown"

        return safe[
            :max_length
        ]

    def _positive_int(
        self,
        value,
        field_name: str
    ) -> int:

        try:
            normalized = int(value)
        except (
            TypeError,
            ValueError
        ) as error:
            raise ValueError(
                f"{field_name} must be an integer."
            ) from error

        if normalized < 1:
            raise ValueError(
                f"{field_name} must be positive."
            )

        return normalized

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
