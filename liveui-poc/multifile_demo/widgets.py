from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


def create_action_button(text: str) -> QPushButton:
    return QPushButton(text)


class InspectorPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.heading = QLabel("Inspector")
        layout.addWidget(self.heading)

