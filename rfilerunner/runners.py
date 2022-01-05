import subprocess
import tempfile
import os
import textwrap
import pty

from rfilerunner import util
from rfilerunner import colors, Colors
from rfilerunner.util import verbose, padding_from_run, color_from_run

c = Colors


def run_in_interpreter(params, args, cwd, run_info, preamble):
    verbose(f"Shell executing: {params}")
    env = os.environ.copy()
    for k, v in args.items():
        env[k.lower()] = v
        env[k.upper()] = v

    recorded_stdout = None
    record = run_info is not None and run_info.get("record_stdout", False)
    hide_output = run_info is not None and run_info.get("hide_stdout", record)
    single = True
    if run_info is not None:
        single = run_info.get("single", False)
    if record:
        recorded_stdout = ""

    with tempfile.NamedTemporaryFile(delete=False) as f:
        with open(f.name, "w") as f_w:
            f_w.write(preamble)
            f_w.write(params.code)

        stderr = None
        stdout = None
        if run_info is not None:
            pty_r, pty_w = pty.openpty()
            stderr = pty_w
            stdout = pty_w

        command = [params.shell, f_w.name] + list(params.args.values())
        verbose(f"  running {command}")
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stderr=stderr,
            stdout=stdout,
            universal_newlines=True,
        )

        padding = padding_from_run(params.name, run_info)
        color = color_from_run(run_info)
        if run_info is not None:
            os.close(pty_w)

            while True:
                try:
                    output = os.read(pty_r, 1000)
                except OSError as e:
                    verbose(f"OSError: {e}")
                    break
                if not output:
                    break

                output = output.decode().rstrip()
                lines = output.split("\n")
                for line in lines:
                    if record:
                        recorded_stdout += line.rstrip() + "\n"

                    if not hide_output:
                        if single:
                            print(f"{line.rstrip()}")
                        else:
                            print(
                                f"{color}{params.name}{c.END}{padding} | {line.rstrip()}"
                            )
        rc = proc.wait()

        return rc, recorded_stdout


def python(params, args, cwd, run_info):
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
    return run_in_interpreter(params, args, cwd, run_info, preamble)


def shell(params, args, cwd, run_info):
    preamble = "set -e\n"
    if util.VERBOSE:
        preamble = "set -ex\n"
    return run_in_interpreter(params, args, cwd, run_info, preamble)


def generic(params, args, cwd, run_info):
    preamble = ""
    return run_in_interpreter(params, args, cwd, run_info, preamble)
