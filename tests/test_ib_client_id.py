"""Connection policy: single clientId, infinite retry until Gateway returns."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.connection import (
    _is_client_id_in_use_error,
    _is_gateway_down_error,
    connect_with_retry,
)
from core.client_id_guard import ClientIdInUseError
from core.shutdown import ShutdownRequested


def test_client_id_in_use_error_detection():
    assert _is_client_id_in_use_error(Exception("Error 326: client id is already in use"))
    assert _is_gateway_down_error(ConnectionRefusedError("connection refused"))


def test_connect_retries_through_gateway_down_then_succeeds():
    ib = MagicMock()
    ib.isConnected.return_value = False
    ib.disconnect = MagicMock()
    calls = {"n": 0}

    async def _connect(*_a, **_k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionRefusedError("connection refused")
        return None

    ib.connectAsync = AsyncMock(side_effect=_connect)
    async def _run():
        with patch("core.connection.asyncio.sleep", new_callable=AsyncMock):
            return await connect_with_retry(
                ib, port=4002, base_client_id=100, give_up=False,
            )

    cid = asyncio.run(_run())
    assert cid == 100
    assert calls["n"] == 3


def test_connect_give_up_raises_on_persistent_326():
    ib = MagicMock()
    ib.isConnected.return_value = False
    ib.disconnect = MagicMock()
    ib.connectAsync = AsyncMock(
        side_effect=Exception("326 client id is already in use"),
    )
    async def _run():
        with patch("core.connection.asyncio.sleep", new_callable=AsyncMock):
            await connect_with_retry(
                ib, port=4002, base_client_id=100, give_up=True,
            )

    with pytest.raises(ClientIdInUseError):
        asyncio.run(_run())


def test_connect_respects_shutdown():
    ib = MagicMock()
    ib.isConnected.return_value = False
    async def _run():
        await connect_with_retry(ib, base_client_id=100)

    with patch("core.connection.is_shutdown_requested", return_value=True):
        with pytest.raises(ShutdownRequested):
            asyncio.run(_run())
