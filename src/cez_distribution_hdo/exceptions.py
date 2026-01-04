"""Custom exceptions for CEZ Distribution HDO client."""

from __future__ import annotations


class CezHdoError(Exception):
    """Base error for the CEZ Distribution HDO module."""


class InvalidRequestError(CezHdoError):
    """Raised when the request payload is invalid."""


class HttpRequestError(CezHdoError):
    """Raised when the HTTP request fails or times out."""


class InvalidResponseError(CezHdoError):
    """Raised when the response JSON is missing expected fields or is malformed."""


class ApiError(CezHdoError):
    """Raised when the API returns a non-success status in the payload."""
