import sys

from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        self.save = QPushButton("Save")
        self.save.setObjectName("saveButton")
        self.save.setMinimumWidth(120)
        layout.addWidget(self.save)

        self.cancel = QPushButton("Cancel")
        self.cancel.setObjectName("cancelButton")
        self.cancel.setMinimumWidth(120)
        layout.addWidget(self.cancel)

        for label in ["One", "Two", "Three"]:
            button = QPushButton(label)
            layout.addWidget(button)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

