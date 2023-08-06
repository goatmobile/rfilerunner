# Examples

## [`simple.yaml`](simple.yaml)

```bash
# example invocations:
#   need to specify "-r" since simple.yaml is different from the
#   default filename of rfile.yml / rfile.yaml
$ r -r simple.yaml
$ r -r simple.yaml test
```

## [`advanced.yaml`](advanced.yaml)

```bash
$ r -r advanced.yaml
hello

# run two commands in parallel forever
$ r -r advanced.yaml alternate
ticka | start ticka
ticka | ticka1
ticka | ticka2
tickb | start tickb
tickb | tickb1
tickb | tickb2
ticka | ticka1
ticka | ticka2
...

# run via Python instead of a shell
$ r -r advanced.yaml python
{'pyarg': None}
<module 'json' from '/home/user/miniconda3/lib/python3.9/json/__init__.py'>
neat

# use CLI variables in a script
$ r -r advanced.yaml realscript
OK not set

$ r -r advanced.yaml realscript --ok hello
OK is set
```
