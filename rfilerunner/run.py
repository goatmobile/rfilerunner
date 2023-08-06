import os
import asyncio
import threading
import time
import signal
import re
import json
import logging
import sys

from typing import Dict, List, Optional, Tuple
from pathlib import Path

from rfilerunner.colors import Colors, color
from rfilerunner.util import (
    verbose,
    error,
    ngather,
    VERBOSE,
    merge,
    RUN_IDX_STDIN,
)
from rfilerunner.parse import Params
from rfilerunner import runners

import watchdog
import watchdog.observers

# List of running process IDs (used to terminate running processes from
# another thread in the event of a watch cancel)
_procs = {}


def strip_ansi(s: str) -> str:
    ansi_escape = re.compile(
        r"""
        \x1B  # ESC
        (?:   # 7-bit C1 Fe (except CSI)
            [@-Z\\-_]
        |     # or [ for CSI, followed by a control sequence
            \[
            [0-?]*  # Parameter bytes
            [ -/]*  # Intermediate bytes
            [@-~]   # Final byte
        )
    """,
        re.VERBOSE,
    )

    return ansi_escape.sub("", s)


def isfloat(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def observer_join(observer):
    try:
        observer.join()
    except KeyboardInterrupt:
        print("overserver")
        return


async def aiojoin(observer):
    # Wrapper to join via asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, observer_join, observer)


def worker(loop):
    # Worker thread to execute an async loop (filled with tasks by a file
    # listener)
    # print(loop)
    # id(loop)
    asyncio.set_event_loop(loop)
    # print("Worker started")
    loop.run_forever()
    # print("Worker STOPPED RUN_FOREVER")


class Handler(watchdog.events.FileSystemEventHandler):
    def __init__(self, paths, procs, params, watch_run):
        self.paths = set(str(Path(p).resolve()) for p in paths)
        self.last_handle = None
        self.loop = asyncio.new_event_loop()
        self.watch_run = watch_run
        self.procs = procs
        self.params = params

        worker_thread = threading.Thread(target=worker, args=(self.loop,))
        worker_thread.start()

    def on_any_event(self, event):
        if event is not None and event.event_type in {"closed"}:
            # Ignored events
            return

        if event is not None and event.src_path not in self.paths:
            # Not sure why these get triggered, but ignore events to files that
            # aren't in the list
            return

        # On a file change event, run the relevant script
        if self.params.cancel_watch:

            # Terminate any async processes in the worker thread's loop
            if self.last_handle is not None:
                self.last_handle.cancel()

            verbose(event)

            # Stop any previous runs of this command if present (this gets
            # filled out in runners.py when the process is actually run via
            # subprocess)
            if self.procs[self.params.name] is not None:
                try:
                    os.kill(self.procs[self.params.name], signal.SIGKILL)
                except ProcessLookupError:
                    pass

            self.last_handle = asyncio.run_coroutine_threadsafe(
                self.watch_run(event), self.loop
            )
        else:
            asyncio.run(self.watch_run(event))


def make_catch(
    params: Params, args: Dict[str, str], commands: Dict[str, Params], cwd: str
):
    async def catch(rc, stdout):
        pass

    padding = len(params.name)
    color = "\x1B[41m"

    if params.catch is not None:
        if params.catch in commands:
            dependency_params = commands[params.catch]

            async def catch(rc, stdout):
                await run(
                    dependency_params,
                    merge(args, {"ERROR": strip_ansi(stdout), "ERROR_COLOR": stdout}),
                    commands,
                    cwd,
                    run_idx=color,
                    padding=padding,
                )

        else:

            async def catch(rc, stdout):
                new_args = merge(
                    args, {"ERROR": strip_ansi(stdout), "ERROR_COLOR": stdout}
                )
                run_code = params.catch + "\n"
                run_params = Params(
                    name=f"{params.name}-catch",
                    shell=params.shell,
                    help="",
                    args=new_args,
                    deps=[],
                    parallel=False,
                    watch=None,
                    catch=None,
                    code=run_code,
                    cancel_watch=False,
                )
                await runners.shell(
                    run_params,
                    new_args,
                    cwd,
                    run_idx=color,
                    padding=padding,
                )

    return catch


async def watch(
    params: Params,
    args: Dict[str, str],
    commands: Dict[str, Params],
    cwd: str,
    padding: int,
    run_idx: Optional[int],
    watch_files: Optional[List[str]] = None,
):
    """
    Run a command via a watch. This loops infinitely based on 'params' (e.g.
    based on files or a timer).
    """

    catch = make_catch(params, args, commands, cwd)

    async def watch_run(event):
        new_args = args.copy()

        if event is not None:
            new_args["CHANGED"] = event.src_path

        rc, stdout = await runners.shell(
            params,
            new_args,
            cwd,
            padding=padding,
            run_idx=run_idx,
            running_pids=_procs[params.name],
        )
        if rc != 0:
            await catch(rc, stdout)

    _procs[params.name] = None
    if run_idx is None:
        # no prefix if this isn't run alongside other commands
        preamble = ""
    else:
        # prepend with: "<name> |"
        preamble = f"{params.name}{' ' * (padding - len(params.name))} | "

    if watch_files is not None:
        # files passed in via CLI override, don't run anything
        paths_to_watch = [Path(x) for x in watch_files]
    else:
        if params.watch in commands:
            # Recurse down to another run to get its output
            dependency_params = commands[params.watch]
            rc, stdout = await run(
                dependency_params,
                args,
                commands,
                cwd,
                padding=padding,
                run_idx=run_idx,
                hide_output=True,
            )
        elif isfloat(params.watch):
            # Passed a timer so no need to listen to any files, just sit here
            # in a loop forever
            sleep_time = float(params.watch)
            print(
                color(
                    f"{preamble}watching every {sleep_time} seconds",
                    Colors.YELLOW,
                )
            )
            while True:
                await watch_run(None)
                time.sleep(sleep_time)
        else:
            # Inline shell code used, so issue an ad-hoc call to the default
            # shell
            new_args = merge(params.args, {"CHANGED": ""})
            run_code = params.watch + "\n"
            run_params = Params(
                name=f"{params.name}-watch",
                shell=params.shell,
                help="",
                args=new_args,
                deps=[],
                parallel=False,
                watch=None,
                catch=None,
                code=run_code,
                cancel_watch=False,
            )
            rc, stdout = await runners.shell(
                run_params, new_args, cwd, hide_output=True
            )
            # This is probably unreachable
            if rc != 0:
                error(f"watch command failed: {run_code.strip()}\n{stdout.rstrip()}")

        paths_to_watch = [
            cwd / x.strip() for x in stdout.split("\n") if x.strip() != ""
        ]

    # Check that any files referenced exist (watchdog will error out otherwise
    # with a less helpful message)
    non_existent = [p for p in paths_to_watch if not p.exists()]
    if len(non_existent):
        non_existent = ", ".join([str(x.relative_to(cwd)) for x in non_existent])
        error(f"Some paths to watch didn't exist: {non_existent}")

    # Output watch status
    paths_str = " ".join([str(x.relative_to(cwd)) for x in paths_to_watch])
    if len(paths_str) > 140 and not VERBOSE:
        print(color(f"{preamble}watching {len(paths_to_watch)} files", Colors.YELLOW))
    else:
        print(
            color(
                f"{preamble}watching {paths_str}",
                Colors.YELLOW,
            )
        )

    # Register all the relevant paths with watchdog
    observer = watchdog.observers.Observer()

    handler = Handler(paths_to_watch, _procs, params, watch_run)
    for path in paths_to_watch:
        # TODO: inotify limits seem pretty low (around 100?), so watching a whole
        # repo doesn't work
        observer.schedule(handler, str(path.resolve()), recursive=False)

    observer.start()

    # Run once to start
    if params.cancel_watch:
        handler.on_any_event(None)
    else:
        await watch_run(None)

    # This should loop forever
    await aiojoin(observer)

    return 0, None


async def run(
    params: Params,
    args: Dict[str, str],
    commands: Dict[str, Params],
    cwd: str,
    padding: int = 0,
    run_idx: Optional[int] = None,
    hide_output: bool = False,
    no_watch: bool = False,
    no_parallel: bool = False,
    watch_files: Optional[List[str]] = None,
    listen_on_stdin: bool = False,
) -> Tuple[int, str]:
    """
    Execute an rfile command and any transitive dependencies.
    """
    verbose(f"Running command {params.name}, {params}")

    last_handle = None
    listen_loop = None
    if listen_on_stdin and len(params.deps) > 0 and params.parallel:
        listen_loop = asyncio.new_event_loop()

        async def go(command):
            await run(
                commands[command],
                {},
                commands,
                cwd,
                padding=1,
                run_idx=RUN_IDX_STDIN,
            )

        async def listen():
            # print("Listening")
            while True:
                # print("awaiting aioread")

                line = await runners.aioread(sys.stdin, mode="line")
                command = line.strip()
                if command == "":
                    continue

                if command not in commands:
                    candidates = [item for item in commands if item.startswith(command)]
                    if len(candidates) == 0:
                        print(
                            f"Command '{command}' not found in {json.dumps(list(commands.keys()))}"
                        )
                    elif len(candidates) == 1:
                        await go(candidates[0])
                    else:
                        print(
                            f"Command '{command}' not found and prefixes are ambiguous: {candidates}"
                        )
                else:
                    await go(command)

        # print("Thread start")
        worker_thread = threading.Thread(target=worker, args=(listen_loop,))
        worker_thread.start()

        # print("schedule")
        fut = asyncio.run_coroutine_threadsafe(listen(), loop=listen_loop)
        # fut = listen_loop.call_soon_threadsafe(listen)

        # run_coroutine_threadsafe
        # print("scheduled with", fut)
        # fut.result()
        # asyncio.ensure_future(fut)
        # last_handle = listen_loop.create_task(listen())

    # Run dependencies
    failed = []
    if len(params.deps) > 0:
        # Actual invocations don't know about the others, so compute the padding
        # for each output line and pass it down
        padding = max(len(p) for p in params.deps)

        for dep in params.deps:
            if dep not in commands:
                error(
                    f"'{dep}' command not found in rfile but was specified as a dependency of '{params.name}'"
                )

        # Gather a set of coroutines for each dependency. These all run in the
        # same async loop but yield for reading from stdout of each subprocess.
        dependency_runs = [
            run(
                commands[dep],
                args,
                commands,
                cwd,
                padding=padding,
                run_idx=i,
                hide_output=hide_output,
            )
            for i, dep in enumerate(params.deps)
        ]

        if not no_parallel and params.parallel:
            results = await ngather(dependency_runs)
            for i, (rc, _) in enumerate(results):
                if rc != 0:
                    failed.append(params.deps[i])
        else:
            for i, c in enumerate(dependency_runs):
                rc, _ = await c
                if rc != 0:
                    failed.append(params.deps[i])

    if len(failed) > 0:
        msg = ", ".join([f"'{p}'" for p in failed])
        print(
            color(
                f"Dependencies failed: {msg}, not running '{params.name}'", Colors.RED
            )
        )
        return 0, None

    if params.code.strip() == "":
        # No actual code (but can't do this any earlier in case there are dependencies)
        return 0, ""

    if params.watch is not None and not no_watch:
        # This shouldn't ever actually return, just spin forever watching the
        # specified files
        return await watch(
            params, args, commands, cwd, padding, run_idx, watch_files=watch_files
        )
    else:
        # Normal run, determine the runner based on params.shell
        runner = runners.generic
        if params.shell.name in {"bash", "zsh", "sh", "fish"}:
            runner = runners.shell
        elif params.shell.name in {"python", "python3"}:
            runner = runners.python

        # Execute code
        rc, stdout = await runner(
            params, args, cwd, padding=padding, run_idx=run_idx, hide_output=hide_output
        )

        # print(last_handle, listen_loop)
        if last_handle:
            # print("Cancel handle")
            last_handle.cancel()

        if listen_loop:
            # print("Cancel loop handle")
            listen_loop.call_soon_threadsafe(listen_loop.stop)
            worker_thread.join()
        if last_handle and listen_loop:
            pass
            # print("CAncelling")
            # last_handle.cancel()
            # listen_loop.call_soon_threadsafe(listen_loop.stop)
            # print("Joining")
        # print("Done")

        return rc, stdout
