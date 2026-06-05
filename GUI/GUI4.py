

# =========================================================
# EnviroPulse GUI Prototype V2
# Placeholder Interface Layout With Node Selection
#
# Author: Lee Pickett
# =========================================================
import pyqtgraph as pg
import numpy as np
import sys
import random
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QFrame,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QMainWindow,
    QComboBox,
)


# =========================================================
# STATUS LED WIDGET
# =========================================================

class StatusIndicator(QWidget):
    def __init__(self, label_text, color="green"):
        super().__init__()

        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)

        self.indicator = QLabel("●")
        self.indicator.setStyleSheet(f"color: {color}; font-size: 18px;")

        self.label = QLabel(label_text)
        self.label.setStyleSheet("color: white; font-size: 14px;")

        layout.addWidget(self.indicator)
        layout.addWidget(self.label)

        self.setLayout(layout)


# =========================================================
# MAIN WINDOW
# =========================================================

class EnviroPulseGUI(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("EnviroPulse V1")
        self.setMinimumSize(1400, 850)

        self.nodes = {
            "Node 01": "Animas Valley",
            "Node 02": "North Field",
            "Node 03": "River Edge",
            "Node 04": "Ridge Line",
            "Node 05": "Backyard Station",
        }
        
        self.hours = np.arange(24)
        self.temp_history = np.random.normal(58, 4, 24)
        self.humidity_history = np.random.normal(42, 8, 24)
        self.pressure_history = np.random.normal(1012, 3, 24)


        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # =================================================
        # HEADER
        # =================================================

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
        self.node_selector.addItems(self.nodes.keys())
        self.node_selector.currentTextChanged.connect(self.update_node_display)
        self.node_selector.setStyleSheet(
            """
            QComboBox {
                background-color: #222222;
                color: white;
                border: 1px solid #555;
                padding: 6px;
                font-size: 16px;
                min-width: 180px;
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

        self.node_location = QLabel(self.nodes["Node 01"])
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

        # =================================================
        # MAIN CONTENT AREA
        # =================================================

        content_layout = QHBoxLayout()

        # =================================================
        # LEFT PANEL: ENVIRONMENT
        # =================================================

        left_panel = QFrame()
        left_panel.setFrameShape(QFrame.Shape.Box)
        left_panel.setMinimumWidth(250)
        left_panel.setStyleSheet(
            """
            background-color: #222222;
            border: 1px solid #444;
            """
        )

        left_layout = QVBoxLayout()

        weather_title = QLabel("ENVIRONMENT")
        weather_title.setStyleSheet(
            """
            color: #66ccff;
            font-size: 20px;
            font-weight: bold;
            """
        )

        self.temp_label = QLabel("Temperature: 52°F")
        self.humidity_label = QLabel("Humidity: 31%")
        self.pressure_label = QLabel("Pressure: 1012 mb")
        self.wind_label = QLabel("Wind: 4 mph")
        self.gps_label = QLabel("GPS: 37.2753, -107.8801")
        self.altitude_label = QLabel("Altitude: 6512 ft")

        self.weather_labels = [
            self.temp_label,
            self.humidity_label,
            self.pressure_label,
            self.wind_label,
            self.gps_label,
            self.altitude_label,
        ]

        for label in self.weather_labels:
            label.setStyleSheet(
                """
                color: white;
                font-size: 16px;
                padding: 6px;
                border: 1px solid #444;
                """
            )

        left_layout.addWidget(weather_title)
        left_layout.addSpacing(15)

        for label in self.weather_labels:
            left_layout.addWidget(label)

        # =================================================
        # TEMPERATURE GRAPH
        # =================================================

        temp_graph_title = QLabel("24 Hour Temperature")
        temp_graph_title.setStyleSheet(
            """
            color: #66ccff;
            font-size: 14px;
            padding-top: 10px;
            """
        )

        self.temp_graph = pg.PlotWidget()

        # =================================================
        # HUMIDITY GRAPH
        # =================================================

        humidity_graph_title = QLabel("24 Hour Humidity")
        humidity_graph_title.setStyleSheet(
            """
            color: #66ccff;
            font-size: 14px;
            padding-top: 10px;
            """
        )

        self.humidity_graph = pg.PlotWidget()

        # =================================================
        # PRESSURE GRAPH
        # =================================================

        pressure_graph_title = QLabel("24 Hour Pressure")
        pressure_graph_title.setStyleSheet(
            """
            color: #66ccff;
            font-size: 14px;
            padding-top: 10px;
            """
        )

        self.pressure_graph = pg.PlotWidget()
        
        graphs = [
            self.temp_graph,
            self.humidity_graph,
            self.pressure_graph
        ]

        for graph in graphs:

            graph.setBackground("#181818")

            graph.showGrid(x=True, y=True)
        
            graph.setMenuEnabled(False)
            graph.setMouseEnabled(x=False, y=False)

            graph.getAxis("left").setTextPen("#888888")
            graph.getAxis("bottom").setTextPen("#888888")

            graph.setFixedHeight(120)
            
        self.temp_graph.plot(
            self.hours,
            self.temp_history,
            pen=pg.mkPen("#ff6666", width=2)
        )

        self.humidity_graph.plot(
            self.hours,
            self.humidity_history,
            pen=pg.mkPen("#66ccff", width=2)
        )

        self.pressure_graph.plot(
            self.hours,
            self.pressure_history,
            pen=pg.mkPen("#66ff99", width=2)
        )
        
        left_layout.addSpacing(15)

        left_layout.addWidget(temp_graph_title)
        left_layout.addWidget(self.temp_graph)

        left_layout.addWidget(humidity_graph_title)
        left_layout.addWidget(self.humidity_graph)

        left_layout.addWidget(pressure_graph_title)
        left_layout.addWidget(self.pressure_graph)

        left_layout.addStretch()
        left_panel.setLayout(left_layout)


        # =================================================
        # CENTER PANEL: PRIMARY VISUALIZATION
        # =================================================

        center_panel = QFrame()
        center_panel.setFrameShape(QFrame.Shape.Box)

        center_panel.setStyleSheet(
            """
            background-color: #181818;
            border: 1px solid #555;
            """
        )

        center_layout = QVBoxLayout()

        # =================================================
        # TITLE
        # =================================================

        map_title = QLabel("PRIMARY VISUALIZATION PANEL")
        
        map_title.setStyleSheet(
            """
            color: #ffaa66;
            font-size: 22px;
            font-weight: bold;
            padding-bottom: 8px;
            """
        )

        center_layout.addWidget(map_title)

        # =================================================
        # TOP ROW
        # SPECIES + CONFIDENCE
        # =================================================

        top_row = QHBoxLayout()

        # ---------------------------------------------
        # SPECIES PANEL
        # ---------------------------------------------

        species_panel = QFrame()
        species_panel.setFrameShape(QFrame.Shape.Box)

        species_panel.setStyleSheet(
            """
            background-color: #101010;
            border: 1px solid #444;
            """
        )

        species_layout = QVBoxLayout()

        species_label = QLabel("SPECIES ID")

        species_label.setStyleSheet(
            """
            color: white;
            font-size: 16px;
            """
        )

        self.current_bird = QLabel("Northern Flicker")

        self.current_bird.setStyleSheet(
            """
            color: #66ff99;
            font-size: 42px;
            font-weight: bold;
            padding-top: 20px;
            padding-bottom: 20px;
            """
        )

        self.current_bird.setAlignment(Qt.AlignmentFlag.AlignCenter)

        species_layout.addWidget(species_label,1)
        species_layout.addWidget(self.current_bird,3)

        species_panel.setLayout(species_layout)

        # ---------------------------------------------
        # CONFIDENCE PANEL
        # ---------------------------------------------

        confidence_panel = QFrame()
        confidence_panel.setFrameShape(QFrame.Shape.Box)

        confidence_panel.setStyleSheet(
            """
            background-color: #101010;
            border: 1px solid #444;
            """
        )

        confidence_layout = QVBoxLayout()

        confidence_title = QLabel("CONFIDENCE")

        confidence_title.setStyleSheet(
            """
            color: white;
            font-size: 16px;
            """
        )

        self.confidence = QLabel("83%")

        self.confidence.setStyleSheet(
            """
            color: #66ff99;
            font-size: 38px;
            font-weight: bold;
            """
        )

        self.confidence.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ---------------------------------------------
        # CONFIDENCE BAR PLACEHOLDER
        # ---------------------------------------------
    
        confidence_bar = QLabel("▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮ ▮")

        confidence_bar.setStyleSheet(
            """
            color: #66ff99;
            font-size: 22px;
            """
        )

        confidence_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        confidence_layout.addWidget(confidence_title,1)
        confidence_layout.addWidget(self.confidence,2)
        confidence_layout.addWidget(confidence_bar,1)

        confidence_panel.setLayout(confidence_layout)

        # ---------------------------------------------
        # ADD TOP ROW
        # ---------------------------------------------

        top_row.addWidget(species_panel, 3)
        top_row.addWidget(confidence_panel, 1)

        center_layout.addLayout(top_row,1)


        # =================================================
        # BOTTOM ROW
        # =================================================

        bottom_row = QHBoxLayout()

        # ---------------------------------------------
        # SPECTROGRAM PANEL
        # ---------------------------------------------

        spectrogram_panel = QFrame()
        spectrogram_panel.setFrameShape(QFrame.Shape.Box)

        spectrogram_panel.setStyleSheet(
            """
            background-color: #101010;
            border: 1px solid #444;
            """
        )

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

        self.spectrogram_placeholder.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.spectrogram_placeholder.setStyleSheet(
            """
            color: #777777;
            font-size: 22px;
            padding: 60px;
            border: 2px dashed #444;
            """
        )

        spectrogram_layout.addWidget(spectrogram_title,1)
        spectrogram_layout.addWidget(self.spectrogram_placeholder,8)

        spectrogram_panel.setLayout(spectrogram_layout)

        # ---------------------------------------------
        # NODE MAP PANEL
        # ---------------------------------------------

        node_map_panel = QFrame()
        node_map_panel.setFrameShape(QFrame.Shape.Box)

        node_map_panel.setStyleSheet(
            """
            background-color: #101010;
            border: 1px solid #444;
            """
        )

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

        self.node_map_placeholder.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.node_map_placeholder.setStyleSheet(
            """
            color: #777777;
            font-size: 22px;
            padding: 60px;
            border: 2px dashed #444;
            """
        )

        node_map_layout.addWidget(node_map_title,1)
        node_map_layout.addWidget(self.node_map_placeholder,8)

        node_map_panel.setLayout(node_map_layout)

        # ---------------------------------------------
        # ADD BOTTOM ROW
        # ---------------------------------------------

        bottom_row.addWidget(spectrogram_panel)
        bottom_row.addWidget(node_map_panel)

        center_layout.addLayout(bottom_row,3)

        # =================================================
        # FINALIZE CENTER PANEL
        # =================================================

        center_panel.setLayout(center_layout)

        # =================================================
        # RIGHT PANEL: RECENT SPECIES
        # =================================================

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

        starter_species = [
            "Red-winged Blackbird",
            "Yellow Warbler",
            "House Finch",
            "Common Raven",
            "Western Tanager",
            "Song Sparrow",
            "Spotted Towhee",
            "Black-headed Grosbeak",
            "Bullock's Oriole",
            "Northern Flicker",
        ]

        for species in starter_species:
            self.species_list.addItem(species)

        right_layout.addWidget(species_title)
        right_layout.addSpacing(10)
        right_layout.addWidget(self.species_list)

        # =================================================
        # RARE BIRD ALERT SECTION
        # =================================================

        right_layout.addSpacing(20)

        alert_title = QLabel("RARE BIRD ALERTS")

        alert_title.setStyleSheet(
            """
            color: #ff6666;
            font-size: 18px;
            font-weight: bold;
            """
        )

        right_layout.addWidget(alert_title)

        # ---------------------------------------------
        # ALERT PANEL
        # ---------------------------------------------

        alert_panel = QFrame()
        alert_panel.setFrameShape(QFrame.Shape.Box)

        alert_panel.setStyleSheet(
            """
            background-color: #101010;
            border: 1px solid #444;
            """
        )

        alert_layout = QVBoxLayout()

        # ---------------------------------------------
        # ALERT TEXT
        # ---------------------------------------------

        self.alert_status = QLabel("First sighting in 74 days")

        self.alert_status.setStyleSheet(
            """
            color: #bbbbbb;
            font-size: 14px;
            padding-top: 10px;
            """
        )

        self.alert_species = QLabel("Bullock's Oriole")

        self.alert_species.setStyleSheet(
            """
            color: #ffcc66;
            font-size: 28px;
            font-weight: bold;
            padding-top: 6px;
            padding-bottom: 12px;
            """
        )

        last_seen_label = QLabel("Last Seen")

        last_seen_label.setStyleSheet(
            """
            color: #888888;
            font-size: 13px;
            """
        )

        self.last_seen_value = QLabel("March 3")
        
        self.last_seen_value.setStyleSheet(
            """
            color: white;
            font-size: 18px;
            padding-bottom: 12px;
            """
        )

        priority_label = QLabel("Priority")

        priority_label.setStyleSheet(
            """
            color: #888888;
            font-size: 13px;
            """
        )

        self.priority_value = QLabel("MEDIUM")

        self.priority_value.setStyleSheet(
            """
            color: #ffaa66;
            font-size: 20px;
            font-weight: bold;
            """
        )

        # ---------------------------------------------
        # ADD TO LAYOUT
        # ---------------------------------------------
        
        alert_layout.addWidget(self.alert_status)
        alert_layout.addWidget(self.alert_species)
        
        alert_layout.addSpacing(10)
        
        alert_layout.addWidget(last_seen_label)
        alert_layout.addWidget(self.last_seen_value)
        
        alert_layout.addSpacing(10)
        
        alert_layout.addWidget(priority_label)
        alert_layout.addWidget(self.priority_value)
        
        alert_layout.addStretch()
        
        alert_panel.setLayout(alert_layout)
        
        right_layout.addWidget(alert_panel)

        right_panel.setLayout(right_layout)

        # =================================================
        # ADD PANELS TO MAIN CONTENT
        # =================================================

        content_layout.addWidget(left_panel, 1)
        content_layout.addWidget(center_panel, 3)
        content_layout.addWidget(right_panel, 1)

        # =================================================
        # FOOTER: SYSTEM STATUS
        # =================================================

        footer = QFrame()
        footer.setFrameShape(QFrame.Shape.Box)
        footer.setStyleSheet(
            """
            background-color: #1f1f1f;
            border: 1px solid #444;
            """
        )

        footer_layout = QHBoxLayout()

        footer_layout.addWidget(StatusIndicator("PPS"))
        footer_layout.addWidget(StatusIndicator("GPS"))
        footer_layout.addWidget(StatusIndicator("BirdNET"))
        footer_layout.addWidget(StatusIndicator("Microphones"))
        footer_layout.addWidget(StatusIndicator("Sensors"))
        footer_layout.addWidget(StatusIndicator("Network"))
        footer_layout.addStretch()

        footer.setLayout(footer_layout)

        # =================================================
        # BUILD MAIN LAYOUT
        # =================================================

        main_layout.addWidget(header)
        main_layout.addLayout(content_layout)
        main_layout.addWidget(footer)

        # =================================================
        # TIMERS
        # =================================================

        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)

        self.fake_data_timer = QTimer()
        self.fake_data_timer.timeout.connect(self.fake_updates)
        self.fake_data_timer.start(3000)

        self.update_clock()

    # =====================================================
    # NODE SELECTION UPDATE
    # =====================================================

    def update_node_display(self, node_name):
        self.node_location.setText(self.nodes.get(node_name, "Unknown Node"))

    # =====================================================
    # CLOCK UPDATE
    # =====================================================

    def update_clock(self):
        now = datetime.now()
        self.timestamp.setText(now.strftime("%Y-%m-%d  %I:%M:%S %p"))

    # =====================================================
    # PLACEHOLDER DATA UPDATES
    # =====================================================

    def fake_updates(self):
        birds = [
            "Northern Flicker",
            "Western Tanager",
            "Song Sparrow",
            "Black-headed Grosbeak",
            "Bullock's Oriole",
            "Common Raven",
            "Yellow Warbler",
            "Tree Swallow",
        ]

        bird = random.choice(birds)
        confidence = random.randint(72, 99)

        self.current_bird.setText(bird)
        self.confidence.setText(f"Confidence: {confidence}%")

        temp = random.randint(45, 68)
        humidity = random.randint(20, 60)
        pressure = random.randint(1008, 1022)
        wind = random.randint(0, 18)

        self.temp_label.setText(f"Temperature: {temp}°F")
        self.humidity_label.setText(f"Humidity: {humidity}%")
        self.pressure_label.setText(f"Pressure: {pressure} mb")
        self.wind_label.setText(f"Wind: {wind} mph")


# =========================================================
# APPLICATION START
# =========================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)

    app.setStyleSheet(
        """
        QWidget {
            background-color: #121212;
            font-family: Arial;
        }
        """
    )

    window = EnviroPulseGUI()
    window.show()

    sys.exit(app.exec())