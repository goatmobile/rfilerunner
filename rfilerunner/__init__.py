import sys
import os
import textwrap
import argparse
import yaml

from pathlib import Path
from typing import Any


from rfilerunner import util
from rfilerunner.colors import Colors, color
from rfilerunner.util import (
    verbose,
    error,
    internal_assert,
    check,
)
from rfilerunner.parse import parse
from rfilerunner.run import run


def check_rfile(content: Any):
    """
    Check that an rfile's content is the right structure
    """
    check(
        isinstance(content, dict),
        f"Expected rfile top level be a flat YAML dictionary, but found {type(content)}",
    )

    for v in content.values():
        check(
            isinstance(v, str),
            f"Expected rfile dictionary entries to be strings, but found {type(v)}",
        )


def show_help(missing_file: bool, commands, error=None):
    preamble = textwrap.dedent(
        f"""
    {color('usage', Colors.YELLOW)}: r [-h, --help] [-v, --verbose] [-r, --rfile rfile] {color('COMMAND', Colors.CYAN)}

    rfile is a simple command runner for executing Python and shell scripts
    """
    ).strip()

    if missing_file:
        print(
            preamble
            + "\n\n"
            + f"{color('note', Colors.GREEN)}: no rfile was found so no commands are available"
        )
    else:
        command_str = ""
        max_len = max(len(name) for name in commands.keys())

        for name, params in commands.items():
            line = f"    {color(name, Colors.PURPLE)}"
            padding = " " * (max_len - len(name) + 5)
            if params.help is not None:
                line += f"{padding}{params.help}"

            command_str += f"{line}\n"
        print(
            f"{preamble}\n\n{color('available commands:', Colors.BOLD)}\n{command_str}",
            end="",
        )

    if error is not None:
        print(f"{Colors.BOLD}{Colors.RED}{error}{Colors.END}")

    exit(0)


def show_subcommand_help(command, options):
    params = options

    preamble = (
        f"{color('usage', Colors.YELLOW)}: r [-v, --verbose] {command} [-h, --help]"
    )
    args_desc = ""
    if len(params.args) > 0:
        args = [f"[--{a} {a.upper()}]" for a in params.args]
        preamble += " " + " ".join(args)

        arg_strs = [("  -h, --help", "show this help message and exit")]
        for name, help in params.args.items():
            arg_strs.append((f"  --{name}", help))
        padding = max(len(x) for x, _ in arg_strs)
        args_descs = [
            f"{name}{' ' * (padding - len(name) + 2)}{help}" for name, help in arg_strs
        ]
        args_desc = f"\n\n{color('optional arguments:', Colors.BOLD)}\n" + "\n".join(
            args_descs
        )
    print(f"{preamble}\n\n    {params.help}{args_desc}")
    exit(0)


def locate_rfile(help: bool) -> str:
    rfile_names = ["rfile", "rfile.yml", "rfile.yaml"]
    verbose(f"Guessing rfile from {rfile_names}")
    cwd = Path(os.getcwd())

    for part in [cwd] + list(cwd.parents):
        possible_rfiles = [part / f for f in rfile_names]
        existing_rfiles = [f for f in possible_rfiles if f.exists() and f.is_file()]
        if len(existing_rfiles) == 1:
            return existing_rfiles[0]

    sample = textwrap.dedent(
        """
    # rfiles are just yaml, but comments under commands have meaning

    my_prereq1:
        echo working...

    my_prereq2:
        echo really working...

    my_command:
        # arg: name (your name)
        # parallel
        # dep: my_prereq1
        # dep: my_prereq2
        echo hello "$NAME"
    """.rstrip()
    )
    msg = color(
        "File 'rfile' not found in this directory or parents! Make one! Here is an example:",
        Colors.RED,
    )
    error(msg + sample)


