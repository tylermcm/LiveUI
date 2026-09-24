from PySide6.QtWidgets import QPushButton


class FancyButton(QPushButton):
    pass


def make_button(text: str) -> QPushButton:
    return QPushButton(text)


def build_fancy_button(text: str) -> FancyButton:
    return FancyButton(text)

