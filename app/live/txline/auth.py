"""Authentication helpers for TxLINE REST and SSE requests."""

import httpx

from app.core.logging import get_logger
from app.live.txline.exceptions import (
    TxLineAuthenticationError,
    TxLineSubscriptionMismatchError,
)

logger = get_logger(__name__)


def build_txline_headers(
    guest_jwt: str,
    api_token: str,
    *,
    accept_sse: bool = False,
) -> dict[str, str]:
    """Build the two required TxLINE authentication headers.

    Args:
        guest_jwt: Guest JWT issued by the selected TxLINE network.
        api_token: Activated API token for the on-chain subscription.
        accept_sse: Add the headers required by the scores SSE endpoint.

    Returns:
        Request headers for a TxLINE REST or SSE call.
    """
    headers = {
        "Authorization": f"Bearer {guest_jwt}",
        "X-Api-Token": api_token,
    }
    if accept_sse:
        headers.update(
            {
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
            }
        )
    return headers


def raise_for_txline_auth_error(response: httpx.Response) -> None:
    """Classify TxLINE authentication responses into actionable errors.

    Args:
        response: HTTP response to inspect before generic status handling.

    Raises:
        TxLineAuthenticationError: If the guest JWT is missing or expired.
        TxLineSubscriptionMismatchError: If network/subscription pairing is invalid.
    """
    if response.status_code == 401:
        logger.error(
            "live.txline.auth_expired",
            status_code=response.status_code,
            url=str(response.request.url),
        )
        raise TxLineAuthenticationError(
            "TxLINE guest JWT is expired or invalid. Repeat Task 0's guest-auth flow "
            "and update TXLINE_GUEST_JWT before retrying."
        )

    if response.status_code == 403:
        logger.error(
            "live.txline.subscription_mismatch",
            status_code=response.status_code,
            url=str(response.request.url),
        )
        raise TxLineSubscriptionMismatchError(
            "TxLINE rejected the subscription. Verify TXLINE_NETWORK, "
            "TXLINE_API_BASE_URL, program ID, RPC endpoint, JWT, and API token all "
            "belong to the same network."
        )