def handle_shell_completions(prev, options):
    shell = os.getenv("SHELL", None)
    if shell is None:
        print("Didn't find anything in SHELL environment variable, exiting")
        exit(0)
    shell = Path(shell)

    if prev is not None:
        prev = prev.split()
    else:
        prev = []

    if shell.name == "fish":
        if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
            completions_dir = (
                Path(os.path.expanduser("~")) / ".config" / "fish" / "completions"
            )
            out = completions_dir / "r.fish"

            print(f"Install completions for fish shell in {out}?\n(y/n) ", end="")
            response = input().lower()
            data = textwrap.dedent(
                """
                function get_r_completions
                    set prev_arg (commandline -pco)
                    r --completions --prev "$prev_arg"
                end

                complete -c r -k -a '(get_r_completions)' --no-files
            """
            )
            if response == "y":
                completions_dir.mkdir(exist_ok=True, parents=True)
                with open(out, "w") as f:
                    f.write(data)
                print("Installed successfully!")

            else:
                printable = data.replace("'", "\\'")
                print(
                    f"'no' chosen, aborting. You can install manually via:\necho '{printable}' > {out}"
                )
        else:
            if len(prev) == 1:
                for command, params in options.items():
                    print(f"{command}\t{params.help}")
            elif len(prev) == 2:
                curr_command = prev[-1]
                if curr_command in options:
                    params = options[curr_command]
                    for arg, help in params.args.items():
                        print(f"--{arg}\t{help}")
    else:
        print(f"Shell '{shell.name}' isn't supported, only these shells are: fish")

    exit(0)


def cli():
    # First argparser to silently grab the rfile and verbose args before
    # building the real one with user supplied info
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-r", "--rfile")
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--completions",
        action="store_true",
        help="(dev) Print shell completions",
    )
    parser.add_argument(
        "--prev",
        help="(dev) Previous shell args",
        default=None,
    )
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args, other = parser.parse_known_args()

    first_help = args.help

    if args.verbose:
        util.VERBOSE = True

    if args.rfile:
        verbose(f"Using hardcoded rfile at {args.rfile}")
        rfile = Path(args.rfile)
        if not rfile.exists():
            if args.help:
                show_help(missing_file=True, commands=None)
            error(f"Could not find rfile '{args.rfile}'")
    else:
        rfile = locate_rfile(help=args.help)

    # Load the file
    internal_assert(rfile.exists(), "check rfile exists")

    with open(rfile) as f:
        content = yaml.safe_load(f)
    check_rfile(content)

    # Generate the real args
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "-r",
        "--rfile",
        help="the YAML rfile to use ('rfile' in the current directory by default)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output for debugging",
    )
    parser.add_argument(
        "-h",
        "--help",
        action="store_true",
    )
    parser.add_argument("subparser", nargs="?")

    default = None
    commands = {}
    for index, (command, code) in enumerate(content.items()):
        is_default = index == 0
        if is_default:
            default = command
        params = parse(name=command, code=code, is_default=is_default)

        commands[params.name] = params

    if args.completions:
        handle_shell_completions(args.prev, commands)

    check(default is not None, "There should be at least 1 command in the rfile")
    args, other = parser.parse_known_args()

    command = args.subparser
    if args.subparser is None:
        command = default
    if command not in commands:
        # If the commmand isn't a literal name of an command, try to guess it
        # based on the prefix
        candidates = [item for item in commands if item.startswith(command)]
        if len(candidates) == 0:
            # No matches
            show_help(
                missing_file=False,
                commands=commands,
                error=f"No possible matches found for command '{command}'",
            )
        elif len(candidates) > 1:
            # Too many matches
            candidates = ", ".join(candidates)
            show_help(
                missing_file=False,
                commands=commands,
                error=f"Ambiguous short command '{command}', could be any of: {candidates}",
            )
        else:
            # Just right, use the full command
            print(
                color(
                    f"Assuming '{command}' is short for '{candidates[0]}'",
                    Colors.YELLOW,
                )
            )
            command = candidates[0]

    inner_parser = argparse.ArgumentParser(add_help=False)
    params = commands[command]
    for name, help in params.args.items():
        inner_parser.add_argument(f"--{name}")

    subparser_args, subparser_other = inner_parser.parse_known_args()

    if first_help or args.help:
        if args.subparser is None:
            show_help(missing_file=False, commands=commands)
        else:
            show_subcommand_help(command, commands[command])

    params = commands[command]
    runtime_args = {}

    for name in params.args.keys():
        value = getattr(subparser_args, name, None)
        if value is not None:
            runtime_args[name] = value

    code, stdout = run(params, runtime_args, commands, cwd=rfile.parent, run_info=None)
    exit(code)
