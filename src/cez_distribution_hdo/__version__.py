"""The package version is automatically set by uv-dynamic-versioning."""

from importlib import metadata

__version__: str
try:
    __version__ = metadata.version(__name__.split(".")[0])
except metadata.PackageNotFoundError:
    __version__ = "0.0.0"
