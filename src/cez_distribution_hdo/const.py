"""Constants for CEZ Distribution HDO integration."""

REQUEST_URL: str = (
    "https://dip.cezdistribuce.cz/irj/portal/anonymous/casy-spinani?path=switch-times/signals"
)
"""URL for fetching HDO switch times."""

KEY_NAME_EAN: str = "ean"
"""EAN number of the electricity meter."""
KEY_NAME_SN: str = "sn"
"""Serial number of the electricity meter."""
KEY_NAME_PLACE: str = "place"
"""Place number of the electricity meter."""

DEFAULT_TIMEOUT: int = 10
"""Default timeout for HTTP requests in seconds."""

# Named constant for successful API response status code
HTTP_STATUS_OK = 200
MAX_PRINT_SIGNALS = 10

TARIFF_LOW = "NT"
TARIFF_HIGH = "VT"
"""Tariff type constants: NT (low tariff) and VT (high tariff)."""
