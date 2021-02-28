#!/usr/bin/env python
"""scrapli-replay - scrapli mock server and pytest plugin"""
import setuptools

__author__ = "Carl Montanari"
__version__ = "2021.07.30a3"


with open("README.md", "r", encoding="utf-8") as f:
    README = f.read()


with open("requirements.txt", "r") as f:
    INSTALL_REQUIRES = f.read().splitlines()


setuptools.setup(
    name="scrapli_replay",
    version=__version__,
    author=__author__,
    author_email="carl.r.montanari@gmail.com",
    description="Tools to enable easy testing of scrapli programs",
    long_description=README,
    long_description_content_type="text/markdown",
    keywords="ssh telnet netconf automation network cisco iosxr iosxe nxos arista eos juniper "
    "junos",
    url="https://github.com/scrapli/scrapli-replay",
    project_urls={"Changelog": "https://scrapli.github.io/scrapli/scrapli_repaly/chnagelog"},
    license="MIT",
    packages=setuptools.find_packages(),
    install_requires=INSTALL_REQUIRES,
    extras_require={},
    classifiers=[
        "Framework :: Pytest",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.6",
    entry_points={"pytest11": ["scrapli_replay = scrapli_replay.replay.pytest_scrapli_replay"]},
)
