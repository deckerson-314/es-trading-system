"""
core/connection.py - IBKR Connection & Contract Management
Ported from ib_deployment_v4.py lines 1553-1573, 3882-3911
"""
import logging
import asyncio
import os
from datetime import datetime, timedelta
from ib_insync import Future

from core.client_id_guard import ClientIdInUseError
from core.shutdown import ShutdownRequested, interruptible_sleep, is_shutdown_requested

# First wave: short waits while IB Gateway restarts (nightly reboot is usually 1–5 min).
_GHOST_CLIENT_ID_WAIT_SEC = (3, 5, 8, 10, 15, 20, 25, 30, 40, 50, 60)
# After the wave, keep trying every 60s until Gateway is back (do not exit / rotate clientId).
_STEADY_RECONNECT_WAIT_SEC = 60
_GATEWAY_DOWN_WAIT_CAP_SEC = 60


def warn_stale_persisted_client_id(port: int, expected_client_id: int, mode: str = "PAPER") -> None:
    """Legacy spillover left ib_last_client_id_*.json — warn if it disagrees with config."""
    path = os.path.join(f"{mode.lower()}_logs", f"ib_last_client_id_{int(port)}.json")
    if not os.path.isfile(path):
        return
    try:
        import json
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        old = int(data.get("client_id", 0) or 0)
        if old > 0 and old != int(expected_client_id):
            logging.critical(
                "Removing stale %s (recorded clientId %s; bot uses %s only). "
                "Cancel any open orders on old clientIds in TWS.",
                path,
                old,
                expected_client_id,
            )
            os.remove(path)
    except Exception as e:
        logging.warning("Could not read legacy clientId file %s: %s", path, e)


def _is_client_id_in_use_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "client id is already in use" in msg or "326" in msg


def _is_gateway_down_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "connection refused",
            "connect call failed",
            "failed to connect",
            "timeout",
            "timed out",
            "connection reset",
            "no connection",
            "socket",
            "10061",
            "10054",
        )
    )


async def disconnect_ib_quiet(ib) -> None:
    """Release local API session so Gateway can free the clientId slot after reboot."""
    try:
        if ib.isConnected():
            ib.disconnect()
            await asyncio.sleep(0.5)
    except Exception:
        pass


def get_front_es_contract(ib):
    """Auto-resolve front-month ES contract. Retries 3 times with 5s delay."""
    for attempt in range(3):
        if is_shutdown_requested():
            raise ShutdownRequested()
        try:
            temp_contract = Future('ES', '', 'CME', currency='USD')
            cds = ib.reqContractDetails(temp_contract)
            if not cds:
                raise ValueError("No ES contracts found")
            today = datetime.now().date()
            # Customary ES roll happens 8 days before expiration (3rd Friday)
            roll_cutoff = today + timedelta(days=8)
            future_cds = [cd for cd in cds
                         if datetime.strptime(cd.contract.lastTradeDateOrContractMonth, '%Y%m%d').date() > roll_cutoff]
            if not future_cds:
                raise ValueError("No future ES contract found")
            front = min(future_cds,
                       key=lambda cd: datetime.strptime(cd.contract.lastTradeDateOrContractMonth, '%Y%m%d'))
            ib.qualifyContracts(front.contract)
            logging.info(f"Resolved front ES contract: {front.contract.conId} exp {front.contract.lastTradeDateOrContractMonth}")
            return front.contract
        except ShutdownRequested:
            raise
        except Exception as e:
            logging.error(f"Failed to resolve contract on attempt {attempt+1}: {e}")
            if attempt < 2:
                interruptible_sleep(5)
    raise ValueError("Failed to resolve ES contract after retries")


def _reconnect_wait_sec(attempt: int, *, client_id_busy: bool) -> int:
    if attempt == 0:
        return 0
    if client_id_busy:
        if attempt <= len(_GHOST_CLIENT_ID_WAIT_SEC):
            return _GHOST_CLIENT_ID_WAIT_SEC[attempt - 1]
        return _STEADY_RECONNECT_WAIT_SEC
    # Gateway still starting / port closed
    return min(_GATEWAY_DOWN_WAIT_CAP_SEC, 5 * attempt)


