import unittest
import time
import subprocess
import textwrap
import tempfile
import os

from typing import List, Dict, Optional

IS_GHA = os.getenv("IS_GHA", "0") == "1"


class RFileTestCase(unittest.TestCase):
    def exec(
        self,
        fn,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
        content: str = None,
    ):
        if content is None:
            content = textwrap.dedent(self.rfile)

        with tempfile.NamedTemporaryFile(delete=False) as f:
            with open(f.name, "w") as f_w:
                f_w.write(content)

            if env is not None:
                os_env = os.environ.copy()
                os_env.update(env)
                env = os_env

            proc = fn(
                ["r", "-r", f.name] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                env=env,
            )
            return proc

    def rrun(self, *args, **kwargs):
        proc = self.exec(subprocess.run, *args, **kwargs)
        return proc.stdout

    def ropen(self, *args, **kwargs):
        proc = self.exec(subprocess.Popen, *args, **kwargs)
        return proc

    def run_for(
        self,
        seconds: int,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
        content: str = None,
        action=None,
    ):
        proc = self.ropen(args, env, content)
        if action is not None:
            action()
        try:
            proc.communicate(timeout=seconds)
        except subprocess.TimeoutExpired:
            proc.kill()

        out, err = proc.communicate()
        return out, err


class TestBasic(RFileTestCase):
    rfile = """
    go: |
        echo hi
    """

    def test_default(self):
        output = self.rrun([])
        self.assertEqual("hi\n", output)

    def test_help(self):
        output = self.rrun(["--help"])
        self.assertTrue(output, "available commands:\n    go     echo hi (default)\n")

    def test_nonexistent(self):
        output = self.rrun(["nonexistent"])
        self.assertTrue(output.startswith("usage"))
        self.assertTrue(
            output.endswith("No possible matches found for command 'nonexistent'\n")
        )


class TestHelp(RFileTestCase):
    rfile = """
    go: |
        # some help
        echo hello

    go2: |
        # help: some other help
        echo wow

    go3: |
        # dep: go2
        # dep: go
        echo go3

    realscript: |
        echo no help on this one

    python: |
        # parallel
        # watch: echo file.txt
        # arg: pyarg (a python arg)
    """
    maxDiff = None

    def assertHelp(self, expected, actual):
        self.assertEqual(textwrap.dedent(expected).strip(), actual.strip())

    def test_help_simple(self):
        out = self.rrun(["go", "--help"])
        self.assertHelp(
            """
        usage: r [-v, --verbose] go [-h, --help]

            some help (default)

        optional arguments:
          -h, --help  [r] show this help message and exit
          """,
            out,
        )

    def test_deps_help(self):
        out = self.rrun(["go3", "--help"])
        self.assertHelp(
            """
            usage: r [-v, --verbose] go3 [-h, --help]

                run go2 and go

            optional arguments:
              -h, --help  [r] show this help message and exit
            """,
            out,
        )

    def test_inferred_help(self):
        out = self.rrun(["realscript", "--help"])
        self.assertHelp(
            """
            usage: r [-v, --verbose] realscript [-h, --help]

                echo no help on this one

            optional arguments:
              -h, --help  [r] show this help message and exit
            """,
            out,
        )

    def test_extra_args(self):
        out = self.rrun(["python", "--help"])
        self.assertHelp(
            """
        usage: r [-v, --verbose] python [-h, --help] [--pyarg PYARG]

            (no script found in command)

        optional arguments:
          -h, --help                [r] show this help message and exit
          --no-watch / --once       [r] disable '# watch' behavior and only run once
          --watch WATCH             [r] comma-separated list of files to watch (override '# watch')
          --no-parallel / --serial  [r] disable 'parallel' behavior and run dependencies serially
          --pyarg PYARG             a python arg
          """,
            out,
        )


class TestBigger(RFileTestCase):
    rfile = """
    go: |
        echo hello

    go2: |
        echo wow

    go3: |
        # dep: go2
        # dep: go
        echo go3

    realscript: |
        if [ -z $OK ]; then
            echo OK not set
        else
            echo OK is set
        fi
    
    something: |
        # a custom help
        # arg: myarg (a description of myarg)
        echo $MYARG
        echo $myarg

    python: |
        # shell: python
        # arg: pyarg (a python arg)
        print(args)
        print(json)
        print("neat")
    """

    def test_realscript(self):
        output = self.rrun(["realscript"])
        self.assertEqual("OK not set\n", output)

        output2 = self.rrun(["realscript"], env={"OK": "1"})
        self.assertEqual("OK is set\n", output2)

    def test_args(self):
        output = self.rrun(["something", "--help"])
        self.assertTrue(output.endswith("--myarg MYARG  a description of myarg\n"))

        output2 = self.rrun(["something", "--myarg", "abc"])
        self.assertEqual("abc\nabc\n", output2)

    def test_deps(self):
        output = self.rrun(["go3"])
        self.assertEqual("go2 | wow\n" "go  | hello\n" "go3\n", output)

    def test_prefix(self):
        output = self.rrun(["some"])
        self.assertTrue("Assuming 'some' is short for 'something'" in output)

    def test_python(self):
        output = self.rrun(["python"])
        lines = output.split("\n")
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], "{'pyarg': None}")
        self.assertTrue(lines[1].startswith("<module 'json' from"))
        self.assertEqual(lines[2], "neat")
        self.assertEqual(lines[3], "")


