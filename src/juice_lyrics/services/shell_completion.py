from __future__ import annotations

import argparse
from dataclasses import dataclass
import shlex


@dataclass(frozen=True, slots=True)
class CompletionOption:
    names: tuple[str, ...]
    description: str
    takes_value: bool
    choices: tuple[str, ...] = ()
    path_value: bool = False


@dataclass(frozen=True, slots=True)
class CompletionNode:
    path: tuple[str, ...]
    description: str
    options: tuple[CompletionOption, ...]
    positional_choices: tuple[str, ...]
    children: tuple["CompletionNode", ...]


_PATH_DESTINATIONS = {
    "path",
    "save_report",
    "config",
    "lyrics_dir",
    "destination",
    "manifest",
    "manifest_path",
    "backup",
}


def _description(value: object) -> str:
    if value is None or value is argparse.SUPPRESS:
        return ""
    return " ".join(str(value).split())


def _takes_value(action: argparse.Action) -> bool:
    return not isinstance(
        action,
        (
            argparse._HelpAction,
            argparse._StoreTrueAction,
            argparse._StoreFalseAction,
            argparse._VersionAction,
            argparse._CountAction,
        ),
    ) and action.nargs != 0


def completion_tree(parser: argparse.ArgumentParser) -> CompletionNode:
    """Build a small immutable completion model from the real argparse tree."""

    def visit(
        current: argparse.ArgumentParser,
        path: tuple[str, ...],
        description: str,
    ) -> CompletionNode:
        options: list[CompletionOption] = []
        positional_choices: list[str] = []
        children: list[CompletionNode] = []
        for action in current._actions:
            if isinstance(action, argparse._SubParsersAction):
                help_by_name = {
                    choice.dest: _description(choice.help)
                    for choice in action._choices_actions
                }
                for name, child_parser in action.choices.items():
                    children.append(
                        visit(child_parser, (*path, name), help_by_name.get(name, ""))
                    )
                continue
            if action.option_strings:
                options.append(
                    CompletionOption(
                        tuple(action.option_strings),
                        _description(action.help),
                        _takes_value(action),
                        tuple(str(item) for item in action.choices)
                        if action.choices
                        else (),
                        action.dest in _PATH_DESTINATIONS,
                    )
                )
            elif action.choices:
                positional_choices.extend(str(item) for item in action.choices)
        return CompletionNode(
            path,
            description,
            tuple(options),
            tuple(positional_choices),
            tuple(children),
        )

    return visit(parser, (), _description(parser.description))


def _flatten(root: CompletionNode) -> tuple[CompletionNode, ...]:
    values = [root]
    for child in root.children:
        values.extend(_flatten(child))
    return tuple(values)


def _all_option_names(node: CompletionNode) -> tuple[str, ...]:
    return tuple(name for option in node.options for name in option.names)


def _bash(root: CompletionNode) -> str:
    nodes = _flatten(root)
    root_commands = "|".join(child.path[-1] for child in root.children)
    lines = [
        "# bash completion for 999 (generated from the argparse command tree)",
        "_999_complete() {",
        "    local cur prev path first second command_index i",
        "    COMPREPLY=()",
        "    cur=\"${COMP_WORDS[COMP_CWORD]}\"",
        "    prev=\"${COMP_WORDS[COMP_CWORD-1]}\"",
        "    first=",
        "    second=",
        "    command_index=0",
        "    for ((i=1; i<COMP_CWORD; i++)); do",
        "        case \"${COMP_WORDS[i]}\" in",
        f"            {root_commands}) first=\"${{COMP_WORDS[i]}}\"; command_index=$i; break ;;",
        "        esac",
        "    done",
        "    path=\"$first\"",
    ]
    parents = [node for node in nodes if node.children]
    for node in parents:
        if not node.path:
            continue
        children = "|".join(child.path[-1] for child in node.children)
        lines.extend((
            f"    if [[ \"$first\" == {shlex.quote(node.path[0])} ]]; then",
            "        second=\"${COMP_WORDS[command_index+1]}\"",
            "        case \"$second\" in",
            f"            {children}) path=\"$first $second\" ;;",
            "        esac",
            "    fi",
        ))
    lines.append("    case \"$path\" in")
    for node in nodes:
        key = "" if not node.path else " ".join(node.path)
        opts = " ".join(_all_option_names(node))
        choices = " ".join(node.positional_choices)
        children = " ".join(child.path[-1] for child in node.children)
        lines.append(f"        {shlex.quote(key)})")
        for option in node.options:
            if option.takes_value and (option.choices or option.path_value):
                names = "|".join(option.names)
                lines.append("            case \"$prev\" in")
                lines.append(f"                {names})")
                if option.choices:
                    values = shlex.quote(" ".join(option.choices))
                    lines.append(
                        f"                    COMPREPLY=( $(compgen -W {values} -- \"$cur\") )"
                    )
                else:
                    lines.append("                    COMPREPLY=( $(compgen -f -- \"$cur\") )")
                lines.extend(("                    return", "                    ;;", "            esac"))
        if node.children:
            lines.append("            if (( command_index == 0 || COMP_CWORD == command_index + 1 )); then")
            values = shlex.quote((children + " " + opts).strip())
            lines.append(
                f"                COMPREPLY=( $(compgen -W {values} -- \"$cur\") )"
            )
            lines.extend(("                return", "            fi"))
        if choices:
            lines.append("            if (( COMP_CWORD == command_index + " + str(len(node.path)) + " )); then")
            values = shlex.quote((choices + " " + opts).strip())
            lines.append(
                f"                COMPREPLY=( $(compgen -W {values} -- \"$cur\") )"
            )
            lines.extend(("                return", "            fi"))
        lines.append(f"            COMPREPLY=( $(compgen -W {shlex.quote(opts)} -- \"$cur\") )")
        lines.append("            ;;")
    lines.extend((
        "        *) COMPREPLY=() ;;",
        "    esac",
        "}",
        "complete -F _999_complete 999",
        "complete -F _999_complete juice-lyrics",
        "",
    ))
    return "\n".join(lines)