async def connect_with_retry(
    ib,
    host='127.0.0.1',
    port=7497,
    base_client_id=100,
    max_retries=5,
    mode='PAPER',
    give_up: bool = False,
):
    """
    Connect using exactly one configured clientId. Never rotates to another id.

    Default (give_up=False): retry until connected — intended for production including
    nightly IB Gateway reboot. A disconnect is normal; the bot waits for Gateway to
    return and reuses the same --client_id.

    give_up=True: stop after one ghost wave and raise (unit tests / manual diagnostics).
    """
    del max_retries
    warn_stale_persisted_client_id(port, base_client_id, mode)
    client_id = int(base_client_id)
    attempt = 0
    logged_steady = False

    while True:
        if is_shutdown_requested():
            raise ShutdownRequested()

        wait_sec = _reconnect_wait_sec(attempt, client_id_busy=(attempt > 0))
        if attempt > 0 and wait_sec > 0:
            reason = (
                "clientId slot busy (post-reboot ghost)"
                if attempt <= len(_GHOST_CLIENT_ID_WAIT_SEC)
                else "waiting for IB Gateway"
            )
            logging.info(
                "IB reconnect: %s — retry clientId %s in %ss (attempt %s)",
                reason,
                client_id,
                wait_sec,
                attempt + 1,
            )
            await asyncio.sleep(wait_sec)

        try:
            await disconnect_ib_quiet(ib)
            if attempt == 0:
                logging.info(
                    "Connecting to IB on port %s with clientId %s (exclusive, no rotation)...",
                    port,
                    client_id,
                )
            await ib.connectAsync(host, port, clientId=client_id, timeout=20)
            logging.info("Connected to IB with clientId %s", client_id)
            return client_id
        except ShutdownRequested:
            raise
        except Exception as e:
            attempt += 1
            if _is_client_id_in_use_error(e):
                if attempt == 1:
                    logging.warning(
                        "clientId %s temporarily in use after disconnect — normal during "
                        "nightly Gateway restart; will keep retrying same clientId (not %s).",
                        client_id,
                        client_id + 1,
                    )
                elif attempt > len(_GHOST_CLIENT_ID_WAIT_SEC) and not logged_steady:
                    logged_steady = True
                    logging.warning(
                        "clientId %s still busy — continuing 60s retries (check for a second "
                        "bot process only if this persists >30 min).",
                        client_id,
                    )
                if give_up and attempt > len(_GHOST_CLIENT_ID_WAIT_SEC):
                    raise ClientIdInUseError(
                        f"clientId {client_id} still in use on port {port} after ghost wave "
                        f"(give_up=True). Production uses give_up=False and keeps retrying."
                    ) from e
                continue
            if _is_gateway_down_error(e):
                if attempt == 1:
                    logging.warning(
                        "IB Gateway not reachable on port %s (restarting?) — will retry until back.",
                        port,
                    )
                else:
                    logging.debug("Gateway still down: %s", e)
                if give_up and attempt >= 12:
                    raise RuntimeError(
                        f"IB Gateway on port {port} not reachable after {attempt} attempts: {e}"
                    ) from e
                continue
            logging.error("Unexpected connect error on clientId %s: %s", client_id, e)
            if give_up and attempt >= 5:
                raise RuntimeError(
                    f"Failed to connect on port {port} clientId {client_id}: {e}"
                ) from e
            continue


def request_historical_data_with_retry(ib, contract, max_retries=5):
    """Request historical data with exponential backoff. Returns bars object."""
    for attempt in range(max_retries):
        if is_shutdown_requested():
            raise ShutdownRequested()
        try:
            logging.info(f"Requesting historical data (attempt {attempt+1}/{max_retries})...")
            ib.reqMarketDataType(1)  # Live data
            bars = ib.reqHistoricalData(
                contract, endDateTime='', durationStr='10 D',
                barSizeSetting='1 min', whatToShow='TRADES',
                useRTH=False, keepUpToDate=True
            )
            if bars and len(bars) > 0:
                logging.info(f"Received {len(bars)} historical bars")
                return bars
            else:
                raise ValueError("Empty bars returned")
        except ShutdownRequested:
            raise
        except Exception as e:
            delay = min(2 ** attempt, 32)
            logging.error(f"Historical data request failed (attempt {attempt+1}): {e}. Retrying in {delay}s...")
            if attempt < max_retries - 1:
                interruptible_sleep(delay)
            else:
                raise
    return None
