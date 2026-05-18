import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Union, Tuple
from ib_insync import IB, MarketOrder, Order, Trade

from core.protection import cancel_residual_orders_when_flat_on_contract

# Exact CSV `Name` values only — substring matching previously picked up unrelated GA rows
# (e.g. names containing "daily target") and wrong $ limits.
_DAILY_LOSS_PARAM_KEYS: Tuple[str, ...] = ("Max Daily Loss ($)", "Max Daily Loss")
_DAILY_PROFIT_PARAM_KEYS: Tuple[str, ...] = (
    "Max Daily Profit ($)",
    "Max Daily Profit",
    "Daily Profit Target ($)",
    "Daily Target ($)",  # legacy / tests; whole-key match only
)


def _first_positive_param_value(params: Dict[str, Any], keys: Tuple[str, ...]) -> Tuple[Optional[str], float]:
    """Return (matched_key, abs(float value))) for the first key with a positive numeric value."""
    for key in keys:
        if key not in params:
            continue
        entry = params[key]
        if not isinstance(entry, dict):
            continue
        try:
            val = abs(float(entry.get("value", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
        if val > 0:
            return key, val
    return None, 0.0


def _to_local_naive(dt: Union[datetime, None]) -> Union[datetime, None]:
    """
    Normalize datetimes for comparison with datetime.now() (naive local wall clock).
    UTC- or ET-aware values from IB / pytz are converted to local then tz-stripped.
    Naive values are returned unchanged.
    """
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt

try:
    from tools.notifications.email_service import send_email
except ImportError:
    logging.warning("Could not import email_service - notifications will be disabled.")
    send_email = lambda subject, body: False

class SecurityGuard:
    """
    Handles trading safety constraints, orphaned order cleanup, 
    daily PnL limits, and connection health monitoring.
    """
    def __init__(self, params: Dict[str, Any] = None):
        self.params = params or {}
        
        # Connection monitoring
        self.disconnect_start_time: Optional[datetime] = None
        self.disconnect_email_sent: bool = False
        self.DISCONNECT_ALERT_THRESHOLD = 30  # seconds
        
        # State tracking
        self.last_pnl_check = datetime.now()
        self.last_orphan_check = datetime.min
        self.flattened_today = False
        self.flattened_date = None  # Track which date was flattened for daily reset
        self._daily_loss_source_key: Optional[str] = None
        self._daily_profit_source_key: Optional[str] = None

        # Max position limit (from strategy params)
        self.max_open_trades = 1  # Default
        for k, v in self.params.items():
            k_lower = k.lower()
            if 'max open' in k_lower or 'max position' in k_lower:
                try:
                    self.max_open_trades = int(float(v.get('value', 1)))
                except (ValueError, TypeError, AttributeError):
                    pass

        self.max_daily_loss = 0.0
        self.max_daily_profit = 0.0
        lk, lv = _first_positive_param_value(self.params, _DAILY_LOSS_PARAM_KEYS)
        if lk is not None:
            self._daily_loss_source_key = lk
            self.max_daily_loss = lv
        pk, pv = _first_positive_param_value(self.params, _DAILY_PROFIT_PARAM_KEYS)
        if pk is not None:
            self._daily_profit_source_key = pk
            self.max_daily_profit = pv

        if self.max_daily_loss > 0:
            logging.info(
                "🛡️ SecurityGuard Max Daily Loss: -$%s (CSV key: %s)",
                f"{self.max_daily_loss:,.2f}",
                self._daily_loss_source_key,
            )
        if self.max_daily_profit > 0:
            logging.info(
                "🛡️ SecurityGuard Max Daily Profit: +$%s (CSV key: %s)",
                f"{self.max_daily_profit:,.2f}",
                self._daily_profit_source_key,
            )

    def check_connection(self, ib: IB, active_positions: List[Dict]) -> None:
        """
        Check API connection status and send alerts if disconnected.
        Also sends a reconnection email when re-established.
        """
        if not ib.isConnected():
            if self.disconnect_start_time is None:
                self.disconnect_start_time = datetime.now()
                self.disconnect_email_sent = False
                logging.warning("🚨 API disconnected - tracking disconnect time")
            
            if not self.disconnect_email_sent:
                duration = (datetime.now() - self.disconnect_start_time).total_seconds()
                
                if duration >= self.DISCONNECT_ALERT_THRESHOLD:
                    duration_str = f"{int(duration)}s"
                    
                    pos_info = []
                    for bracket in active_positions:
                        direction = bracket.get('direction', 0)
                        if direction != 0:
                            qty = 1 # Fallback
                            if 'stopLoss' in bracket and hasattr(bracket['stopLoss'], 'totalQuantity'):
                                qty = abs(bracket['stopLoss'].totalQuantity)
                            dir_str = 'LONG' if direction == 1 else 'SHORT'
                            pos_info.append(f"  {qty} contract(s) {dir_str}")
                    
                    pos_summary = "\n".join(pos_info) if pos_info else "  No tracked positions"
                    
                    msg = (f"API DISCONNECTION ALERT\n{'='*50}\n\n"
                           f"The Interactive Brokers API connection has been lost.\n\n"
                           f"Duration: {duration_str}\n"
                           f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                           f"Current Positions:\n{pos_summary}\n\n"
                           f"WARNING: Orders may fill without notification while disconnected.")
                    
                    send_email("Trading Bot - API DISCONNECTED", msg)
                    self.disconnect_email_sent = True
        else:
            # We are connected. Check if we just recovered.
            if self.disconnect_start_time is not None:
                duration = (datetime.now() - self.disconnect_start_time).total_seconds()
                duration_str = f"{int(duration)}s"
                
                msg = (f"API RECONNECTION NOTIFICATION\n{'='*50}\n\n"
                       f"The IB API connection has been restored.\n\n"
                       f"Disconnect Duration: {duration_str}\n"
                       f"Reconnection Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                       f"The script will now verify positions and clean up orphaned orders.")
                
                send_email("Trading Bot - API RECONNECTED", msg)
                logging.info(f"🔄 Reconnected after {duration_str}")
                
                self.disconnect_start_time = None
                self.disconnect_email_sent = False

    def check_orphaned_orders(self, ib: IB, contract, tracked_positions: List[Dict]) -> None:
        """
        Cancel active orders for this contract that are NOT part of our `tracked_positions`.
        Protects against rogue stop-losses left behind if a position closed unexpectedly.
        """
        if contract is None or not ib.isConnected():
            return
        now = datetime.now()
        # Throttle orphan checks to reduce race conditions during bracket submission.
        if (now - self.last_orphan_check).total_seconds() < 3:
            return
        self.last_orphan_check = now

        try:
            # 1. Check actual open positions in account
            es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
            has_open_position = any(abs(p.position) > 0 for p in es_positions)
            
            # 2. Get all known IDs from tracked brackets
            tracked_perm_ids = set()
            tracked_order_ids = set()
            tracked_parent_ids = set()
            newest_guard_until = None
            for bracket in tracked_positions:
                entry_obj = bracket.get('entry')
                if entry_obj and getattr(entry_obj, 'orderId', 0):
                    tracked_parent_ids.add(entry_obj.orderId)
                if bracket.get('entryOrderId'):
                    tracked_parent_ids.add(bracket.get('entryOrderId'))
                guard_until = bracket.get('guard_until')
                if guard_until:
                    gu_naive = _to_local_naive(guard_until)
                    if gu_naive is not None:
                        newest_guard_until = (
                            gu_naive
                            if newest_guard_until is None
                            else max(newest_guard_until, gu_naive)
                        )
                for key in ['entry', 'stopLoss', 'takeProfit']:
                    order = bracket.get(key)
                    if not order:
                        continue
                    if hasattr(order, 'permId') and order.permId:
                        tracked_perm_ids.add(order.permId)
                    if hasattr(order, 'orderId') and order.orderId:
                        tracked_order_ids.add(order.orderId)

            # 3. Analyze active trades
            for trade in ib.trades():
                order = trade.order
                if (trade.contract.conId == contract.conId and 
                    trade.isActive() and
                    hasattr(order, 'permId')):
                    
                    # If position is closed, ALL protective orders should be cancelled
                    is_orphaned = False
                    
                    # Grace window: if we are actively building a new bracket, don't cancel.
                    if newest_guard_until is not None and now < newest_guard_until:
                        continue

                    # Brand new pending orders can race with IB assignment; skip.
                    if trade.log:
                        created = _to_local_naive(trade.log[0].time)
                        if created is None:
                            continue
                        if (now - created).total_seconds() < 15:
                            continue

                    if not has_open_position and not tracked_positions:
                        is_orphaned = True
                        
                    # If we DO have a position, but this order isn't in our tracked brackets
                    elif (order.permId not in tracked_perm_ids and
                          order.orderId not in tracked_order_ids):
                        parent_id = getattr(order, 'parentId', 0) or 0
                        # Keep child orders whose parent orderId is tracked.
                        if parent_id in tracked_parent_ids:
                            continue
                        # Only target standalone orders (no parent ID), highly likely to be trailing updates.
                        if parent_id == 0:
                            is_orphaned = True
                        else:
                            # parentId is an orderId (not permId)
                            parent_filled = any(
                                getattr(p_trade.order, 'orderId', 0) == parent_id and p_trade.filled()
                                for p_trade in ib.trades()
                            )
                            if parent_filled:
                                is_orphaned = True
                    
                    if is_orphaned:
                        try:
                            order_type = type(order).__name__
                            ib.cancelOrder(order)
                            logging.info(f"🧹 Cancelled orphaned {order_type} order (PermID: {order.permId})")
                        except Exception as e:
                            logging.warning(f"Error cancelling orphaned order {order.permId}: {e}")

            cancel_residual_orders_when_flat_on_contract(ib, contract, None)

        except Exception as e:
            logging.error(f"Error in check_orphaned_orders: {e}")

    def _check_daily_reset(self):
        """Reset flattened_today flag at midnight for next trading day."""
        today = datetime.now().date()
        if self.flattened_today and self.flattened_date and self.flattened_date < today:
            logging.info("🛡️ SecurityGuard: New trading day - resetting flatten flag")
            self.flattened_today = False
            self.flattened_date = None

    def check_max_positions(self, ib: IB, contract, tracked_positions: List) -> None:
        """
        Enforce max position limit at IB level. Cancels any active entry orders
        if position count exceeds limit.
        """
        if contract is None or not ib.isConnected():
            return
        
        es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId and p.position != 0]
        if len(es_positions) > self.max_open_trades:
            logging.warning(f"🛡️ MAX POSITIONS EXCEEDED: {len(es_positions)} > {self.max_open_trades}. Cancelling entry orders.")
            for trade in ib.trades():
                if (trade.contract.conId == contract.conId and trade.isActive() and
                        isinstance(trade.order, MarketOrder) and
                        (getattr(trade.order, "parentId", 0) or 0) == 0):
                    try:
                        ib.cancelOrder(trade.order)
                        logging.info(f"🛡️ Cancelled excess entry order: {trade.order.orderId}")
                    except Exception as e:
                        logging.warning(f"Error cancelling excess entry: {e}")

    def check_daily_pnl(self, ib: IB, contract, account_summary: Dict[str, float], tracked_positions: List) -> bool:
        """
        Check if daily PnL has breached the Max Loss or Max Profit limits.
        If breached, flattens all positions and cancels all working orders for the contract.

        **Callers must pass an atomic snapshot** for ``account_summary``, e.g. the dict returned
        by ``core.account.get_account_summary()`` (same-timestamp RealizedPNL + UnrealizedPNL).
        Do **not** drive this from ``accountSummaryEvent`` one tag at a time — that mixes fresh
        and stale fields and produces impossible totals (and duplicate false flatten emails).

        Returns True if a flatten occurred, False otherwise.
        """
        self._check_daily_reset()  # Auto-reset at midnight
        
        if contract is None or not ib.isConnected() or self.flattened_today:
            return False
            
        # Limits must be configured
        if self.max_daily_loss == 0 and self.max_daily_profit == 0:
            return False

        # Require coherent PnL fields from get_account_summary() (not per-tag accountSummaryEvent).
        if "RealizedPNL" not in account_summary or "UnrealizedPNL" not in account_summary:
            return False
        try:
            realized = float(account_summary["RealizedPNL"])
            unrealized = float(account_summary["UnrealizedPNL"])
        except (TypeError, ValueError):
            return False

        # Throttle checks (UI loop runs ~1s; avoid hammering IB / duplicate work)
        if (datetime.now() - self.last_pnl_check).total_seconds() < 10:
            return False
        self.last_pnl_check = datetime.now()

        # Daily PnL (realized + unrealized) — values must come from the same atomic snapshot
        total_pnl = realized + unrealized
        
        limit_breached = False
        reason = ""
        
        if self.max_daily_loss > 0 and total_pnl <= -abs(self.max_daily_loss):
            limit_breached = True
            reason = f"MAX DAILY LOSS BREACHED: ${total_pnl:,.2f} <= -${self.max_daily_loss:,.2f}"
            
        elif self.max_daily_profit > 0 and total_pnl >= abs(self.max_daily_profit):
            limit_breached = True
            reason = f"DAILY PROFIT TARGET HIT: ${total_pnl:,.2f} >= ${self.max_daily_profit:,.2f}"

        if limit_breached:
            logging.error(
                "EMERGENCY_FLATTEN total_pnl=%.2f realized=%.2f unrealized=%.2f | %s",
                total_pnl,
                realized,
                unrealized,
                reason,
            )
            logging.error(f"🚨🚨 {reason} 🚨🚨")
            logging.error("Initiating emergency flatten procedure...")
            # Latch before IB work so a burst of accountSummary callbacks cannot each send
            # a separate flatten email while Realized/Unrealized tags are still settling.
            self.flattened_today = True
            self.flattened_date = datetime.now().date()

            try:
                # 1. Cancel all active orders for this contract
                for trade in ib.trades():
                    if trade.contract.conId == contract.conId and trade.isActive():
                        ib.cancelOrder(trade.order)

                # 2. Flatten any open positions
                es_pos = [p for p in ib.positions() if p.contract.conId == contract.conId]
                for p in es_pos:
                    if p.position != 0:
                        action = 'SELL' if p.position > 0 else 'BUY'
                        qty = abs(p.position)

                        logging.info(f"Flattening: {action} {qty} @ MKT")
                        mkt_order = MarketOrder(action, qty, tif="DAY")
                        ib.placeOrder(contract, mkt_order)

                # 3. Clear tracked positions list reference
                tracked_positions.clear()

                time.sleep(0.5)
                cancel_residual_orders_when_flat_on_contract(ib, contract, None)

                src = []
                if self._daily_loss_source_key:
                    src.append(f"loss limit key: {self._daily_loss_source_key}")
                if self._daily_profit_source_key:
                    src.append(f"profit limit key: {self._daily_profit_source_key}")
                src_line = ("; ".join(src) + "\n\n") if src else ""

                # 4. Notify User
                msg = (f"EMERGENCY FLATTEN TRIGGERED\n{'='*50}\n\n"
                       f"Reason: {reason}\n"
                       f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                       f"PnL (same snapshot): realized ${realized:,.2f} + unrealized ${unrealized:,.2f} = ${total_pnl:,.2f}\n"
                       f"(from get_account_summary / accountValues + ES position merge — not per-tag stream)\n\n"
                       f"{src_line}"
                       f"All active orders cancelled and positions closed.\n"
                       f"The bot will evaluate no further trades today.")
                send_email("Trading Bot - EMERGENCY FLATTEN", msg)

                return True

            except Exception as e:
                logging.error(f"Failed during flatten procedure: {e}")

        return False
