"""Available screen adapters. Rendering is independent of these modules."""
from importlib import import_module

ADAPTERS = {"turing-35-rev-a": "driver.turing_35_rev_a"}


def load(name):
    return import_module(ADAPTERS[name])
