from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from widgets import InspectorPanel, create_action_button


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LiveUI provenance demo")

        central = QWidget()
        root = QVBoxLayout(central)
        self.setCentralWidget(central)

        # Case A: direct constructor.
        self.title = QLabel("Settings")
        self.title.setObjectName("settingsTitle")
        root.addWidget(self.title)

        # Case B: a widget inside a nested layout hierarchy.
        toolbar = QHBoxLayout()
        nested_caption = QLabel("Actions")
        toolbar.addWidget(nested_caption)

        # Case D: multiple calls into one helper constructor site.
        self.open_button = create_action_button("Open")
        self.close_button = create_action_button("Close")
        toolbar.addWidget(self.open_button)
        toolbar.addWidget(self.close_button)
        root.addLayout(toolbar)

        # Case C: three runtime objects will share this one constructor site.
        self.loop_buttons = []
        loop_row = QHBoxLayout()
        for label in ["One", "Two", "Three"]:
            button = QPushButton(label)
            self.loop_buttons.append(button)
            loop_row.addWidget(button)
        root.addLayout(loop_row)

        # Case E: an ordinary project-local QWidget subclass.
        self.inspector = InspectorPanel()
        root.addWidget(self.inspector)

        # Case F: explicit QGridLayout positions.
        grid = QGridLayout()
        name_label = QLabel("Name")
        self.name_edit = QLineEdit()
        status_label = QLabel("Ready")
        grid.addWidget(name_label, 0, 0)
        grid.addWidget(self.name_edit, 0, 1)
        grid.addWidget(status_label, 1, 0, 1, 2)
        root.addLayout(grid)

        # Case G: retain a normal signal connection for future graph work.
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("saveButton")
        self.save_button.clicked.connect(self.handle_save)
        root.addWidget(self.save_button)
        self.status_label = status_label

    def handle_save(self):
        self.status_label.setText("Saved")

