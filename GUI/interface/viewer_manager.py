# ============================================================
# viewer_manager.py
#
# EnviroPulse V2 GUI
#
# Subsystem:
#   Interface
#
# Role:
#   Manager
#
# Purpose:
#   Own the visible GUI layout and update visual widgets from
#   repository-approved Interface events.
#
# Does:
#   - Display registered nodes
#   - Display node state updates
#   - Display node event updates
#   - Display environmental readings
#   - Display Avis Lite detections
#   - Display GPS coordinates
#   - Display basic TDOA calculation output when available
#   - Provide operator command buttons
#
# Does NOT:
#   - Publish events
#   - Subscribe to the event bus
#   - Build command payloads
#   - Decide command meaning
#   - Route events
#   - Store server truth outside local display cache
#
# Owner:
#   interface_dispatcher.py
#
# ============================================================


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

from datetime import datetime
from typing import Any, Optional

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QComboBox,
    QPushButton,
    QLabel,
    QGroupBox,
    QFrame,
    QListWidget,
    QMainWindow,
)


# ============================================================
# STATUS INDICATOR WIDGET
# ============================================================

class StatusIndicator(QWidget):

    def __init__(self, label_text: str, initial_state: Optional[bool] = None):
        super().__init__()

        self.label_text = label_text
        self.current_state = initial_state

        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)

        self.indicator = QLabel("●")
        self.label = QLabel(label_text)
        self.label.setStyleSheet("color: white; font-size: 14px;")

        layout.addWidget(self.indicator)
        layout.addWidget(self.label)
        self.setLayout(layout)

        self.set_status(initial_state)

    def set_status(self, state: Optional[bool]):
        self.current_state = state

        if state is True:
            color = "#33cc66"
        elif state is False:
            color = "#666666"
        else:
            color = "#ffaa66"

        self.indicator.setStyleSheet(
            f"color: {color}; font-size: 18px;"
        )


# ============================================================
# VIEWER MANAGER
# ============================================================

