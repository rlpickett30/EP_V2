from __future__ import annotations

import importlib.util
import tempfile
import unittest
import wave

from pathlib import Path

import numpy as np


REPOSITORY_ROOT = Path(
    __file__
).resolve().parents[1]


def load_class(
    module_name,
    relative_path,
    class_name
):

    module_path = REPOSITORY_ROOT / relative_path

    spec = importlib.util.spec_from_file_location(
        module_name,
        module_path
    )

    module = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(
        module
    )

    return getattr(
        module,
        class_name
    )


SpectrogramManager = load_class(
    "test_node_spectrogram_manager",
    "node/birdnet/spectrogram_manager.py",
    "SpectrogramManager"
)

SpectrogramUploadClient = load_class(
    "test_node_spectrogram_upload_client",
    "node/communication/spectrogram_upload_client.py",
    "SpectrogramUploadClient"
)

TDOAUploadClient = load_class(
    "test_node_tdoa_upload_client",
    "node/communication/tdoa_upload_client.py",
    "TDOAUploadClient"
)

SpectrogramUploadManager = load_class(
    "test_server_spectrogram_upload_manager",
    "server/communication/spectrogram_upload_manager.py",
    "SpectrogramUploadManager"
)

TDOAUploadManager = load_class(
    "test_server_tdoa_upload_manager",
    "server/communication/tdoa_upload_manager.py",
    "TDOAUploadManager"
)

TDOAUploadServer = load_class(
    "test_server_http_transfer",
    "server/communication/tdoa_upload_server.py",
    "TDOAUploadServer"
)

SpectrogramDownloadClient = load_class(
    "test_gui_spectrogram_download_client",
    "GUI/communication/spectrogram_download_client.py",
    "SpectrogramDownloadClient"
)


class StubDispatcher:

    def __init__(
        self,
        manager,
        tdoa_manager=None
    ):

        self.manager = manager
        self.tdoa_manager = tdoa_manager

    def handle_spectrogram_http_upload(
        self,
        transaction
    ):

        return self.manager.process_upload(
            transaction
        )

    def handle_spectrogram_http_download(
        self,
        media_id
    ):

        return self.manager.get_download(
            media_id
        )

    def handle_tdoa_http_upload(
        self,
        transaction
    ):

        if self.tdoa_manager is None:
            raise AssertionError(
                "TDOA path was not expected in this test."
            )

        return self.tdoa_manager.process_upload(
            transaction
        )


