#!/usr/bin/env python
"""scrapli-replay - tools to enable easy testing of scrapli programs"""
from pathlib import Path

import setuptools

__author__ = "Carl Montanari"
__version__ = "2021.07.30a4"


with open("README.md", "r", encoding="utf-8") as f:
    README = f.read()


with open("requirements.txt", "r") as f:
    INSTALL_REQUIRES = f.read().splitlines()


def get_packages(package):
    """Return root package and all sub-packages"""
    return [str(path.parent) for path in Path(package).glob("**/__init__.py")]


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
    # include scrapli_cfg of course, but make sure to also include py.typed!
    package_data={"scrapli_replay": ["py.typed"]},
    packages=get_packages("scrapli_replay"),
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
    # zip_safe False for mypy
    # https://mypy.readthedocs.io/en/stable/installed_packages.html
    zip_safe=False,
)
