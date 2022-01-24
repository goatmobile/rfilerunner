import subprocess
import sys
import json
import asyncio
import os
import multiprocessing
from typing import Any, Optional

VERBOSE = False
from rfilerunner.colors import Colors, color


NPROC = multiprocessing.cpu_count()
c = Colors
usable_colors = [
    c.GREEN,
    c.PURPLE,
    c.BLUE,
    c.CYAN,
    c.YELLOW,
    c.LIGHT_CYAN,
    c.LIGHT_GREEN,
    c.LIGHT_BLUE,
    c.LIGHT_PURPLE,
    c.BROWN,
]

RUN_IDX_STDIN = -2


def cmd(s, **kwargs):
    print(s)
    subprocess.run(s, shell=True, **kwargs)


def error(error_message, code=1):
    print(f"{color('User error:', Colors.RED)} {error_message}", file=sys.stderr)
    os._exit(code)


def dump(obj):
    return json.dumps(obj, default=str)


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


def color_from_run(run_idx: Optional[int]) -> str:
    if run_idx is None:
        return ""

    return usable_colors[run_idx % len(usable_colors)]


def padding_from_run(name, run_info):
    padding = 0
    if run_info is not None and "padding" in run_info:
        padding = run_info["padding"] - len(name)

    return " " * padding


async def ngather(tasks, n=NPROC - 1):
    semaphore = asyncio.Semaphore(n)

    async def sem_task(task):
        async with semaphore:
            return await task

    return await asyncio.gather(*(sem_task(task) for task in tasks))


def jprint(o):
    """
    JSON dump an object
    """
    print(json.dumps(o, indent=2, default=str))


def merge(*dicts):
    result = {}
    for d in dicts:
        result.update(d)
    return result
