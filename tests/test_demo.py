from PySide6.QtWidgets import QPushButton

from main_window import MainWindow
from widgets import InspectorPanel


def test_demo_exercises_required_widget_patterns(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.title.text() == "Settings"
    assert isinstance(window.inspector, InspectorPanel)
    assert [button.text() for button in window.loop_buttons] == ["One", "Two", "Three"]
    assert len({id(button) for button in window.loop_buttons}) == 3
    assert len(window.findChildren(QPushButton)) >= 6


def test_demo_signal_remains_ordinary_qt(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    window.save_button.click()

    assert window.status_label.text() == "Saved"

