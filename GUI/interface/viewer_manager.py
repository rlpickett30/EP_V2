# ============================================================
# viewer_manager.py
#
# EnviroPulse V2
#
# Subsystem:
#   Interface
#
# Role:
#   Manager
#
# Purpose:
#   Own the visible GUI layout.
#
# Does:
#   - Display repository or journal-style updates
#   - Allow node selection
#   - Provide operator command buttons
#
# Does NOT:
#   - Publish events
#   - Build event payloads
#   - Decide command meaning
#   - Route events
#   - Store state
#
# Owner:
#   interface_dispatcher.py
#
# ============================================================

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QComboBox,
    QPushButton,
    QLabel,
    QGroupBox
)


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class ViewerManager(QWidget):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            "EnviroPulse V2"
        )

        self.resize(
            800,
            600
        )

        main_layout = QVBoxLayout()

        # --------------------------------------------
        # Node Selection
        # --------------------------------------------

        node_label = QLabel(
            "Node Selection"
        )

        main_layout.addWidget(
            node_label
        )

        self.node_selector = QComboBox()

        main_layout.addWidget(
            self.node_selector
        )

        # --------------------------------------------
        # Network Mode Change
        # --------------------------------------------

        network_group = QGroupBox(
            "Network Mode Change"
        )

        network_layout = QHBoxLayout()

        self.enable_wifi_button = QPushButton(
            "Node: Enable WiFi"
        )

        self.enable_lora_button = QPushButton(
            "Node: Enable LoRa"
        )

        network_layout.addWidget(
            self.enable_wifi_button
        )

        network_layout.addWidget(
            self.enable_lora_button
        )

        network_group.setLayout(
            network_layout
        )

        main_layout.addWidget(
            network_group
        )

        # --------------------------------------------
        # Detection Mode Change
        # --------------------------------------------

        detection_group = QGroupBox(
            "Detection Mode Change"
        )

        detection_layout = QHBoxLayout()

        self.energy_onset_button = QPushButton(
            "Enable Energy Onset"
        )

        self.pattern_onset_button = QPushButton(
            "Enable Pattern Onset"
        )

        detection_layout.addWidget(
            self.energy_onset_button
        )

        detection_layout.addWidget(
            self.pattern_onset_button
        )

        detection_group.setLayout(
            detection_layout
        )

        main_layout.addWidget(
            detection_group
        )

        # --------------------------------------------
        # Feature Mode Change
        # --------------------------------------------

        feature_group = QGroupBox(
            "Feature Mode Change"
        )

        feature_layout = QHBoxLayout()

        self.amp_feature_button = QPushButton(
            "Enable Amplitude Feature"
        )

        self.onset_feature_button = QPushButton(
            "Enable Onset Feature"
        )

        feature_layout.addWidget(
            self.amp_feature_button
        )

        feature_layout.addWidget(
            self.onset_feature_button
        )

        feature_group.setLayout(
            feature_layout
        )

        main_layout.addWidget(
            feature_group
        )

        # --------------------------------------------
        # Event Display
        # --------------------------------------------

        self.event_view = QTextEdit()

        self.event_view.setReadOnly(
            True
        )

        main_layout.addWidget(
            self.event_view
        )

        self.setLayout(
            main_layout
        )

    # ========================================================
    # DISPLAY EVENT
    # ========================================================

    def display_event(
        self,
        event: dict
    ):

        self.event_view.append(
            str(event)
        )

    # ========================================================
    # UPDATE NODES
    # ========================================================

    def update_nodes(
        self,
        nodes: list
    ):

        self.node_selector.clear()

        self.node_selector.addItems(
            nodes
        )