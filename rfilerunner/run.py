import os
import threading
import time
import re
from typing import Dict, List, Optional, Tuple

from pathlib import Path
from rfilerunner.colors import Colors, color
from rfilerunner.util import (
    verbose,
    padding_from_run,
    error,
    color_from_run,
)
from rfilerunner.parse import Params
from rfilerunner import runners


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


def run(
    params: Params,
    args: Dict[str, str],
    commands: Dict[str, Params],
    cwd: str,
    run_info: Dict[str, str],
) -> Tuple[int, str]:
    """
    Execute an rfile command and any transitive dependencies.
    """
    verbose(f"Running command {params.name}, {params}")
    if params.parallel and len(params.deps) > 0:
        # run dependencies in parallel
        padding = max(len(p) for p in params.deps)
        if run_info is not None:
            raise RuntimeError("Nested parallel runs aren't supported")
        threads = []
        for i, dep in enumerate(params.deps):
            run_info = {
                "padding": padding,
                "index": i,
            }
            if dep not in commands:
                error(
                    f"'{dep}' command not found in rfile but was specified as a dependency of '{params.name}'"
                )
            dependency_params = commands[dep]
            threads.append(
                threading.Thread(
                    target=run,
                    args=(dependency_params, args, commands, cwd, run_info),
                )
            )

        [t.start() for t in threads]

        try:
            [t.join() for t in threads]
        except KeyboardInterrupt:
            # use os._exit to quit from another thread
            # https://stackoverflow.com/questions/1489669/how-to-exit-the-entire-application-from-a-python-thread
            os._exit(0)
    else:
        for dep in params.deps:
            dependency_params = commands[dep]
            run(dependency_params, args, commands, cwd, run_info=None)

    if params.code.strip() == "":
        # no-op
        return 0, ""

    if params.watch is not None:
        import watchdog
        import watchdog.observers

        def catch(rc, stdout):
            pass

        if params.catch is not None:
            if params.catch in commands:
                dependency_params = commands[params.catch]

                def catch(rc, stdout):
                    new_args["ERROR"] = strip_ansi(stdout)
                    new_args["ERROR_COLOR"] = stdout
                    rc, stdout = run(
                        dependency_params,
                        new_args,
                        commands,
                        cwd,
                        run_info=None,
                    )

            else:

                def catch(rc, stdout):
                    nonlocal new_args
                    new_args = new_args.copy()
                    new_args["ERROR"] = strip_ansi(stdout)
                    new_args["ERROR_COLOR"] = stdout
                    run_params = Params(
                        name=f"{params.name}-catch",
                        shell=params.shell,
                        help="",
                        args=new_args,
                        deps=[],
                        parallel=False,
                        watch=None,
                        catch=None,
                    )
                    run_code = params.catch + "\n"
                    rc, stdout = runners.shell(
                        run_params, new_args, run_code, cwd, None
                    )

        def watch_run(event):
            new_args = args.copy()

            if event is not None:
                new_args["CHANGED"] = event.src_path

            if run_info is None:
                new_info = {}
            else:
                new_info = run_info.copy()
            new_info["record_stdout"] = True
            new_info["hide_stdout"] = False
            new_info["single"] = run_info is None
            rc, stdout = runners.shell(params, new_args, cwd, new_info)
            if rc != 0:
                catch(rc, stdout)

        if params.watch in commands:
            dependency_params = commands[params.watch]
            rc, stdout = run(
                dependency_params,
                args,
                commands,
                cwd,
                run_info={"record_stdout": True},
            )
        elif isfloat(params.watch):
            sleep_time = float(params.watch)
            try:
                while True:
                    watch_run(None)
                    time.sleep(sleep_time)
            except KeyboardInterrupt:
                exit(0)
        else:
            new_args = params.args.copy()
            new_args["CHANGED"] = ""
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
            )
            rc, stdout = runners.shell(
                run_params, new_args, cwd, run_info={"record_stdout": True}
            )
            if rc != 0:
                error(f"watch command failed: {run_code.strip()}\n{stdout}")

        paths_to_watch = [
            Path(x.strip()) for x in stdout.split("\n") if x.strip() != ""
        ]

        non_existent = [p for p in paths_to_watch if not p.exists()]
        if len(non_existent):
            non_existent = ", ".join([str(x) for x in non_existent])
            error(f"Some paths to watch didn't exist: {non_existent}")

        if run_info is None:
            info_msg = ""
        else:
            info_msg = color(
                f"{color_from_run(run_info)}{params.name}{Colors.END}{padding_from_run(params.name, run_info)} | ",
                Colors.YELLOW,
            )

        print(
            f"{color('[watching]', Colors.YELLOW)} {info_msg}{' '.join([str(x) for x in paths_to_watch])}"
        )

        observer = watchdog.observers.Observer()

        class Handler(watchdog.events.FileSystemEventHandler):
            def on_any_event(self, event):
                super().on_any_event(event)
                verbose(event)
                watch_run(event)

        event_handler = Handler()

        for path in paths_to_watch:
            observer.schedule(event_handler, str(path.resolve()), recursive=False)

        # Run once to start
        watch_run(None)

        observer.start()

        try:
            observer.join()
        except KeyboardInterrupt:
            exit(0)
        #     observer.stop()

        rc = 0
        return rc, None
    else:
        rc = 0
        runner = runners.generic
        if params.shell.name in {"bash", "zsh", "sh", "fish"}:
            runner = runners.shell
        elif params.shell.name in {"python", "python3"}:
            runner = runners.python

        try:
            _, stdout = runner(params, args, cwd, run_info)
        except KeyboardInterrupt:
            exit(0)
            rc = 0

        return rc, stdout
