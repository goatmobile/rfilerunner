import shutil
from typing import Dict, List, Optional, Tuple
from typing import NamedTuple
from pathlib import Path
from rfilerunner.util import (
    error,
    check,
)
from rfilerunner.colors import Colors, color


class Params(NamedTuple):
    shell: str
    name: str
    args: Dict[str, str]  # name: arg(help, value)
    help: str
    watch: str
    catch: str
    deps: List[str]
    parallel: bool
    code: str


def default_shell() -> Optional[str]:
    """
    Find a shell on the system via shutil
    """
    items = ["bash", "zsh", "sh"]
    for i in items:
        path = shutil.which(i)
        if path is not None:
            return path

    error(f"No shell found, tried: {items}")


def parse_name_and_help(s: str) -> Tuple[str, str]:
    """
    handle stuff like
    # shell: /bin/sh (my help text)
    """
    parts = s.split(" ")
    name = parts[0]
    rest = None
    if len(parts) > 1:
        rest = " ".join(parts[1:])
        rest = rest.lstrip("(").rstrip(")")

    return name, rest


def parse(name: str, code: str, is_default: bool) -> Params:
    """
    Parse an entry in an rfile (a single command, i.e. a key + string in the
    top level dictionary in the rfile).

    This handles these directives (see docs for details):
    # shell
    # parallel
    # dep
    # help
    # watch
    # arg
    """
    lines = code.split("\n")
    preamble = []

    for index, line in enumerate(lines):
        line = line.strip()
        if line.startswith("# "):
            preamble.append(line)
        else:
            # TODO: Probably broken if it's all preamble
            break

    code = lines[index:]
    shell = default_shell()
    help = None
    args = {}
    deps = []
    parallel = False
    catch = None
    watch_target = None
    for line in preamble:
        if line.startswith("# shell: "):
            shell_path, help = parse_name_and_help(line[len("# shell: ") :])
            shell = shutil.which(shell_path)
            check(shell is not None, f"Shell {shell_path} could not be found in PATH")
        elif line.startswith("# arg: "):
            arg, arg_help = parse_name_and_help(line[len("# arg: ") :])
            args[arg] = arg_help if arg_help is not None else ""
        elif line.startswith("# dep: "):
            deps.append(line[len("# dep: ") :])
        elif line.startswith("# help: "):
            help = line[len("# help: ") :]
        elif line.strip() == "# parallel":
            parallel = True
        elif line.startswith("# watch:"):
            watch_target = line[len("# watch:") :].strip()
        elif line.startswith("# catch:"):
            catch = line[len("# catch:") :].strip()
        elif help is None:
            help = line[len("# ") :]

    if help is None and len(deps) > 0:
        if len(deps) == 1:
            help = f"run {deps[0]}"
        else:
            help = "run " + ", ".join(deps[:-1]) + ", and " + deps[-1]

    full_code = "\n".join(code)

    if help is None:
        # put in some help text so it's not blank, just use the code
        sample = full_code[:31].strip().replace("\n", "; ")
        if len(sample) == 31:
            sample = sample[:27] + "..."
        else:
            sample = sample[:30]
        help = color(sample, Colors.FAINT)

    if is_default:
        if help is None:
            help = "(default)"
        else:
            help += " (default)"

    if catch is not None and watch_target is None:
        print(
            f"{Colors.BOLD}{Colors.RED}[r] '# catch' cannot be used without '# watch', but this was found in target '{name}'{Colors.END}"
        )

    return Params(
        name=name,
        shell=Path(shell),
        help=help,
        args=args,
        deps=deps,
        parallel=parallel,
        watch=watch_target,
        catch=catch,
        code=full_code,
    )
