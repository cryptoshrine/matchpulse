"""Exceptions raised by the TxLINE data pipeline."""


class TxLineError(Exception):
    """Base exception for TxLINE data pipeline operations."""


class TxLineAuthenticationError(TxLineError):
    """Raised when the guest JWT is expired or credentials are unset."""


class TxLineSubscriptionMismatchError(TxLineError):
    """Raised when the API token, network, or subscription does not match."""


class TxLineConnectionError(TxLineError):
    """Raised when the TxLINE SSE connection fails."""


class TxLineStreamEndedError(TxLineConnectionError):
    """Raised when an SSE stream reaches EOF and should be reconnected."""
