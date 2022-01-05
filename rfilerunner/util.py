import subprocess
import sys
import json
from typing import Any

VERBOSE = False
from rfilerunner.colors import Colors, color


c = Colors
usable_colors = [c.BLUE, c.PURPLE, c.GREEN, c.YELLOW, c.LIGHT_RED, c.LIGHT_GREEN]


def cmd(s, **kwargs):
    print(s)
    subprocess.run(s, shell=True, **kwargs)


def error(error_message, code=1):
    print(f"{color('User error:', Colors.RED)} {error_message}", file=sys.stderr)
    exit(code)


def verbose(message):
    if VERBOSE:
        print(message)


def check(cond, message):
    if not cond:
        error(message)


def internal_assert(cond, message):
    if not cond:
        print(message)
        error("If you're seeing this, this is an rfile bug")


def color_from_run(run_info):
    color = ""
    if run_info is not None and "index" in run_info:
        color = usable_colors[run_info["index"] % len(usable_colors)]
    return color


def padding_from_run(name, run_info):
    padding = 0
    if run_info is not None and "padding" in run_info:
        padding = run_info["padding"] - len(name)

    return " " * padding


def jprint(o):
    """
    JSON dump an object
    """
    print(json.dumps(o, indent=2, default=str))