def _zsh_quote(value: str) -> str:
    return value.replace("'", "'\\''").replace(":", "\\:")


def _zsh(root: CompletionNode) -> str:
    nodes = _flatten(root)
    root_commands = "|".join(child.path[-1] for child in root.children)
    lines = [
        "#compdef 999 juice-lyrics",
        "# zsh completion for 999 (generated from the argparse command tree)",
        "_999() {",
        "  local path= first= second=",
        "  integer command_index=0 i",
        "  for ((i=2; i<CURRENT; i++)); do",
        "    case $words[i] in",
        f"      ({root_commands}) first=$words[i]; command_index=$i; break ;;",
        "    esac",
        "  done",
        "  path=$first",
    ]
    for node in nodes:
        if len(node.path) == 1 and node.children:
            child_pattern = "|".join(child.path[-1] for child in node.children)
            lines.append(
                f"  if [[ $first == {shlex.quote(node.path[0])} ]]; then "
                f"second=$words[command_index+1]; case $second in ({child_pattern}) "
                'path="$first $second" ;; esac; fi'
            )
    lines.extend(("  local -a values", "  case $path in"))
    for node in nodes:
        key = "" if not node.path else " ".join(node.path)
        candidates: list[tuple[str, str]] = []
        candidates.extend((child.path[-1], child.description or "command") for child in node.children)
        candidates.extend((choice, "value") for choice in node.positional_choices)
        candidates.extend((name, option.description or "option") for option in node.options for name in option.names)
        lines.append(f"    {shlex.quote(key)})")
        described = [f"{value}:{_zsh_quote(desc)}" for value, desc in candidates]
        lines.append("      values=(" + " ".join(shlex.quote(value) for value in described) + ")")
        for option in node.options:
            if option.takes_value and (option.choices or option.path_value):
                names = "|".join(option.names)
                lines.append(f"      case $words[CURRENT-1] in ({names})")
                if option.choices:
                    lines.append("        compadd -- " + " ".join(shlex.quote(item) for item in option.choices))
                else:
                    lines.append("        _files")
                lines.extend(("        return", "        ;;", "      esac"))
        lines.extend(("      _describe '999 command or option' values", "      ;;"))
    lines.extend(("  esac", "}", "compdef _999 999 juice-lyrics", ""))
    return "\n".join(lines)


def _fish_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _fish_condition(path: tuple[str, ...], *, exact: bool) -> str:
    function = "__999_at_path" if exact else "__999_in_path"
    return function + (" " + " ".join(shlex.quote(item) for item in path) if path else "")


def _fish(root: CompletionNode) -> str:
    root_commands = " ".join(child.path[-1] for child in root.children)
    lines = [
        "# fish completion for 999 (generated from the argparse command tree)",
        "function __999_in_path",
        "    set -l words (commandline -opc)",
        "    test (count $argv) -gt 0; or return 0",
        "    for start in (seq 2 (count $words))",
        "        set -l matched 1",
        "        for i in (seq (count $argv))",
        "            set -l word_index (math $start + $i - 1)",
        "            if test $word_index -gt (count $words); or test \"$words[$word_index]\" != \"$argv[$i]\"",
        "                set matched 0",
        "                break",
        "            end",
        "        end",
        "        test $matched -eq 1; and return 0",
        "    end",
        "    return 1",
        "end",
        "function __999_at_path",
        "    set -l words (commandline -opc)",
        "    if test (count $argv) -eq 0",
        f"        for command in {root_commands}",
        "            contains -- $command $words[2..-1]; and return 1",
        "        end",
        "        return 0",
        "    end",
        "    __999_in_path $argv; or return 1",
        "    test \"$words[-1]\" = \"$argv[-1]\"",
        "end",
    ]
    for command in ("999", "juice-lyrics"):
        for node in _flatten(root):
            at_condition = _fish_condition(node.path, exact=True)
            option_condition = _fish_condition(node.path, exact=bool(node.children) or not node.path)
            for child in node.children:
                description = _fish_escape(child.description or "command")
                lines.append(f"complete -c {command} -f -n '{at_condition}' -a '{_fish_escape(child.path[-1])}' -d '{description}'")
            for choice in node.positional_choices:
                lines.append(f"complete -c {command} -f -n '{at_condition}' -a '{_fish_escape(choice)}'")
            for option in node.options:
                pieces = [f"complete -c {command}", f"-n '{option_condition}'"]
                for name in option.names:
                    pieces.append(("-l " + name[2:]) if name.startswith("--") else ("-s " + name[1:]))
                if option.description:
                    pieces.append(f"-d '{_fish_escape(option.description)}'")
                if option.takes_value:
                    pieces.append("-r")
                if option.choices:
                    pieces.extend(("-f", f"-a '{_fish_escape(' '.join(option.choices))}'"))
                lines.append(" ".join(pieces))
    lines.append("")
    return "\n".join(lines)


def generate_completion(parser: argparse.ArgumentParser, shell: str) -> str:
    """Generate a completion script without reading settings or application data."""

    root = completion_tree(parser)
    if shell == "bash":
        return _bash(root)
    if shell == "zsh":
        return _zsh(root)
    if shell == "fish":
        return _fish(root)
    raise ValueError(f"Unsupported shell: {shell}")
