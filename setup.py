import setuptools


with open("README.md", "r") as f:
    long_description = f.read()


setuptools.setup(
    name="rfilerunner",
    version="0.1.3",
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
