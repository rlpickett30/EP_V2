# ============================================================
# birdnet_dispatcher.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   BirdNET
#
# Role:
#   Dispatcher
#
# Purpose:
#   Own the BirdNET subsystem workflow. Receive recording and GPS events,
#   coordinate BirdNetManager analysis, and publish canonical AVIS_LITE
#   events through BirdNetEventServices.
#
# Expected config source:
#   birdnet_config.json
#
# Expected config section:
#   Full file
#
# Does:
#   - Load BirdNET configuration
#   - Start the BirdNET subsystem
#   - Register BirdNET event subscriptions
#   - Track runtime BirdNET location state
#   - Handle GPS_COORD events
#   - Handle RECORDING_AVAILABLE events
#   - Coordinate BirdNetManager
#   - Build canonical AVIS_LITE events
#   - Attach payload-safe spectrogram packages when available
#   - Publish AVIS_LITE events through BirdNetEventServices
#
# Does NOT:
#   - Analyze WAV files directly
#   - Generate spectrograms directly
#   - Subscribe directly to the event bus
#   - Publish directly to the event bus
#   - Rewrite runtime GPS values back into config
#   - Publish state events
#   - Publish mode events
#   - Own node registration
#   - Send AVIS_LITE to the server directly
#
# Owner:
#   Main / Subsystem root
#
# ============================================================

from __future__ import annotations

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from birdnet.birdnet_event_services import BirdNetEventServices
from birdnet.birdnet_manager import BirdNetManager

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import copy
import json
import queue
import threading

