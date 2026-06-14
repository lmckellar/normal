"""Local workbench for movie library normalization and quality management."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("normal")
except PackageNotFoundError:
    __version__ = "0+unknown"
