import sys
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(POC_ROOT))

from poc import inspect_in_target_process, run_round_trip
from transform import set_minimum_width


def test_constructor_interception_captures_qpushbutton_and_qlabel(tmp_path: Path):
    target = tmp_path / "probe.py"
    target.write_text(
        "from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget\n\n"
        "class MainWindow(QWidget):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        layout = QVBoxLayout(self)\n"
        "        self.label = QLabel('Probe')\n"
        "        layout.addWidget(self.label)\n"
        "        self.button = QPushButton('Push')\n"
        "        layout.addWidget(self.button)\n",
        encoding="utf-8",
    )

    snapshot = inspect_in_target_process(target)
    widgets = {widget["binding"]: widget for widget in snapshot["widgets"]}

    assert widgets["self.label"]["qt_class"] == "QLabel"
    assert widgets["self.label"]["text"] == "Probe"
    assert widgets["self.button"]["qt_class"] == "QPushButton"
    assert widgets["self.button"]["text"] == "Push"


def test_gate_1_distinguishes_runtime_instances_and_shares_loop_anchor():
    snapshot = inspect_in_target_process(POC_ROOT / "demo_app.py")
    widgets = snapshot["widgets"]
    loop = [widget for widget in widgets if widget["binding"] == "button"]

    assert next(widget for widget in widgets if widget["binding"] == "self.save")["text"] == "Save"
    assert next(widget for widget in widgets if widget["binding"] == "self.cancel")["text"] == "Cancel"
    assert len(loop) == 3
    assert len({widget["runtime_id"] for widget in loop}) == 3
    assert len({widget["source_anchor"] for widget in loop}) == 1
    assert len({widget["source_line"] for widget in loop}) == 1


def test_transform_targets_binding_not_shared_literal():
    source = (POC_ROOT / "demo_app.py").read_text(encoding="utf-8")

    result = set_minimum_width(source, binding="self.save", width=280)

    assert result.status == "applied"
    assert "self.save.setMinimumWidth(280)" in result.source
    assert "self.cancel.setMinimumWidth(120)" in result.source
    compile(result.source, "demo_app.py", "exec")


def test_transform_refuses_unknown_binding_without_mutation():
    source = (POC_ROOT / "demo_app.py").read_text(encoding="utf-8")

    result = set_minimum_width(source, binding="self.dynamic", width=280)

    assert result.status == "unsupported"
    assert result.source == source


def test_full_round_trip_restarts_reacquires_and_verifies(tmp_path: Path):
    target = tmp_path / "demo_app.py"
    target.write_bytes((POC_ROOT / "demo_app.py").read_bytes())

    report = run_round_trip(target, width=280, emit=False)
    final_snapshot = inspect_in_target_process(target)
    save = next(widget for widget in final_snapshot["widgets"] if widget["binding"] == "self.save")
    cancel = next(
        widget for widget in final_snapshot["widgets"] if widget["binding"] == "self.cancel"
    )

    assert report["status"] == "PASS"
    assert report["before_epoch"] != report["after_epoch"]
    assert report["before_runtime_id"] != report["after_runtime_id"]
    assert save["minimum_width"] == 280
    assert cancel["minimum_width"] == 120

