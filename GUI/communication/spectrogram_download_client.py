# ============================================================
# spectrogram_download_client.py
#
# EnviroPulse V2 GUI
#
# Subsystem:
#   GUI Communication
#
# Role:
#   Helper Script
#
# Purpose:
#   Download and verify one server-hosted BirdNET spectrogram referenced by
#   SERVER_AVIS_LITE.
#
# Expected config source:
#   communication_config.json
#
# Expected config section:
#   config["http_media"]
#
# Does:
#   - Validate HTTP spectrogram references
#   - Download PNG bytes with a strict size ceiling
#   - Verify PNG signature, byte count, and SHA-256
#   - Cache the PNG atomically for the Interface
#   - Return a node-local GUI file path
#
# Does NOT:
#   - Publish events
#   - Render images
#   - Receive UDP packets
#   - Modify server events beyond returning download results
#
# Owner:
#   communication_dispatcher.py
#
# ============================================================

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from pathlib import Path


DEFAULT_CACHE_DIR = "communication/data/spectrogram_cache"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_IMAGE_BYTES = 4 * 1024 * 1024

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SAFE_MEDIA_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,240}$")


class SpectrogramDownloadClient:

    def __init__(
        self,
        config: dict | None = None
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

        self.cache_dir = Path(
            self.config.get(
                "cache_dir",
                DEFAULT_CACHE_DIR
            )
        ).expanduser().resolve()

        self.timeout_seconds = float(
            self.config.get(
                "download_timeout_seconds",
                self.config.get(
                    "timeout_seconds",
                    DEFAULT_TIMEOUT_SECONDS
                )
            )
        )

        self.max_image_bytes = int(
            self.config.get(
                "max_image_bytes",
                DEFAULT_MAX_IMAGE_BYTES
            )
        )

    def download(
        self,
        spectrogram: dict
    ) -> dict:

        if not self.enabled:
            return self._failure(
                "spectrogram_download_disabled",
                "HTTP media download is disabled."
            )

        if not isinstance(spectrogram, dict):
            return self._failure(
                "spectrogram_reference_invalid",
                "Spectrogram reference is not a dictionary."
            )

        media_id = str(
            spectrogram.get(
                "media_id",
                ""
            )
        ).strip()

        if not SAFE_MEDIA_ID_PATTERN.fullmatch(
            media_id
        ):
            return self._failure(
                "spectrogram_reference_invalid",
                "Spectrogram media_id is missing or invalid."
            )

        download_url = str(
            spectrogram.get(
                "download_url",
                ""
            )
        ).strip()

        parsed_url = urllib.parse.urlsplit(
            download_url
        )

        if (
            parsed_url.scheme not in {
                "http",
                "https",
            }
            or not parsed_url.netloc
        ):
            return self._failure(
                "spectrogram_reference_invalid",
                "Spectrogram download_url is missing or invalid."
            )

        if self.timeout_seconds <= 0.0:
            return self._failure(
                "spectrogram_download_configuration_invalid",
                "Download timeout must be positive."
            )

        if self.max_image_bytes < 1:
            return self._failure(
                "spectrogram_download_configuration_invalid",
                "Maximum image size must be positive."
            )

        expected_byte_count = self._optional_int(
            spectrogram.get(
                "byte_count"
            )
        )

        expected_sha256 = str(
            spectrogram.get(
                "sha256",
                ""
            )
        ).strip().lower()

        self.cache_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        cache_path = self.cache_dir / (
            media_id + ".png"
        )

        cached_result = self._validate_cached_file(
            cache_path=cache_path,
            expected_byte_count=expected_byte_count,
            expected_sha256=expected_sha256
        )

        if cached_result is not None:
            return cached_result

        request = urllib.request.Request(
            download_url,
            headers={
                "Accept": "image/png",
                "User-Agent": "EnviroPulse-GUI/2"
            },
            method="GET"
        )

        try:

            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds
            ) as response:

                content_type = (
                    response.headers.get_content_type()
                    if response.headers is not None
                    else ""
                )

                if content_type != "image/png":
                    return self._failure(
                        "spectrogram_download_content_type_invalid",
                        (
                            "Server returned "
                            f"{content_type!r} instead of image/png."
                        )
                    )

                image_bytes = response.read(
                    self.max_image_bytes + 1
                )

        except urllib.error.HTTPError as error:
            return self._failure(
                "spectrogram_download_http_rejected",
                f"HTTP {error.code}: {error.reason}"
            )

        except (
            urllib.error.URLError,
            TimeoutError,
            OSError
        ) as error:
            return self._failure(
                "spectrogram_download_failed",
                str(error)
            )

        validation_result = self._validate_image_bytes(
            image_bytes=image_bytes,
            expected_byte_count=expected_byte_count,
            expected_sha256=expected_sha256
        )

        if not validation_result["success"]:
            return validation_result

        temporary_path = self.cache_dir / (
            "." + media_id + "." + uuid.uuid4().hex + ".tmp"
        )

        try:

            temporary_path.write_bytes(
                image_bytes
            )

            temporary_path.replace(
                cache_path
            )

        finally:

            if temporary_path.exists():

                try:
                    temporary_path.unlink()
                except OSError:
                    pass

        return {
            "success": True,
            "local_path": str(cache_path),
            "byte_count": validation_result["byte_count"],
            "sha256": validation_result["sha256"],
            "cached": False
        }

    def _validate_cached_file(
        self,
        cache_path: Path,
        expected_byte_count,
        expected_sha256: str
    ):

        if not cache_path.is_file():
            return None

        try:
            image_bytes = cache_path.read_bytes()
        except OSError:
            return None

        result = self._validate_image_bytes(
            image_bytes=image_bytes,
            expected_byte_count=expected_byte_count,
            expected_sha256=expected_sha256
        )

        if not result["success"]:
            return None

        return {
            "success": True,
            "local_path": str(cache_path),
            "byte_count": result["byte_count"],
            "sha256": result["sha256"],
            "cached": True
        }

    def _validate_image_bytes(
        self,
        image_bytes: bytes,
        expected_byte_count,
        expected_sha256: str
    ) -> dict:

        if len(image_bytes) > self.max_image_bytes:
            return self._failure(
                "spectrogram_download_too_large",
                "Downloaded PNG exceeds the configured limit."
            )

        if not image_bytes.startswith(
            PNG_SIGNATURE
        ):
            return self._failure(
                "spectrogram_download_image_invalid",
                "Downloaded data is not a PNG."
            )

        actual_byte_count = len(
            image_bytes
        )

        actual_sha256 = hashlib.sha256(
            image_bytes
        ).hexdigest()

        if (
            expected_byte_count is not None
            and actual_byte_count != expected_byte_count
        ):
            return self._failure(
                "spectrogram_download_byte_count_mismatch",
                (
                    f"Expected {expected_byte_count} bytes; "
                    f"received {actual_byte_count}."
                )
            )

        if (
            expected_sha256
            and actual_sha256 != expected_sha256
        ):
            return self._failure(
                "spectrogram_download_checksum_mismatch",
                "Downloaded PNG SHA-256 does not match AVIS_LITE."
            )

        return {
            "success": True,
            "byte_count": actual_byte_count,
            "sha256": actual_sha256
        }

    def _optional_int(
        self,
        value
    ):

        if value in (
            None,
            ""
        ):
            return None

        try:
            return int(value)
        except (
            TypeError,
            ValueError
        ):
            return None

    def _failure(
        self,
        reason: str,
        detail: str
    ) -> dict:

        return {
            "success": False,
            "failure_reason": str(reason),
            "failure_detail": str(detail),
            "local_path": None
        }
