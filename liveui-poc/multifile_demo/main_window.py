from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from widgets import InspectorPanel, create_action_button


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.save = create_action_button("Save")
        self.save.setObjectName("saveButton")
        self.save.setMinimumWidth(120)
        layout.addWidget(self.save)

        self.cancel = create_action_button("Cancel")
        self.cancel.setObjectName("cancelButton")
        self.cancel.setMinimumWidth(120)
        layout.addWidget(self.cancel)

        for label in ["One", "Two", "Three"]:
            button = QPushButton(label)
            layout.addWidget(button)

        self.inspector = InspectorPanel()
        layout.addWidget(self.inspector)

