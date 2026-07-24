# ============================================================
# tdoa_upload_client.py
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
#   Upload one guarded TDOA WAV and its event metadata to the server through
#   a request-scoped binary HTTP transaction.
#
# Expected config source:
#   TDOA_REQUEST payload
#
# Expected config section:
#   payload["upload"]
#
# Does:
#   - Validate request-scoped upload instructions
#   - Validate the guarded WAV path
#   - Calculate the exact WAV byte count and SHA-256
#   - Build multipart/form-data metadata and WAV sections
#   - Stream the WAV to the server without loading it all into memory
#   - Read and validate the server JSON receipt
#   - Return a structured success or failure result
#
# Does NOT:
#   - Subscribe to the event bus
#   - Publish events
#   - Decide whether an event should use HTTP or UDP
#   - Cache upload instructions
#   - Retry uploads
#   - Delete or modify recordings
#   - Validate TDOA timing quality
#   - Decide whether the server has a complete recording set
#
# Owner:
#   sender_manager.py
#
# ============================================================

from __future__ import annotations

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import hashlib
import http.client
import json
import logging
import socket
import uuid

from pathlib import Path
from typing import BinaryIO


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_CHUNK_SIZE = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RECEIPT_BYTES = 64 * 1024

ACCEPTED_RECEIPT_STATUSES = {
    "accepted",
    "ok",
    "success",
}


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class TDOAUploadClient:
    """
    Stream one guarded WAV to a request-scoped server endpoint.

    The client returns dictionaries rather than raising transport errors so
    CommunicationDispatcher can convert every failure into an explicit
    TDOA_RECORDING failure event on the existing UDP path.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_receipt_bytes: int = DEFAULT_MAX_RECEIPT_BYTES
    ):

        self.chunk_size = max(
            1024,
            int(chunk_size)
        )

        self.max_receipt_bytes = max(
            1024,
            int(max_receipt_bytes)
        )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def upload(
        self,
        event_metadata: dict,
        wav_path,
        upload_instructions: dict
    ) -> dict:
        """
        Upload one WAV and return a structured transaction result.
        """

        instructions_result = self._normalize_instructions(
            upload_instructions
        )

        if not instructions_result["success"]:

            return instructions_result

        instructions = instructions_result[
            "instructions"
        ]

        identity_result = self._extract_identity(
            event_metadata
        )

        if not identity_result["success"]:

            return identity_result

        identity = identity_result[
            "identity"
        ]

        path_result = self._validate_wav_path(
            wav_path
        )

        if not path_result["success"]:

            return path_result

        guarded_path = path_result[
            "wav_path"
        ]

        connection = None

        try:

            with guarded_path.open(
                "rb"
            ) as wav_file:

                wav_byte_count, wav_sha256 = (
                    self._measure_wav(
                        wav_file
                    )
                )

                metadata = self._build_upload_metadata(
                    event_metadata=event_metadata,
                    identity=identity,
                    wav_path=guarded_path,
                    wav_byte_count=wav_byte_count,
                    wav_sha256=wav_sha256
                )

                metadata_bytes = json.dumps(
                    metadata,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True
                ).encode(
                    "utf-8"
                )

                multipart = self._build_multipart_sections(
                    metadata_bytes=metadata_bytes,
                    wav_path=guarded_path,
                    wav_byte_count=wav_byte_count
                )

                connection = self._build_connection(
                    instructions
                )

                response = self._send_request(
                    connection=connection,
                    instructions=instructions,
                    multipart=multipart,
                    wav_file=wav_file
                )

                receipt_result = self._read_receipt(
                    response=response,
                    identity=identity,
                    wav_byte_count=wav_byte_count,
                    wav_sha256=wav_sha256
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
                    "wav_byte_count": wav_byte_count,
                    "wav_sha256": wav_sha256,
                    "wav_filename": guarded_path.name
                }

        except socket.timeout as error:

            return self._failure(
                reason="upload_timeout",
                detail=str(error) or "The HTTP upload timed out."
            )

        except (
            ConnectionError,
            http.client.HTTPException,
            OSError
        ) as error:

            return self._failure(
                reason="upload_connection_failed",
                detail=str(error)
            )

        except (
            TypeError,
            ValueError
        ) as error:

            return self._failure(
                reason="upload_metadata_invalid",
                detail=str(error)
            )

        except Exception as error:

            logging.exception(
                "[TDOAUploadClient] Unexpected upload failure."
            )

            return self._failure(
                reason="upload_failed",
                detail=str(error)
            )

        finally:

            if connection is not None:

                try:

                    connection.close()

                except Exception:

                    pass

    # ========================================================
    # INSTRUCTION VALIDATION
    # ========================================================

    def _normalize_instructions(
        self,
        upload_instructions
    ) -> dict:

        if not isinstance(
            upload_instructions,
            dict
        ):

            return self._failure(
                reason="upload_instructions_missing",
                detail="TDOA_REQUEST did not provide upload instructions."
            )

        scheme = str(
            upload_instructions.get(
                "scheme",
                "http"
            )
        ).strip().lower()

        if scheme not in (
            "http",
            "https"
        ):

            return self._failure(
                reason="upload_instruction_invalid",
                detail=f"Unsupported upload scheme: {scheme!r}."
            )

        host = upload_instructions.get(
            "host"
        )

        if not isinstance(host, str) or not host.strip():

            return self._failure(
                reason="upload_instruction_invalid",
                detail="Upload host is missing."
            )

        host = host.strip()

        try:

            port = int(
                upload_instructions.get(
                    "port"
                )
            )

        except (
            TypeError,
            ValueError
        ):

            return self._failure(
                reason="upload_instruction_invalid",
                detail="Upload port is missing or invalid."
            )

        if not 1 <= port <= 65535:

            return self._failure(
                reason="upload_instruction_invalid",
                detail=f"Upload port is outside 1-65535: {port}."
            )

        path = upload_instructions.get(
            "path"
        )

        if not isinstance(path, str) or not path.strip():

            return self._failure(
                reason="upload_instruction_invalid",
                detail="Upload path is missing."
            )

        path = path.strip()

        if not path.startswith("/"):

            path = "/" + path

        token = upload_instructions.get(
            "token"
        )

        if not isinstance(token, str) or not token:

            return self._failure(
                reason="upload_instruction_invalid",
                detail="Upload request token is missing."
            )

        try:

            timeout_seconds = float(
                upload_instructions.get(
                    "timeout_seconds",
                    DEFAULT_TIMEOUT_SECONDS
                )
            )

        except (
            TypeError,
            ValueError
        ):

            return self._failure(
                reason="upload_instruction_invalid",
                detail="Upload timeout is invalid."
            )

        if timeout_seconds <= 0.0:

            return self._failure(
                reason="upload_instruction_invalid",
                detail="Upload timeout must be greater than zero."
            )

        return {
            "success": True,
            "instructions": {
                "scheme": scheme,
                "host": host,
                "port": port,
                "path": path,
                "token": token,
                "timeout_seconds": timeout_seconds
            }
        }

    # ========================================================
    # WAV VALIDATION
    # ========================================================

    def _validate_wav_path(
        self,
        wav_path
    ) -> dict:

        if wav_path in (
            None,
            ""
        ):

            return self._failure(
                reason="upload_wav_path_missing",
                detail="Successful TDOA_RECORDING has no guarded WAV path."
            )

        guarded_path = Path(
            str(wav_path)
        )

        if not guarded_path.is_file():

            return self._failure(
                reason="upload_wav_not_found",
                detail=str(guarded_path)
            )

        return {
            "success": True,
            "wav_path": guarded_path
        }

    def _measure_wav(
        self,
        wav_file: BinaryIO
    ) -> tuple[int, str]:

        digest = hashlib.sha256()
        byte_count = 0

        wav_file.seek(
            0
        )

        while True:

            chunk = wav_file.read(
                self.chunk_size
            )

            if not chunk:

                break

            byte_count += len(
                chunk
            )

            digest.update(
                chunk
            )

        wav_file.seek(
            0
        )

        return (
            byte_count,
            digest.hexdigest()
        )

    # ========================================================
    # METADATA
    # ========================================================

    def _extract_identity(
        self,
        event_metadata
    ) -> dict:

        if not isinstance(
            event_metadata,
            dict
        ):

            return self._failure(
                reason="upload_metadata_invalid",
                detail="TDOA_RECORDING metadata is not a dictionary."
            )

        payload = event_metadata.get(
            "payload",
            {}
        )

        if not isinstance(
            payload,
            dict
        ):

            payload = {}

        identity = {
            "tdoa_request_id": (
                payload.get("tdoa_request_id")
                or payload.get("request_id")
                or event_metadata.get("tdoa_request_id")
                or event_metadata.get("request_id")
            ),
            "node_id": (
                payload.get("node_id")
                or event_metadata.get("node_id")
            ),
            "recording_id": (
                payload.get("recording_id")
                or event_metadata.get("recording_id")
            )
        }

        missing = [
            name
            for name, value in identity.items()
            if value in (
                None,
                ""
            )
        ]

        if missing:

            return self._failure(
                reason="upload_metadata_invalid",
                detail=(
                    "TDOA_RECORDING is missing upload identity fields: "
                    + ", ".join(missing)
                )
            )

        return {
            "success": True,
            "identity": identity
        }

    def _build_upload_metadata(
        self,
        event_metadata: dict,
        identity: dict,
        wav_path: Path,
        wav_byte_count: int,
        wav_sha256: str
    ) -> dict:

        metadata = dict(
            event_metadata
        )

        payload = metadata.get(
            "payload",
            {}
        )

        if not isinstance(
            payload,
            dict
        ):

            payload = {}

        else:

            payload = dict(
                payload
            )

        upload_manifest = {
            "schema_version": 1,
            "transport": "http_multipart",
            "field_name": "wav",
            "filename": wav_path.name,
            "content_type": "audio/wav",
            "byte_count": wav_byte_count,
            "sha256": wav_sha256,
            "tdoa_request_id": identity["tdoa_request_id"],
            "node_id": identity["node_id"],
            "recording_id": identity["recording_id"]
        }

        payload["upload_manifest"] = upload_manifest
        metadata["payload"] = payload
        metadata["upload_manifest"] = upload_manifest

        return metadata

    # ========================================================
    # MULTIPART HTTP
    # ========================================================

    def _build_multipart_sections(
        self,
        metadata_bytes: bytes,
        wav_path: Path,
        wav_byte_count: int
    ) -> dict:

        boundary = (
            "enviropulse-"
            + uuid.uuid4().hex
        )

        safe_filename = (
            wav_path.name
            .replace('"', "_")
            .replace("\r", "_")
            .replace("\n", "_")
        )

        metadata_header = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="metadata"\r\n'
            "Content-Type: application/json; charset=utf-8\r\n"
            "\r\n"
        ).encode(
            "ascii"
        )

        metadata_footer = b"\r\n"

        wav_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="wav"; '
            f'filename="{safe_filename}"\r\n'
            "Content-Type: audio/wav\r\n"
            "\r\n"
        ).encode(
            "utf-8"
        )

        closing = (
            f"\r\n--{boundary}--\r\n"
        ).encode(
            "ascii"
        )

        content_length = sum(
            (
                len(metadata_header),
                len(metadata_bytes),
                len(metadata_footer),
                len(wav_header),
                wav_byte_count,
                len(closing)
            )
        )

        return {
            "boundary": boundary,
            "metadata_header": metadata_header,
            "metadata_bytes": metadata_bytes,
            "metadata_footer": metadata_footer,
            "wav_header": wav_header,
            "closing": closing,
            "content_length": content_length
        }

    def _build_connection(
        self,
        instructions: dict
    ):

        connection_class = (
            http.client.HTTPSConnection
            if instructions["scheme"] == "https"
            else http.client.HTTPConnection
        )

        return connection_class(
            host=instructions["host"],
            port=instructions["port"],
            timeout=instructions["timeout_seconds"]
        )

    def _send_request(
        self,
        connection,
        instructions: dict,
        multipart: dict,
        wav_file: BinaryIO
    ):

        connection.putrequest(
            "POST",
            instructions["path"]
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
            str(
                multipart["content_length"]
            )
        )

        connection.putheader(
            "Accept",
            "application/json"
        )

        connection.putheader(
            "X-EnviroPulse-Upload-Token",
            instructions["token"]
        )

        connection.endheaders()

        for section_name in (
            "metadata_header",
            "metadata_bytes",
            "metadata_footer",
            "wav_header"
        ):

            connection.send(
                multipart[section_name]
            )

        while True:

            chunk = wav_file.read(
                self.chunk_size
            )

            if not chunk:

                break

            connection.send(
                chunk
            )

        connection.send(
            multipart["closing"]
        )

        return connection.getresponse()

    # ========================================================
    # RECEIPT VALIDATION
    # ========================================================

    def _read_receipt(
        self,
        response,
        identity: dict,
        wav_byte_count: int,
        wav_sha256: str
    ) -> dict:

        response_bytes = response.read(
            self.max_receipt_bytes + 1
        )

        if len(response_bytes) > self.max_receipt_bytes:

            return self._failure(
                reason="upload_receipt_invalid",
                detail="Server receipt exceeded the allowed size.",
                http_status=response.status,
                http_reason=response.reason
            )

        try:

            receipt = json.loads(
                response_bytes.decode(
                    "utf-8"
                )
            )

        except (
            UnicodeDecodeError,
            json.JSONDecodeError
        ) as error:

            if not 200 <= int(response.status) < 300:

                try:

                    rejection_detail = response_bytes.decode(
                        "utf-8",
                        errors="replace"
                    ).strip()

                except Exception:

                    rejection_detail = ""

                return self._failure(
                    reason="upload_http_rejected",
                    detail=(
                        rejection_detail
                        or str(error)
                        or "Server rejected the upload."
                    ),
                    http_status=response.status,
                    http_reason=response.reason
                )

            return self._failure(
                reason="upload_receipt_invalid",
                detail=str(error),
                http_status=response.status,
                http_reason=response.reason
            )

        if not isinstance(
            receipt,
            dict
        ):

            if not 200 <= int(response.status) < 300:

                return self._failure(
                    reason="upload_http_rejected",
                    detail="Server rejected the upload.",
                    http_status=response.status,
                    http_reason=response.reason
                )

            return self._failure(
                reason="upload_receipt_invalid",
                detail="Server receipt is not a JSON object.",
                http_status=response.status,
                http_reason=response.reason
            )

        if not 200 <= int(response.status) < 300:

            return self._failure(
                reason="upload_http_rejected",
                detail=self._get_receipt_detail(
                    receipt
                ),
                http_status=response.status,
                http_reason=response.reason,
                receipt=receipt
            )

        accepted = receipt.get(
            "accepted"
        ) is True

        receipt_status = str(
            receipt.get(
                "status",
                ""
            )
        ).strip().lower()

        if not (
            accepted
            or receipt_status in ACCEPTED_RECEIPT_STATUSES
        ):

            return self._failure(
                reason="upload_http_rejected",
                detail=self._get_receipt_detail(
                    receipt
                ),
                http_status=response.status,
                http_reason=response.reason,
                receipt=receipt
            )

        expected_values = {
            "tdoa_request_id": identity["tdoa_request_id"],
            "node_id": identity["node_id"],
            "recording_id": identity["recording_id"],
            "byte_count": wav_byte_count,
            "sha256": wav_sha256
        }

        actual_values = {
            "tdoa_request_id": (
                receipt.get("tdoa_request_id")
                or receipt.get("request_id")
            ),
            "node_id": receipt.get(
                "node_id"
            ),
            "recording_id": receipt.get(
                "recording_id"
            ),
            "byte_count": (
                receipt.get("byte_count")
                if receipt.get("byte_count") is not None
                else receipt.get("wav_byte_count")
            ),
            "sha256": (
                receipt.get("sha256")
                or receipt.get("wav_sha256")
            )
        }

        for field_name, expected_value in expected_values.items():

            actual_value = actual_values.get(
                field_name
            )

            if field_name == "byte_count":

                try:

                    actual_value = int(
                        actual_value
                    )

                except (
                    TypeError,
                    ValueError
                ):

                    actual_value = None

            if field_name == "sha256" and isinstance(
                actual_value,
                str
            ):

                actual_value = actual_value.lower()
                expected_value = str(
                    expected_value
                ).lower()

            if actual_value != expected_value:

                return self._failure(
                    reason="upload_receipt_mismatch",
                    detail=(
                        f"Receipt {field_name} mismatch: "
                        f"expected {expected_value!r}, "
                        f"received {actual_value!r}."
                    ),
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
        receipt: dict
    ) -> str:

        detail = (
            receipt.get("failure_detail")
            or receipt.get("detail")
            or receipt.get("message")
            or receipt.get("error")
            or receipt.get("failure_reason")
            or receipt.get("status")
            or "Server rejected the upload."
        )

        return str(
            detail
        )

    # ========================================================
    # RESULT HELPERS
    # ========================================================

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
