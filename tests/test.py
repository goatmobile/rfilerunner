import unittest
import subprocess
import textwrap
import tempfile
import os

from typing import List, Dict, Optional


class RFileTestCase(unittest.TestCase):
    def zrun(self, args: List[str], env: Optional[Dict[str, str]] = None):
        content = textwrap.dedent(self.rfile)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            with open(f.name, "w") as f_w:
                f_w.write(content)

            if env is not None:
                os_env = os.environ.copy()
                os_env.update(env)
                env = os_env

            proc = subprocess.run(
                ["r", "-r", f.name] + args,
                stdout=subprocess.PIPE,
                encoding="utf-8",
                env=env,
            )
            return proc.stdout


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
        self.assertEqual("wow\nhello\ngo3\n", output)

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


if __name__ == "__main__":
    unittest.main()
