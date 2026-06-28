# ============================================================
# spectrogram_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   BirdNET
#
# Role:
#   Manager
#
# Purpose:
#   Generate a compact PNG spectrogram from a supplied WAV recording and
#   return a serialized payload-safe dictionary for AVIS_LITE events.
#
# Expected config source:
#   birdnet_config.json
#
# Expected config section:
#   spectrogram
#
# Does:
#   - Read WAV audio from disk
#   - Convert PCM audio into normalized mono samples
#   - Build a compact STFT spectrogram
#   - Encode the spectrogram as PNG
#   - Serialize the PNG as base64 text
#   - Return metadata needed by the GUI to decode and display the image
#   - Support classic pink / purple spectrogram coloring
#
# Does NOT:
#   - Subscribe to the event bus
#   - Publish events
#   - Run BirdNET analysis
#   - Build final AVIS_LITE events
#   - Require matplotlib, PIL, or OpenCV
#
# Owner:
#   birdnet_manager.py
#
# ============================================================

from __future__ import annotations

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import base64
import io
import struct
import wave
import zlib

from pathlib import Path
from typing import Any

# ============================================================
# IMPORT THIRD-PARTY SUPPORT LIBRARIES
# ============================================================

import numpy as np


# ============================================================
# MODULE DEFAULTS
# ============================================================

