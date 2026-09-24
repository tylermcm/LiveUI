"""Run Gate 4 against the real locally installed Claude Code client."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from gate4_tools import get_selected_component, prepare_workspace
from shadow import generate_shadow
from shadow_poc import inspect_shadow_process, validate_shadow_provenance


REPO_ROOT = Path(__file__).resolve().parent.parent
POC_ROOT = Path(__file__).resolve().parent
DEFAULT_CLAUDE = Path("C:/Users/tylle/.local/bin/claude.exe")


def _windows_cli_environment() -> dict[str, str]:
    environment = os.environ.copy()
    user_profile = Path("C:/Users/tylle")
    values = {
        "SystemRoot": "C:/Windows",
        "WINDIR": "C:/Windows",
        "ComSpec": "C:/Windows/System32/cmd.exe",
        "USERPROFILE": str(user_profile),
        "HOMEDRIVE": "C:",
        "HOMEPATH": "/Users/tylle",
        "APPDATA": str(user_profile / "AppData/Roaming"),
        "LOCALAPPDATA": str(user_profile / "AppData/Local"),
        "TEMP": str(user_profile / "AppData/Local/Temp"),
        "TMP": str(user_profile / "AppData/Local/Temp"),
        "PROGRAMDATA": "C:/ProgramData",
        "PYTHONHASHSEED": "0",
        "QT_QPA_PLATFORM": "offscreen",
    }
    environment.update(values)
    python_paths = [str(POC_ROOT), str(REPO_ROOT / "src")]
    existing_python_path = environment.get("PYTHONPATH")
    if existing_python_path:
        python_paths.append(existing_python_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    return environment


def _walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _tool_commands(events: list[dict[str, Any]]) -> list[str]:
    commands = []
    for event in events:
        for value in _walk_json(event):
            if value.get("type") != "tool_use" or value.get("name") != "Bash":
                continue
            tool_input = value.get("input")
            if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
                commands.append(tool_input["command"])
    return commands


def _relative_state(state_path: Path) -> str:
    return state_path.resolve().relative_to(REPO_ROOT).as_posix()


def run_gate4(
    *,
    claude_executable: Path = DEFAULT_CLAUDE,
    workspace_root: Path = REPO_ROOT / ".gate4_workspace",
) -> dict[str, Any]:
    state_path = prepare_workspace(workspace_root)
    relative_state = _relative_state(state_path)
    get_command = (
        "python liveui-poc/gate4_tools.py get_selected_component "
        f"--state {relative_state}"
    )
    set_command_template = (
        "python liveui-poc/gate4_tools.py set_minimum_width "
        f"--state {relative_state} --runtime-id <runtime_id> "
        "--width 340 --base-revision <revision>"
    )
    prompt = f"""You are operating a deliberately constrained LiveUI feasibility interface.

User request: Make the selected button about 340 pixels wide.

You have exactly two permitted interface operations, both exposed as Bash commands.
First call this command exactly to obtain the selected component:
{get_command}

Read its JSON result. If it identifies the selected Save button, call this second
operation, replacing both angle-bracket placeholders with the exact values returned:
{set_command_template}

Do not read or edit files directly, do not call any other command, and do not invent
IDs or revisions. After the second operation returns, briefly report its status.
"""
    allowed_get = "Bash(python liveui-poc/gate4_tools.py get_selected_component *)"
    allowed_set = "Bash(python liveui-poc/gate4_tools.py set_minimum_width *)"
    command = [
        str(claude_executable.resolve()),
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--safe-mode",
        "--no-session-persistence",
        "--tools",
        "Bash",
        "--allowedTools",
        allowed_get,
        allowed_set,
        "--permission-mode",
        "dontAsk",
    ]
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=_windows_cli_environment(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    events = []
    for line in completed.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    audit_path = state_path.parent / "claude_stream.jsonl"
    audit_path.write_text(completed.stdout, encoding="utf-8")

    result_events = [event for event in events if event.get("type") == "result"]
    terminal = result_events[-1] if result_events else {}
    if terminal.get("is_error"):
        error_text = str(terminal.get("result", "Claude model call failed"))
        status = (
            "BLOCKED_AUTHENTICATION"
            if "authenticate" in error_text.lower() or "oauth" in error_text.lower()
            else "BLOCKED_CLAUDE_ERROR"
        )
        return {
            "status": status,
            "reason": error_text,
            "claude_exit_code": completed.returncode,
            "state_path": str(state_path),
            "audit_path": str(audit_path),
        }

    state = json.loads(state_path.read_text(encoding="utf-8"))
    commands = _tool_commands(events)
    last_commit = state.get("last_commit")
    if last_commit is None:
        return {
            "status": "FAIL",
            "reason": "Claude returned without committing through set_minimum_width",
            "tool_commands": commands,
            "state_path": str(state_path),
            "audit_path": str(audit_path),
        }

    project = Path(state["project_root"])
    build = generate_shadow(project)
    resolved = validate_shadow_provenance(inspect_shadow_process(build.workspace))
    save = resolved["save"]
    cancel = resolved["cancel"]
    get_calls = [item for item in commands if "get_selected_component" in item]
    set_calls = [item for item in commands if "set_minimum_width" in item]
    passed = (
        len(get_calls) == 1
        and len(set_calls) == 1
        and last_commit["status"] == "COMMITTED"
        and state["revision"] == 2
        and save["minimum_width"] == 340
        and cancel["minimum_width"] == 120
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "model_tool_calls": len(commands),
        "get_selected_component_calls": len(get_calls),
        "set_minimum_width_calls": len(set_calls),
        "committed_revision": state["revision"],
        "verified_save_width": save["minimum_width"],
        "verified_cancel_width": cancel["minimum_width"],
        "last_commit": last_commit,
        "state_path": str(state_path),
        "audit_path": str(audit_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", type=Path, default=DEFAULT_CLAUDE)
    parser.add_argument("--prepare-only", action="store_true")
    arguments = parser.parse_args()

    if arguments.prepare_only:
        state_path = prepare_workspace(REPO_ROOT / ".gate4_workspace")
        selected = get_selected_component(state_path)
        print(
            "GATE4_PREPARED="
            + json.dumps(
                {"state_path": str(state_path), "selection": selected}, sort_keys=True
            )
        )
        return 0

    try:
        result = run_gate4(claude_executable=arguments.claude)
    except Exception as error:
        result = {"status": "FAIL", "reason": f"{type(error).__name__}: {error}"}
    print("GATE4_RESULT=" + json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
