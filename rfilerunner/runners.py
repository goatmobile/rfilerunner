import subprocess
import tempfile
import os
import sys
import textwrap
import pty
import asyncio
from typing import Dict, Optional, List, Set

from rfilerunner import util
from rfilerunner import colors, Colors
from rfilerunner.parse import Params
from rfilerunner.util import verbose, padding_from_run, color_from_run

c = Colors


def read(f, mode):
    if mode == "line":
        # print("reading line")
        l = f.readline()
        # print("read line")
        return l
    else:
        return os.read(f, 1000)


async def aioread(f, mode: str = "buffered"):
    """
    asyncio wrapper for os.read
    detials: https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.run_in_executor
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, read, f, mode)


async def run_in_interpreter(
    params: Params,
    args: Dict[str, str],
    cwd: str,
    preamble: str,
    running_pids: Optional[Set[int]] = None,
    hide_output: bool = False,
    padding: int = 0,
    run_idx: Optional[int] = None,
):
    """
    Actually execute 'params'
    """
    verbose(f"Shell executing: {params}")
    env = os.environ.copy()
    for k, v in args.items():
        env[k.lower()] = v
        env[k.upper()] = v

    single = run_idx is None
    recorded_stdout = ""

    with tempfile.NamedTemporaryFile(delete=False) as f:
        with open(f.name, "w") as f_w:
            f_w.write(preamble)
            f_w.write(params.code)

        # Use a pseudo-terminal so subprocesses send color output (color codes
        # will be stripped out later if necessary)
        pty_r, pty_w = pty.openpty()
        stderr = pty_w
        stdout = pty_w

        command = [params.shell, f_w.name] + list(args.values())
        command_args = [f_w.name] + list(args.values())
        verbose(f"  running {command}")

        # Calculate padding based on other runs
        padding = padding - len(params.name)
        proc = await asyncio.create_subprocess_exec(
            params.shell,
            *command_args,
            cwd=cwd,
            env=env,
            stderr=stderr,
            stdout=stdout,
        )

        # Store the PID in case this needs to be terminated for a cancel by the
        # file event listener
        if running_pids is not None:
            running_pids.add(proc.pid)

        padding = " " * padding
        color = ""
        if run_idx is not None:
            if isinstance(run_idx, str):
                color = run_idx
            elif run_idx == util.RUN_IDX_STDIN:
                color = "\x1B[45m"
            else:
                color = util.usable_colors[run_idx % len(util.usable_colors)]

        os.close(pty_w)

        # Read from the pty output until the process finishes
        while True:
            try:
                output = await aioread(pty_r)
            except OSError as e:
                verbose(f"OSError: {e}")
                break
            if not output:
                # subprocess closed stdout / stderr
                break

            output = output.decode()
            if not hide_output:
                if single:
                    print(output, end="")
                else:
                    lines = output.split("\n")
                    end = len(lines)
                    if output.endswith("\n"):
                        end = end - 1
                    for line in lines[:end]:
                        print(f"{color}{params.name}{padding} |{c.END} {line.rstrip()}")

            recorded_stdout += output
            sys.stdout.flush()

        aioout, aioerr = await proc.communicate()

        # All output should already have been read in the loop above
        if aioout is not None:
            print(f"Unexpected output after closing read pipe:\n{aioout}")
        if aioerr is not None:
            print(f"Unexpected output after closing read pipe:\n{aioerr}")

        return proc.returncode, recorded_stdout


def python(params, args, cwd, **kwargs):
    # Build args to pass into Python as a dotdict (defined below)
    arg_data = {}
    for name in params.args:
        arg_data[name] = None
    for name, value in args.items():
        arg_data[name] = f'"{value}"'

    data = [f"{k}={v}" for k, v in arg_data.items()]
    data = ", ".join(data)

    # Import some common stuff to avoid boilerplate in scripts
    preamble = textwrap.dedent(
        f"""
    import os
    import sys
    import subprocess
    import math
    import re
    import json
    import random

    class dotdict(dict):
        __getattr__ = dict.get
        __setattr__ = dict.__setitem__
        __delattr__ = dict.__delitem__

    args = dotdict({data})
    """
    )
    return run_in_interpreter(params, args, cwd, preamble=preamble, **kwargs)


def shell(params, args, cwd, **kwargs):
    # It's a shell, so error out when a command fails via set -e
    preamble = "set -e\n"
    if util.VERBOSE:
        preamble = "set -ex\n"
    return run_in_interpreter(params, args, cwd, preamble=preamble, **kwargs)


def generic(params, args, cwd, **kwargs):
    # Execution environment isn't known, so add nothing and just pass through
    return run_in_interpreter(params, args, cwd, preamble="", **kwargs)
