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


def read(f):
    return os.read(f, 1000)


async def aioread(f):
    """
    asyncio wrapper for os.read
    detials: https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.run_in_executor
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, read, f)


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
    verbose(f"Shell executing: {params}")
    env = os.environ.copy()
    for k, v in args.items():
        env[k.lower()] = v
        env[k.upper()] = v

    # record = run_info is not None and run_info.get("record_stdout", False)
    record = True

    # hide_output = run_info is not None and run_info.get("hide_stdout", record)
    single = run_idx is None
    # if run_info is not None:
    #     single = run_info.get("single", False)
    # if record:
    recorded_stdout = ""

    # if run_info is None:
    #     run_info = "not real"

    with tempfile.NamedTemporaryFile(delete=False) as f:
        with open(f.name, "w") as f_w:
            f_w.write(preamble)
            f_w.write(params.code)

        # stderr = None
        # stdout = None
        # if run_info is not None:
        pty_r, pty_w = pty.openpty()
        stderr = pty_w
        stdout = pty_w

        command = [params.shell, f_w.name] + list(args.values())
        command_args = [f_w.name] + list(args.values())
        verbose(f"  running {command}")

        # print("EXEC", params.shell, params.code.strip())
        # print(params.code)
        # print(run_info)
        # print(params.shell)
        proc = await asyncio.create_subprocess_exec(
            params.shell,
            *command_args,
            cwd=cwd,
            env=env,
            stderr=stderr,
            stdout=stdout,
        )

        # if run_info is not None and "procs" in run_info:
        #     # run_id = run_info["gen_id"]()
        #     run_info["procs"][run_info["name"]] = proc.pid
        if running_pids is not None:
            running_pids.add(proc.pid)

        padding = " " * padding
        color = ""
        if run_idx is not None:
            color = util.usable_colors[run_idx % len(util.usable_colors)]
        # line_started = False

        class Printer:
            def __init__(self, prefix):
                self.partial_line = False
                self._prefix = prefix

            def line(self, line):
                if not self.partial_line:
                    self.prefix()
                print(line)
                self.partial_line = False
                sys.stdout.flush()

            def partial(self, text):
                if not self.partial_line:
                    self.partial_line = True
                    self.prefix()
                print(text, end="")
                sys.stdout.flush()

            def prefix(self):
                print(self._prefix, end="")

        # if single:
        #     p = Printer(f"")
        # else:
        #     p = Printer(f"{color}{params.name}{c.END}{padding} | ")
        # If run_info is set, the output needs be handled manually
        os.close(pty_w)

        # print("spin read")
        while True:
            try:
                # print('   waiting for read')
                output = await aioread(pty_r)
                # print('   read!')
            except OSError as e:
                verbose(f"OSError: {e}")
                break
            if not output:
                # subprocess closed stdout / stderr
                break

            # print("out", output.decode())

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
                        # recorded_stdout += line.rstrip() + "\n"
                        print(f"{color}{params.name}{c.END}{padding} | {line.rstrip()}")
                        # print(f"{line.rstrip()}")

            recorded_stdout += output
            sys.stdout.flush()
        aioout, aioerr = await proc.communicate()

        if aioout is not None:
            print(f"Unexpected output after closing read pipe:\n{aioout}")

        if aioerr is not None:
            print(f"Unexpected output after closing read pipe:\n{aioerr}")

        return proc.returncode, recorded_stdout


def python(params, args, cwd, **kwargs):
    arg_data = {}
    for name in params.args:
        arg_data[name] = None

    for name, value in args.items():
        arg_data[name] = f'"{value}"'

    data = [f"{k}={v}" for k, v in arg_data.items()]
    data = ", ".join(data)
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
    preamble = "set -e\n"
    if util.VERBOSE:
        preamble = "set -ex\n"
    return run_in_interpreter(params, args, cwd, preamble=preamble, **kwargs)


def generic(params, args, cwd, **kwargs):
    return run_in_interpreter(params, args, cwd, preamble="", **kwargs)
