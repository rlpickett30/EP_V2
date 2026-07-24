# ============================================================
# tdoa_upload_server.py
#
# EnviroPulse V2
#
# Subsystem:
#   Server Communication
#
# Role:
#   Helper Script
#
# Purpose:
#   Own the threaded HTTP transport used to receive guarded TDOA WAV uploads.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["http_upload"]
#
# Does:
#   - Start and stop a threaded HTTP server
#   - Enforce the configured request-body ceiling before reading
#   - Parse the expected multipart metadata and WAV fields
#   - Forward normalized upload transactions to Communication Dispatcher
#   - Return JSON acceptance or rejection receipts
#
# Does NOT:
#   - Register expected uploads
#   - Validate TDOA identities or tokens
#   - Validate checksums or WAV contents
#   - Store accepted recordings
#   - Publish Event Bus events
#   - Decide TDOA quorum
#
# Owner:
#   communication_dispatcher.py
#
# ============================================================

from __future__ import annotations

import json
import logging
import socket
import threading

from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit


DEFAULT_LISTEN_HOST = "0.0.0.0"
DEFAULT_LISTEN_PORT = 5007
DEFAULT_UPLOAD_PATH = "/tdoa/upload"
DEFAULT_MAX_UPLOAD_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_METADATA_BYTES = 256 * 1024
DEFAULT_UPLOAD_TIMEOUT_SECONDS = 30.0


class ReusableThreadingHTTPServer(
    ThreadingHTTPServer
):

    allow_reuse_address = True
    daemon_threads = True


