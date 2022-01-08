import os
import asyncio
import threading
import time
import re
import watchdog
import watchdog.observers
from typing import Dict, List, Optional, Tuple

from pathlib import Path
from rfilerunner.colors import Colors, color
from rfilerunner.util import (
    verbose,
    padding_from_run,
    error,
    color_from_run,
    ngather,
    VERBOSE,
)
from rfilerunner.parse import Params
from rfilerunner import runners


_run_id = 0
_procs = {}


def run_id():
    global _run_id
    _run_id += 1
    return _run_id


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
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, observer_join, observer)


async def run(
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
        # threads = []
        coros = []
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
            coros.append(run(dependency_params, args, commands, cwd, run_info))

        await ngather(coros)
    else:
        for dep in params.deps:
            dependency_params = commands[dep]
            await run(dependency_params, args, commands, cwd, run_info=None)

    if params.code.strip() == "":
        # no-op
        return 0, ""

    if params.watch is not None:


        async def catch(rc, stdout):
            pass

        if params.catch is not None:
            if params.catch in commands:
                dependency_params = commands[params.catch]

                async def catch(rc, stdout):
                    new_args = args.copy()
                    new_args["ERROR"] = strip_ansi(stdout)
                    new_args["ERROR_COLOR"] = stdout
                    rc, stdout = await run(
                        dependency_params,
                        new_args,
                        commands,
                        cwd,
                        run_info=None,
                    )

            else:

                async def catch(rc, stdout):
                    new_args = args.copy()
                    new_args["ERROR"] = strip_ansi(stdout)
                    new_args["ERROR_COLOR"] = stdout
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
                    )
                    rc, stdout = await runners.shell(run_params, new_args, cwd, None)

        ran_once = False

        async def watch_run(event):
            # print("Watch run!")
            nonlocal ran_once
            # if not ran_once:
            #     ran_once = True
            #     return
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
            new_info["procs"] = _procs
            new_info["name"] = params.name
            rc, stdout = await runners.shell(params, new_args, cwd, new_info)
            if rc != 0:
                await catch(rc, stdout)
            # print("WATCH_)RUN IS OVER")

        if params.watch in commands:
            dependency_params = commands[params.watch]
            rc, stdout = await run(
                dependency_params,
                args,
                commands,
                cwd,
                run_info={"record_stdout": True},
            )
        elif isfloat(params.watch):
            sleep_time = float(params.watch)
            while True:
                await watch_run(None)
                time.sleep(sleep_time)
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
            rc, stdout = await runners.shell(
                run_params, new_args, cwd, run_info={"record_stdout": True}
            )
            if rc != 0:
                error(f"watch command failed: {run_code.strip()}\n{stdout.rstrip()}")
                return rc, None

        paths_to_watch = [
            Path(x.strip()) for x in stdout.split("\n") if x.strip() != ""
        ]

        non_existent = [p for p in paths_to_watch if not p.exists()]
        if len(non_existent):
            non_existent = ", ".join([str(x) for x in non_existent])
            error(f"Some paths to watch didn't exist: {non_existent}")

        if run_info is None:
            # no prefix if this isn't run alongside other commands
            info_msg = ""
        else:
            # prepend with: "<name> |"
            info_msg = color(
                f"{color_from_run(run_info)}{params.name}{Colors.END}{padding_from_run(params.name, run_info)} | ",
                Colors.YELLOW,
            )

        paths_str = " ".join([str(x) for x in paths_to_watch])
        if len(paths_str) > 100 and not VERBOSE:
            print(
                f"{color('[watching]', Colors.YELLOW)} {info_msg}watching {len(paths_to_watch)} files"
            )
        else:
            print(
                f"{color('[watching]', Colors.YELLOW)} {info_msg}{' '.join([str(x) for x in paths_to_watch])}"
            )

        observer = watchdog.observers.Observer()
        observer2 = watchdog.observers.Observer()
        import signal

        tloop = None
        _procs[params.name] = None

        def worker(loop):
            # print("Working...")
            asyncio.set_event_loop(loop)
            loop.run_forever()


        tl2 = asyncio.new_event_loop()
        tworker = threading.Thread(target=worker, args=(tl2,))
        tworker.start()
        # print(tl2)
        # print(asyncio.all_tasks(loop=tl2))
        last_handle = None

        class Handler(watchdog.events.FileSystemEventHandler):
            def on_any_event(self, event):
                nonlocal last_handle

                if last_handle is not None:
                    last_handle.cancel()
                # super().on_any_event(event)
                nonlocal tloop
                if tloop is None:
                    tloop = asyncio.new_event_loop()
                    asyncio.set_event_loop(tloop)
                verbose(event)
                # print("--------------------------------")
                # print("last run:", _procs[params.name])
                # print("run in loop")
                if _procs[params.name] is not None:
                    # print("KILLING LAST")
                    try:
                        os.kill(_procs[params.name], signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                        # print("Failed to lookup pid", _procs[params.name])
                # tl2.create_task(watch_run(event))
                # tl2.call_soon_threadsafe(watch_run(event))
                # tl2.call_soon_threadsafe(watch_run, (event,))
                last_handle = asyncio.run_coroutine_threadsafe(watch_run(event), tl2)
                # print(asyncio.all_tasks(loop=tl2))
                # for t in asyncio.all_tasks(loop=tl2):
                #     print(t)


                # print("sent to loop")

        # class KillerHandler(watchdog.events.FileSystemEventHandler):
        #     def on_any_event(self, event):
        #         pass
        #         # super().on_any_event(event)
        #         # print("kill event", _procs)
        #         # for pid in _procs.values():
        #         #     if pid == _procs["last"]:
        #         #         continue
        #         #     print("killing", pid)
        #         #     os.kill(pid, signal.SIGTERM)
        #         # to_remove = list(_procs.keys())
        #         # print("removing", to_remove)
        #         # for k in to_remove:
        #         #     if k == 'last':
        #         #         continue
        #         #     if pid == _procs["last"]:
        #         #         continue

        #         #     del _procs[k]

        event_handler = Handler()
        # event_handler2 = KillerHandler()

        for path in paths_to_watch:
            observer.schedule(event_handler, str(path.resolve()), recursive=False)
            # observer2.schedule(event_handler2, str(path.resolve()), recursive=False)

        observer.start()
        # observer2.start()

        # Run once to start
        # await watch_run(None)

        # This should loop forever
        # print("yielding...")
        await aiojoin(observer)
        # await aiojoin(observer2)
        # print("done with everything")

        return 0, None
    else:
        runner = runners.generic
        if params.shell.name in {"bash", "zsh", "sh", "fish"}:
            runner = runners.shell
        elif params.shell.name in {"python", "python3"}:
            runner = runners.python

        rc, stdout = await runner(params, args, cwd, run_info)
        return rc, stdout
