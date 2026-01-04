"""The package version is automatically set by uv-dynamic-versioning."""

from importlib import metadata

__version__: str
try:
    __version__ = metadata.version("cez-distribution-hdo")
except metadata.PackageNotFoundError:
    __version__ = "0.0.0"
