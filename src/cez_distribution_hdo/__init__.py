"""CEZ Distribution HDO integration package."""

from .__version__ import __version__
from .client import CezHdoClient
from .exceptions import ApiError, HttpRequestError, InvalidRequestError, InvalidResponseError
from .service import TariffService, TariffSnapshot, sanitize_signal_for_entity, snapshot_to_dict

__all__ = [
    "ApiError",
    "CezHdoClient",
    "HttpRequestError",
    "InvalidRequestError",
    "InvalidResponseError",
    "TariffService",
    "TariffSnapshot",
    "__version__",
    "sanitize_signal_for_entity",
    "snapshot_to_dict",
]