class ViewerManager(QMainWindow):

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self):
        super().__init__()

        self.setWindowTitle("EnviroPulse V2")
        self.setMinimumSize(1400, 850)

        self.node_records = {}
        self.node_histories = {}
        self.recent_species = []
        self.event_log_limit = 250

        self._build_window()
        self._start_clock()

    # ========================================================
    # BUILD WINDOW
    # ========================================================

    def _build_window(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        main_layout.addWidget(self._build_header())
        main_layout.addWidget(self._build_operator_controls())

        content_layout = QHBoxLayout()
        content_layout.addWidget(self._build_left_environment_panel(), 1)
        content_layout.addWidget(self._build_center_visualization_panel(), 3)
        content_layout.addWidget(self._build_right_species_panel(), 1)

        main_layout.addLayout(content_layout)
        main_layout.addWidget(self._build_footer())

        self.setStyleSheet(
            """
            QWidget {
                background-color: #121212;
                font-family: Arial;
            }
            """
        )

    # ========================================================
    # BUILD HEADER
    # ========================================================

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setFrameShape(QFrame.Shape.Box)
        header.setStyleSheet(
            """
            background-color: #1f1f1f;
            border: 1px solid #444;
            """
        )

        header_layout = QHBoxLayout()

        node_label = QLabel("Display Node:")
        node_label.setStyleSheet(
            """
            color: #bbbbbb;
            font-size: 16px;
            """
        )

        self.node_selector = QComboBox()
        self.node_selector.currentTextChanged.connect(
            self._handle_node_selection_changed
        )
        self.node_selector.setStyleSheet(
            """
            QComboBox {
                background-color: #222222;
                color: white;
                border: 1px solid #555;
                padding: 6px;
                font-size: 16px;
                min-width: 220px;
            }
            QComboBox QAbstractItemView {
                background-color: #222222;
                color: white;
                selection-background-color: #444444;
            }
            """
        )

        self.timestamp = QLabel()
        self.timestamp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timestamp.setStyleSheet(
            """
            color: #bbbbbb;
            font-size: 20px;
            """
        )

        self.node_location = QLabel("No Node Selected")
        self.node_location.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.node_location.setStyleSheet(
            """
            color: #66ccff;
            font-size: 16px;
            """
        )

        header_layout.addWidget(node_label)
        header_layout.addWidget(self.node_selector)
        header_layout.addStretch()
        header_layout.addWidget(self.timestamp)
        header_layout.addStretch()
        header_layout.addWidget(self.node_location)

        header.setLayout(header_layout)
        return header

    # ========================================================
    # BUILD OPERATOR CONTROLS
    # ========================================================

    def _build_operator_controls(self) -> QFrame:
        controls_frame = QFrame()
        controls_frame.setFrameShape(QFrame.Shape.Box)
        controls_frame.setStyleSheet(
            """
            background-color: #1a1a1a;
            border: 1px solid #444;
            """
        )

        controls_layout = QHBoxLayout()

        network_group = QGroupBox("Network Mode Change")
        network_group.setStyleSheet(self._group_style())
        network_layout = QHBoxLayout()

        self.enable_wifi_button = QPushButton("Node: Enable WiFi")
        self.enable_lora_button = QPushButton("Node: Enable LoRa")

        network_layout.addWidget(self.enable_wifi_button)
        network_layout.addWidget(self.enable_lora_button)
        network_group.setLayout(network_layout)

        detection_group = QGroupBox("Detection Mode Change")
        detection_group.setStyleSheet(self._group_style())
        detection_layout = QHBoxLayout()

        self.energy_onset_button = QPushButton("Enable Energy Onset")
        self.pattern_onset_button = QPushButton("Enable Pattern Onset")

        detection_layout.addWidget(self.energy_onset_button)
        detection_layout.addWidget(self.pattern_onset_button)
        detection_group.setLayout(detection_layout)

        feature_group = QGroupBox("Feature Mode Change")
        feature_group.setStyleSheet(self._group_style())
        feature_layout = QHBoxLayout()

        self.amp_feature_button = QPushButton("Enable Amplitude Feature")
        self.onset_feature_button = QPushButton("Enable Onset Feature")

        feature_layout.addWidget(self.amp_feature_button)
        feature_layout.addWidget(self.onset_feature_button)
        feature_group.setLayout(feature_layout)

        for button in (
            self.enable_wifi_button,
            self.enable_lora_button,
            self.energy_onset_button,
            self.pattern_onset_button,
            self.amp_feature_button,
            self.onset_feature_button,
        ):
            button.setStyleSheet(self._button_style())

        controls_layout.addWidget(network_group)
        controls_layout.addWidget(detection_group)
        controls_layout.addWidget(feature_group)

        controls_frame.setLayout(controls_layout)
        return controls_frame

    # ========================================================
    # BUILD LEFT ENVIRONMENT PANEL
    # ========================================================

    def _build_left_environment_panel(self) -> QFrame:
        left_panel = QFrame()
        left_panel.setFrameShape(QFrame.Shape.Box)
        left_panel.setMinimumWidth(260)
        left_panel.setStyleSheet(
            """
            background-color: #222222;
            border: 1px solid #444;
            """
        )

        left_layout = QVBoxLayout()

        environment_title = QLabel("ENVIRONMENT")
        environment_title.setStyleSheet(
            """
            color: #66ccff;
            font-size: 20px;
            font-weight: bold;
            """
        )

        self.temp_label = QLabel("Temperature: --")
        self.humidity_label = QLabel("Humidity: --")
        self.pressure_label = QLabel("Pressure: --")
        self.gps_label = QLabel("GPS: --")
        self.altitude_label = QLabel("Altitude: --")
        self.tdoa_label = QLabel("TDOA Ready: --")

        self.weather_labels = [
            self.temp_label,
            self.humidity_label,
            self.pressure_label,
            self.gps_label,
            self.altitude_label,
            self.tdoa_label,
        ]

        for label in self.weather_labels:
            label.setStyleSheet(self._data_label_style())

        left_layout.addWidget(environment_title)
        left_layout.addSpacing(10)

        for label in self.weather_labels:
            left_layout.addWidget(label)

        self.temp_graph = self._build_graph()
        self.humidity_graph = self._build_graph()
        self.pressure_graph = self._build_graph()

        left_layout.addSpacing(10)
        left_layout.addWidget(self._panel_subtitle("24 Hour Temperature"))
        left_layout.addWidget(self.temp_graph)
        left_layout.addWidget(self._panel_subtitle("24 Hour Humidity"))
        left_layout.addWidget(self.humidity_graph)
        left_layout.addWidget(self._panel_subtitle("24 Hour Pressure"))
        left_layout.addWidget(self.pressure_graph)
        left_layout.addStretch()

        left_panel.setLayout(left_layout)
        return left_panel

    # ========================================================
    # BUILD CENTER VISUALIZATION PANEL
    # ========================================================

    def _build_center_visualization_panel(self) -> QFrame:
        center_panel = QFrame()
        center_panel.setFrameShape(QFrame.Shape.Box)
        center_panel.setStyleSheet(
            """
            background-color: #181818;
            border: 1px solid #555;
            """
        )

        center_layout = QVBoxLayout()

        title = QLabel("PRIMARY VISUALIZATION PANEL")
        title.setStyleSheet(
            """
            color: #ffaa66;
            font-size: 22px;
            font-weight: bold;
            padding-bottom: 8px;
            """
        )
        center_layout.addWidget(title)

        top_row = QHBoxLayout()

        species_panel = QFrame()
        species_panel.setFrameShape(QFrame.Shape.Box)
        species_panel.setStyleSheet(self._dark_panel_style())
        species_layout = QVBoxLayout()

        species_title = QLabel("SPECIES ID")
        species_title.setStyleSheet(self._white_title_style())

        self.current_bird = QLabel("Waiting For Detection")
        self.current_bird.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_bird.setStyleSheet(
            """
            color: #66ff99;
            font-size: 40px;
            font-weight: bold;
            padding-top: 20px;
            padding-bottom: 20px;
            """
        )

        species_layout.addWidget(species_title, 1)
        species_layout.addWidget(self.current_bird, 3)
        species_panel.setLayout(species_layout)

        confidence_panel = QFrame()
        confidence_panel.setFrameShape(QFrame.Shape.Box)
        confidence_panel.setStyleSheet(self._dark_panel_style())
        confidence_layout = QVBoxLayout()

        confidence_title = QLabel("CONFIDENCE")
        confidence_title.setStyleSheet(self._white_title_style())

        self.confidence = QLabel("--")
        self.confidence.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.confidence.setStyleSheet(
            """
            color: #66ff99;
            font-size: 36px;
            font-weight: bold;
            """
        )

        self.confidence_bar = QLabel("▯ ▯ ▯ ▯ ▯ ▯ ▯ ▯ ▯")
        self.confidence_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.confidence_bar.setStyleSheet(
            """
            color: #66ff99;
            font-size: 22px;
            """
        )

        confidence_layout.addWidget(confidence_title, 1)
        confidence_layout.addWidget(self.confidence, 2)
        confidence_layout.addWidget(self.confidence_bar, 1)
        confidence_panel.setLayout(confidence_layout)

        top_row.addWidget(species_panel, 3)
        top_row.addWidget(confidence_panel, 1)
        center_layout.addLayout(top_row, 1)

        bottom_row = QHBoxLayout()

        spectrogram_panel = QFrame()
        spectrogram_panel.setFrameShape(QFrame.Shape.Box)
        spectrogram_panel.setStyleSheet(self._dark_panel_style())
        spectrogram_layout = QVBoxLayout()

        spectrogram_title = QLabel("SPECTROGRAM")
        spectrogram_title.setStyleSheet(
            """
            color: #cc66ff;
            font-size: 18px;
            font-weight: bold;
            """
        )

        self.spectrogram_placeholder = QLabel(
            "Spectrogram visualization\nwill appear here"
        )
        self.spectrogram_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spectrogram_placeholder.setStyleSheet(self._placeholder_style())

        spectrogram_layout.addWidget(spectrogram_title, 1)
        spectrogram_layout.addWidget(self.spectrogram_placeholder, 8)
        spectrogram_panel.setLayout(spectrogram_layout)

        node_map_panel = QFrame()
        node_map_panel.setFrameShape(QFrame.Shape.Box)
        node_map_panel.setStyleSheet(self._dark_panel_style())
        node_map_layout = QVBoxLayout()

        node_map_title = QLabel("NODE MAP")
        node_map_title.setStyleSheet(
            """
            color: #66ccff;
            font-size: 18px;
            font-weight: bold;
            """
        )

        self.node_map_placeholder = QLabel(
            "Node visualization\nwill appear here"
        )
        self.node_map_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.node_map_placeholder.setStyleSheet(self._placeholder_style())

        node_map_layout.addWidget(node_map_title, 1)
        node_map_layout.addWidget(self.node_map_placeholder, 8)
        node_map_panel.setLayout(node_map_layout)

        bottom_row.addWidget(spectrogram_panel)
        bottom_row.addWidget(node_map_panel)
        center_layout.addLayout(bottom_row, 3)

        center_panel.setLayout(center_layout)
        return center_panel

    # ========================================================
    # BUILD RIGHT SPECIES PANEL
    # ========================================================

    def _build_right_species_panel(self) -> QFrame:
        right_panel = QFrame()
        right_panel.setFrameShape(QFrame.Shape.Box)
        right_panel.setMinimumWidth(320)
        right_panel.setStyleSheet(
            """
            background-color: #222222;
            border: 1px solid #444;
            """
        )

        right_layout = QVBoxLayout()

        species_title = QLabel("RECENT SPECIES")
        species_title.setStyleSheet(
            """
            color: #ffcc66;
            font-size: 20px;
            font-weight: bold;
            """
        )

        self.species_list = QListWidget()
        self.species_list.setStyleSheet(
            """
            background-color: #1a1a1a;
            color: white;
            font-size: 16px;
            padding: 5px;
            border: 1px solid #444;
            """
        )

        right_layout.addWidget(species_title)
        right_layout.addSpacing(8)
        right_layout.addWidget(self.species_list, 4)

        alert_title = QLabel("RARE BIRD ALERTS")
        alert_title.setStyleSheet(
            """
            color: #ff6666;
            font-size: 18px;
            font-weight: bold;
            """
        )
        right_layout.addWidget(alert_title)

        alert_panel = QFrame()
        alert_panel.setFrameShape(QFrame.Shape.Box)
        alert_panel.setStyleSheet(self._dark_panel_style())
        alert_layout = QVBoxLayout()

        self.alert_status = QLabel("No active rare bird alert")
        self.alert_status.setStyleSheet(
            """
            color: #bbbbbb;
            font-size: 14px;
            padding-top: 8px;
            """
        )

        self.alert_species = QLabel("--")
        self.alert_species.setStyleSheet(
            """
            color: #ffcc66;
            font-size: 26px;
            font-weight: bold;
            padding-top: 6px;
            padding-bottom: 8px;
            """
        )

        last_seen_label = QLabel("Last Seen")
        last_seen_label.setStyleSheet(self._small_gray_label_style())

        self.last_seen_value = QLabel("--")
        self.last_seen_value.setStyleSheet(self._data_label_style())

        priority_label = QLabel("Priority")
        priority_label.setStyleSheet(self._small_gray_label_style())

        self.priority_value = QLabel("--")
        self.priority_value.setStyleSheet(
            """
            color: #ffaa66;
            font-size: 20px;
            font-weight: bold;
            padding: 4px;
            border: 1px solid #444;
            """
        )

        alert_layout.addWidget(self.alert_status)
        alert_layout.addWidget(self.alert_species)
        alert_layout.addWidget(last_seen_label)
        alert_layout.addWidget(self.last_seen_value)
        alert_layout.addWidget(priority_label)
        alert_layout.addWidget(self.priority_value)
        alert_panel.setLayout(alert_layout)

        right_layout.addWidget(alert_panel, 2)

        event_log_title = QLabel("EVENT LOG")
        event_log_title.setStyleSheet(
            """
            color: #66ccff;
            font-size: 18px;
            font-weight: bold;
            """
        )

        self.event_view = QTextEdit()
        self.event_view.setReadOnly(True)
        self.event_view.setStyleSheet(
            """
            background-color: #101010;
            color: #dddddd;
            font-size: 12px;
            border: 1px solid #444;
            """
        )

        right_layout.addWidget(event_log_title)
        right_layout.addWidget(self.event_view, 3)

        right_panel.setLayout(right_layout)
        return right_panel

    # ========================================================
    # BUILD FOOTER
    # ========================================================

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setFrameShape(QFrame.Shape.Box)
        footer.setStyleSheet(
            """
            background-color: #1f1f1f;
            border: 1px solid #444;
            """
        )

        footer_layout = QHBoxLayout()

        self.status_indicators = {
            "PPS": StatusIndicator("PPS", None),
            "GPS": StatusIndicator("GPS", None),
            "RTK": StatusIndicator("RTK", None),
            "BirdNET": StatusIndicator("BirdNET", None),
            "Microphones": StatusIndicator("Microphones", None),
            "Sensors": StatusIndicator("Sensors", None),
            "Network": StatusIndicator("Network", None),
            "TDOA": StatusIndicator("TDOA", None),
        }

        for indicator in self.status_indicators.values():
            footer_layout.addWidget(indicator)

        footer_layout.addStretch()
        footer.setLayout(footer_layout)
        return footer

    # ========================================================
    # CLOCK
    # ========================================================

    def _start_clock(self):
        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        self.update_clock()

    def update_clock(self):
        now = datetime.now()
        self.timestamp.setText(now.strftime("%Y-%m-%d  %I:%M:%S %p"))

    # ========================================================
    # DISPLAY EVENT
    # ========================================================

    def display_event(self, event: dict):
        if not isinstance(event, dict):
            self._append_event_log(
                f"[Interface] Non-dictionary event received: {event}"
            )
            return

        event_type = event.get("event_type", "UNKNOWN_EVENT")
        payload = self._safe_dict(event.get("payload", {}))
        node_id = self._extract_node_id(event)

        if node_id:
            self.add_node(node_id)

        if event_type == "NEW_NODE_REGISTERED":
            self._handle_new_node_registered(event, payload, node_id)
            return

        if event_type == "REPOSITORY_STATE_UPDATE":
            self._handle_repository_state_update(event, payload, node_id)
            return

        if event_type == "REPOSITORY_EVENT_UPDATE":
            self._handle_repository_event_update(event, payload, node_id)
            return

        self._append_event_log(f"[{event_type}] {node_id or 'unknown node'}")

    # ========================================================
    # EVENT HANDLERS
    # ========================================================

    def _handle_new_node_registered(self, event: dict, payload: dict, node_id: Optional[str]):
        if not node_id:
            self._append_event_log("[Node Registered] Missing node_id")
            return

        registry = self._safe_dict(payload.get("registry", {}))
        state = self._safe_dict(payload.get("state", {}))

        record = self._get_or_create_node_record(node_id)
        record["registry"] = registry
        record["state"] = state
        record["last_event"] = event

        node_name = registry.get("node_name") or registry.get("source") or node_id
        self.node_location.setText(node_name)
        self._render_node(node_id)
        self._append_event_log(f"[Node Registered] {node_id}")

    def _handle_repository_state_update(self, event: dict, payload: dict, node_id: Optional[str]):
        if not node_id:
            self._append_event_log("[State Update] Missing node_id")
            return

        state = self._safe_dict(payload.get("state", {}))
        registry = self._safe_dict(payload.get("registry", {}))

        record = self._get_or_create_node_record(node_id)
        record["registry"].update(registry)
        record["state"].update(state)
        record["last_state_event"] = event

        self._render_node(node_id)
        self._append_event_log(
            self._build_state_summary(node_id=node_id, state=record["state"])
        )

    def _handle_repository_event_update(self, event: dict, payload: dict, node_id: Optional[str]):
        if not node_id:
            self._append_event_log("[Event Update] Missing node_id")
            return

        source_event_type = payload.get("source_event_type", "UNKNOWN_SOURCE_EVENT")
        state = self._safe_dict(payload.get("state", {}))
        registry = self._safe_dict(payload.get("registry", {}))

        record = self._get_or_create_node_record(node_id)
        record["registry"].update(registry)
        record["state"].update(state)
        record["last_event"] = event

        if source_event_type == "SERVER_AVIS_LITE":
            self._apply_avis_lite_event(node_id, event)
        elif source_event_type == "SERVER_ENVIRO_EVENT":
            self._apply_enviro_event(node_id, event)
        elif source_event_type == "SERVER_GPS_COORD":
            self._apply_gps_coord_event(node_id, event)
        elif source_event_type == "SERVER_TDOA_CALC":
            self._apply_tdoa_calc_event(node_id, event)
        else:
            self._append_event_log(f"[Event Update] {node_id} | {source_event_type}")

        self._render_node(node_id)

    # ========================================================
    # APPLY SPECIFIC EVENT TYPES
    # ========================================================

    def _apply_avis_lite_event(self, node_id: str, event: dict):
        avis_lite = self._find_nested_dict(event, "avis_lite") or {}

        species = (
            avis_lite.get("common_name")
            or avis_lite.get("species")
            or avis_lite.get("species_common")
            or self._find_nested_value(event, "common_name")
            or self._find_nested_value(event, "species_common")
            or self._find_nested_value(event, "species")
            or "Unknown Species"
        )

        confidence = avis_lite.get("confidence")
        if confidence is None:
            confidence = self._find_nested_value(event, "confidence")

        audio_path = (
            avis_lite.get("audio_path")
            or self._find_nested_value(event, "audio_path")
            or self._find_nested_value(event, "recording_path")
        )

        record = self._get_or_create_node_record(node_id)
        record["last_species"] = species
        record["last_confidence"] = confidence
        record["last_audio_path"] = audio_path

        self.current_bird.setText(species)
        self._set_confidence(confidence)
        self._add_recent_species(species)
        self.status_indicators["BirdNET"].set_status(True)

        if audio_path:
            self.spectrogram_placeholder.setText(f"Audio received\n{audio_path}")

        self._append_event_log(
            f"[Avis Lite] {node_id} | {species} | {self._format_confidence(confidence)}"
        )

    def _apply_enviro_event(self, node_id: str, event: dict):
        enviro_event = self._find_nested_dict(event, "enviro_event") or {}

        temperature_c = enviro_event.get("temperature_c")
        if temperature_c is None:
            temperature_c = self._find_nested_value(event, "temperature_c")

        humidity_percent = enviro_event.get("humidity_percent")
        if humidity_percent is None:
            humidity_percent = self._find_nested_value(event, "humidity_percent")

        pressure_hpa = enviro_event.get("pressure_hpa")
        if pressure_hpa is None:
            pressure_hpa = self._find_nested_value(event, "pressure_hpa")

        record = self._get_or_create_node_record(node_id)
        record["last_enviro"] = {
            "temperature_c": temperature_c,
            "humidity_percent": humidity_percent,
            "pressure_hpa": pressure_hpa,
        }

        self._update_environment_labels(node_id)
        self._update_environment_history(
            node_id=node_id,
            temperature_c=temperature_c,
            humidity_percent=humidity_percent,
            pressure_hpa=pressure_hpa,
        )
        self.status_indicators["Sensors"].set_status(True)

        self._append_event_log(
            f"[Environmental] {node_id} | "
            f"{self._format_temperature(temperature_c)} | "
            f"{self._format_humidity(humidity_percent)} | "
            f"{self._format_pressure(pressure_hpa)}"
        )

    def _apply_gps_coord_event(self, node_id: str, event: dict):
        gps_coord = self._find_nested_dict(event, "gps_coord") or {}

        record = self._get_or_create_node_record(node_id)
        record["last_gps_coord"] = gps_coord
        record["state"]["gps_coord"] = gps_coord

        self._update_environment_labels(node_id)
        self.status_indicators["GPS"].set_status(True)
        self.node_map_placeholder.setText(
            self._format_node_map_text(node_id=node_id, gps_coord=gps_coord)
        )
        self._append_event_log(f"[GPS Coord] {node_id} | {self._format_gps(gps_coord)}")

    def _apply_tdoa_calc_event(self, node_id: str, event: dict):
        estimate = (
            self._find_nested_dict(event, "estimate")
            or self._find_nested_dict(event, "tdoa_calc")
            or self._find_nested_dict(event, "tdoa")
            or {}
        )

        self.status_indicators["TDOA"].set_status(True)
        self.node_map_placeholder.setText(
            self._format_tdoa_text(node_id=node_id, estimate=estimate)
        )
        self._append_event_log(f"[TDOA Calc] {node_id} | {estimate}")

    # ========================================================
    # RENDER NODE
    # ========================================================

    def _render_node(self, node_id: str):
        if not node_id:
            return

        current_node = self.node_selector.currentText()
        if current_node and current_node != node_id:
            return

        record = self._get_or_create_node_record(node_id)
        registry = record.get("registry", {})
        state = record.get("state", {})

        node_name = registry.get("node_name") or registry.get("source") or node_id
        self.node_location.setText(node_name)

        self._update_environment_labels(node_id)
        self._update_status_indicators(state=state, registry=registry)

    def _update_environment_labels(self, node_id: str):
        record = self._get_or_create_node_record(node_id)
        state = record.get("state", {})
        last_enviro = record.get("last_enviro", {})

        temperature_c = last_enviro.get("temperature_c")
        if temperature_c is None:
            temperature_c = state.get("temperature_c")

        humidity_percent = last_enviro.get("humidity_percent")
        if humidity_percent is None:
            humidity_percent = state.get("humidity_percent")

        pressure_hpa = last_enviro.get("pressure_hpa")
        if pressure_hpa is None:
            pressure_hpa = state.get("pressure_hpa")

        gps_coord = record.get("last_gps_coord") or state.get("gps_coord") or {}
        tdoa_capable = state.get("tdoa_capable")

        self.temp_label.setText(f"Temperature: {self._format_temperature(temperature_c)}")
        self.humidity_label.setText(f"Humidity: {self._format_humidity(humidity_percent)}")
        self.pressure_label.setText(f"Pressure: {self._format_pressure(pressure_hpa)}")
        self.gps_label.setText(f"GPS: {self._format_gps(gps_coord)}")
        self.altitude_label.setText(f"Altitude: {self._format_altitude(gps_coord)}")
        self.tdoa_label.setText(f"TDOA Ready: {self._format_bool(tdoa_capable)}")

    def _update_status_indicators(self, state: dict, registry: dict):
        capabilities = self._safe_dict(registry.get("capabilities", {}))

        self.status_indicators["PPS"].set_status(
            self._first_bool(state, ["pps_locked", "pps_lock", "pps_available"])
        )
        self.status_indicators["GPS"].set_status(
            self._first_bool(state, ["gps_locked", "gps_lock", "gps_available"])
        )
        self.status_indicators["RTK"].set_status(
            self._first_bool(state, ["rtk_online", "rtk_available", "rtk_ready"])
        )
        self.status_indicators["Sensors"].set_status(
            self._first_bool(state, ["enviro_online", "bmp390_online", "sht45_online"])
        )
        self.status_indicators["TDOA"].set_status(
            self._first_bool(state, ["tdoa_capable", "rtk_tdoa_capable"])
        )
        self.status_indicators["BirdNET"].set_status(capabilities.get("avis_lite"))
        self.status_indicators["Microphones"].set_status(capabilities.get("tdoa_recording"))
        self.status_indicators["Network"].set_status(None)

    # ========================================================
    # NODE LIST METHODS USED BY DISPATCHER
    # ========================================================

    def add_node(self, node_id: str):
        if not node_id:
            return

        self._get_or_create_node_record(node_id)

        existing_nodes = [
            self.node_selector.itemText(index)
            for index in range(self.node_selector.count())
        ]

        if node_id not in existing_nodes:
            previous_block_state = self.node_selector.blockSignals(True)
            self.node_selector.addItem(node_id)
            self.node_selector.blockSignals(previous_block_state)

            if self.node_selector.count() == 1:
                self.node_selector.setCurrentText(node_id)
                self._render_node(node_id)

    def update_nodes(self, nodes: list):
        previous_selection = self.node_selector.currentText()
        previous_block_state = self.node_selector.blockSignals(True)

        self.node_selector.clear()

        for node_id in nodes:
            if node_id:
                self._get_or_create_node_record(node_id)
                self.node_selector.addItem(node_id)

        self.node_selector.blockSignals(previous_block_state)

        if previous_selection in nodes:
            self.node_selector.setCurrentText(previous_selection)
        elif nodes:
            self.node_selector.setCurrentText(nodes[0])

        self._render_node(self.node_selector.currentText())

    def _handle_node_selection_changed(self, node_id: str):
        if not node_id:
            return

        self._render_node(node_id)
        self._redraw_history_graphs(node_id)

    # ========================================================
    # HISTORY GRAPHS
    # ========================================================

    def _update_environment_history(self, node_id: str, temperature_c, humidity_percent, pressure_hpa):
        history = self._get_or_create_history(node_id)
        self._append_history_value(history["temperature_c"], temperature_c)
        self._append_history_value(history["humidity_percent"], humidity_percent)
        self._append_history_value(history["pressure_hpa"], pressure_hpa)

        if self.node_selector.currentText() == node_id:
            self._redraw_history_graphs(node_id)

    def _redraw_history_graphs(self, node_id: str):
        history = self._get_or_create_history(node_id)

        self.temp_graph.clear()
        self.humidity_graph.clear()
        self.pressure_graph.clear()

        self._plot_history(self.temp_graph, history["temperature_c"], "#ff6666")
        self._plot_history(self.humidity_graph, history["humidity_percent"], "#66ccff")
        self._plot_history(self.pressure_graph, history["pressure_hpa"], "#66ff99")

    def _plot_history(self, graph, values: list, color: str):
        clean_values = [value for value in values if value is not None]

        if not clean_values:
            return

        x_values = np.arange(len(clean_values))
        graph.plot(x_values, clean_values, pen=pg.mkPen(color, width=2))

    def _append_history_value(self, values: list, value):
        if value is None:
            return

        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return

        values.append(numeric_value)

        while len(values) > 24:
            values.pop(0)

    # ========================================================
    # CACHE HELPERS
    # ========================================================

    def _get_or_create_node_record(self, node_id: str) -> dict:
        if node_id not in self.node_records:
            self.node_records[node_id] = {
                "registry": {},
                "state": {},
                "last_enviro": {},
                "last_gps_coord": {},
                "last_species": None,
                "last_confidence": None,
                "last_audio_path": None,
                "last_event": None,
                "last_state_event": None,
            }

        self._get_or_create_history(node_id)
        return self.node_records[node_id]

    def _get_or_create_history(self, node_id: str) -> dict:
        if node_id not in self.node_histories:
            self.node_histories[node_id] = {
                "temperature_c": [],
                "humidity_percent": [],
                "pressure_hpa": [],
            }

        return self.node_histories[node_id]

    # ========================================================
    # SPECIES AND CONFIDENCE
    # ========================================================

    def _set_confidence(self, confidence):
        confidence_percent = self._confidence_to_percent(confidence)

        if confidence_percent is None:
            self.confidence.setText("--")
            self.confidence_bar.setText("▯ ▯ ▯ ▯ ▯ ▯ ▯ ▯ ▯")
            return

        self.confidence.setText(f"Confidence: {confidence_percent:.0f}%")

        filled_blocks = max(0, min(9, round(confidence_percent / 100 * 9)))
        empty_blocks = 9 - filled_blocks
        self.confidence_bar.setText(
            ("▮ " * filled_blocks + "▯ " * empty_blocks).strip()
        )

    def _add_recent_species(self, species: str):
        if not species:
            return

        if species in self.recent_species:
            self.recent_species.remove(species)

        self.recent_species.insert(0, species)
        self.recent_species = self.recent_species[:20]

        self.species_list.clear()

        for species_name in self.recent_species:
            self.species_list.addItem(species_name)

        self._update_rare_bird_panel(species)

    def _update_rare_bird_panel(self, species: str):
        rare_species = {
            "Bullock's Oriole",
            "Black-headed Grosbeak",
            "Western Tanager",
        }

        if species in rare_species:
            self.alert_status.setText("Priority detection")
            self.alert_species.setText(species)
            self.last_seen_value.setText("History pending")
            self.priority_value.setText("MEDIUM")
        else:
            self.alert_status.setText("No active rare bird alert")
            self.alert_species.setText("--")
            self.last_seen_value.setText("--")
            self.priority_value.setText("--")

    # ========================================================
    # EVENT LOG
    # ========================================================

    def _append_event_log(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.event_view.append(f"{timestamp}  {text}")

    # ========================================================
    # EXTRACTION HELPERS
    # ========================================================

    def _extract_node_id(self, event: dict) -> Optional[str]:
        if event.get("node_id"):
            return event.get("node_id")

        payload = self._safe_dict(event.get("payload", {}))

        if payload.get("node_id"):
            return payload.get("node_id")

        return self._find_nested_value(event, "node_id")

    def _find_nested_dict(self, data: Any, key_name: str) -> dict:
        value = self._find_nested_value(data, key_name)

        if isinstance(value, dict):
            return value

        return {}

    def _find_nested_value(self, data: Any, key_name: str):
        if isinstance(data, dict):
            if key_name in data:
                return data[key_name]

            for value in data.values():
                result = self._find_nested_value(value, key_name)
                if result is not None:
                    return result

        elif isinstance(data, list):
            for item in data:
                result = self._find_nested_value(item, key_name)
                if result is not None:
                    return result

        return None

    def _safe_dict(self, value) -> dict:
        if isinstance(value, dict):
            return value

        return {}

    def _first_bool(self, data: dict, keys: list) -> Optional[bool]:
        for key in keys:
            value = data.get(key)

            if isinstance(value, bool):
                return value

        return None

    # ========================================================
    # SUMMARY AND FORMATTERS
    # ========================================================

    def _build_state_summary(self, node_id: str, state: dict) -> str:
        pps = self._format_bool(
            self._first_bool(state, ["pps_locked", "pps_lock", "pps_available"])
        )
        gps = self._format_bool(
            self._first_bool(state, ["gps_locked", "gps_lock", "gps_available"])
        )
        rtk = self._format_bool(
            self._first_bool(state, ["rtk_online", "rtk_available", "rtk_ready"])
        )
        tdoa = self._format_bool(
            self._first_bool(state, ["tdoa_capable", "rtk_tdoa_capable"])
        )

        return f"[State] {node_id} | PPS: {pps} | GPS: {gps} | RTK: {rtk} | TDOA: {tdoa}"

    def _format_temperature(self, temperature_c) -> str:
        if temperature_c is None:
            return "--"

        try:
            temp_c = float(temperature_c)
        except (TypeError, ValueError):
            return "--"

        temp_f = temp_c * 9 / 5 + 32
        return f"{temp_c:.1f}°C / {temp_f:.1f}°F"

    def _format_humidity(self, humidity_percent) -> str:
        if humidity_percent is None:
            return "--"

        try:
            return f"{float(humidity_percent):.1f}%"
        except (TypeError, ValueError):
            return "--"

    def _format_pressure(self, pressure_hpa) -> str:
        if pressure_hpa is None:
            return "--"

        try:
            return f"{float(pressure_hpa):.1f} hPa"
        except (TypeError, ValueError):
            return "--"

    def _format_gps(self, gps_coord) -> str:
        if not isinstance(gps_coord, dict):
            return "--"

        lat = gps_coord.get("lat") if gps_coord.get("lat") is not None else gps_coord.get("latitude")
        lon = gps_coord.get("lon") if gps_coord.get("lon") is not None else gps_coord.get("longitude")

        if lat is None or lon is None:
            return "--"

        try:
            return f"{float(lat):.6f}, {float(lon):.6f}"
        except (TypeError, ValueError):
            return "--"

    def _format_altitude(self, gps_coord) -> str:
        if not isinstance(gps_coord, dict):
            return "--"

        altitude_m = gps_coord.get("alt") if gps_coord.get("alt") is not None else gps_coord.get("altitude")

        if altitude_m is None:
            return "--"

        try:
            altitude_m = float(altitude_m)
        except (TypeError, ValueError):
            return "--"

        altitude_ft = altitude_m * 3.28084
        return f"{altitude_m:.1f} m / {altitude_ft:.0f} ft"

    def _format_bool(self, value) -> str:
        if value is True:
            return "YES"

        if value is False:
            return "NO"

        return "--"

    def _confidence_to_percent(self, confidence) -> Optional[float]:
        if confidence is None:
            return None

        try:
            value = float(confidence)
        except (TypeError, ValueError):
            return None

        if value <= 1.0:
            value = value * 100

        return max(0.0, min(100.0, value))

    def _format_confidence(self, confidence) -> str:
        confidence_percent = self._confidence_to_percent(confidence)

        if confidence_percent is None:
            return "Confidence: --"

        return f"Confidence: {confidence_percent:.0f}%"

    def _format_node_map_text(self, node_id: str, gps_coord: dict) -> str:
        return (
            f"Node: {node_id}\n\n"
            f"GPS:\n{self._format_gps(gps_coord)}\n\n"
            f"Altitude:\n{self._format_altitude(gps_coord)}"
        )

    def _format_tdoa_text(self, node_id: str, estimate: dict) -> str:
        if not estimate:
            return (
                f"TDOA estimate received\n"
                f"Node: {node_id}\n"
                f"Estimate payload pending"
            )

        lines = ["TDOA Estimate", "", f"Node: {node_id}"]

        for key, value in estimate.items():
            lines.append(f"{key}: {value}")

        return "\n".join(lines)

    # ========================================================
    # STYLE HELPERS
    # ========================================================

    def _build_graph(self):
        graph = pg.PlotWidget()
        graph.setBackground("#181818")
        graph.showGrid(x=True, y=True)
        graph.setMenuEnabled(False)
        graph.setMouseEnabled(x=False, y=False)
        graph.getAxis("left").setTextPen("#888888")
        graph.getAxis("bottom").setTextPen("#888888")
        graph.setFixedHeight(120)
        return graph

    def _panel_subtitle(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            """
            color: #66ccff;
            font-size: 14px;
            padding-top: 8px;
            """
        )
        return label

    def _button_style(self) -> str:
        return """
            QPushButton {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #555;
                padding: 7px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
            }
            QPushButton:pressed {
                background-color: #555555;
            }
        """

    def _group_style(self) -> str:
        return """
            QGroupBox {
                color: white;
                border: 1px solid #555;
                margin-top: 8px;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0px 4px 0px 4px;
            }
        """

    def _data_label_style(self) -> str:
        return """
            color: white;
            font-size: 15px;
            padding: 6px;
            border: 1px solid #444;
        """

    def _dark_panel_style(self) -> str:
        return """
            background-color: #101010;
            border: 1px solid #444;
        """

    def _placeholder_style(self) -> str:
        return """
            color: #777777;
            font-size: 22px;
            padding: 60px;
            border: 2px dashed #444;
        """

    def _white_title_style(self) -> str:
        return """
            color: white;
            font-size: 16px;
        """

    def _small_gray_label_style(self) -> str:
        return """
            color: #888888;
            font-size: 13px;
        """
