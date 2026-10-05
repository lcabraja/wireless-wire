"""Compatibility import for shared host status, usable from source or installed."""
from pathlib import Path
import sys

source = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(source if source.is_dir() else Path("/opt/wireless-wire/wireless-wire.pyz")))
# Alias the actual module so tests and consumers patch the same functions.
from wireless_wire import host_status
sys.modules[__name__] = host_status
