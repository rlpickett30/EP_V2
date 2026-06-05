# ============================================================
# viewer_manager.py
#
# EnviroPulse V2
#
# V1 Test Viewer
#
# Responsibilities:
#   - Display repository updates
#   - Allow node selection
#
# ============================================================

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QComboBox,
    QPushButton
)


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

        layout = QVBoxLayout()

        # --------------------------------------------
        # Node Selection
        # --------------------------------------------

        self.node_selector = (
            QComboBox()
        )

        layout.addWidget(
            self.node_selector
        )

        # --------------------------------------------
        # Test Button
        # --------------------------------------------

        self.test_button = (
            QPushButton(
                "Enable WiFi"
            )
        )

        layout.addWidget(
            self.test_button
        )

        # --------------------------------------------
        # Event Display
        # --------------------------------------------

        self.event_view = (
            QTextEdit()
        )

        self.event_view.setReadOnly(
            True
        )

        layout.addWidget(
            self.event_view
        )

        self.setLayout(
            layout
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

