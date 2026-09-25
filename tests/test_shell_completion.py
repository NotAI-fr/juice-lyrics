from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics import cli
from juice_lyrics.services.shell_completion import completion_tree, generate_completion


EXPECTED_COMMAND_PATHS = {
    ("setup",),
    ("sync",),
    ("status",),
    ("scan",),
    ("embed",),
    ("verify",),
    ("restore",),
    ("doctor",),
    ("completion",),
    ("guide",),
    ("tui",),
    ("search",),
    ("info",),
    ("acquire",),
    ("acquire", "search"),
    ("acquire", "add"),
    ("acquire", "manifest"),
    ("acquire", "jobs"),
    ("acquire", "run"),
    ("acquire", "retry"),
    ("acquire", "delete"),
    ("rmpc",),
    ("rmpc", "setup"),
    ("rmpc", "sync"),
    ("rmpc", "verify"),
    ("config",),
    ("config", "init"),
    ("config", "show"),
    ("cache",),
    ("cache", "clear"),
    ("state",),
    ("state", "clean"),
    ("state", "rebuild-identities"),
}


def _nodes(root):
    yield root
    for child in root.children:
        yield from _nodes(child)


def _parser_options(parser: argparse.ArgumentParser) -> set[str]:
    options: set[str] = set()
    for action in parser._actions:
        options.update(action.option_strings)
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                options.update(_parser_options(child))
    return options


def test_completion_model_covers_the_current_argparse_command_tree():
    parser = cli.build_parser()
    root = completion_tree(parser)
    nodes = tuple(_nodes(root))

    assert {node.path for node in nodes if node.path} == EXPECTED_COMMAND_PATHS
    assert {name for node in nodes for option in node.options for name in option.names} == _parser_options(parser)
    completion_node = next(node for node in nodes if node.path == ("completion",))
    assert completion_node.positional_choices == ("bash", "zsh", "fish")


@pytest.mark.parametrize("shell", ("bash", "zsh", "fish"))
def test_generated_completion_is_deterministic_and_covers_commands_and_options(shell):
    parser = cli.build_parser()

    first = generate_completion(parser, shell)
    second = generate_completion(parser, shell)

    assert first == second
    assert first.endswith("\n")
    for path in EXPECTED_COMMAND_PATHS:
        for command in path:
            assert command in first
    for option in _parser_options(parser):
        rendered = (
            f"-l {option[2:]}" if shell == "fish" and option.startswith("--")
            else f"-s {option[1:]}" if shell == "fish"
            else option
        )
        assert rendered in first
    expected_long_options = (
        ("-l support-report", "-l save-report", "-l include-locked", "-l dry-run")
        if shell == "fish"
        else ("--support-report", "--save-report", "--include-locked", "--dry-run")
    )
    assert all(option in first for option in expected_long_options)
    assert "--retry-all" not in first
    assert "--force-match" not in first
    assert "--cancel-download" not in first


@pytest.mark.parametrize("shell", ("bash", "zsh", "fish"))
def test_completion_command_skips_settings_state_and_catalogue(shell, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("settings loaded")),
    )
    monkeypatch.setattr(
        cli,
        "api_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("catalogue accessed")),
    )

    assert cli.main(["completion", shell]) == 0

    output = capsys.readouterr().out
    assert output
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("shell", "binding"),
    (
        ("bash", "complete -F _999_complete"),
        ("zsh", "compdef _999"),
        ("fish", "complete -c"),
    ),
)
def test_completion_supports_primary_and_legacy_commands(shell, binding):
    script = generate_completion(cli.build_parser(), shell)

    assert f"{binding} 999" in script
    assert "juice-lyrics" in script


@pytest.mark.parametrize("shell", ("bash", "zsh", "fish"))
def test_generated_script_has_valid_syntax_when_shell_is_available(shell, tmp_path):
    executable = shutil.which(shell)
    if executable is None:
        pytest.skip(f"{shell} is not installed")
    script = tmp_path / f"999.{shell}"
    script.write_text(generate_completion(cli.build_parser(), shell), encoding="utf-8")

    result = subprocess.run(
        [executable, "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_bash_completion_handles_global_options_and_nested_commands(tmp_path):
    script = tmp_path / "999.bash"
    script.write_text(generate_completion(cli.build_parser(), "bash"), encoding="utf-8")
    probe = tmp_path / "probe.bash"
    probe.write_text(
        f'''source "{script}"
COMP_WORDS=(999 --no-color state "")
COMP_CWORD=3
_999_complete
printf '%s\n' "${{COMPREPLY[@]}}"
printf '%s\n' --separator--
COMP_WORDS=(999 state rebuild-identities --d)
COMP_CWORD=3
_999_complete
printf '%s\n' "${{COMPREPLY[@]}}"
''',
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(probe)],
        check=True,
        capture_output=True,
        text=True,
    )

    first, second = result.stdout.split("--separator--\n")
    assert {"clean", "rebuild-identities"} <= set(first.splitlines())
    assert second.splitlines() == ["--details"]
