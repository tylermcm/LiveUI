from pathlib import Path

from liveui.provenance.anchors import analyze_project


def test_project_analysis_is_deterministic_and_uses_posix_paths(tmp_path: Path):
    package = tmp_path / "ui"
    package.mkdir()
    (package / "panel.py").write_text(
        "from PySide6.QtWidgets import QWidget\nvalue = QWidget()\n",
        encoding="utf-8",
    )

    first = analyze_project(tmp_path)
    second = analyze_project(tmp_path)

    assert list(first) == ["ui/panel.py"]
    assert first == second


def test_transitive_custom_widget_inheritance_is_supported(tmp_path: Path):
    (tmp_path / "base.py").write_text(
        "from PySide6.QtWidgets import QWidget\nclass BasePanel(QWidget):\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "view.py").write_text(
        "class DetailPanel(BasePanel):\n"
        "    pass\n\n"
        "panel = DetailPanel()\n",
        encoding="utf-8",
    )

    index = analyze_project(tmp_path)
    site = next(site for site in index["view.py"] if site.source_text == "DetailPanel()")

    assert site.symbol == "DetailPanel"

