from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


def create_action_button(text: str) -> QPushButton:
    """A deliberately reused factory for the helper-function provenance case."""

    return QPushButton(text)


class InspectorPanel(QWidget):
    """A project-local QWidget subclass for custom-constructor discovery."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.heading = QLabel("Inspector")
        self.value = QLabel("Nothing selected")
        layout.addWidget(self.heading)
        layout.addWidget(self.value)

