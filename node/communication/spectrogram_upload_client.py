# ============================================================
# spectrogram_upload_client.py
#
# EnviroPulse V2
#
# Subsystem:
#   Node Communication
#
# Role:
#   Helper Script
#
# Purpose:
#   Upload one BirdNET spectrogram PNG and its AVIS_LITE lineage to the
#   server through verified multipart HTTP.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["http_media"] with config["udp"]["send_host"] fallback
#
# Does:
#   - Validate the node-local PNG
#   - Calculate its exact byte count and SHA-256
#   - Stream metadata and PNG bytes through multipart HTTP
#   - Validate the server receipt
#   - Return a lightweight remote image reference
#
# Does NOT:
#   - Publish events
#   - Send AVIS_LITE through UDP
#   - Generate spectrograms
#   - Delete local files
#   - Decide whether a detection should be sent
#
# Owner:
#   sender_manager.py
#
# ============================================================

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import logging
import socket
import uuid

from pathlib import Path
from typing import BinaryIO


DEFAULT_CHUNK_SIZE = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RECEIPT_BYTES = 64 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class SpectrogramUploadClient:

    def __init__(
        self,
        config: dict | None = None,
        fallback_host=None
    ):

        self.config = (
            dict(config)
            if isinstance(config, dict)
            else {}
        )

        self.enabled = bool(
            self.config.get(
                "enabled",
                True
            )
        )

        self.scheme = str(
            self.config.get(
                "scheme",
                "http"
            )
        ).strip().lower()

        self.host = (
            self.config.get("host")
            or self.config.get("upload_host")
            or fallback_host
        )

        self.port = int(
            self.config.get(
                "port",
                self.config.get(
                    "upload_port",
                    5007
                )
            )
        )

        self.path = str(
            self.config.get(
                "path",
                self.config.get(
                    "upload_path",
                    "/media/spectrogram"
                )
            )
        ).strip()

        if not self.path.startswith("/"):
            self.path = "/" + self.path

        self.timeout_seconds = float(
            self.config.get(
                "timeout_seconds",
                DEFAULT_TIMEOUT_SECONDS
            )
        )

        self.chunk_size = max(
            1024,
            int(
                self.config.get(
                    "chunk_size",
                    DEFAULT_CHUNK_SIZE
                )
            )
        )

        self.max_receipt_bytes = max(
            1024,
            int(
                self.config.get(
                    "max_receipt_bytes",
                    DEFAULT_MAX_RECEIPT_BYTES
                )
            )
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def upload(
        self,
        event_metadata: dict,
        image_path
    ) -> dict:

        configuration_error = self._validate_configuration()

        if configuration_error is not None:
            return configuration_error

        identity_result = self._extract_identity(
            event_metadata
        )

        if not identity_result["success"]:
            return identity_result

        path_result = self._validate_image_path(
            image_path
        )

        if not path_result["success"]:
            return path_result

        identity = identity_result["identity"]
        guarded_path = path_result["image_path"]
        connection = None

        try:

            with guarded_path.open("rb") as image_file:

                byte_count, sha256 = self._measure_image(
                    image_file
                )

                metadata = self._build_upload_metadata(
                    event_metadata=event_metadata,
                    identity=identity,
                    image_path=guarded_path,
                    byte_count=byte_count,
                    sha256=sha256
                )

                metadata_bytes = json.dumps(
                    metadata,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True
                ).encode("utf-8")

                multipart = self._build_multipart_sections(
                    metadata_bytes=metadata_bytes,
                    image_path=guarded_path,
                    image_byte_count=byte_count
                )

                connection = self._build_connection()

                response = self._send_request(
                    connection=connection,
                    multipart=multipart,
                    image_file=image_file
                )

                receipt_result = self._read_receipt(
                    response=response,
                    identity=identity,
                    byte_count=byte_count,
                    sha256=sha256
                )

                if not receipt_result["success"]:
                    return receipt_result

                return {
                    "success": True,
                    "accepted": True,
                    "failure_reason": None,
                    "failure_detail": None,
                    "http_status": response.status,
                    "http_reason": response.reason,
                    "receipt": receipt_result["receipt"],
                    "image_byte_count": byte_count,
                    "image_sha256": sha256,
                    "image_filename": guarded_path.name
                }

        except socket.timeout as error:

            return self._failure(
                reason="spectrogram_upload_timeout",
                detail=str(error) or "The HTTP upload timed out."
            )

        except (
            ConnectionError,
            http.client.HTTPException,
            OSError
        ) as error:

            return self._failure(
                reason="spectrogram_upload_connection_failed",
                detail=str(error)
            )

        except (
            TypeError,
            ValueError
        ) as error:

            return self._failure(
                reason="spectrogram_upload_metadata_invalid",
                detail=str(error)
            )

        except Exception as error:

            logging.exception(
                "[SpectrogramUploadClient] Unexpected upload failure."
            )

            return self._failure(
                reason="spectrogram_upload_failed",
                detail=str(error)
            )

        finally:

            if connection is not None:

                try:
                    connection.close()
                except Exception:
                    pass

    # ========================================================
    # VALIDATION
    # ========================================================

    def _validate_configuration(
        self
    ):

        if not self.enabled:
            return self._failure(
                reason="spectrogram_upload_disabled",
                detail="HTTP media upload is disabled."
            )

        if self.scheme not in {
            "http",
            "https",
        }:
            return self._failure(
                reason="spectrogram_upload_configuration_invalid",
                detail=f"Unsupported upload scheme: {self.scheme!r}."
            )

        if not isinstance(self.host, str) or not self.host.strip():
            return self._failure(
                reason="spectrogram_upload_configuration_invalid",
                detail="The server upload host is missing."
            )

        if not 1 <= self.port <= 65535:
            return self._failure(
                reason="spectrogram_upload_configuration_invalid",
                detail="The server upload port is invalid."
            )

        if self.timeout_seconds <= 0.0:
            return self._failure(
                reason="spectrogram_upload_configuration_invalid",
                detail="The upload timeout must be positive."
            )

        return None

    def _extract_identity(
        self,
        event_metadata
    ) -> dict:

        if not isinstance(event_metadata, dict):
            return self._failure(
                reason="spectrogram_upload_metadata_invalid",
                detail="AVIS_LITE metadata is not a dictionary."
            )

        payload = event_metadata.get(
            "payload",
            {}
        )

        if not isinstance(payload, dict):
            payload = {}

        identity = {
            "node_id": (
                payload.get("node_id")
                or event_metadata.get("node_id")
                or event_metadata.get("source")
            ),
            "recording_id": (
                payload.get("recording_id")
                or event_metadata.get("recording_id")
            ),
            "birdnet_event_id": (
                payload.get("birdnet_event_id")
                or event_metadata.get("birdnet_event_id")
            )
        }

        missing = [
            name
            for name, value in identity.items()
            if value in (None, "")
        ]

        if missing:
            return self._failure(
                reason="spectrogram_upload_metadata_invalid",
                detail=(
                    "AVIS_LITE is missing spectrogram identity fields: "
                    + ", ".join(missing)
                )
            )

        return {
            "success": True,
            "identity": {
                key: str(value)
                for key, value in identity.items()
            }
        }

    def _validate_image_path(
        self,
        image_path
    ) -> dict:

        if image_path in (None, ""):
            return self._failure(
                reason="spectrogram_path_missing",
                detail="AVIS_LITE has no node-local spectrogram path."
            )

        guarded_path = Path(
            str(image_path)
        )

        if not guarded_path.is_file():
            return self._failure(
                reason="spectrogram_file_not_found",
                detail=str(guarded_path)
            )

        try:
            signature = guarded_path.read_bytes()[:len(PNG_SIGNATURE)]
        except OSError as error:
            return self._failure(
                reason="spectrogram_file_unreadable",
                detail=str(error)
            )

        if signature != PNG_SIGNATURE:
            return self._failure(
                reason="spectrogram_file_invalid",
                detail="The spectrogram file is not a PNG."
            )

        return {
            "success": True,
            "image_path": guarded_path
        }

    def _measure_image(
        self,
        image_file: BinaryIO
    ) -> tuple[int, str]:

        digest = hashlib.sha256()
        byte_count = 0

        image_file.seek(0)

        while True:

            chunk = image_file.read(
                self.chunk_size
            )

            if not chunk:
                break

            byte_count += len(chunk)
            digest.update(chunk)

        image_file.seek(0)

        return byte_count, digest.hexdigest()

    # ========================================================
    # METADATA
    # ========================================================

    def _build_upload_metadata(
        self,
        event_metadata: dict,
        identity: dict,
        image_path: Path,
        byte_count: int,
        sha256: str
    ) -> dict:

        metadata = copy.deepcopy(
            event_metadata
        )

        payload = metadata.get(
            "payload",
            {}
        )

        if not isinstance(payload, dict):
            payload = {}

        spectrogram = payload.get(
            "spectrogram",
            {}
        )

        if not isinstance(spectrogram, dict):
            spectrogram = {}
        else:
            spectrogram = dict(spectrogram)

        for private_field in (
            "local_path",
            "image_png_b64",
            "spectrogram_png_b64",
        ):
            spectrogram.pop(
                private_field,
                None
            )

        manifest = {
            "schema_version": 1,
            "transport": "http_multipart",
            "field_name": "image",
            "filename": image_path.name,
            "content_type": "image/png",
            "byte_count": byte_count,
            "sha256": sha256,
            "node_id": identity["node_id"],
            "recording_id": identity["recording_id"],
            "birdnet_event_id": identity["birdnet_event_id"]
        }

        spectrogram["upload_manifest"] = manifest
        payload["spectrogram"] = spectrogram
        metadata["payload"] = payload
        metadata["spectrogram_upload_manifest"] = manifest

        return metadata

    # ========================================================
    # MULTIPART HTTP
    # ========================================================

    def _build_multipart_sections(
        self,
        metadata_bytes: bytes,
        image_path: Path,
        image_byte_count: int
    ) -> dict:

        boundary = "enviropulse-" + uuid.uuid4().hex

        safe_filename = (
            image_path.name
            .replace('"', "_")
            .replace("\r", "_")
            .replace("\n", "_")
        )

        metadata_header = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="metadata"\r\n'
            "Content-Type: application/json; charset=utf-8\r\n"
            "\r\n"
        ).encode("ascii")

        metadata_footer = b"\r\n"

        image_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; '
            f'filename="{safe_filename}"\r\n'
            "Content-Type: image/png\r\n"
            "\r\n"
        ).encode("utf-8")

        closing = (
            f"\r\n--{boundary}--\r\n"
        ).encode("ascii")

        content_length = sum(
            (
                len(metadata_header),
                len(metadata_bytes),
                len(metadata_footer),
                len(image_header),
                image_byte_count,
                len(closing)
            )
        )

        return {
            "boundary": boundary,
            "metadata_header": metadata_header,
            "metadata_bytes": metadata_bytes,
            "metadata_footer": metadata_footer,
            "image_header": image_header,
            "closing": closing,
            "content_length": content_length
        }

    def _build_connection(
        self
    ):

        connection_class = (
            http.client.HTTPSConnection
            if self.scheme == "https"
            else http.client.HTTPConnection
        )

        return connection_class(
            host=self.host.strip(),
            port=self.port,
            timeout=self.timeout_seconds
        )

    def _send_request(
        self,
        connection,
        multipart: dict,
        image_file: BinaryIO
    ):

        connection.putrequest(
            "POST",
            self.path
        )

        connection.putheader(
            "Content-Type",
            (
                "multipart/form-data; boundary="
                + multipart["boundary"]
            )
        )

        connection.putheader(
            "Content-Length",
            str(multipart["content_length"])
        )

        connection.putheader(
            "Accept",
            "application/json"
        )

        connection.endheaders()

        for section_name in (
            "metadata_header",
            "metadata_bytes",
            "metadata_footer",
            "image_header",
        ):
            connection.send(
                multipart[section_name]
            )

        while True:

            chunk = image_file.read(
                self.chunk_size
            )

            if not chunk:
                break

            connection.send(chunk)

        connection.send(
            multipart["closing"]
        )

        return connection.getresponse()

    # ========================================================
    # RECEIPT
    # ========================================================

    def _read_receipt(
        self,
        response,
        identity: dict,
        byte_count: int,
        sha256: str
    ) -> dict:

        response_bytes = response.read(
            self.max_receipt_bytes + 1
        )

        if len(response_bytes) > self.max_receipt_bytes:
            return self._failure(
                reason="spectrogram_upload_receipt_invalid",
                detail="Server receipt exceeded the allowed size.",
                http_status=response.status,
                http_reason=response.reason
            )

        try:
            receipt = json.loads(
                response_bytes.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError
        ) as error:
            return self._failure(
                reason="spectrogram_upload_receipt_invalid",
                detail=str(error),
                http_status=response.status,
                http_reason=response.reason
            )

        if (
            not isinstance(receipt, dict)
            or not 200 <= int(response.status) < 300
            or receipt.get("accepted") is not True
        ):
            return self._failure(
                reason="spectrogram_upload_rejected",
                detail=self._get_receipt_detail(receipt),
                http_status=response.status,
                http_reason=response.reason,
                receipt=receipt
            )

        expected = {
            "node_id": identity["node_id"],
            "recording_id": identity["recording_id"],
            "birdnet_event_id": identity["birdnet_event_id"],
            "byte_count": byte_count,
            "sha256": sha256
        }

        for field_name, expected_value in expected.items():

            actual_value = receipt.get(
                field_name
            )

            if field_name == "byte_count":

                try:
                    actual_value = int(actual_value)
                except (
                    TypeError,
                    ValueError
                ):
                    actual_value = None

            if field_name == "sha256":
                actual_value = str(actual_value or "").lower()
                expected_value = str(expected_value).lower()

            if actual_value != expected_value:
                return self._failure(
                    reason="spectrogram_upload_receipt_mismatch",
                    detail=(
                        f"Receipt {field_name} mismatch: "
                        f"expected {expected_value!r}, "
                        f"received {actual_value!r}."
                    ),
                    http_status=response.status,
                    http_reason=response.reason,
                    receipt=receipt
                )

        if not receipt.get("download_url"):
            return self._failure(
                reason="spectrogram_upload_receipt_mismatch",
                detail="Receipt has no download_url.",
                http_status=response.status,
                http_reason=response.reason,
                receipt=receipt
            )

        return {
            "success": True,
            "receipt": receipt
        }

    def _get_receipt_detail(
        self,
        receipt
    ) -> str:

        if not isinstance(receipt, dict):
            return "Server rejected the spectrogram upload."

        return str(
            receipt.get("failure_detail")
            or receipt.get("detail")
            or receipt.get("message")
            or receipt.get("error")
            or receipt.get("failure_reason")
            or receipt.get("status")
            or "Server rejected the spectrogram upload."
        )

    def _failure(
        self,
        reason: str,
        detail=None,
        http_status=None,
        http_reason=None,
        receipt=None
    ) -> dict:

        return {
            "success": False,
            "accepted": False,
            "failure_reason": str(reason),
            "failure_detail": (
                None
                if detail is None
                else str(detail)
            ),
            "http_status": http_status,
            "http_reason": http_reason,
            "receipt": (
                receipt
                if isinstance(receipt, dict)
                else None
            )
        }