from datetime import datetime
from datetime import timezone


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class BirdNetDispatcher:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        event_bus,
        config_path="birdnet/birdnet_config.json",
        debug=None
    ):

        self.event_bus = event_bus
        self.config_path = config_path
        self.config = self.load_config()

        if debug is None:

            self.debug = self.config.get(
                "debug",
                True
            )

        else:

            self.debug = debug

        self.current_latitude = self.config.get(
            "current_latitude",
            self.config.get(
                "default_latitude"
            )
        )

        self.current_longitude = self.config.get(
            "current_longitude",
            self.config.get(
                "default_longitude"
            )
        )

        self.gps_acquired = bool(
            self.config.get(
                "gps_acquired",
                False
            )
        )

        self.started = False
        self.worker_stop_requested = False

        try:

            analysis_queue_max_size = int(
                self.config.get(
                    "analysis_queue_max_size",
                    16
                )
            )

        except Exception:

            analysis_queue_max_size = 16

        if analysis_queue_max_size < 1:

            analysis_queue_max_size = 1

        self.analysis_queue = queue.Queue(
            maxsize=analysis_queue_max_size
        )

        self.analysis_worker = None

        self.manager = BirdNetManager(
            debug=self.debug,
            spectrogram_config=self.get_spectrogram_config()
        )

        self.event_services = BirdNetEventServices(
            event_bus=self.event_bus,
            debug=self.debug
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
                f"[BirdNetDispatcher] {message}"
            )

    # ========================================================
    # CONFIG
    # ========================================================

    def load_config(
        self
    ):

        with open(
            self.config_path,
            "r"
        ) as file:

            return json.load(
                file
            )

    def get_spectrogram_config(
        self
    ):

        spectrogram_config = self.config.get(
            "spectrogram",
            {}
        )

        if isinstance(
            spectrogram_config,
            dict
        ):

            return spectrogram_config

        return {}

    # ========================================================
    # STARTUP
    # ========================================================

    def start(
        self
    ):

        if self.started:

            self.log(
                "BirdNET subsystem already started"
            )

            return

        self.log(
            "Starting BirdNET subsystem"
        )

        self.register_subscriptions()
        self.start_analysis_worker()

        self.started = True

        self.log(
            "BirdNET subsystem started"
        )

    def stop(
        self
    ):

        self.started = False
        self.stop_analysis_worker()

        self.log(
            "BirdNET subsystem stopped"
        )

    # ========================================================
    # EVENT REGISTRATION
    # ========================================================

    def register_subscriptions(
        self
    ):

        self.event_services.subscribe_gps_coord(
            self.handle_gps_coord
        )

        self.event_services.subscribe_recording_available(
            self.handle_recording_available
        )

        self.log(
            "Subscriptions registered"
        )

    # ========================================================
    # ANALYSIS WORKER LIFECYCLE
    # ========================================================

    def start_analysis_worker(
        self
    ):

        if (
            self.analysis_worker is not None
            and self.analysis_worker.is_alive()
        ):

            return

        self.worker_stop_requested = False

        self.analysis_worker = threading.Thread(
            target=self.analysis_worker_loop,
            name="BirdNetAnalysisWorker",
            daemon=True
        )

        self.analysis_worker.start()

        self.log(
            "Analysis worker started"
        )

    def stop_analysis_worker(
        self
    ):

        self.worker_stop_requested = True

        try:

            self.analysis_queue.put_nowait(
                None
            )

        except queue.Full:

            pass

        if self.analysis_worker is not None:

            self.analysis_worker.join(
                timeout=2.0
            )

        self.analysis_worker = None

    def analysis_worker_loop(
        self
    ):

        while not self.worker_stop_requested:

            try:

                job = self.analysis_queue.get(
                    timeout=0.25
                )

            except queue.Empty:

                continue

            try:

                if job is None:

                    return

                self.process_recording_job(
                    job
                )

            except Exception as error:

                self.log(
                    f"Analysis worker error: {error}"
                )

            finally:

                try:

                    self.analysis_queue.task_done()

                except Exception:

                    pass

    def enqueue_recording_job(
        self,
        job
    ):

        try:

            self.analysis_queue.put_nowait(
                job
            )

            self.log(
                (
                    f"Queued recording for async BirdNET analysis: "
                    f"{job.get('recording_id')} "
                    f"queue_size={self.analysis_queue.qsize()}"
                )
            )

            return True

        except queue.Full:

            self.log(
                (
                    "Analysis queue full; dropping recording to protect "
                    f"microphone timing: {job.get('recording_id')}"
                )
            )

            return False

    # ========================================================
    # EVENT HANDLING: GPS_COORD
    # ========================================================

    def handle_gps_coord(
        self,
        event
    ):

        if not self.should_use_gps_updates():

            self.log(
                "GPS_COORD ignored because GPS updates are disabled"
            )

            return

        payload = self.get_payload(
            event
        )

        gps_coord = payload.get(
            "gps_coord",
            {}
        )

        latitude = self.get_first_available(
            gps_coord,
            [
                "lat",
                "latitude"
            ],
            default=self.get_first_available(
                payload,
                [
                    "lat",
                    "latitude"
                ]
            )
        )

        longitude = self.get_first_available(
            gps_coord,
            [
                "lon",
                "longitude"
            ],
            default=self.get_first_available(
                payload,
                [
                    "lon",
                    "longitude"
                ]
            )
        )

        if latitude is None or longitude is None:

            self.log(
                "GPS_COORD ignored because latitude or longitude was missing"
            )

            return

        self.current_latitude = latitude
        self.current_longitude = longitude
        self.gps_acquired = True

        self.log(
            f"Runtime GPS updated: {latitude}, {longitude}"
        )

    # ========================================================
    # EVENT HANDLING: RECORDING_AVAILABLE
    # ========================================================

    def handle_recording_available(
        self,
        event
    ):

        event_dict = self.get_event_dict(
            event
        )

        payload = self.get_payload(
            event_dict
        )

        recording_id = self.get_first_available(
            payload,
            [
                "recording_id",
                "event_id"
            ],
            default=self.get_first_available(
                event_dict,
                [
                    "recording_id",
                    "event_id"
                ]
            )
        )

        if recording_id is None:

            self.log(
                "RECORDING_AVAILABLE ignored because recording_id was missing"
            )

            return

        recording_path = self.get_first_available(
            payload,
            [
                "recording_path",
                "wav_path"
            ],
            default=self.get_first_available(
                event_dict,
                [
                    "recording_path",
                    "wav_path"
                ]
            )
        )

        if recording_path is None:

            self.log(
                "RECORDING_AVAILABLE ignored because recording_path was missing"
            )

            return

        job = {
            "event_dict": copy.deepcopy(
                event_dict
            ),
            "payload": copy.deepcopy(
                payload
            ),
            "recording_id": recording_id,
            "recording_path": recording_path,
            "latitude": self.current_latitude,
            "longitude": self.current_longitude,
            "week": self.get_week(),
            "min_confidence": self.get_min_confidence()
        }

        self.enqueue_recording_job(
            job
        )

    def process_recording_job(
        self,
        job
    ):

        payload = job.get(
            "payload",
            {}
        )

        recording_id = job.get(
            "recording_id"
        )

        recording_path = job.get(
            "recording_path"
        )

        self.log(
            f"Processing queued recording: {recording_id}"
        )

        try:

            detection_packages = self.manager.process_recording(
                recording_id=recording_id,
                recording_path=recording_path,
                latitude=job.get("latitude"),
                longitude=job.get("longitude"),
                week=job.get("week"),
                min_confidence=job.get("min_confidence")
            )

        except Exception as error:

            self.log(
                f"BirdNET processing failed for {recording_id}: {error}"
            )

            return

        if not detection_packages:

            self.log(
                f"No BirdNET detections met threshold for {recording_id}"
            )

            return

        selected_detection_packages = self.select_detection_packages(
            detection_packages=detection_packages,
            recording_id=recording_id
        )

        for detection_package in selected_detection_packages:

            avis_lite_event = self.build_avis_lite_event(
                detection_package=detection_package,
                source_payload=payload,
                recording_id=recording_id,
                recording_path=recording_path
            )

            self.event_services.publish_avis_lite(
                avis_lite_event
            )

        self.log(
            (
                f"Published {len(selected_detection_packages)} AVIS_LITE event(s) "
                f"for {recording_id}; "
                f"filtered_from={len(detection_packages)}"
            )
        )

    # ========================================================
    # DETECTION OUTPUT FILTERING
    # ========================================================

    def get_max_avis_events_per_recording(
        self
    ) -> int:
        """
        Limit how many AVIS_LITE packets one recording window can emit.

        Default is one visual packet per recording. BirdNET may find several
        3-second detections inside a 14-second file, but the GUI transport
        should not receive several duplicate spectrogram images for the same
        15-second window.
        """

        raw_value = self.config.get(
            "max_avis_events_per_recording",
            self.config.get(
                "max_events_per_recording",
                1
            )
        )

        try:

            value = int(
                raw_value
            )

        except Exception:

            value = 1

        return max(
            1,
            value
        )

    def select_detection_packages(
        self,
        detection_packages,
        recording_id=None
    ):

        if not detection_packages:

            return []

        max_events = self.get_max_avis_events_per_recording()

        selected = detection_packages[:max_events]

        dropped_count = max(
            0,
            len(detection_packages) - len(selected)
        )

        if dropped_count > 0:

            self.log(
                (
                    f"Filtered {dropped_count} secondary BirdNET detection(s) "
                    f"for {recording_id}; max_avis_events_per_recording={max_events}"
                )
            )

        return selected

    # ========================================================
    # AVIS_LITE EVENT NORMALIZATION
    # ========================================================

    def build_avis_lite_event(
        self,
        detection_package,
        source_payload,
        recording_id,
        recording_path
    ):

        detection_time_utc = self.get_utc_timestamp()

        species_common = self.get_first_available(
            detection_package,
            [
                "species_common",
                "common_name"
            ],
            default="unknown"
        )

        species_scientific = self.get_first_available(
            detection_package,
            [
                "species_scientific",
                "scientific_name"
            ],
            default="unknown"
        )

        species_code = self.get_first_available(
            detection_package,
            [
                "species_code"
            ],
            default="unknown"
        )

        confidence = self.get_first_available(
            detection_package,
            [
                "confidence"
            ],
            default=0.0
        )

        birdnet_event_id = self.get_first_available(
            detection_package,
            [
                "birdnet_event_id"
            ]
        )

        birdnet_event_utc = self.get_first_available(
            detection_package,
            [
                "birdnet_event_utc"
            ]
        )

        birdnet_start_time = self.get_first_available(
            detection_package,
            [
                "birdnet_start_time",
                "start_time"
            ]
        )

        birdnet_end_time = self.get_first_available(
            detection_package,
            [
                "birdnet_end_time",
                "end_time"
            ]
        )

        payload = {
            "node_id": source_payload.get(
                "node_id"
            ),
            "node_name": source_payload.get(
                "node_name"
            ),
            "species_common": species_common,
            "species_scientific": species_scientific,
            "species_code": species_code,
            "confidence": confidence,
            "detection_time_utc": detection_time_utc,
            "birdnet_event_id": birdnet_event_id,
            "birdnet_event_utc": birdnet_event_utc,
            "birdnet_start_time": birdnet_start_time,
            "birdnet_end_time": birdnet_end_time,
            "detection_index": detection_package.get(
                "detection_index"
            ),
            "primary_detection": detection_package.get(
                "primary_detection",
                False
            ),
            "spectrogram_attached": detection_package.get(
                "spectrogram_attached",
                False
            ),
            "recording_id": recording_id,
            "recording_path": recording_path,
            "wav_path": source_payload.get(
                "wav_path",
                recording_path
            ),
            "recording_utc": source_payload.get(
                "recording_utc"
            ),
            "sample_rate": source_payload.get(
                "sample_rate"
            ),
            "channels": source_payload.get(
                "channels"
            ),
            "duration_sec": source_payload.get(
                "duration_sec"
            ),
            "recording_type": source_payload.get(
                "recording_type"
            ),
            "sync_source": source_payload.get(
                "sync_source"
            ),
            "pps_locked": source_payload.get(
                "pps_locked"
            )
        }

        self.attach_spectrogram_payload(
            payload=payload,
            detection_package=detection_package
        )

        return {
            "event_type": "AVIS_LITE",
            "source": "birdnet",
            "target": "sender",
            "timestamp": detection_time_utc,
            "payload": payload
        }

    def attach_spectrogram_payload(
        self,
        payload,
        detection_package
    ):
        """
        Attach the serialized spectrogram package to AVIS_LITE.

        The large base64 image string is stored only once inside the nested
        payload["spectrogram"] dictionary.
        """

        spectrogram_package = detection_package.get(
            "spectrogram"
        )

        if not isinstance(
            spectrogram_package,
            dict
        ):

            payload["spectrogram_available"] = False

            return

        payload["spectrogram_available"] = bool(
            spectrogram_package.get(
                "available",
                False
            )
        )

        payload["spectrogram"] = spectrogram_package

    # ========================================================
    # WEEK SELECTION
    # ========================================================

    def get_week(
        self
    ):

        if self.config.get(
            "week_mode"
        ) == "manual":

            return self.config.get(
                "manual_week"
            )

        return (
            datetime.now(
                timezone.utc
            )
            .isocalendar()
            .week
        )

    def get_min_confidence(
        self
    ):

        return self.config.get(
            "min_confidence",
            0.25
        )

    # ========================================================
    # RUNTIME LOCATION SETTINGS
    # ========================================================

    def should_use_gps_updates(
        self
    ):

        if not self.config.get(
            "use_gps_updates",
            True
        ):

            return False

        if self.config.get(
            "location_mode",
            "auto"
        ) != "auto":

            return False

        return True

    # ========================================================
    # EVENT HELPERS
    # ========================================================

    def get_event_dict(
        self,
        event
    ):

        if isinstance(
            event,
            dict
        ):

            return event

        return {}

    def get_payload(
        self,
        event
    ):

        if not isinstance(
            event,
            dict
        ):

            return {}

        payload = event.get(
            "payload"
        )

        if isinstance(
            payload,
            dict
        ):

            return payload

        return event

    def get_first_available(
        self,
        source,
        keys,
        default=None
    ):

        if not isinstance(
            source,
            dict
        ):

            return default

        for key in keys:

            value = source.get(
                key
            )

            if value is not None:

                return value

        return default

    def get_utc_timestamp(
        self
    ):

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
