"""Tests for TxLINE header and authentication response helpers."""

import httpx
import pytest

from app.live.txline.auth import build_txline_headers, raise_for_txline_auth_error
from app.live.txline.exceptions import (
    TxLineAuthenticationError,
    TxLineSubscriptionMismatchError,
)


def _response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("GET", "https://txline.test/api/fixtures/snapshot"),
    )


def test_build_headers_for_rest() -> None:
    headers = build_txline_headers("jwt", "token")

    assert headers == {"Authorization": "Bearer jwt", "X-Api-Token": "token"}


def test_build_headers_for_sse() -> None:
    headers = build_txline_headers("jwt", "token", accept_sse=True)

    assert headers == {
        "Authorization": "Bearer jwt",
        "X-Api-Token": "token",
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
    }


def test_unauthorized_response_raises_authentication_error() -> None:
    with pytest.raises(TxLineAuthenticationError, match="guest JWT"):
        raise_for_txline_auth_error(_response(401))


def test_forbidden_response_raises_subscription_error() -> None:
    with pytest.raises(TxLineSubscriptionMismatchError, match="same network"):
        raise_for_txline_auth_error(_response(403))


def test_success_response_does_not_raise() -> None:
    raise_for_txline_auth_error(_response(200))
