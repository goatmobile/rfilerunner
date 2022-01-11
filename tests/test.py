import unittest
import time
import subprocess
import textwrap
import tempfile
import os

from typing import List, Dict, Optional


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

    def zrun(self, *args, **kwargs):
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
        output = self.zrun([])
        self.assertEqual("hi\n", output)

    def test_help(self):
        output = self.zrun(["--help"])
        self.assertTrue(output, "available commands:\n    go     echo hi (default)\n")

    def test_nonexistent(self):
        output = self.zrun(["nonexistent"])
        self.assertTrue(output.startswith("usage"))
        self.assertTrue(
            output.endswith("No possible matches found for command 'nonexistent'\n")
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
        output = self.zrun(["realscript"])
        self.assertEqual("OK not set\n", output)

        output2 = self.zrun(["realscript"], env={"OK": "1"})
        self.assertEqual("OK is set\n", output2)

    def test_args(self):
        output = self.zrun(["something", "--help"])
        self.assertTrue(output.endswith("--myarg     a description of myarg\n"))

        output2 = self.zrun(["something", "--myarg", "abc"])
        self.assertEqual("abc\nabc\n", output2)

    def test_deps(self):
        output = self.zrun(["go3"])
        self.assertEqual("go2 | wow\n" "go  | hello\n" "go3\n", output)

    def test_prefix(self):
        output = self.zrun(["some"])
        self.assertTrue("Assuming 'some' is short for 'something'" in output)

    def test_python(self):
        output = self.zrun(["python"])
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

    watch2: |
        # watch: files
        echo watchin $CHANGED
    
    files: |
        echo {file}
    """

    @wrap_with_temp
    def test_run(self, rfile, fname):
        out, err = self.run_for(1, [], content=rfile)
        self.assertEqual("", err.strip())
        self.assertEqual(f"[watching] {fname}\nstart", out.strip())

    @wrap_with_temp
    def test_multirun(self, rfile, fname):
        out, err = self.run_for(5, [], content=rfile)
        self.assertEqual("", err.strip())
        self.assertEqual(f"[watching] {fname}\nstart\ndone", out.strip())

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
        self.assertEqual(f"[watching] {fname}\nwatchin", out.strip())

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
            f"[watching] {fname}\nwatchin\nwatchin {fname}\nwatchin {fname}",
            out.strip(),
        )


if __name__ == "__main__":
    unittest.main()
