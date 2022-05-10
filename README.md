# rfilerunner

[rfilerunner](https://pypi.org/project/rfilerunner/) runs commands, similar to [`just`](https://github.com/casey/just) or a simple Makefile.
This installs an `r` executable into your PATH that reads from an rfile, which is a YAML file that runs commands in some interpreter (e.g. shell, Python).

```bash
$ pip install rfilerunner

$ echo '
something: |
  echo something
' > rfile.yml

$ r
something
```

## Installation

Get the latest release from [PyPi](https://pypi.org/project/rfilerunner/)

```bash
pip install rfilerunner

r --help
```

or install the latest code from GitHub

```
pip install git+https://github.com/goatmobile/rfilerunner.git
```

This installs the `rfilerunner` package, which includes an executable called `rfile` and an easier to type alias of `r` (they are the same, you can delete `r` and use `rfile` if it conflicts with something on your system).

## Quick Start

Create an `rfile.yml` in a directory and define some commands:

```bash
echo '
hello: |
  echo hello

goodbye: |
  echo goodbye
' > rfile.yml
```

Run it with `r` (or `rfile`):

```bash
# rfilerunner picks the first command as the default
$ r
hello

# specify the command by name
$ r goodbye
goodbye

# if possible, rfilerunner will guess based on the prefix
$ r go
Assuming 'go' is short for 'goodbye'
goodbye
```

### Shell Completions

(fish shell only) Get shell completions based on the current directory

```bash
$ r --completions
Install completions for ...?
(y/n) y
Installed successfully!
```

## Features

- Run Bash / Python scripts with a quick and simple language for passing in arguments and creating helpful CLIs
- Easy conversion from a simple `Makefile` (e.g. if it's just targets and shell commands without using any actual features of `make`, run `sed 's/:$/: \|/g' Makefile > rfile.yml`)
- Prefix-based command matching (e.g. `r hel` is equivalent to `r hello` in most cases)
- Search through parent directories to find an rfile
- Run dependencies in parallel with `# parallel`
- Watch files and re-run commands on modifications (or catch errors and run some other command)

## Advanced Usage

### Help

Comments at the start of the script can be used to specify arguments. If none is provided, a help text will be generated automatically.

```yaml
test1: |
  # some help text
  echo hi

test2: |
  # shell: bash (some help text)
  echo hi

test3: |
  # help: some help text
  echo hi
```

Then

```
$ r --help
usage: r [-h, --help] [-v, --verbose] [-r, --rfile rfile] COMMAND

rfile is a simple command runner for executing Python and shell scripts

available commands:
    test1     some help text (default)
    test2     some help text
    test3     some help text
```

### Arguments

You can specify arguments which are passed to the running script. In Python, they are available via an `args` variable and in Shell they can be accessed from the environment (e.g. `$MY_ARG` or as positional arguments on the script (e.g. `$1`):

```yaml
test4: |
  # arg: something (does something)
  echo arg is: $SOMETHING
```

```
$ r test4 --arg wow
arg is: wow
```

### Python

You can also use Python instead of `bash` / `sh`. A few modules are included by default and any args are in the `args` variable and can be accessed with a `.` (args are `None` if not provided)

```yaml
python: |
  # use Python! a smattering of modules are included by default
  # arg: hello
  print(os)
  print(args.hello)
  print("neat")
```

### Other Interpreters

Any interpreter that can be run like `/path/to/intepreter a_file` will work as a `# shell:`, though only Python and shells will get arguments passed in correctly.

```yaml
ruby: |
  # shell: ruby
  puts "Hello from ruby"
```

### Parallel Dependencies

With `# parallel`, dependencies will be run in parallel each in their own thread.

```yaml
d: |
  # parallel
  # dep: a
  # dep: b
  # dep: c

a: |
  yes hello

b: |
  yes goodbye

c: |
  yes meow
```

```bash
# invoke default command 'd'
$ r
b | goodbye
c | meow
c | meow
c | meow

# outputs from each dependency are interleaved with and prefixed with '<name> |'
```

### Watch Files

The `# watch:` directive will make rfile watch the specified files and re-run the script on any changes. The argument to `watch` can be a 1-liner shell script, float number of seconds to sleep, or another command. The environment variable `CHANGED` will contain the triggering file (or may be empty). For more advanced functionality you can use external tools to keep your scripts running in watch mode forever manually via something like [`entr`](https://eradman.com/entrproject/) or [Watchman](https://facebook.github.io/watchman/).

```yaml
inline-watch: |
  # watch: find . -type f
  echo changed file: $CHANGED

use-another-command: |
  # watch: find-files
  echo changed file: $CHANGED

sleep-watch: |
  # watch: 1.4
  echo hello

find-files: |
  find . -type f
```

For long running commands it may be preferred to cancel their run before running the next event, this can be done via the `# cancel` directive.

```yaml
# Edits to `test.txt` will cause the running command to be killed and restarted
long: |
  # watch: echo test.txt
  # cancel
  echo hi
  sleep 30
  echo bye
```

#### Catch

If a watch command fails, you can specify another script/command to run on each failure. `ERROR` will contain the output with stdout and stderr intermixed (ANSI color codes are removed, the full message can be found in `ERROR_COLOR`).

```yaml
watch: |
  # watch: echo file.txt
  # catch: echo failed!
  exit 1

watch2: |
  # watch: echo file.txt
  # catch: fallback
  echo script failed
  exit 1

fallback: |
  echo "Failed with message:" $ERROR
```