class TDOAUploadServer:
    """
    Threaded HTTP receiver for request-scoped multipart uploads.
    """

    def __init__(
        self,
        dispatcher,
        config: dict | None = None
    ):

        self.dispatcher = dispatcher

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

        self.listen_host = str(
            self.config.get(
                "listen_host",
                DEFAULT_LISTEN_HOST
            )
        ).strip()

        self.listen_port = int(
            self.config.get(
                "listen_port",
                DEFAULT_LISTEN_PORT
            )
        )

        self.upload_path = str(
            self.config.get(
                "path",
                DEFAULT_UPLOAD_PATH
            )
        ).strip()

        if not self.upload_path.startswith(
            "/"
        ):
            self.upload_path = "/" + self.upload_path

        self.advertise_host = self.config.get(
            "advertise_host"
        )

        self.scheme = str(
            self.config.get(
                "scheme",
                "http"
            )
        ).strip().lower()

        self.max_upload_bytes = int(
            self.config.get(
                "max_upload_bytes",
                DEFAULT_MAX_UPLOAD_BYTES
            )
        )

        self.max_metadata_bytes = int(
            self.config.get(
                "max_metadata_bytes",
                DEFAULT_MAX_METADATA_BYTES
            )
        )

        self.upload_timeout_seconds = float(
            self.config.get(
                "upload_timeout_seconds",
                DEFAULT_UPLOAD_TIMEOUT_SECONDS
            )
        )

        if self.scheme != "http":
            raise ValueError(
                "Block 3 TDOA upload receiver supports HTTP only."
            )

        if not self.listen_host:
            raise ValueError(
                "HTTP upload listen_host must not be empty."
            )

        if not 0 <= self.listen_port <= 65535:
            raise ValueError(
                "HTTP upload listen_port must be between 0 and 65535."
            )

        if self.max_upload_bytes < 1:
            raise ValueError(
                "HTTP upload max_upload_bytes must be positive."
            )

        if self.max_metadata_bytes < 1:
            raise ValueError(
                "HTTP upload max_metadata_bytes must be positive."
            )

        if self.upload_timeout_seconds <= 0.0:
            raise ValueError(
                "HTTP upload timeout must be positive."
            )

        self.http_server = None
        self.server_thread = None
        self.running = False

    # ========================================================
    # START / STOP
    # ========================================================

    def start(
        self
    ):

        if not self.enabled:

            logging.info(
                "[Communication] TDOA HTTP upload receiver disabled."
            )

            return

        if self.running:
            return

        handler_class = self._build_handler_class()

        self.http_server = ReusableThreadingHTTPServer(
            (
                self.listen_host,
                self.listen_port
            ),
            handler_class
        )

        self.server_thread = threading.Thread(
            target=self.http_server.serve_forever,
            name="tdoa-http-upload-server",
            daemon=True
        )

        self.server_thread.start()
        self.running = True

        logging.info(
            "[Communication] TDOA HTTP upload receiver started: "
            f"listen={self.listen_host}:{self.bound_port} "
            f"path={self.upload_path} "
            f"max_bytes={self.max_upload_bytes}"
        )

    def stop(
        self
    ):

        if self.http_server is not None:

            self.http_server.shutdown()
            self.http_server.server_close()

        if (
            self.server_thread is not None
            and self.server_thread.is_alive()
        ):

            self.server_thread.join(
                timeout=5.0
            )

        self.http_server = None
        self.server_thread = None
        self.running = False

        logging.info(
            "[Communication] TDOA HTTP upload receiver stopped."
        )

    # ========================================================
    # UPLOAD INSTRUCTIONS
    # ========================================================

    @property
    def bound_port(
        self
    ) -> int:

        if self.http_server is not None:

            return int(
                self.http_server.server_address[1]
            )

        return self.listen_port

    def build_upload_instructions(
        self,
        token: str
    ) -> dict:
        """
        Build one request ticket.

        A null host intentionally tells Node Communication to use the source
        IP of the UDP TDOA_REQUEST packet. That keeps the server address
        dynamic and selects the correct active network interface per node.
        """

        advertise_host = self.advertise_host

        if advertise_host is not None:

            advertise_host = str(
                advertise_host
            ).strip()

        if (
            not advertise_host
            or advertise_host.lower() in {
                "auto",
                "source_ip",
                "udp_source_ip",
            }
        ):

            advertise_host = None

        return {
            "scheme": self.scheme,
            "host": advertise_host,
            "port": self.bound_port,
            "path": self.upload_path,
            "token": str(token),
            "timeout_seconds": self.upload_timeout_seconds
        }

    # ========================================================
    # HTTP HANDLER
    # ========================================================

    def _build_handler_class(
        self
    ):

        owner = self

        class UploadRequestHandler(
            BaseHTTPRequestHandler
        ):

            protocol_version = "HTTP/1.1"

            def do_POST(
                self
            ):

                request_path = urlsplit(
                    self.path
                ).path

                if request_path != owner.upload_path:

                    self._send_result(
                        owner._transport_rejection(
                            "upload_path_invalid",
                            "The requested upload path does not exist.",
                            404
                        )
                    )

                    return

                length_header = self.headers.get(
                    "Content-Length"
                )

                if length_header is None:

                    self._send_result(
                        owner._transport_rejection(
                            "upload_length_missing",
                            "Content-Length is required.",
                            411
                        )
                    )

                    return

                try:
                    content_length = int(length_header)
                except (TypeError, ValueError):

                    self._send_result(
                        owner._transport_rejection(
                            "upload_length_invalid",
                            "Content-Length is invalid.",
                            400
                        )
                    )

                    return

                if content_length < 1:

                    self._send_result(
                        owner._transport_rejection(
                            "upload_body_missing",
                            "The upload body is empty.",
                            400
                        )
                    )

                    return

                if content_length > owner.max_upload_bytes:

                    self._send_result(
                        owner._transport_rejection(
                            "upload_too_large",
                            (
                                "Upload body exceeds the configured "
                                f"{owner.max_upload_bytes}-byte limit."
                            ),
                            413
                        )
                    )

                    return

                content_type = self.headers.get(
                    "Content-Type",
                    ""
                )

                try:

                    self.connection.settimeout(
                        owner.upload_timeout_seconds
                    )

                    body = owner._read_exact(
                        self.rfile,
                        content_length
                    )

                    parts = owner._parse_multipart(
                        content_type=content_type,
                        body=body
                    )

                except socket.timeout:

                    self._send_result(
                        owner._transport_rejection(
                            "upload_timeout",
                            "The upload body timed out.",
                            408
                        )
                    )

                    return

                except UploadTransportError as error:

                    self._send_result(
                        owner._transport_rejection(
                            error.reason,
                            error.detail,
                            error.http_status
                        )
                    )

                    return

                transaction = {
                    "transport": "http_multipart",
                    "received_path": request_path,
                    "source_ip": self.client_address[0],
                    "source_port": self.client_address[1],
                    "token": self.headers.get(
                        "X-EnviroPulse-Upload-Token"
                    ),
                    "metadata_bytes": parts["metadata_bytes"],
                    "metadata_content_type": parts[
                        "metadata_content_type"
                    ],
                    "wav_bytes": parts["wav_bytes"],
                    "wav_filename": parts["wav_filename"],
                    "wav_content_type": parts["wav_content_type"],
                    "request_byte_count": content_length
                }

                try:

                    result = owner.dispatcher.handle_tdoa_http_upload(
                        transaction
                    )

                except Exception as error:

                    logging.exception(
                        "[Communication] TDOA HTTP dispatcher failure."
                    )

                    result = owner._transport_rejection(
                        "upload_server_failure",
                        str(error),
                        500
                    )

                self._send_result(
                    result
                )

            def do_GET(
                self
            ):

                self._send_result(
                    owner._transport_rejection(
                        "upload_method_invalid",
                        "Only POST is supported.",
                        405
                    )
                )

            def _send_result(
                self,
                result: dict
            ):

                http_status = int(
                    result.get(
                        "http_status",
                        500
                    )
                )

                receipt = result.get(
                    "receipt"
                )

                if not isinstance(receipt, dict):

                    receipt = {
                        "accepted": False,
                        "status": "rejected",
                        "failure_reason": "upload_server_failure",
                        "failure_detail": (
                            "Server produced no structured receipt."
                        )
                    }

                    http_status = 500

                response_bytes = json.dumps(
                    receipt,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True
                ).encode(
                    "utf-8"
                )

                try:

                    self.send_response(
                        http_status
                    )

                    self.send_header(
                        "Content-Type",
                        "application/json; charset=utf-8"
                    )

                    self.send_header(
                        "Content-Length",
                        str(len(response_bytes))
                    )

                    self.send_header(
                        "Connection",
                        "close"
                    )

                    self.end_headers()

                    self.wfile.write(
                        response_bytes
                    )

                except (
                    BrokenPipeError,
                    ConnectionResetError
                ):

                    logging.warning(
                        "[Communication] Node disconnected before "
                        "the upload receipt was delivered."
                    )

                self.close_connection = True

            def log_message(
                self,
                format_string,
                *arguments
            ):

                logging.debug(
                    "[Communication] TDOA HTTP "
                    + format_string,
                    *arguments
                )

        return UploadRequestHandler

    # ========================================================
    # MULTIPART PARSING
    # ========================================================

    def _read_exact(
        self,
        stream,
        byte_count: int
    ) -> bytes:

        remaining = int(
            byte_count
        )

        chunks = []

        while remaining:

            chunk = stream.read(
                min(remaining, 64 * 1024)
            )

            if not chunk:
                raise UploadTransportError(
                    "upload_body_truncated",
                    "The HTTP request ended before Content-Length bytes arrived.",
                    400
                )

            chunks.append(
                chunk
            )

            remaining -= len(
                chunk
            )

        return b"".join(
            chunks
        )

    def _parse_multipart(
        self,
        content_type: str,
        body: bytes
    ) -> dict:

        if not isinstance(content_type, str):
            content_type = ""

        synthetic_message = (
            "Content-Type: "
            + content_type
            + "\r\n"
            + "MIME-Version: 1.0\r\n"
            + "\r\n"
        ).encode(
            "utf-8"
        ) + body

        try:

            message = BytesParser(
                policy=policy.default
            ).parsebytes(
                synthetic_message
            )

        except Exception as error:

            raise UploadTransportError(
                "upload_multipart_invalid",
                f"Multipart body could not be parsed: {error}.",
                400
            ) from error

        if (
            message.get_content_type()
            != "multipart/form-data"
            or not message.is_multipart()
        ):

            raise UploadTransportError(
                "upload_content_type_invalid",
                "Content-Type must be multipart/form-data with a boundary.",
                415
            )

        parts = {}

        for part in message.iter_parts():

            field_name = part.get_param(
                "name",
                header="content-disposition"
            )

            if field_name not in {
                "metadata",
                "wav",
            }:

                raise UploadTransportError(
                    "upload_multipart_field_invalid",
                    f"Unexpected multipart field: {field_name!r}.",
                    400
                )

            if field_name in parts:
                raise UploadTransportError(
                    "upload_multipart_field_duplicate",
                    f"Multipart field {field_name!r} was repeated.",
                    400
                )

            payload = part.get_payload(
                decode=True
            )

            if not isinstance(payload, bytes):
                raise UploadTransportError(
                    "upload_multipart_field_invalid",
                    f"Multipart field {field_name!r} has no binary payload.",
                    400
                )

            parts[field_name] = {
                "bytes": payload,
                "content_type": part.get_content_type(),
                "filename": part.get_filename()
            }

        if set(parts) != {
            "metadata",
            "wav",
        }:

            raise UploadTransportError(
                "upload_multipart_incomplete",
                "Multipart body must contain metadata and wav fields.",
                400
            )

        if len(parts["metadata"]["bytes"]) > self.max_metadata_bytes:
            raise UploadTransportError(
                "upload_metadata_too_large",
                "Multipart metadata exceeds the configured limit.",
                413
            )

        if parts["metadata"]["content_type"] != "application/json":
            raise UploadTransportError(
                "upload_metadata_content_type_invalid",
                "Multipart metadata content type must be application/json.",
                415
            )

        if parts["wav"]["content_type"] != "audio/wav":
            raise UploadTransportError(
                "upload_wav_content_type_invalid",
                "Multipart WAV content type must be audio/wav.",
                415
            )

        wav_filename = parts["wav"]["filename"]

        if not isinstance(wav_filename, str) or not wav_filename.strip():
            raise UploadTransportError(
                "upload_wav_filename_missing",
                "Multipart WAV filename is missing.",
                400
            )

        return {
            "metadata_bytes": parts["metadata"]["bytes"],
            "metadata_content_type": parts[
                "metadata"
            ]["content_type"],
            "wav_bytes": parts["wav"]["bytes"],
            "wav_filename": wav_filename,
            "wav_content_type": parts[
                "wav"
            ]["content_type"]
        }

    # ========================================================
    # TRANSPORT REJECTION
    # ========================================================

    def _transport_rejection(
        self,
        reason: str,
        detail: str,
        http_status: int
    ) -> dict:

        return {
            "accepted": False,
            "success": False,
            "publish_events": False,
            "http_status": int(http_status),
            "receipt": {
                "accepted": False,
                "status": "rejected",
                "schema_version": 1,
                "failure_reason": str(reason),
                "failure_detail": str(detail)
            }
        }


class UploadTransportError(Exception):
    """
    Structured HTTP/multipart rejection.
    """

    def __init__(
        self,
        reason: str,
        detail: str,
        http_status: int
    ):

        super().__init__(detail)

        self.reason = str(reason)
        self.detail = str(detail)
        self.http_status = int(http_status)