class SpectrogramHTTPTransferTest(
    unittest.TestCase
):

    def test_png_moves_outside_udp_event_and_reaches_gui_cache(
        self
    ):

        with tempfile.TemporaryDirectory() as temporary_directory:

            root = Path(
                temporary_directory
            )

            wav_path = root / "recording.wav"

            sample_rate = 48000
            seconds = 1
            samples = (
                np.sin(
                    np.linspace(
                        0.0,
                        2.0 * np.pi * 1000.0 * seconds,
                        sample_rate * seconds,
                        endpoint=False
                    )
                )
                * 12000.0
            ).astype("<i2")

            with wave.open(
                str(wav_path),
                "wb"
            ) as wav_file:

                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(
                    samples.tobytes()
                )

            spectrogram_manager = SpectrogramManager(
                config={
                    "max_width": 320,
                    "height": 128,
                    "max_duration_sec": 1.0,
                    "max_frequency_hz": 12000.0,
                    "debug": False
                },
                debug=False
            )

            package = spectrogram_manager.build_spectrogram_package(
                wav_path
            )

            self.assertTrue(
                package["available"]
            )

            self.assertGreater(
                package["width"],
                160
            )

            self.assertLessEqual(
                package["width"],
                320
            )

            self.assertEqual(
                package["height"],
                128
            )

            self.assertNotIn(
                "image_png_b64",
                package
            )

            image_path = Path(
                package["local_path"]
            )

            self.assertTrue(
                image_path.is_file()
            )

            server_storage = root / "server_media"

            upload_manager = SpectrogramUploadManager(
                config={
                    "storage_dir": str(server_storage)
                }
            )

            dispatcher = StubDispatcher(
                upload_manager
            )

            server = TDOAUploadServer(
                dispatcher=dispatcher,
                config={
                    "enabled": True,
                    "listen_host": "127.0.0.1",
                    "listen_port": 0,
                    "path": "/tdoa/upload",
                    "spectrogram_enabled": True,
                    "spectrogram_upload_path": "/media/spectrogram",
                    "spectrogram_download_path": "/media/spectrogram",
                    "max_spectrogram_upload_bytes": 4 * 1024 * 1024
                }
            )

            server.start()

            try:

                event = {
                    "event_type": "AVIS_LITE",
                    "source": "birdnet",
                    "target": "server",
                    "payload": {
                        "node_id": "node_01",
                        "recording_id": "recording_2026-07-27T20-25-15",
                        "birdnet_event_id": "AVIS_test_canada_goose",
                        "spectrogram": package
                    }
                }

                upload_client = SpectrogramUploadClient(
                    config={
                        "host": "127.0.0.1",
                        "port": server.bound_port,
                        "path": "/media/spectrogram"
                    }
                )

                upload_result = upload_client.upload(
                    event_metadata=event,
                    image_path=image_path
                )

                self.assertTrue(
                    upload_result["success"],
                    upload_result
                )

                receipt = upload_result[
                    "receipt"
                ]

                self.assertTrue(
                    receipt["download_url"].startswith(
                        f"http://127.0.0.1:{server.bound_port}/"
                    )
                )

                gui_cache = root / "gui_cache"

                download_client = SpectrogramDownloadClient(
                    config={
                        "cache_dir": str(gui_cache)
                    }
                )

                download_result = download_client.download(
                    {
                        "media_id": receipt["media_id"],
                        "download_url": receipt["download_url"],
                        "byte_count": receipt["byte_count"],
                        "sha256": receipt["sha256"]
                    }
                )

                self.assertTrue(
                    download_result["success"],
                    download_result
                )

                downloaded_path = Path(
                    download_result["local_path"]
                )

                self.assertEqual(
                    downloaded_path.read_bytes(),
                    image_path.read_bytes()
                )

            finally:

                server.stop()

    def test_existing_tdoa_http_route_remains_operational(
        self
    ):

        with tempfile.TemporaryDirectory() as temporary_directory:

            root = Path(
                temporary_directory
            )

            wav_path = root / "tdoa.wav"

            frame_count = 480

            with wave.open(
                str(wav_path),
                "wb"
            ) as wav_file:

                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(48000)
                wav_file.writeframes(
                    np.zeros(
                        frame_count,
                        dtype="<i2"
                    ).tobytes()
                )

            spectrogram_manager = SpectrogramUploadManager(
                config={
                    "storage_dir": str(
                        root / "server_media"
                    )
                }
            )

            tdoa_manager = TDOAUploadManager(
                config={
                    "storage_dir": str(
                        root / "tdoa_uploads"
                    ),
                    "temp_dir": str(
                        root / "tdoa_uploads" / ".incoming"
                    ),
                    "enforce_source_ip": False
                }
            )

            request_id = "request_http_regression"
            node_id = "node_01"
            recording_id = "recording_node_01"

            registration = tdoa_manager.register_expected_request(
                request_id=request_id,
                target_nodes=[
                    node_id
                ],
                request_items={
                    node_id: {
                        "node_id": node_id,
                        "recording_id": recording_id
                    }
                }
            )

            dispatcher = StubDispatcher(
                manager=spectrogram_manager,
                tdoa_manager=tdoa_manager
            )

            server = TDOAUploadServer(
                dispatcher=dispatcher,
                config={
                    "enabled": True,
                    "listen_host": "127.0.0.1",
                    "listen_port": 0,
                    "path": "/tdoa/upload",
                    "spectrogram_enabled": True
                }
            )

            server.start()

            try:

                instructions = server.build_upload_instructions(
                    token=registration["token"]
                )

                instructions["host"] = "127.0.0.1"

                event_metadata = {
                    "event_type": "TDOA_RECORDING",
                    "source": "microphone",
                    "target": "server",
                    "payload": {
                        "tdoa_request_id": request_id,
                        "request_id": request_id,
                        "node_id": node_id,
                        "recording_id": recording_id,
                        "requested_recording_id": recording_id,
                        "status": "success",
                        "recording_engine": "continuous_pps",
                        "continuous_stream": True,
                        "timing_state": "raw",
                        "boundary_utc": "2026-07-27T20:00:00Z",
                        "boundary_epoch": 1785182400.0,
                        "boundary_sample": 0,
                        "guarded_stream_start_sample": 0,
                        "guarded_stream_end_sample_exclusive": frame_count,
                        "raw_timing_quality": "RAW",
                        "timing_issues": [],
                        "channels": 1,
                        "sample_width_bytes": 2,
                        "sample_rate": 48000,
                        "frame_count": frame_count,
                        "guarded_frame_count": frame_count
                    }
                }

                upload_result = TDOAUploadClient().upload(
                    event_metadata=event_metadata,
                    wav_path=wav_path,
                    upload_instructions=instructions
                )

                self.assertTrue(
                    upload_result["success"],
                    upload_result
                )

                self.assertEqual(
                    upload_result["receipt"]["tdoa_request_id"],
                    request_id
                )

            finally:

                server.stop()


if __name__ == "__main__":
    unittest.main()
