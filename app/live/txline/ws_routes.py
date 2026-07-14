"""Public WebSocket delivery for MatchPulse state and notifications."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.live.notification_manager import NotificationManager
from app.live.notification_schemas import AnyNotification
from app.live.state_manager import LiveMatchStateManager
from app.live.subscription_manager import LiveEventSubscriptionManager

logger = get_logger(__name__)
router = APIRouter(prefix="/api/matchpulse", tags=["matchpulse-ws"])
STATE_REFRESH_SECONDS = 1.0


def _format_notification(notification: AnyNotification) -> dict[str, Any]:
    """Format the shared live-update envelope used by chat and MatchPulse."""
    timestamp = getattr(notification, "timestamp", datetime.now(UTC))
    timestamp_string = timestamp if isinstance(timestamp, str) else timestamp.isoformat()
    return {
        "type": "live_update",
        "content": notification.message,
        "live_notification": {
            "notification_type": notification.notification_type,
            "match_id": notification.match_id,
            "message": notification.message,
            "event_id": getattr(notification, "event_id", None),
            "timestamp": timestamp_string,
            **notification.model_dump(
                exclude={
                    "notification_type",
                    "match_id",
                    "message",
                    "event_id",
                    "timestamp",
                    "notification_id",
                }
            ),
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def _state_snapshot(
    match_id: int,
    state_manager: LiveMatchStateManager,
    subscription_manager: LiveEventSubscriptionManager,
) -> dict[str, Any]:
    """Build a state snapshot with the current rolling momentum delta."""
    state = await state_manager.get_state(match_id)
    tracker = subscription_manager.get_momentum_tracker(match_id)
    return {
        "type": "state_snapshot",
        "state": state.model_dump(mode="json") if state is not None else None,
        "momentum_delta": tracker.current_delta if tracker is not None else 0.0,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.websocket("/ws/{match_id}")
async def matchpulse_websocket(websocket: WebSocket, match_id: int) -> None:
    """Stream replay state and notifications without authentication."""
    await websocket.accept()
    notification_manager = NotificationManager()
    state_manager = LiveMatchStateManager()
    subscription_manager = LiveEventSubscriptionManager()
    queue = await notification_manager.subscribe(match_id)
    logger.info("matchpulse.websocket.connected", match_id=match_id)

    try:
        await websocket.send_json(
            await _state_snapshot(match_id, state_manager, subscription_manager)
        )
        while True:
            try:
                notification = await asyncio.wait_for(queue.get(), timeout=STATE_REFRESH_SECONDS)
                await websocket.send_json(
                    await _state_snapshot(match_id, state_manager, subscription_manager)
                )
                await websocket.send_json(_format_notification(notification))
            except TimeoutError:
                await websocket.send_json(
                    await _state_snapshot(match_id, state_manager, subscription_manager)
                )
    except WebSocketDisconnect:
        logger.info("matchpulse.websocket.disconnected", match_id=match_id)
    finally:
        await notification_manager.unsubscribe(match_id, queue)
