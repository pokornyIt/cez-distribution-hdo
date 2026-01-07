"""CEZ Distribution HDO integration package."""

from .__version__ import __version__
from .client import CezHdoClient
from .exceptions import ApiError, HttpRequestError, InvalidRequestError, InvalidResponseError
from .models import SignalsResponse
from .service import TariffService, TariffSnapshot, sanitize_signal_for_entity, snapshot_to_dict
from .validators import validate_ean

__all__ = [
    "ApiError",
    "CezHdoClient",
    "HttpRequestError",
    "InvalidRequestError",
    "InvalidResponseError",
    "SignalsResponse",
    "TariffService",
    "TariffSnapshot",
    "__version__",
    "sanitize_signal_for_entity",
    "snapshot_to_dict",
    "validate_ean",
]
