import setuptools
import subprocess


with open("README.md", "r") as f:
    long_description = f.read()


def fetch_tag():
    proc = subprocess.run(
        ["git", "tag", "--points-at", "HEAD"],
        stdout=subprocess.PIPE,
        encoding="utf-8",
        check=True,
    )
    tags = proc.stdout.strip().split("\n")
    if tags[0] == "":
        raise RuntimeError("no tags found")
    return tags[0].replace("v", "")


def shorthash():
    proc = subprocess.run(
        ["git", "log", "-1", "--format='%h'"],
        stdout=subprocess.PIPE,
        encoding="utf-8",
        check=True,
    )
    return proc.stdout.strip().replace("'", "")


try:
    version = fetch_tag()
except Exception as e:
    print("Failed to fetch tag", e)
    try:
        version = f"git+{shorthash()}"
    except Exception as e:
        print("Failed to fetch shorthash", e)
        version = "0.1.5"

print("VERSION", version)
setuptools.setup(
    name="rfilerunner",
    version=version,
    description="a simple command runner",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/goatmobile/rfilerunner",
    author="goatmobile",
    entry_points={
        "console_scripts": ["r = rfilerunner:cli", "rfile = rfilerunner:cli"]
    },
    python_requires=">=3.7",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    packages=setuptools.find_packages(),
    install_requires=["Click", "PyYAML", "watchdog"],
)
