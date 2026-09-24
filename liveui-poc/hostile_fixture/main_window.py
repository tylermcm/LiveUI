"""Adversarial source patterns for conservative provenance resolution."""

from __future__ import annotations

from PySide6 import QtWidgets
from PySide6.QtWidgets import QPushButton, QPushButton as Btn, QVBoxLayout, QWidget

from helpers import build_fancy_button, make_button


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.save = make_button("Save")
        self.save_as = make_button("Save As")
        self.cancel = make_button("Cancel")
        self.fancy = build_fancy_button("Fancy")

        self.alias = Btn("Alias")
        self.qualified = QtWidgets.QPushButton("Qualified")
        self.annotated: QPushButton = QPushButton("Annotated")

        if True:
            self.conditional = QPushButton("Conditional")

        factory = QPushButton
        self.dynamic = factory("Dynamic")

        names = ["One", "Two", "Three"]
        self.buttons = [QPushButton(name) for name in names]

        for widget in [
            self.save,
            self.save_as,
            self.cancel,
            self.fancy,
            self.alias,
            self.qualified,
            self.annotated,
            self.conditional,
            self.dynamic,
            *self.buttons,
        ]:
            layout.addWidget(widget)