def wrap_with_temp(fn):
    def wrapped(self):
        with tempfile.NamedTemporaryFile() as f:
            return fn(self, self.rfile_template.format(file=f.name), f.name)

    return wrapped


class TestWatch(RFileTestCase):
    rfile_template = """
    watch: |
        # watch: echo {file}
        echo start
        sleep 3
        echo done

    watch-cancel: |
        # watch: echo {file}
        # cancel
        echo start
        sleep 3
        echo done

    watch2: |
        # watch: files
        echo watchin $CHANGED
    
    files: |
        echo {file}

    go1: |
        # watch: echo {file}
        echo go1
    
    go2: |
        # watch: echo {file}
        echo go2
    
    go3: |
        # parallel
        # dep: go1
        # dep: go2
        echo go3

    timed: |
        # watch: 1
        echo ran
    """

    @wrap_with_temp
    def test_run(self, rfile, fname):
        out, err = self.run_for(1, [], content=rfile)
        self.assertEqual("", err.strip())
        self.assertEqual(f"watching {fname}\nstart", out.strip())

    @wrap_with_temp
    def test_multirun(self, rfile, fname):
        out, err = self.run_for(5, [], content=rfile)
        self.assertEqual("", err.strip())
        self.assertEqual(f"watching {fname}\nstart\ndone", out.strip())

    @unittest.skipIf(IS_GHA, "doesn't work in GHA")
    def test_files_exist(self):
        out, err = self.run_for(
            1, ["watch2"], content=self.rfile_template.format(file="nonexistent.txt")
        )
        self.assertEqual(
            "User error: Some paths to watch didn't exist: nonexistent.txt", err.strip()
        )

    @wrap_with_temp
    def test_watch_command(self, rfile, fname):
        out, err = self.run_for(1, ["watch2"], content=rfile)
        self.assertEqual("", err.strip())
        self.assertEqual(f"watching {fname}\nwatchin", out.strip())

    @unittest.skipIf(IS_GHA, "doesn't work in GHA")
    @wrap_with_temp
    def test_watch_write(self, rfile, fname):
        def edit():
            time.sleep(1)
            with open(fname, "w") as f:
                f.write("hello")
            time.sleep(1)
            with open(fname, "w") as f:
                f.write("hello2")

        out, err = self.run_for(1, ["watch2"], content=rfile, action=edit)
        self.assertEqual("", err.strip())
        self.assertEqual(
            f"watching {fname}\nwatchin\nwatchin {fname}\nwatchin {fname}",
            out.strip(),
        )

    @unittest.skipIf(IS_GHA, "doesn't work in GHA")
    @wrap_with_temp
    def test_timed(self, rfile, fname):
        out, err = self.run_for(3, ["timed"], content=rfile)
        self.assertEqual("ran\nran\nran\n", out)

    @unittest.skipIf(IS_GHA, "doesn't work in GHA")
    @wrap_with_temp
    def test_cancel(self, rfile, fname):
        def edit():
            time.sleep(1)
            with open(fname, "w") as f:
                f.write("hello")
            time.sleep(1)
            with open(fname, "w") as f:
                f.write("hello2")

        out, err = self.run_for(5, ["watch-cancel"], content=rfile, action=edit)
        self.assertEqual("", err.strip())
        self.assertEqual(
            f"watching {fname}\nstart\nstart\nstart\ndone",
            out.strip(),
        )

    @unittest.skipIf(IS_GHA, "doesn't work in GHA")
    @wrap_with_temp
    def test_parallel_watch_write(self, rfile, fname):
        def edit():
            time.sleep(1)
            with open(fname, "w") as f:
                f.write("hello")
            time.sleep(1)
            with open(fname, "w") as f:
                f.write("hello2")

        out, err = self.run_for(1, ["go3"], content=rfile, action=edit)
        self.assertEqual("", err.strip())
        lines = out.split("\n")
        self.assertTrue(
            f"go1 | watching {fname}" in lines[0:2], msg=f"Full output:\n{out}"
        )
        self.assertTrue(
            f"go2 | watching {fname}" in lines[0:2], msg=f"Full output:\n{out}"
        )

        for i in range(2, 8, 2):
            self.assertTrue(
                f"go1 | go1" in lines[i : i + 2], msg=f"Full output:\n{out}"
            )
            self.assertTrue(
                f"go2 | go2" in lines[i : i + 2], msg=f"Full output:\n{out}"
            )


if __name__ == "__main__":
    unittest.main()