DEFAULT_CONFIG = {
    "enabled": True,
    "max_width": 240,
    "height": 96,
    "fft_size": 1024,
    "hop_length": 256,
    "max_duration_sec": 14.5,
    "min_frequency_hz": 0.0,
    "max_frequency_hz": 6000.0,
    "db_floor": 85.0,
    "gamma": 0.65,
    "black_level": 0.08,
    "color_mode": "classic",
    "max_payload_chars": 45000,
    "transport_max_payload_chars": 45000,
    "adaptive_payload_resize": True,
    "debug": True
}


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class SpectrogramManager:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        config: dict | None = None,
        debug: bool = True
    ):

        merged_config = dict(
            DEFAULT_CONFIG
        )

        if isinstance(
            config,
            dict
        ):

            merged_config.update(
                config
            )

        self.config = merged_config
        self.debug = bool(
            self.config.get(
                "debug",
                debug
            )
        )

    # ========================================================
    # DEBUG
    # ========================================================

    def log(
        self,
        message
    ):

        if self.debug:

            print(
                f"[SpectrogramManager] {message}"
            )

    # ========================================================
    # PUBLIC API
    # ========================================================

    def build_spectrogram_package(
        self,
        wav_path: Path | str
    ) -> dict:
        """
        Build a compact serialized spectrogram package.

        Returned package is safe to place inside an AVIS_LITE payload:
            {
                "available": bool,
                "encoding": "base64",
                "mime_type": "image/png",
                "image_png_b64": str,
                ...metadata...
            }
        """

        if not self.is_enabled():

            return self.build_unavailable_package(
                reason="spectrogram_disabled"
            )

        path = Path(
            wav_path
        )

        if not path.exists():

            return self.build_unavailable_package(
                reason="wav_path_missing"
            )

        try:

            samples, sample_rate, duration_sec = self.read_wav_mono(
                path
            )

            if samples.size == 0:

                return self.build_unavailable_package(
                    reason="empty_audio"
                )

            image_array = self.build_image_array(
                samples=samples,
                sample_rate=sample_rate
            )

            image_array, image_b64 = self.encode_payload_safe_image(
                image_array=image_array
            )

            height, width = image_array.shape[:2]

            package = {
                "available": True,
                "encoding": "base64",
                "mime_type": "image/png",
                "format": "png",
                "scope": "recording",
                "image_png_b64": image_b64,
                "width": int(width),
                "height": int(height),
                "sample_rate": int(sample_rate),
                "duration_sec": float(duration_sec),
                "fft_size": self.get_int(
                    "fft_size",
                    DEFAULT_CONFIG["fft_size"]
                ),
                "hop_length": self.get_int(
                    "hop_length",
                    DEFAULT_CONFIG["hop_length"]
                ),
                "min_frequency_hz": self.get_float(
                    "min_frequency_hz",
                    DEFAULT_CONFIG["min_frequency_hz"]
                ),
                "max_frequency_hz": self.get_float(
                    "max_frequency_hz",
                    DEFAULT_CONFIG["max_frequency_hz"]
                ),
                "db_floor": self.get_float(
                    "db_floor",
                    DEFAULT_CONFIG["db_floor"]
                ),
                "gamma": self.get_float(
                    "gamma",
                    DEFAULT_CONFIG["gamma"]
                ),
                "black_level": self.get_float(
                    "black_level",
                    DEFAULT_CONFIG["black_level"]
                ),
                "color_mode": self.get_string(
                    "color_mode",
                    DEFAULT_CONFIG["color_mode"]
                ),
                "payload_chars": len(image_b64)
            }

            self.log(
                (
                    "Spectrogram generated: "
                    f"{width}x{height}, "
                    f"{len(image_b64)} base64 chars, "
                    f"mode={package['color_mode']}"
                )
            )

            return package

        except Exception as error:

            self.log(
                f"Spectrogram generation failed: {error}"
            )

            return self.build_unavailable_package(
                reason="spectrogram_generation_failed",
                error=str(error)
            )

    # ========================================================
    # WAV READING
    # ========================================================

    def read_wav_mono(
        self,
        path: Path
    ) -> tuple[np.ndarray, int, float]:
        """
        Read PCM WAV audio and return normalized mono float32 samples.
        """

        with wave.open(
            str(path),
            "rb"
        ) as wav_file:

            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            frame_count = wav_file.getnframes()

            max_duration_sec = self.get_float(
                "max_duration_sec",
                DEFAULT_CONFIG["max_duration_sec"]
            )

            if max_duration_sec > 0:

                max_frames = int(
                    sample_rate * max_duration_sec
                )

                frame_count = min(
                    frame_count,
                    max_frames
                )

            raw = wav_file.readframes(
                frame_count
            )

        samples = self.decode_pcm_samples(
            raw=raw,
            sample_width=sample_width
        )

        if samples.size == 0:

            return (
                np.array(
                    [],
                    dtype=np.float32
                ),
                sample_rate,
                0.0
            )

        if channels > 1:

            usable_length = (
                samples.size // channels
            ) * channels

            samples = samples[:usable_length]

            samples = samples.reshape(
                -1,
                channels
            ).mean(
                axis=1
            )

        samples = samples.astype(
            np.float32
        )

        samples = self.normalize_audio(
            samples=samples,
            sample_width=sample_width
        )

        duration_sec = (
            float(samples.size) / float(sample_rate)
        )

        return (
            samples,
            sample_rate,
            duration_sec
        )

    def decode_pcm_samples(
        self,
        raw: bytes,
        sample_width: int
    ) -> np.ndarray:
        """
        Convert PCM byte data into integer samples.
        Supports 8-bit, 16-bit, 24-bit, and 32-bit PCM.
        """

        if not raw:

            return np.array(
                [],
                dtype=np.int32
            )

        if sample_width == 1:

            unsigned = np.frombuffer(
                raw,
                dtype=np.uint8
            )

            return unsigned.astype(
                np.int16
            ) - 128

        if sample_width == 2:

            return np.frombuffer(
                raw,
                dtype="<i2"
            ).astype(
                np.int32
            )

        if sample_width == 3:

            bytes_array = np.frombuffer(
                raw,
                dtype=np.uint8
            )

            usable = (
                bytes_array.size // 3
            ) * 3

            bytes_array = bytes_array[:usable]

            if bytes_array.size == 0:

                return np.array(
                    [],
                    dtype=np.int32
                )

            reshaped = bytes_array.reshape(
                -1,
                3
            )

            values = (
                reshaped[:, 0].astype(np.int32)
                | (reshaped[:, 1].astype(np.int32) << 8)
                | (reshaped[:, 2].astype(np.int32) << 16)
            )

            sign_mask = 1 << 23
            values = np.where(
                values & sign_mask,
                values - (1 << 24),
                values
            )

            return values.astype(
                np.int32
            )

        if sample_width == 4:

            return np.frombuffer(
                raw,
                dtype="<i4"
            ).astype(
                np.int32
            )

        raise ValueError(
            f"Unsupported WAV sample width: {sample_width}"
        )

    def normalize_audio(
        self,
        samples: np.ndarray,
        sample_width: int
    ) -> np.ndarray:
        """
        Normalize integer PCM samples into float32 range -1.0 to 1.0.
        """

        if samples.size == 0:

            return samples.astype(
                np.float32
            )

        if sample_width == 1:
            scale = 128.0
        elif sample_width == 2:
            scale = 32768.0
        elif sample_width == 3:
            scale = float(1 << 23)
        elif sample_width == 4:
            scale = float(1 << 31)
        else:
            scale = float(
                np.max(np.abs(samples))
            ) or 1.0

        normalized = (
            samples.astype(np.float32) / float(scale)
        )

        peak = float(
            np.max(np.abs(normalized))
        )

        if peak > 0.0:
            normalized = normalized / peak

        return np.clip(
            normalized,
            -1.0,
            1.0
        ).astype(
            np.float32
        )

    # ========================================================
    # SPECTROGRAM CONSTRUCTION
    # ========================================================

    def build_image_array(
        self,
        samples: np.ndarray,
        sample_rate: int
    ) -> np.ndarray:
        """
        Build the final spectrogram image array.
        Returns either grayscale (H, W) or RGB (H, W, 3).
        """

        fft_size = self.get_int(
            "fft_size",
            DEFAULT_CONFIG["fft_size"]
        )

        hop_length = self.get_int(
            "hop_length",
            DEFAULT_CONFIG["hop_length"]
        )

        max_width = self.get_int(
            "max_width",
            DEFAULT_CONFIG["max_width"]
        )

        height = self.get_int(
            "height",
            DEFAULT_CONFIG["height"]
        )

        if fft_size < 64:
            fft_size = 64

        if hop_length < 1:
            hop_length = 1

        if samples.size < fft_size:

            padded = np.zeros(
                fft_size,
                dtype=np.float32
            )

            padded[:samples.size] = samples
            samples = padded

        starts = np.arange(
            0,
            samples.size - fft_size + 1,
            hop_length
        )

        if starts.size == 0:

            starts = np.array(
                [0]
            )

        if starts.size > max_width:

            selected = np.linspace(
                0,
                starts.size - 1,
                max_width
            ).astype(
                int
            )

            starts = starts[selected]

        window = np.hanning(
            fft_size
        ).astype(
            np.float32
        )

        frames = np.stack(
            [
                samples[start:start + fft_size]
                for start in starts
            ],
            axis=0
        )

        frames = frames * window

        spectrum = np.abs(
            np.fft.rfft(
                frames,
                axis=1
            )
        ).T

        spectrum_db = 20.0 * np.log10(
            spectrum + 1.0e-10
        )

        freq_axis = np.fft.rfftfreq(
            fft_size,
            d=1.0 / float(sample_rate)
        )

        freq_mask = self.build_frequency_mask(
            freq_axis=freq_axis,
            sample_rate=sample_rate
        )

        spectrum_db = spectrum_db[freq_mask, :]

        if spectrum_db.size == 0:

            spectrum_db = np.zeros(
                (1, starts.size),
                dtype=np.float32
            )

        normalized = self.normalize_db_image(
            spectrum_db=spectrum_db
        )

        normalized = self.resize_frequency_axis_float(
            image=normalized,
            height=height
        )

        normalized = np.flipud(
            normalized
        )

        color_mode = self.get_string(
            "color_mode",
            DEFAULT_CONFIG["color_mode"]
        ).strip().lower()

        if color_mode in (
            "classic",
            "pink_purple",
            "classic_pink_purple"
        ):

            return self.apply_classic_colormap(
                normalized
            )

        if color_mode == "thermal":

            return self.apply_thermal_colormap(
                normalized
            )

        return (
            np.clip(normalized, 0.0, 1.0) * 255.0
        ).astype(
            np.uint8
        )

    def build_frequency_mask(
        self,
        freq_axis: np.ndarray,
        sample_rate: int
    ) -> np.ndarray:
        """
        Select the frequency band shown in the spectrogram.
        """

        min_frequency_hz = self.get_float(
            "min_frequency_hz",
            DEFAULT_CONFIG["min_frequency_hz"]
        )

        max_frequency_hz = self.get_float(
            "max_frequency_hz",
            DEFAULT_CONFIG["max_frequency_hz"]
        )

        nyquist = sample_rate / 2.0

        if max_frequency_hz <= 0:
            max_frequency_hz = nyquist

        max_frequency_hz = min(
            max_frequency_hz,
            nyquist
        )

        return (
            (freq_axis >= min_frequency_hz)
            & (freq_axis <= max_frequency_hz)
        )

    def normalize_db_image(
        self,
        spectrum_db: np.ndarray
    ) -> np.ndarray:
        """
        Normalize dB values into a float image range 0.0 to 1.0.

        Also applies:
        - floor clipping
        - black level trimming
        - gamma lift for faint detail
        """

        db_floor = abs(
            self.get_float(
                "db_floor",
                DEFAULT_CONFIG["db_floor"]
            )
        )

        gamma = self.get_float(
            "gamma",
            DEFAULT_CONFIG["gamma"]
        )

        black_level = self.get_float(
            "black_level",
            DEFAULT_CONFIG["black_level"]
        )

        peak = float(
            np.max(
                spectrum_db
            )
        )

        floor = peak - db_floor

        clipped = np.clip(
            spectrum_db,
            floor,
            peak
        )

        normalized = (
            clipped - floor
        ) / max(
            peak - floor,
            1.0e-9
        )

        black_level = max(
            0.0,
            min(0.95, black_level)
        )

        if black_level > 0.0:

            normalized = np.clip(
                (normalized - black_level) / max(1.0 - black_level, 1.0e-9),
                0.0,
                1.0
            )

        gamma = max(
            0.05,
            float(gamma)
        )

        normalized = np.power(
            normalized,
            gamma
        )

        return np.clip(
            normalized,
            0.0,
            1.0
        ).astype(
            np.float32
        )

    def resize_frequency_axis_float(
        self,
        image: np.ndarray,
        height: int
    ) -> np.ndarray:
        """
        Resize the frequency axis by indexed sampling.
        """

        if image.shape[0] == height:

            return image

        indices = np.linspace(
            0,
            image.shape[0] - 1,
            height
        ).astype(
            int
        )

        return image[indices, :]

    # ========================================================
    # COLORMAPS
    # ========================================================

    def apply_classic_colormap(
        self,
        normalized: np.ndarray
    ) -> np.ndarray:
        """
        Convert normalized 0..1 image into a classic pink / purple / orange
        spectrogram palette.
        """

        normalized = np.clip(
            normalized,
            0.0,
            1.0
        )

        positions = np.array(
            [
                0.00,
                0.08,
                0.20,
                0.38,
                0.58,
                0.78,
                0.92,
                1.00,
            ],
            dtype=np.float32
        )

        colors = np.array(
            [
                [0,   0,   0],      # black
                [10,  0,  24],      # near-black purple
                [36,  0,  78],      # deep purple
                [92,  0, 140],      # purple
                [170, 24, 176],     # magenta
                [238, 92, 176],     # hot pink
                [255, 170, 90],     # orange
                [255, 242, 210],    # pale yellow / near white
            ],
            dtype=np.float32
        )

        flat = normalized.flatten()

        red = np.interp(
            flat,
            positions,
            colors[:, 0]
        )

        green = np.interp(
            flat,
            positions,
            colors[:, 1]
        )

        blue = np.interp(
            flat,
            positions,
            colors[:, 2]
        )

        rgb = np.stack(
            [
                red,
                green,
                blue
            ],
            axis=1
        ).reshape(
            normalized.shape[0],
            normalized.shape[1],
            3
        )

        return rgb.astype(
            np.uint8
        )

    def apply_thermal_colormap(
        self,
        normalized: np.ndarray
    ) -> np.ndarray:
        """
        Convert normalized 0..1 image into a thermal-style palette.
        """

        normalized = np.clip(
            normalized,
            0.0,
            1.0
        )

        red = np.clip(
            3.0 * normalized - 1.2,
            0.0,
            1.0
        )

        green = np.clip(
            3.0 * normalized - 0.6,
            0.0,
            1.0
        )

        blue = np.clip(
            2.5 * normalized + 0.1,
            0.0,
            1.0
        ) * (
            1.0 - np.clip(
                2.0 * normalized - 0.9,
                0.0,
                1.0
            )
        )

        rgb = np.stack(
            [
                red,
                green,
                blue
            ],
            axis=2
        )

        return (
            rgb * 255.0
        ).astype(
            np.uint8
        )


    def encode_payload_safe_image(
        self,
        image_array: np.ndarray
    ) -> tuple[np.ndarray, str]:
        """
        Encode a spectrogram image as base64 and shrink it when needed.

        UDP has to carry the entire AVIS_LITE JSON envelope, not just the
        image. This keeps the GUI spectrogram contract intact while reducing
        the chance of oversize UDP packets.
        """

        max_payload_chars = self.get_effective_payload_limit()

        adaptive_resize = bool(
            self.config.get(
                "adaptive_payload_resize",
                DEFAULT_CONFIG["adaptive_payload_resize"]
            )
        )

        candidates = [
            image_array
        ]

        if adaptive_resize:

            for scale in (0.85, 0.70, 0.55, 0.45, 0.35):

                candidates.append(
                    self.resize_image_nearest(
                        image_array=image_array,
                        scale=scale
                    )
                )

        last_image = candidates[-1]
        last_b64 = ""

        for candidate in candidates:

            png_bytes = self.encode_png(
                image_array=candidate
            )

            image_b64 = base64.b64encode(
                png_bytes
            ).decode(
                "ascii"
            )

            last_image = candidate
            last_b64 = image_b64

            if max_payload_chars <= 0 or len(image_b64) <= max_payload_chars:

                if candidate is not image_array:

                    self.log(
                        (
                            "Spectrogram resized for payload safety: "
                            f"{candidate.shape[1]}x{candidate.shape[0]}, "
                            f"{len(image_b64)} base64 chars."
                        )
                    )

                return candidate, image_b64

        self.log(
            (
                "Spectrogram payload still above target after resizing: "
                f"{len(last_b64)} chars; target is {max_payload_chars}. "
                "Sending smallest candidate anyway."
            )
        )

        return last_image, last_b64

    def resize_image_nearest(
        self,
        image_array: np.ndarray,
        scale: float
    ) -> np.ndarray:
        """
        Resize an image array using dependency-free nearest-neighbor sampling.
        """

        scale = max(
            0.05,
            min(
                1.0,
                float(scale)
            )
        )

        height = max(
            1,
            int(
                round(
                    image_array.shape[0] * scale
                )
            )
        )

        width = max(
            1,
            int(
                round(
                    image_array.shape[1] * scale
                )
            )
        )

        y_indices = np.linspace(
            0,
            image_array.shape[0] - 1,
            height
        ).astype(
            int
        )

        x_indices = np.linspace(
            0,
            image_array.shape[1] - 1,
            width
        ).astype(
            int
        )

        if image_array.ndim == 2:

            return image_array[
                y_indices
            ][:, x_indices]

        return image_array[
            y_indices
        ][:, x_indices, :]

    # ========================================================
    # PNG ENCODING
    # ========================================================

    def encode_png(
        self,
        image_array: np.ndarray
    ) -> bytes:
        """
        Encode a grayscale or RGB image array as PNG using stdlib only.
        """

        if image_array.ndim == 2:

            return self.encode_png_grayscale(
                image_array
            )

        if (
            image_array.ndim == 3
            and image_array.shape[2] == 3
        ):

            return self.encode_png_rgb(
                image_array
            )

        raise ValueError(
            f"Unsupported image array shape: {image_array.shape}"
        )

    def encode_png_grayscale(
        self,
        image_array: np.ndarray
    ) -> bytes:
        """
        Encode an 8-bit grayscale PNG.
        """

        height, width = image_array.shape

        rows = []

        for row in image_array:

            rows.append(
                b"\x00" + row.astype(np.uint8).tobytes()
            )

        raw = b"".join(
            rows
        )

        return self.write_png(
            width=width,
            height=height,
            color_type=0,
            raw=raw
        )

    def encode_png_rgb(
        self,
        image_array: np.ndarray
    ) -> bytes:
        """
        Encode an 8-bit RGB PNG.
        """

        height, width, _ = image_array.shape

        rows = []

        for row in image_array:

            rows.append(
                b"\x00" + row.astype(np.uint8).tobytes()
            )

        raw = b"".join(
            rows
        )

        return self.write_png(
            width=width,
            height=height,
            color_type=2,
            raw=raw
        )

    def write_png(
        self,
        width: int,
        height: int,
        color_type: int,
        raw: bytes
    ) -> bytes:
        """
        Write PNG bytes with no external image dependency.
        """

        output = io.BytesIO()

        output.write(
            b"\x89PNG\r\n\x1a\n"
        )

        ihdr = struct.pack(
            ">IIBBBBB",
            width,
            height,
            8,
            color_type,
            0,
            0,
            0
        )

        self.write_png_chunk(
            output,
            b"IHDR",
            ihdr
        )

        compressed = zlib.compress(
            raw,
            level=9
        )

        self.write_png_chunk(
            output,
            b"IDAT",
            compressed
        )

        self.write_png_chunk(
            output,
            b"IEND",
            b""
        )

        return output.getvalue()

    def write_png_chunk(
        self,
        output: io.BytesIO,
        chunk_type: bytes,
        data: bytes
    ):
        """
        Write one PNG chunk.
        """

        output.write(
            struct.pack(
                ">I",
                len(data)
            )
        )

        output.write(
            chunk_type
        )

        output.write(
            data
        )

        checksum = zlib.crc32(
            chunk_type
        )

        checksum = zlib.crc32(
            data,
            checksum
        )

        output.write(
            struct.pack(
                ">I",
                checksum & 0xFFFFFFFF
            )
        )

    # ========================================================
    # PACKAGE HELPERS
    # ========================================================

    def build_unavailable_package(
        self,
        reason: str,
        **extra: Any
    ) -> dict:

        package = {
            "available": False,
            "reason": reason
        }

        package.update(
            extra
        )

        return package

    # ========================================================
    # CONFIG HELPERS
    # ========================================================

    def is_enabled(
        self
    ) -> bool:

        return bool(
            self.config.get(
                "enabled",
                True
            )
        )

    def get_effective_payload_limit(self) -> int:
        """
        Return the payload limit used for the base64 PNG string.

        The GUI receives the spectrogram inside a larger AVIS_LITE JSON
        envelope over UDP, so the image string must stay well below the
        theoretical UDP packet ceiling.  If an older config still says
        65000, this safety cap keeps the image transport-sized without
        requiring an immediate config migration.
        """

        configured_limit = self.get_int(
            "max_payload_chars",
            DEFAULT_CONFIG["max_payload_chars"]
        )

        transport_limit = self.get_int(
            "transport_max_payload_chars",
            DEFAULT_CONFIG["transport_max_payload_chars"]
        )

        if configured_limit <= 0:
            return transport_limit

        if transport_limit <= 0:
            return configured_limit

        return min(
            configured_limit,
            transport_limit
        )

    def get_int(
        self,
        key: str,
        default: int
    ) -> int:

        try:

            return int(
                self.config.get(
                    key,
                    default
                )
            )

        except Exception:

            return int(
                default
            )

    def get_float(
        self,
        key: str,
        default: float
    ) -> float:

        try:

            return float(
                self.config.get(
                    key,
                    default
                )
            )

        except Exception:

            return float(
                default
            )

    def get_string(
        self,
        key: str,
        default: str
    ) -> str:

        value = self.config.get(
            key,
            default
        )

        if value is None:

            return str(
                default
            )

        return str(
            value
        )