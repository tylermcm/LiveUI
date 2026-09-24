from pathlib import Path

from liveui.provenance.anchors import (
    analyze_project,
    analyze_source,
    discover_custom_widget_classes,
)


PROJECT_ROOT = Path(__file__).parents[1]
DEMO_ROOT = PROJECT_ROOT / "examples" / "provenance_demo"


def _all_sites():
    return [site for sites in analyze_project(DEMO_ROOT).values() for site in sites]


def test_direct_widget_constructors_have_file_scope_and_positions():
    sites = _all_sites()
    title = next(site for site in sites if site.source_text == 'QLabel("Settings")')
    save = next(site for site in sites if site.source_text == 'QPushButton("Save")')

    assert title.anchor.relative_path == "main_window.py"
    assert title.anchor.qualified_scope == "MainWindow.__init__"
    assert title.semantic_kind == "widget_constructor"
    assert title.anchor.start_line > 0
    assert title.anchor.end_column > title.anchor.start_column
    assert save.anchor.anchor_id != title.anchor.anchor_id


def test_nested_loop_and_grid_widget_sites_are_discovered():
    sites = _all_sites()

    assert any(site.source_text == 'QLabel("Actions")' for site in sites)
    loop_site = next(site for site in sites if site.source_text == "QPushButton(label)")
    assert loop_site.anchor.qualified_scope == "MainWindow.__init__"
    assert any(
        site.semantic_kind == "layout_operation"
        and site.source_text == "grid.addWidget(self.name_edit, 0, 1)"
        for site in sites
    )


def test_helper_constructor_is_one_static_site_for_multiple_callers():
    index = analyze_project(DEMO_ROOT)
    helper_sites = [
        site
        for site in index["widgets.py"]
        if site.source_text == "QPushButton(text)"
    ]

    assert len(helper_sites) == 1
    assert helper_sites[0].anchor.qualified_scope == "create_action_button"


def test_custom_widget_subclass_and_constructor_are_discovered():
    sources = [path.read_text(encoding="utf-8") for path in DEMO_ROOT.glob("*.py")]
    assert "InspectorPanel" in discover_custom_widget_classes(sources)

    custom_site = next(site for site in _all_sites() if site.source_text == "InspectorPanel()")
    assert custom_site.symbol == "InspectorPanel"
    assert custom_site.semantic_kind == "widget_constructor"

    main_window_site = next(
        site
        for site in analyze_project(DEMO_ROOT)["main.py"]
        if site.source_text == "MainWindow()"
    )
    assert main_window_site.symbol == "MainWindow"


def test_signal_connection_is_retained_as_future_graph_site():
    connection = next(
        site
        for site in _all_sites()
        if site.source_text == "self.save_button.clicked.connect(self.handle_save)"
    )

    assert connection.semantic_kind == "signal_connection"
    assert connection.symbol == "connect"


def test_anchor_survives_unrelated_preceding_line_insertion():
    before = '''\
from PySide6.QtWidgets import QLabel

class Panel:
    def build(self):
        self.title = QLabel("Settings")
'''
    after = '''\
from PySide6.QtWidgets import QLabel

UNRELATED = 42

class Panel:
    def build(self):
        ignored = "new statement"
        self.title = QLabel("Settings")
'''
    first = analyze_source(before, relative_path="ui/panel.py")[0].anchor
    second = analyze_source(after, relative_path="ui/panel.py")[0].anchor

    assert first.equivalent_to(second)
    assert first.start_line != second.start_line
    assert first.source_revision != second.source_revision
    assert first.normalized_node_hash == second.normalized_node_hash


def test_formatting_changes_do_not_change_normalized_syntax_identity():
    compact = "from PySide6.QtWidgets import QLabel\nvalue = QLabel('same')\n"
    spaced = 'from PySide6.QtWidgets import QLabel\nvalue = QLabel(  "same"  )\n'

    compact_anchor = analyze_source(compact, relative_path="view.py")[0].anchor
    spaced_anchor = analyze_source(spaced, relative_path="view.py")[0].anchor

    assert compact_anchor.equivalent_to(spaced_anchor)


def test_identical_sites_in_one_scope_are_distinct_but_explicitly_ordered():
    source = '''\
from PySide6.QtWidgets import QLabel

def build():
    first = QLabel("same")
    second = QLabel("same")
'''
    sites = analyze_source(source, relative_path="view.py")

    assert len(sites) == 2
    assert sites[0].anchor.anchor_id != sites[1].anchor.anchor_id
    assert sites[0].anchor.structural_path.endswith("[0]")
    assert sites[1].anchor.structural_path.endswith("[1]")
