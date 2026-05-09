"""
core/execution.py - Trade Entry & Exit Logic
Ported from ib_deployment_v4.py lines 2250-3185
"""
import logging
import traceback
import pandas as pd
import numpy as np
import os
import copy
from datetime import datetime, timedelta, date
from core.charting import create_trade_chart
from ib_insync import MarketOrder, StopOrder, LimitOrder
import pytz

from core.account import get_account_summary, format_duration, add_to_live_tracker


def _snapshot_strategy_params(strategy) -> dict:
    """Capture a stable, serializable parameter snapshot at entry time."""
    snap = {}
    try:
        if hasattr(strategy, "params_dict") and isinstance(strategy.params_dict, dict):
            snap = copy.deepcopy(strategy.params_dict)
        else:
            attrs = [
                "timeframe", "lookback_buy", "lookback_sell", "initial_sl_pct", "tp_mult_atr",
                "enable_trailing", "atr_mult_ts", "atr_length_ts", "trailing_delay",
                "enable_adx_filter", "adx_period", "min_adx", "min_atr_points", "atr_filter_period",
                "enable_rsi_filter", "rsi_period", "rsi_max_buy", "rsi_min_sell",
                "enable_sma_filter", "sma_period", "enable_vol_filter", "vol_ma_length", "min_vol_mult",
                "enable_vwap_filter", "enable_rth_filter", "rth_start_str", "rth_end_str",
                "rth_exit_buffer_minutes", "enable_maintenance_filter",
                "daily_maintenance_start_str", "daily_maintenance_end_str",
                "weekend_maintenance_start_day", "weekend_maintenance_start_time_str",
                "weekend_maintenance_end_day", "weekend_maintenance_end_time_str",
                "maintenance_buffer_minutes",
            ]
            for name in attrs:
                if hasattr(strategy, name):
                    snap[name] = getattr(strategy, name)
    except Exception:
        return {}
    return snap


def _row_bool(row, key: str) -> bool:
    if isinstance(row, pd.Series):
        return bool(row.get(key, False))
    if isinstance(row, dict):
        return bool(row.get(key, False))
    return bool(getattr(row, key, False))


def _in_rth_flatten_window_wall_clock(strategy) -> bool:
    """True during [RTH_end - buffer, RTH_end): block new entries (matches flatten policy)."""
    if not getattr(strategy, 'enable_rth_filter', False):
        return False
    buf = int(getattr(strategy, 'rth_exit_buffer_minutes', 0) or 0)
    if buf <= 0:
        return False
    rth_end = getattr(strategy, 'rth_end', None)
    if rth_end is None:
        return False
    et = pytz.timezone('US/Eastern')
    now_t = datetime.now(et).time()
    ref = datetime.combine(date.today(), rth_end)
    start_buf = (ref - timedelta(minutes=buf)).time()
    return start_buf <= now_t < rth_end


def _align_ts_naive_et(ts):
    """Normalize bar/entry timestamps to naive US/Eastern for safe comparison."""
    if ts is None:
        return None
    t = pd.Timestamp(ts)
    if getattr(t, 'tzinfo', None) is not None:
        t = t.tz_convert('America/New_York').tz_localize(None)
    return t


def _find_entry_trade(ib, contract, order_id: int, perm_id: int):
    """Locate entry trade by orderId first, then permId."""
    for t in ib.trades():
        if t.contract.conId != contract.conId:
            continue
        if order_id and getattr(t.order, 'orderId', 0) == order_id:
            return t
        if perm_id and getattr(t.order, 'permId', 0) == perm_id:
            return t
    return None


def _ohlcv_resample_for_timeframe(df: pd.DataFrame, timeframe_mins: int) -> pd.DataFrame:
    """Resample 1-minute OHLCV to strategy timeframe (same rules as core.monitoring.resample_data)."""
    base_cols = ['open', 'high', 'low', 'close', 'volume']
    for c in base_cols:
        if c not in df.columns:
            raise ValueError(f"Missing column {c} for resample")
    ohlcv = df[base_cols].copy()
    tf = max(1, int(timeframe_mins or 1))
    if tf <= 1:
        return ohlcv
    logic = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    resampled = ohlcv.resample(f'{tf}min', closed='right', label='right').agg(logic)
    return resampled.dropna()


def check_entries(strategy, ib, contract, data, positions, params_dict, 
                  live_tracker, dashboard_state, send_email_fn, idx, latest_row):
    """Check entry signals and place bracket orders if triggered."""
    # --- Re-entrancy & Bar Debounce Guards ---
    if getattr(check_entries, 'is_processing', False):
        logging.debug("Entry check already in progress, skipping.")
        return
    
    if getattr(check_entries, 'last_idx', None) == idx:
        logging.debug(f"Already processed bar {idx} for entries. Skipping.")
        return

    # Extra Safety: Check for active orders for this contract to prevent double entry
    active_orders = [t for t in ib.trades() if t.contract.conId == contract.conId and t.isActive()]
    if active_orders:
        logging.info(f"Entry blocked: {len(active_orders)} active orders already exist for {contract.localSymbol}")
        return

    # --- Position Count Check (THE STORM FIX) ---
    max_trades = getattr(strategy, 'max_open_trades', 1)
    if len(positions) >= max_trades:
        logging.info(f"Entry blocked: Max trades ({len(positions)}/{max_trades}) already open")
        return

    if _in_rth_flatten_window_wall_clock(strategy):
        logging.info("Entry blocked: RTH end flatten window (wall-clock Eastern)")
        return
    if _row_bool(latest_row, 'force_exit_rth') or _row_bool(latest_row, 'force_exit'):
        logging.info("Entry blocked: force-exit window on signal row (RTH/maintenance)")
        return

    # --- Signal Check ---
    # Check filters
    in_maint = latest_row.get('in_maintenance', False)
    if not (latest_row.get('in_rth', True) and latest_row.get('atr_filter', True) and
            latest_row.get('volume_filter', True) and not in_maint):
        return

    # Strategy-agnostic entry check
    if hasattr(strategy, 'check_entry'):
        triggered, direction_str, _ = strategy.check_entry(latest_row, data)
        enter_long = triggered and direction_str == 'Long'
        enter_short = triggered and direction_str == 'Short'
    elif hasattr(strategy, 'calculate_entry_signals'):
        try:
            tf = max(1, int(getattr(strategy, 'timeframe', 1) or 1))
            htf = _ohlcv_resample_for_timeframe(data, tf)
            data_ind = strategy.calculate_indicators(htf.copy())
            if hasattr(strategy, 'apply_filters'):
                data_ind = strategy.apply_filters(data_ind)
            sigs = strategy.calculate_entry_signals(data_ind)
            if len(sigs) == 3:
                long_sig, short_sig, _ = sigs
            else:
                long_sig, short_sig = sigs
            if idx not in long_sig.index or idx not in short_sig.index:
                logging.debug(f"Entry signal index {idx} not in HTF signal range (tf={tf}).")
                return
            enter_long = bool(long_sig.loc[idx])
            enter_short = bool(short_sig.loc[idx])
        except Exception:
            logging.exception("calculate_entry_signals failed in check_entries")
            return
    else:
        return

    if not (enter_long or enter_short):
        return

    # Record this bar as processed once a signal is detected or we reach this point
    check_entries.last_idx = idx
    check_entries.is_processing = True
    
    try:
        direction = 1 if enter_long else -1
        action = 'BUY' if direction == 1 else 'SELL'
        qty = strategy.qty if hasattr(strategy, 'qty') else 1

        # Setup position using strategy
        entry_price = latest_row['close']
        position_dict = strategy.setup_position(entry_price, direction, latest_row, data)
        stop_price = position_dict['stop']
        tp = position_dict.get('tp')

        # Round to ES tick size (0.25) and validate
        entry_price = round(float(entry_price) * 4) / 4
        
        # SL Validation
        if stop_price is None or pd.isna(stop_price) or stop_price <= 0:
            logging.error(f"CRITICAL: Invalid Stop Price ({stop_price}). Cannot enter trade.")
            add_to_live_tracker(live_tracker, 'error', "Entry blocked: Invalid SL price")
            return
        stop_price = round(float(stop_price) * 4) / 4

        # TP Validation
        valid_tp = False
        if tp is not None and not pd.isna(tp) and tp > 0:
            tp = round(float(tp) * 4) / 4
            if (direction == 1 and tp > entry_price) or (direction == -1 and tp < entry_price):
                valid_tp = True
            
            if not valid_tp:
                logging.warning(f"Invalid TP price {tp} relative to entry {entry_price}. TP disabled.")
                tp = None
        else:
            tp = None

        # Create bracket order
        oca_group = f"bracket_{datetime.now().strftime('%M%S%f')}"
        
        # Explicitly set TIF to GTC to avoid 10349 rejection from IBKR presets
        entry_order = MarketOrder(action=action, totalQuantity=qty, transmit=False, tif='GTC')
        
        # Place entry order
        trade = ib.placeOrder(contract, entry_order)
        
        # --- ATOMIC TRACKING ---
        # Add to positions list IMMEDIATELY to prevent re-entrant checks from seeing empty list
        entry_time = datetime.now()
        bracket = {
            'entry': entry_order, 'stopLoss': None, 'takeProfit': None,
            'direction': direction, 'position_dict': position_dict,
            'entry_time': entry_time, 'entry_price': entry_price,
            'entry_stop_price': stop_price,
            'entry_tp_price': tp,
            'params_snapshot': _snapshot_strategy_params(strategy),
            'ocaGroup': oca_group,  # Store for protection logic
            'contract': contract,
            # Guard cleanup logic against race/callback timing for newly submitted bracket.
            'created_at': datetime.now(pytz.utc),
            'guard_until': datetime.now(pytz.utc) + timedelta(seconds=20),
        }
        positions.append(bracket)

        # Wait brief moment for IB to assign OrderId/PermID
        ib.sleep(1)

        entry_order_id = entry_order.orderId
        if entry_order_id == 0 and trade and trade.order:
            entry_order_id = trade.order.orderId
        if entry_order_id == 0:
            logging.error("Failed to get entry orderId, cannot link bracket orders accurately")
        else:
            bracket['entryOrderId'] = entry_order_id

        # Stop loss
        stop_action = 'SELL' if direction == 1 else 'BUY'
        stop_order = StopOrder(
            action=stop_action, totalQuantity=qty, stopPrice=stop_price,
            parentId=entry_order_id, tif='GTC',
            ocaGroup=oca_group if tp is not None else None,
            ocaType=1 if tp is not None else None,
            transmit=False if tp is not None else True
        )
        bracket['stopLoss'] = stop_order

        # Take profit
        tp_order = None
        if tp is not None:
            tp_action = 'SELL' if direction == 1 else 'BUY'
            tp_order = LimitOrder(
                action=tp_action, totalQuantity=qty, lmtPrice=tp,
                parentId=entry_order_id, tif='GTC',
                ocaGroup=oca_group, ocaType=1,
                transmit=True
            )
            bracket['takeProfit'] = tp_order
            ib.placeOrder(contract, stop_order)
            ib.placeOrder(contract, tp_order)
        else:
            ib.placeOrder(contract, stop_order)

    except Exception as e:
        logging.error(f"Failed to place orders: {e}")
        logging.error(traceback.format_exc())
        if 'bracket' in locals() and bracket in positions:
            positions.remove(bracket)
    finally:
        check_entries.is_processing = False

    ib.sleep(0.5)

    # Entry notifications are sent only after confirming the parent actually filled.
    entry_perm = getattr(entry_order, 'permId', 0)
    confirmed_trade = _find_entry_trade(ib, contract, entry_order_id if 'entry_order_id' in locals() else 0, entry_perm)
    is_filled = bool(confirmed_trade and confirmed_trade.filled())
    if is_filled:
        account = get_account_summary(ib, data, contract)
        contract_multiplier = 50
        risk_dollars = abs(entry_price - stop_price) * contract_multiplier * qty
        reward_dollars = abs(entry_price - tp) * contract_multiplier * qty if tp else None
        rr_ratio = reward_dollars / risk_dollars if (tp and risk_dollars > 0) else None

        msg_lines = [
            f"TRADE OPEN - {'LONG' if direction==1 else 'SHORT'}",
            f"{'='*50}",
            f"Entry Price: ${entry_price:.2f}",
            f"Stop Loss: ${stop_price:.2f} (Risk: ${risk_dollars:,.2f})",
            f"Take Profit: ${tp:.2f} (Reward: ${reward_dollars:,.2f})" if tp else "Take Profit: None",
            f"Risk/Reward: {rr_ratio:.2f}:1" if rr_ratio else "Risk/Reward: N/A",
            f"Position Size: {qty} contract(s)",
            f"",
            f"Account: NetLiq=${account.get('NetLiquidation', 'N/A')}, "
            f"Cash=${account.get('TotalCashValue', 'N/A')}",
            f"Time: {entry_time.strftime('%Y-%m-%d %H:%M:%S')}"
        ]
        dir_str = 'L' if direction == 1 else 'S'
        subj = f"[BB] O: {dir_str} {qty}@{entry_price:.2f}"
        send_email_fn(subj, "\n".join(msg_lines))
        tp_str = f"${tp:.2f}" if tp else "None"
        logging.info(f"TRADE OPEN: {'LONG' if direction==1 else 'SHORT'} @ {entry_price:.2f}, "
                     f"SL: {stop_price:.2f}, TP: {tp_str}")
        add_to_live_tracker(live_tracker, 'trade',
            f"TRADE OPEN: {'LONG' if direction==1 else 'SHORT'} @ ${entry_price:.2f}, SL: ${stop_price:.2f}")
    else:
        logging.warning(
            "Entry parent not filled yet/rejected; suppressing TRADE OPEN email/log until confirmed fill "
            f"(orderId={entry_order_id if 'entry_order_id' in locals() else 0}, permId={entry_perm})"
        )
    
    # Double check order placement success
    ib.sleep(0.5)
    if stop_order and not ib.trades()[-1].isActive() and ib.trades()[-1].orderStatus.status == 'Rejected':
        logging.error(f"CRITICAL: Stop order REJECTED: {ib.trades()[-1].orderStatus.statusReason}")
        send_email_fn("CRITICAL ERROR: Stop Loss Rejected", 
                      f"Stop Loss for {'LONG' if direction==1 else 'SHORT'} @ {entry_price} was rejected.\n"
                      f"Reason: {ib.trades()[-1].orderStatus.statusReason}")
    


def _record_flatten_close_from_market_order(
    ib, bracket_contract, bracket, entry_trade, close_trade,
    dir_, qty, reason_label, stop_at_close_snap, tp_at_close_snap,
    completed_trades, live_tracker, send_email_fn, data, strategy=None,
    send_close_email: bool = False,
):
    """
    Record a completed trade after RTH/maintenance (or similar) forced market flatten.
    Snapshots SL/TP prices must be taken before those orders were cancelled.
    """
    reason = f"{reason_label} (forced close)"
    entry_price = float(bracket.get('entry_price', 0) or 0)
    entry_time = bracket.get('entry_time')
    if not entry_price and entry_trade and getattr(entry_trade, 'fills', None):
        try:
            entry_price = float(entry_trade.fills[0].execution.price)
        except Exception:
            pass

    exit_price = 0.0
    pnl = 0.0
    if close_trade and close_trade.fills:
        try:
            exit_price = float(close_trade.fills[-1].execution.price)
        except Exception:
            exit_price = 0.0
        for f in close_trade.fills:
            cr = getattr(f, 'commissionReport', None)
            if cr is not None and hasattr(cr, 'realizedPNL') and cr.realizedPNL is not None:
                pnl = float(cr.realizedPNL)
                break
        if pnl == 0 and entry_price > 0 and exit_price > 0:
            pnl = (exit_price - entry_price) * dir_ * 50 * qty
    else:
        expected_side = 'SLD' if dir_ == 1 else 'BOT'
        is_aware = entry_time and getattr(entry_time, 'tzinfo', None) is not None
        ref_time = entry_time
        for f in reversed(ib.fills()):
            if f.contract.conId != bracket_contract.conId:
                continue
            if not hasattr(f, 'execution') or f.execution.side != expected_side:
                continue
            f_time = f.execution.time
            if is_aware and f_time.tzinfo is None:
                f_time = pytz.utc.localize(f_time)
            elif not is_aware and f_time.tzinfo is not None:
                f_time = f_time.replace(tzinfo=None)
            if ref_time and f_time < (ref_time - pd.Timedelta(seconds=5)):
                continue
            if abs(f.execution.shares) < qty:
                continue
            exit_price = float(f.execution.price)
            if f.commissionReport and hasattr(f.commissionReport, 'realizedPNL'):
                pnl = float(f.commissionReport.realizedPNL or 0)
            if pnl == 0 and entry_price > 0:
                pnl = (exit_price - entry_price) * dir_ * 50 * qty
            break

    if exit_price <= 0 and data is not None and not data.empty:
        exit_price = float(data['close'].iloc[-1])
        if entry_price > 0 and pnl == 0:
            pnl = (exit_price - entry_price) * dir_ * 50 * qty

    is_aware = entry_time and getattr(entry_time, 'tzinfo', None) is not None
    exit_time = datetime.now()
    if is_aware:
        exit_time = exit_time.astimezone(pytz.utc)

    duration_str = format_duration((exit_time - entry_time).total_seconds()) if entry_time else "N/A"

    curr_stop = float(stop_at_close_snap) if stop_at_close_snap is not None else 0.0
    initial_risk = abs(entry_price - curr_stop) * 50 * qty if curr_stop else 0
    r_multiple = pnl / initial_risk if initial_risk > 0 else 0

    report_url = ""
    if strategy:
        try:
            trades_dir = os.path.join(os.getcwd(), 'web', 'trades')
            os.makedirs(trades_dir, exist_ok=True)
            report_path = strategy.generate_trade_report(
                {
                    'entry_time': entry_time, 'exit_time': exit_time,
                    'direction': dir_, 'entry_price': entry_price,
                    'exit_price': exit_price, 'pnl': pnl, 'qty': qty,
                    'reason': reason,
                    'stop_at_close': stop_at_close_snap,
                    'tp_at_close': tp_at_close_snap,
                    'stop_at_open': bracket.get('entry_stop_price'),
                    'tp_at_open': bracket.get('entry_tp_price'),
                    'params_snapshot': bracket.get('params_snapshot') or {},
                },
                data, trades_dir
            )
            if report_path:
                report_url = f"trades/{os.path.basename(report_path)}"
        except Exception as e:
            logging.error(f"Failed to generate HTML report (flatten): {e}")

    if send_close_email:
        _send_trade_close_notification(
            ib, bracket, dir_, entry_price, exit_price, pnl, qty, reason,
            duration_str, exit_time, data, send_email_fn, live_tracker,
            report_url=report_url
        )

    logging.info(f"TRADE CLOSE: {reason} @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
    add_to_live_tracker(live_tracker, 'trade',
                        f"CLOSE ({reason}): @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")

    completed_trades.append({
        'exit_time': exit_time, 'entry_time': entry_time,
        'direction': 'LONG' if dir_ == 1 else 'SHORT',
        'qty': qty, 'entry_price': entry_price, 'exit_price': exit_price,
        'pnl': pnl, 'r_multiple': r_multiple, 'reason': reason,
        'duration': duration_str,
        'report_url': report_url,
        'params_snapshot': bracket.get('params_snapshot') or {},
        'stop_at_open': bracket.get('entry_stop_price'),
        'tp_at_open': bracket.get('entry_tp_price'),
        'stop_at_close': stop_at_close_snap,
        'tp_at_close': tp_at_close_snap,
        'entry_order_id': bracket.get('entryOrderId'),
    })
    if len(completed_trades) > 1000:
        del completed_trades[:-1000]

    try:
        active_for_contract = [t for t in ib.trades() if t.contract.conId == bracket_contract.conId and t.isActive()]
        for trade in active_for_contract:
            perm_id = trade.order.permId
            if entry_trade and perm_id == getattr(entry_trade.order, 'permId', 0):
                continue
            logging.info(f"Cleanup: Cancelling active order {trade.order.orderType} {trade.order.action} (PermID: {perm_id}) for {bracket_contract.localSymbol}")
            ib.cancelOrder(trade.order)
    except Exception as e:
        logging.error(f"Error during flatten orphan cleanup: {e}")


def _close_all_positions(reason_label, ib, contract, positions, data,
                         live_tracker, send_email_fn, strategy=None, account_fn=None,
                         completed_trades=None):
    """Close all tracked positions with market orders; record completed_trades like other exits."""
    for bracket in positions[:]:
        try:
            entry_order = bracket['entry']
            entry_trade = next((t for t in ib.trades() if t.order.permId == entry_order.permId), None)

            # If entry trade is not filled yet, cancel it
            if entry_trade and entry_trade.isActive():
                ib.cancelOrder(entry_trade.order)
                logging.info(f"Cancelled active entry order during {reason_label} exit")

            # Use bracket's contract if available, fallback to global
            bracket_contract = bracket.get('contract', contract)
            es_positions = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]

            if not es_positions or es_positions[0].position == 0:
                if bracket in positions:
                    positions.remove(bracket)
                continue

            actual_pos = es_positions[0].position
            actual_qty = abs(actual_pos)
            dir_ = 1 if actual_pos > 0 else -1
            close_action = 'SELL' if actual_pos > 0 else 'BUY'

            stop_order = bracket.get('stopLoss')
            tp_order = bracket.get('takeProfit')
            stop_snap = None
            tp_snap = None
            if stop_order:
                raw_sl = getattr(stop_order, 'auxPrice', None)
                if raw_sl is None:
                    raw_sl = getattr(stop_order, 'stopPrice', None)
                if raw_sl is not None:
                    try:
                        stop_snap = float(raw_sl)
                    except (TypeError, ValueError):
                        stop_snap = None
            if tp_order:
                raw_tp = getattr(tp_order, 'lmtPrice', None)
                if raw_tp is not None:
                    try:
                        tp_snap = float(raw_tp)
                    except (TypeError, ValueError):
                        tp_snap = None

            for order in [stop_order, tp_order]:
                if order:
                    try:
                        ib.cancelOrder(order)
                    except Exception:
                        pass

            if bracket in positions:
                positions.remove(bracket)

            close_mkt = MarketOrder(action=close_action, totalQuantity=actual_qty, transmit=True)
            close_trade = ib.placeOrder(bracket_contract, close_mkt)
            ib.sleep(3)
            if not close_trade.fills:
                ib.sleep(2)

            es_after = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
            if (not es_after or es_after[0].position == 0) and completed_trades is not None:
                _record_flatten_close_from_market_order(
                    ib, bracket_contract, bracket, entry_trade, close_trade,
                    dir_, actual_qty, reason_label, stop_snap, tp_snap,
                    completed_trades, live_tracker, send_email_fn, data, strategy=strategy,
                )
            elif es_after and es_after[0].position != 0:
                logging.error(f"{reason_label} market close may not have filled; position still open for {bracket_contract.localSymbol}")

            logging.info(f"Tracked position closed ({reason_label}): {close_action} {actual_qty} {bracket_contract.localSymbol}")
            if live_tracker and completed_trades is None:
                add_to_live_tracker(live_tracker, 'trade', f"{reason_label} EXIT: {bracket_contract.localSymbol}")
        except Exception as e:
            logging.error(f"Error closing tracked position ({reason_label}): {e}")

    # --- NEW: Close any UNTRACKED ES positions (Safety Catch) ---
    try:
        all_es_pos = [p for p in ib.positions() if p.contract.symbol == 'ES' and p.position != 0]
        for pos in all_es_pos:
            # We already tried to close tracked ones. If any ES position remains, it's either
            # one we just placed an order for (wait for fill) or a truly untracked one.
            # To be safe, we check if there are active orders for this contract.
            active_for_this = [t for t in ib.trades() if t.contract.conId == pos.contract.conId and t.isActive()]
            if not active_for_this:
                logging.warning(f"UNTRACKED ES POSITION FOUND during {reason_label} exit: {pos.position} {pos.contract.localSymbol}. Closing...")
                close_action = 'SELL' if pos.position > 0 else 'BUY'
                close_order = MarketOrder(action=close_action, totalQuantity=abs(pos.position), transmit=True)
                ib.placeOrder(pos.contract, close_order)
                if live_tracker:
                    add_to_live_tracker(live_tracker, 'warning', f"Closed untracked {pos.contract.localSymbol} ({reason_label})")
    except Exception as e:
        logging.error(f"Error closing untracked positions during {reason_label}: {e}")

    # Send notification email
    try:
        account = account_fn() if account_fn else {}
        msg = (f"{reason_label} - All Positions Closed\n{'='*50}\n"
               f"NetLiq: ${account.get('NetLiquidation', 0):,.2f}\n"
               f"Realized PNL: ${account.get('RealizedPNL', 0):,.2f}\n"
               f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        send_email_fn(f"BB Strategy - {reason_label}", msg)
    except Exception as e:
        logging.error(f"Error sending {reason_label} email: {e}")


def check_exits(strategy, ib, contract, data, positions, completed_trades,
                live_tracker, send_email_fn, idx, latest_row, allow_strategy_exit=False):
    """Comprehensive exit logic: RTH, maintenance, trailing stop, opposite BB TP, trade close detection."""
    
    # --- RTH Force Exit ---
    if getattr(strategy, 'enable_rth_filter', False) and getattr(strategy, 'rth_exit_buffer_minutes', 0) > 0:
        force_exit_rth = latest_row.get('force_exit_rth', False) if isinstance(latest_row, dict) else getattr(latest_row, 'force_exit_rth', False)
        if force_exit_rth:
            es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
            has_open = any(abs(p.position) > 0 for p in es_positions)
            if has_open or len(positions) > 0:
                if not hasattr(check_exits, '_rth_warned'):
                    logging.warning(f"⚠️ RTH ENDING - Closing all positions ({getattr(strategy, 'rth_exit_buffer_minutes', 0)} min buffer)")
                    add_to_live_tracker(live_tracker, 'warning', 'RTH: Closing all positions')
                    check_exits._rth_warned = True
                acct_fn = lambda: get_account_summary(ib, data, contract)
                # Check for ANY ES position during RTH end
                rth_es_pos = [p for p in ib.positions() if p.contract.symbol == 'ES']
                if rth_es_pos:
                    logging.warning(f"⚠️ RTH ENDING - Closing {len(rth_es_pos)} ES position(s)")
                    _close_all_positions(
                        "RTH End", ib, contract, positions, data, live_tracker, send_email_fn,
                        strategy=strategy, account_fn=acct_fn, completed_trades=completed_trades,
                    )
            else:
                if hasattr(check_exits, '_rth_warned'):
                    delattr(check_exits, '_rth_warned')
            return

    # --- Maintenance Force Exit ---
    if getattr(strategy, 'enable_maintenance_filter', False):
        force_exit = latest_row.get('force_exit', False) if isinstance(latest_row, dict) else getattr(latest_row, 'force_exit', False)
        if force_exit:
            es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
            has_open = any(abs(p.position) > 0 for p in es_positions)
            if has_open or len(positions) > 0:
                if not hasattr(check_exits, '_maint_warned'):
                    current_time = datetime.now(pytz.timezone('America/New_York')).time()
                    logging.warning(f"⚠️ MAINTENANCE APPROACHING - Closing all positions ({current_time.strftime('%H:%M:%S')} ET)")
                    add_to_live_tracker(live_tracker, 'warning', 'MAINTENANCE: Closing all positions')
                    check_exits._maint_warned = True
                acct_fn = lambda: get_account_summary(ib, data, contract)
                # Filter for ANY ES position during maintenance
                maint_es_pos = [p for p in ib.positions() if p.contract.symbol == 'ES']
                if maint_es_pos:
                    _close_all_positions(
                        "Maintenance", ib, contract, positions, data, live_tracker, send_email_fn,
                        strategy=strategy, account_fn=acct_fn, completed_trades=completed_trades,
                    )
            else:
                if hasattr(check_exits, '_maint_warned'):
                    delattr(check_exits, '_maint_warned')
            return

    # --- Per-bracket exit checks ---
    for bracket in positions[:]:
        entry_order = bracket['entry']
        stop_order = bracket['stopLoss']
        tp_order = bracket['takeProfit']
        dir_ = bracket['direction']

        # Find entry trade
        entry_trade = next((t for t in ib.trades() if t.order.permId == entry_order.permId), None)
        if not entry_trade or entry_trade.isActive():
            continue
        fill = entry_trade.fills[0].execution if entry_trade.fills else None
        if not fill:
            continue

        # Find stop/TP trades
        stop_trade = next((t for t in ib.trades() if t.order.permId == stop_order.permId), None)
        tp_trade = next((t for t in ib.trades() if tp_order and t.order.permId == tp_order.permId), None)

        # Use the specific contract for this bracket (handles roll-over)
        bracket_contract = bracket.get('contract', contract)
        
        # --- Check if position closed (TP or Stop filled) ---
        # Look specifically for the contract associated with this bracket
        pos_for_bracket = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
        current_pos = sum(p.position for p in pos_for_bracket)
        
        # Determine if we've successfully seen this position in the portfolio yet
        if not bracket.get('position_verified'):
            if current_pos != 0:
                bracket['position_verified'] = True
            else:
                # Fast exit edge case: if TP/Stop hit perfectly before broker positions sync
                stop_filled = stop_trade and getattr(stop_trade, 'orderStatus', None) and stop_trade.orderStatus.status == 'Filled'
                tp_filled = tp_trade and getattr(tp_trade, 'orderStatus', None) and tp_trade.orderStatus.status == 'Filled'
                if not (stop_filled or tp_filled):
                    continue  # Wait for ib.positions() to sync
        
        position_still_open = (current_pos != 0)
        
        if not position_still_open:
            _record_trade_close(ib, bracket_contract, bracket, entry_trade, stop_order, tp_order,
                               stop_trade, tp_trade, dir_, latest_row, positions,
                               completed_trades, live_tracker, send_email_fn, data,
                               strategy=strategy)
            if bracket in positions:
                positions.remove(bracket)
            continue

        current_price = latest_row['close']
        stop_price = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0))

        # --- PreSubmitted stop force-close ---
        stop_should_trigger = (current_price <= stop_price) if dir_ == 1 else (current_price >= stop_price)
        if stop_should_trigger:
            stop_status = stop_trade.orderStatus.status if stop_trade and stop_trade.orderStatus else None
            why_held = getattr(stop_trade.orderStatus, 'whyHeld', '') if stop_trade and stop_trade.orderStatus else ''

            if stop_status == 'PreSubmitted' and 'trigger' in why_held.lower():
                logging.warning(f"CRITICAL: Stop {stop_price:.2f} breached, order PreSubmitted. Manual close.")
                _force_close_position(ib, bracket_contract, bracket, positions, completed_trades,
                                      live_tracker, send_email_fn, entry_trade, current_price,
                                      "Manual Close (PreSubmitted Stop)", data=data, strategy=strategy)
                continue

        # --- Strategy-Specific Signal Exit (The "Soft Exit") ---
        if allow_strategy_exit:
            try:
                # FIX: Pass the strategy-specific position_dict, not the full bracket
                strat_pos = bracket.get('position_dict', bracket)
                
                # --- SAFETY: Don't use bar ranges (High/Low) from BEFORE the trade started ---
                # A bar with index 10:35 completes at 10:36. If we enter at 10:36:05,
                # the 10:35 bar's range is historical.
                entry_time = bracket.get('entry_time')
                bar_time = latest_row.name if hasattr(latest_row, 'name') else None
                
                eval_row = latest_row
                if entry_time and bar_time:
                    bar_ts = _align_ts_naive_et(bar_time)
                    ent_ts = _align_ts_naive_et(entry_time)
                    # If this is the signal bar (precedes) or the first bar (overlaps):
                    # Clamp High/Low to Close to only check for breaches occurring NOW or forward.
                    # replace(second=0) to align with bar indices
                    if bar_ts is not None and ent_ts is not None:
                        ent_cmp = ent_ts.replace(second=0, microsecond=0) if hasattr(ent_ts, 'replace') else ent_ts
                        cmp_ok = bar_ts <= ent_cmp
                    else:
                        cmp_ok = False
                    if cmp_ok:
                        if isinstance(latest_row, pd.Series):
                            eval_row = latest_row.copy()
                            eval_row['high'] = eval_row['low'] = eval_row['close']
                        elif isinstance(latest_row, dict):
                            eval_row = latest_row.copy()
                            eval_row['high'] = eval_row['low'] = eval_row['close']

                exit_triggered, exit_reason, exit_price_hint = strategy.check_exit(strat_pos, eval_row, data)
                if exit_triggered:
                    logging.info(f"STRATEGY SIGNAL EXIT: {exit_reason} triggered @ {latest_row['close']:.2f}")
                    _force_close_position(ib, bracket_contract, bracket, positions, completed_trades,
                                          live_tracker, send_email_fn, entry_trade, latest_row['close'],
                                          f"Strategy Exit ({exit_reason})", data=data, strategy=strategy)
                    continue
            except Exception as e:
                logging.error(f"Error checking strategy signal exit: {e}")

        # --- Trailing stop update ---
        if position_still_open:
            position_dict = bracket.get('position_dict', {})
            if not position_dict:
                current_stop = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0))
                position_dict = {
                    'direction': dir_, 'bars_held': 0, 'stop': current_stop,
                    'max_high': latest_row['high'] if dir_ == 1 else None,
                    'min_low': latest_row['low'] if dir_ == -1 else None
                }
                bracket['position_dict'] = position_dict

            # FIX: Use strat_pos which was already extracted or get it again
            strat_pos = bracket.get('position_dict', position_dict)
            stop_updated = strategy.update_trailing_stop(strat_pos, latest_row, data)

            # Check if stop order is active
            stop_active = False
            if stop_trade:
                stop_active = stop_trade.isActive() or (stop_trade.orderStatus and 
                            stop_trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending'])

            if stop_updated and stop_active:
                new_stop = round(float(position_dict['stop']) * 4) / 4
                curr_stop = getattr(stop_order, 'stopPrice', getattr(stop_order, 'auxPrice', 0))
                should_update = (dir_ == 1 and new_stop > curr_stop) or (dir_ == -1 and new_stop < curr_stop)
                if should_update:
                    try:
                        stop_order.stopPrice = new_stop
                        stop_order.transmit = True
                        ib.placeOrder(bracket_contract, stop_order)
                        logging.info(f"Trailing stop modified: {curr_stop:.2f} -> {new_stop:.2f}")
                        add_to_live_tracker(live_tracker, 'order', f"Trailing stop -> ${new_stop:.2f}")
                    except Exception as e:
                        logging.error(f"Error modifying trailing stop: {e}")

            # --- Opposite BB TP update ---
            if allow_strategy_exit and position_still_open and getattr(strategy, 'opposite_bb_tp', False) and tp_order:
                _update_opposite_bb_tp(ib, bracket_contract, data, bracket, tp_order, dir_, live_tracker)


def _force_close_position(ib, contract, bracket, positions, completed_trades,
                          live_tracker, send_email_fn, entry_trade, current_price, reason, data=None, strategy=None):
    """Force close a position with market order (PreSubmitted stop handler)."""
    try:
        stop_order = bracket.get('stopLoss')
        tp_order = bracket.get('takeProfit')
        # Cancel existing orders
        for order in [bracket.get('stopLoss'), bracket.get('takeProfit')]:
            if order:
                try: ib.cancelOrder(order)
                except: pass

        # Use bracket's contract for closing
        bracket_contract = bracket.get('contract', contract)
        es_pos = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
        if not es_pos or es_pos[0].position == 0:
            if bracket in positions:
                positions.remove(bracket)
            return

        actual_pos = es_pos[0].position
        dir_ = 1 if actual_pos > 0 else -1
        close_action = 'SELL' if actual_pos > 0 else 'BUY'
        close_order = MarketOrder(action=close_action, totalQuantity=abs(actual_pos), transmit=True)
        
        # Remove bracket proactively before sleep yields to event loop to avoid re-entrancy duplications
        if bracket in positions:
            positions.remove(bracket)
            
        close_trade = ib.placeOrder(bracket_contract, close_order)
        ib.sleep(3)

        # Check result
        es_after = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
        if not es_after or es_after[0].position == 0:
            entry_price = bracket.get('entry_price', 0)
            exit_price = close_trade.fills[0].execution.price if close_trade.fills else current_price
            qty = abs(actual_pos)
            pnl = (exit_price - entry_price) * dir_ * 50 * qty if entry_price else 0

            # Check commission report for accurate PnL
            if close_trade.fills:
                for f in close_trade.fills:
                    if f.commissionReport and hasattr(f.commissionReport, 'realizedPNL'):
                        pnl = f.commissionReport.realizedPNL
                        break

            # Metadata for reporting
            exit_time = datetime.now()
            entry_time = bracket.get('entry_time')
            duration_str = format_duration((exit_time - entry_time).total_seconds()) if entry_time else "N/A"
            
            # Use unified reporting helper
            report_url = ""
            if strategy:
                try:
                    # Save to web/trades/
                    trades_dir = os.path.join(os.getcwd(), 'web', 'trades')
                    os.makedirs(trades_dir, exist_ok=True)
                    report_path = strategy.generate_trade_report(
                        {
                            'entry_time': entry_time, 'exit_time': exit_time,
                            'direction': dir_, 'entry_price': entry_price,
                            'exit_price': exit_price, 'pnl': pnl, 'qty': qty,
                            'reason': reason,
                            'stop_at_close': getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', None)) if stop_order else None,
                            'tp_at_close': getattr(tp_order, 'lmtPrice', None) if tp_order else None,
                            'stop_at_open': bracket.get('entry_stop_price'),
                            'tp_at_open': bracket.get('entry_tp_price'),
                            'params_snapshot': bracket.get('params_snapshot') or {},
                        },
                        data, trades_dir
                    )
                    if report_path:
                        report_url = f"trades/{os.path.basename(report_path)}"
                except Exception as e:
                    logging.error(f"Failed to generate HTML report: {e}")

            _send_trade_close_notification(
                ib, bracket, dir_, entry_price, exit_price, pnl, qty, reason, 
                duration_str, exit_time, data, send_email_fn, live_tracker,
                report_url=report_url
            )
            
            # Record in completed trades for dashboard
            completed_trades.append({
                'exit_time': exit_time, 'entry_time': entry_time,
                'direction': 'LONG' if dir_ == 1 else 'SHORT',
                'qty': qty, 'entry_price': entry_price, 'exit_price': exit_price,
                'pnl': pnl, 'reason': reason, 'duration': duration_str,
                'report_url': report_url,
                'params_snapshot': bracket.get('params_snapshot') or {},
                'stop_at_open': bracket.get('entry_stop_price'),
                'tp_at_open': bracket.get('entry_tp_price'),
                'stop_at_close': getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', None)) if stop_order else None,
                'tp_at_close': getattr(tp_order, 'lmtPrice', None) if tp_order else None,
                'entry_order_id': bracket.get('entryOrderId'),
            })
            if len(completed_trades) > 1000:
                del completed_trades[:-1000]
        else:
            logging.error(f"Force close failed: Position still exists for {bracket_contract.localSymbol}")

    except Exception as e:
        logging.error(f"CRITICAL: Failed to force close: {e}")
        import traceback
        logging.error(traceback.format_exc())


def _update_opposite_bb_tp(ib, contract, data, bracket, tp_order, dir_, live_tracker):
    """Update TP to track opposite Bollinger Band."""
    if 'upper' not in data.columns or 'lower' not in data.columns or len(data) == 0:
        return
    new_tp_raw = data['upper'].iloc[-1] if dir_ == 1 else data['lower'].iloc[-1]
    if pd.isna(new_tp_raw) or np.isnan(new_tp_raw):
        return

    new_tp = round(float(new_tp_raw) * 4) / 4
    current_tp = getattr(tp_order, 'lmtPrice', 0)

    if abs(new_tp - current_tp) < 0.25:
        return

    # Find TP trade
    tp_trade = next((t for t in ib.trades()
                     if hasattr(tp_order, 'permId') and t.order.permId == tp_order.permId), None)
    if tp_trade is None:
        tp_action = 'SELL' if dir_ == 1 else 'BUY'
        tp_trade = next((t for t in ib.trades()
                         if t.contract.conId == contract.conId and
                         isinstance(t.order, LimitOrder) and t.order.action == tp_action and
                         abs(getattr(t.order, 'lmtPrice', 0) - current_tp) < 0.01), None)

    tp_active = False
    if tp_trade:
        tp_active = tp_trade.isActive() or (tp_trade.orderStatus and
            tp_trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending'])

    if tp_active:
        try:
            tp_order.lmtPrice = new_tp
            tp_order.transmit = True
            ib.placeOrder(contract, tp_order)
            logging.info(f"Opposite BB TP modified: {current_tp:.2f} -> {new_tp:.2f}")
            add_to_live_tracker(live_tracker, 'order', f"Opposite BB TP -> ${new_tp:.2f}")
        except Exception as e:
            logging.error(f"Failed to modify TP order: {e}")


def _calculate_trade_metrics(entry_time, exit_time, dir_, entry_price, exit_price, pnl, qty, data, curr_stop, tp_price):
    """Calculate MFE, MAE, Risk, Reward, and R-Multiple for a trade."""
    mfe_pts = 0
    mae_pts = 0
    if entry_time and data is not None and not data.empty:
        try:
            # Standardize index to compare with naive times if needed
            idx = data.index
            localized_entry = entry_time
            localized_exit = exit_time
            if idx.tz is not None:
                if localized_entry.tzinfo is None: localized_entry = pd.Timestamp(localized_entry).tz_localize(idx.tz)
                if localized_exit.tzinfo is None: localized_exit = pd.Timestamp(localized_exit).tz_localize(idx.tz)
            else:
                if localized_entry.tzinfo is not None: localized_entry = localized_entry.replace(tzinfo=None)
                if localized_exit.tzinfo is not None: localized_exit = localized_exit.replace(tzinfo=None)

            # Slice data during trade duration
            trade_mask = (idx >= localized_entry) & (idx <= localized_exit)
            tdf = data.loc[trade_mask]
            if not tdf.empty:
                if dir_ == 1: # LONG
                    mfe_pts = tdf['high'].max() - entry_price
                    mae_pts = tdf['low'].min() - entry_price
                else: # SHORT
                    mfe_pts = entry_price - tdf['low'].min()
                    mae_pts = entry_price - tdf['high'].max()
        except Exception as e:
            logging.warning(f"Failed to calculate MAE/MFE: {e}")

    contract_multiplier = 50
    risk_dollars = abs(entry_price - curr_stop) * contract_multiplier * qty if curr_stop else 0
    reward_dollars = abs(entry_price - tp_price) * contract_multiplier * qty if tp_price else None
    rr_ratio = reward_dollars / risk_dollars if (reward_dollars and risk_dollars > 0) else None
    r_multiple = pnl / risk_dollars if risk_dollars > 0 else 0
    
    return {
        'mfe_pts': mfe_pts,
        'mae_pts': mae_pts,
        'mfe_dollars': mfe_pts * contract_multiplier * qty,
        'mae_dollars': mae_pts * contract_multiplier * qty,
        'risk_dollars': risk_dollars,
        'reward_dollars': reward_dollars,
        'rr_ratio': rr_ratio,
        'r_multiple': r_multiple
    }

def _build_trade_report_lines(metrics, account, status_label, dir_, qty, entry_price, exit_price, duration_str, exit_time, entry_time):
    """Build the list of message lines for the email report."""
    msg_lines = [
        f"TRADE {status_label.upper()}",
        f"{'='*60}",
        f"Signal:      {'LONG' if dir_==1 else 'SHORT'}",
        f"Volume:      {qty} contract(s)",
        f"Entry:       ${entry_price:.2f} ({entry_time.strftime('%H:%M:%S') if entry_time else 'N/A'})",
        f"Current/Exit: ${exit_price:.2f} ({exit_time.strftime('%H:%M:%S')})",
        f"Duration:    {duration_str}",
        f"Status:      {status_label}",
        f"",
        f"EXCURSION STATS",
        f"{'-'*30}",
        f"MFE (Max Fav): +${metrics['mfe_dollars']:,.2f} (+{metrics['mfe_pts']:.2f} pts)",
        f"MAE (Max Adv): ${metrics['mae_dollars']:,.2f} ({metrics['mae_pts']:.2f} pts)",
        f"",
        f"FINANCIAL PERFORMANCE",
        f"{'-'*30}",
        f"PnL:         ${metrics.get('pnl', 0):,.2f}",
        f"R-Multiple:  {metrics['r_multiple']:.2f}R",
        f"Initial Risk: ${metrics['risk_dollars']:,.2f}",
        f"Risk/Reward: {metrics['rr_ratio']:.2f}:1" if metrics['rr_ratio'] else "Risk/Reward: N/A",
        f"",
        f"ACCOUNT CONTEXT",
        f"{'-'*30}",
        f"Net Liquidity: ${account.get('NetLiquidation', 0):,.2f}",
        f"Session PnL:   ${account.get('RealizedPNL', 0):,.2f}",
        f"Equity Value:  ${account.get('EquityWithLoanValue', 0):,.2f}",
        f"Timestamp:     {exit_time.strftime('%Y-%m-%d %H:%M:%S')}"
    ]
    return msg_lines

def _send_trade_close_notification(ib, bracket, dir_, entry_price, exit_price, pnl, qty, reason, 
                                   duration_str, exit_time, data, send_email_fn, live_tracker,
                                   report_url=None):
    """Unified helper for detailed trade closure reporting with analytics and charting."""
    entry_time = bracket.get('entry_time')
    stop_order = bracket.get('stopLoss')
    tp_order = bracket.get('takeProfit')
    curr_stop = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0)) if stop_order else 0
    tp_price = getattr(tp_order, 'lmtPrice', None) if tp_order else None

    # Calculate metrics
    metrics = _calculate_trade_metrics(entry_time, exit_time, dir_, entry_price, exit_price, pnl, qty, data, curr_stop, tp_price)
    metrics['pnl'] = pnl

    # Build report
    account = get_account_summary(ib, data, bracket.get('contract'))
    msg_lines = _build_trade_report_lines(metrics, account, reason, dir_, qty, entry_price, exit_price, duration_str, exit_time, entry_time)
    
    dir_code = "L" if dir_ == 1 else "S"
    subj = f"C: {dir_code} {qty}@{exit_price:.2f} ({'+' if pnl>0 else ''}${pnl:.0f})"
    
    # Charting
    os.makedirs('temp', exist_ok=True)
    chart_path = os.path.join(os.getcwd(), 'temp', f'trade_chart_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png')
    chart_attached = False
    if data is not None and not data.empty:
        try:
            chart_attached = create_trade_chart(
                data, entry_time, exit_time, dir_code, chart_path,
                sl_price=curr_stop, tp_price=tp_price, entry_price=entry_price
            )
        except Exception as e:
            logging.error(f"Chart generation failed: {e}")
            
    # Dispatch Email
    try:
        report_msg = f"\n\nInteractive Report: http://127.0.0.1:8000/{report_url}" if report_url else ""
        full_body = "\n".join(msg_lines) + report_msg
        
        if chart_attached:
            send_email_fn(subj, full_body, attachment_path=chart_path)
            # We don't delete immediately here as multiple calls might happen, 
            # but usually it's fine. We'll let OS cleanup or handle in main.
        else:
            send_email_fn(subj, full_body)
    except Exception as e:
        logging.error(f"Failed to dispatch close email: {e}")

def send_composite_status_notification(ib, positions, data, account_info, send_email_fn):
    """Send a single status email with reports and charts for all active positions."""
    if not positions:
        return

    now = datetime.now()
    all_reports = []
    chart_paths = []

    os.makedirs('temp', exist_ok=True)

    for i, bracket in enumerate(positions):
        try:
            dir_ = bracket.get('direction', 0)
            entry_price = bracket.get('entry_price', 0)
            entry_time = bracket.get('entry_time')
            qty = 1 # Default
            
            # Try to get qty from order
            stop_order = bracket.get('stopLoss')
            if stop_order and hasattr(stop_order, 'totalQuantity'):
                qty = stop_order.totalQuantity
            
            current_price = data['close'].iloc[-1] if not data.empty else entry_price
            pnl = (current_price - entry_price) * dir_ * 50 * qty
            
            duration_str = format_duration((now - entry_time).total_seconds()) if entry_time else "N/A"
            
            tp_order = bracket.get('takeProfit')
            curr_stop = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0)) if stop_order else 0
            tp_price = getattr(tp_order, 'lmtPrice', None) if tp_order else None

            metrics = _calculate_trade_metrics(entry_time, now, dir_, entry_price, current_price, pnl, qty, data, curr_stop, tp_price)
            metrics['pnl'] = pnl
            
            report_lines = _build_trade_report_lines(metrics, account_info, "OPEN STATUS", dir_, qty, entry_price, current_price, duration_str, now, entry_time)
            all_reports.append("\n".join(report_lines))

            # Generate chart
            dir_code = "L" if dir_ == 1 else "S"
            chart_filename = f'status_chart_{i}_{now.strftime("%H%M%S")}.png'
            chart_path = os.path.join(os.getcwd(), 'temp', chart_filename)
            
            if create_trade_chart(data, entry_time, now, dir_code, chart_path, sl_price=curr_stop, tp_price=tp_price, entry_price=entry_price):
                chart_paths.append(chart_path)
                
        except Exception as e:
            logging.error(f"Failed to generate status for position {i}: {e}")

    if all_reports:
        # Subject summary
        total_pnl = sum((data['close'].iloc[-1] - b.get('entry_price', 0)) * b.get('direction', 0) * 50 for b in positions if not data.empty)
        pos_summary = "/".join(["L" if b.get('direction') == 1 else "S" for b in positions])
        subj = f"STAT: {pos_summary} PNL:${total_pnl:,.0f}"
        
        body = "\n\n" + ("\n" + "="*60 + "\n").join(all_reports)
        
        try:
            send_email_fn(subj, body, attachment_paths=chart_paths)
            logging.info("Composite status email sent.")
        except Exception as e:
            logging.error(f"Failed to send composite status email: {e}")
        
        # Cleanup charts
        for cp in chart_paths:
            try: os.remove(cp)
            except: pass



def _record_trade_close(ib, contract, bracket, entry_trade, stop_order, tp_order,
                        stop_trade, tp_trade, dir_, latest_row, positions,
                        completed_trades, live_tracker, send_email_fn, data, 
                        reason='Unknown', strategy=None):
    """Record a completed trade and clean up. Improved reason discovery."""
    # Determine exit reason from orders if not explicitly provided or marked as Manual
    exit_trade = None
    if reason in ['Unknown', 'Manual / External']:
        # 1. Check current session trades
        for trade in ib.trades():
            if trade.contract.conId == contract.conId and trade.filled():
                if tp_order and trade.order.permId == getattr(tp_order, 'permId', 0):
                    exit_trade = trade; reason = 'Take Profit'; break
                elif stop_order and trade.order.permId == getattr(stop_order, 'permId', 0):
                    exit_trade = trade; reason = 'Stop Loss'; break
        
        # 2. Deep Search: Check recent fills (crucial for ghost-bracket reconciliation)
        if reason in ['Unknown', 'Manual / External']:
            for fill in reversed(ib.fills()):
                if fill.contract.conId == contract.conId:
                    p_id = getattr(fill.execution, 'permId', 0)
                    if tp_order and p_id != 0 and p_id == getattr(tp_order, 'permId', -1):
                        reason = 'Take Profit'; break
                    elif stop_order and p_id != 0 and p_id == getattr(stop_order, 'permId', -1):
                        reason = 'Stop Loss'; break
        
        # 3. Check for specific IB errors or rejections (Ghost-Bracket Sync)
        if reason in ['Unknown', 'Manual / External']:
            # Search recent log entries for rejects or cancels related to this bracket's fills
            for trade in ib.trades():
                 if trade.contract.conId != contract.conId:
                     continue
                 status = getattr(trade.orderStatus, 'status', '') or ''
                 why = getattr(trade.orderStatus, 'whyHeld', '') or ''
                 reason_text = why if why else status
                 if status == 'Rejected' or 'discarded' in str(reason_text).lower():
                     reason = f"Rejected: {str(reason_text)[:30]}"
                     break

        # Final fallback: if position is closed but no fill found, it's external
        if reason in ['Unknown', 'Manual / External']:
            reason = 'Manual / External'

    entry_price = bracket.get('entry_price', 0)
    entry_time = bracket.get('entry_time')
    # Determine if we should work with aware or naive based on entry_time
    is_aware = entry_time and entry_time.tzinfo is not None

    if not entry_price and entry_trade and entry_trade.fills:
        entry_price = entry_trade.fills[0].execution.price

    qty = abs(stop_order.totalQuantity) if stop_order and hasattr(stop_order, 'totalQuantity') else 1

    exit_price = 0
    if exit_trade and exit_trade.fills:
        exit_price = exit_trade.fills[0].execution.price
        pnl = 0
        for f in exit_trade.fills:
            if f.commissionReport and hasattr(f.commissionReport, 'realizedPNL'):
                pnl = f.commissionReport.realizedPNL; break
        if pnl == 0 and entry_price > 0:
            pnl = (exit_price - entry_price) * dir_ * 50 * qty
    else:
        # Fallback 1: Scan recent fills for this contract to find the actual manual/untracked execution
        fallback_fill = None
        expected_side = 'SLD' if dir_ == 1 else 'BOT'
        
        # Ensure entry_time is comparable (aware vs naive)
        ref_time = entry_time

        for f in reversed(ib.fills()):
            if f.contract.conId == contract.conId and hasattr(f, 'execution') and f.execution.side == expected_side:
                f_time = f.execution.time
                if is_aware and f_time.tzinfo is None:
                    f_time = pytz.utc.localize(f_time)
                elif not is_aware and f_time.tzinfo is not None:
                    f_time = f_time.replace(tzinfo=None)
                
                # Only consider fills that happened AFTER this trade was initiated
                if ref_time and f_time < (ref_time - pd.Timedelta(seconds=5)):
                    continue

                if abs(f.execution.shares) >= qty:
                    fallback_fill = f; break
                
        if fallback_fill:
            exit_price = fallback_fill.execution.price
            pnl = (exit_price - entry_price) * dir_ * 50 * qty if entry_price > 0 else 0
        else:
            # Fallback 2: Guess using price
            exit_price = latest_row['close'] if latest_row is not None and (isinstance(latest_row, dict) and 'close' in latest_row or hasattr(latest_row, 'close')) else 0
            if exit_price == 0 and data is not None and not data.empty:
                exit_price = data['close'].iloc[-1]
            pnl = (exit_price - entry_price) * dir_ * 50 * qty if entry_price > 0 else 0

    # Duration and Notification
    exit_time = datetime.now()
    if is_aware:
        exit_time = exit_time.astimezone(pytz.utc)
    
    duration_str = format_duration((exit_time - entry_time).total_seconds()) if entry_time else "N/A"

    curr_stop = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0)) if stop_order else 0

    # Generate HTML report if possible
    report_url = ""
    if strategy:
        try:
            # Save to web/trades/
            trades_dir = os.path.join(os.getcwd(), 'web', 'trades')
            os.makedirs(trades_dir, exist_ok=True)
            report_path = strategy.generate_trade_report(
                {
                    'entry_time': entry_time, 'exit_time': exit_time,
                    'direction': dir_, 'entry_price': entry_price,
                    'exit_price': exit_price, 'pnl': pnl, 'qty': qty,
                        'reason': reason,
                        'stop_at_close': curr_stop or None,
                        'tp_at_close': getattr(tp_order, 'lmtPrice', None) if tp_order else None,
                        'stop_at_open': bracket.get('entry_stop_price'),
                        'tp_at_open': bracket.get('entry_tp_price'),
                        'params_snapshot': bracket.get('params_snapshot') or {},
                },
                data, trades_dir
            )
            if report_path:
                report_url = f"trades/{os.path.basename(report_path)}"
        except Exception as e:
            logging.error(f"Failed to generate HTML report: {e}")

    _send_trade_close_notification(
        ib, bracket, dir_, entry_price, exit_price, pnl, qty, reason, 
        duration_str, exit_time, data, send_email_fn, live_tracker,
        report_url=report_url
    )

    logging.info(f"TRADE CLOSE: {reason} @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
    add_to_live_tracker(live_tracker, 'trade',
        f"CLOSE ({reason}): @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
    
    # Risk calculation for completed record
    initial_risk = abs(entry_price - curr_stop) * 50 * qty if curr_stop else 0
    r_multiple = pnl / initial_risk if initial_risk > 0 else 0
    
    # Record completed trade
    completed_trades.append({
        'exit_time': exit_time, 'entry_time': entry_time,
        'direction': 'LONG' if dir_ == 1 else 'SHORT',
        'qty': qty, 'entry_price': entry_price, 'exit_price': exit_price,
        'pnl': pnl, 'r_multiple': r_multiple, 'reason': reason,
        'duration': duration_str,
        'report_url': report_url,
        'params_snapshot': bracket.get('params_snapshot') or {},
        'stop_at_open': bracket.get('entry_stop_price'),
        'tp_at_open': bracket.get('entry_tp_price'),
        'stop_at_close': curr_stop or None,
        'tp_at_close': getattr(tp_order, 'lmtPrice', None) if tp_order else None,
        'entry_order_id': bracket.get('entryOrderId'),
    })
    if len(completed_trades) > 1000:
        del completed_trades[:-1000]

    # Cancel ALL orphaned orders for this contract from ANY bracket (Safety Catch)
    # This prevents the 'stranded order' issue like the one at $7177.75
    try:
        active_for_contract = [t for t in ib.trades() if t.contract.conId == contract.conId and t.isActive()]
        for trade in active_for_contract:
            perm_id = trade.order.permId
            # If this trade isn't the entry that just closed (it shouldn't be anyway as entry is done)
            if entry_trade and perm_id == getattr(entry_trade.order, 'permId', 0):
                continue
                
            logging.info(f"Cleanup: Cancelling active order {trade.order.orderType} {trade.order.action} (PermID: {perm_id}) for {contract.localSymbol}")
            ib.cancelOrder(trade.order)
    except Exception as e:
        logging.error(f"Error during final orphan cleanup: {e}")

    if bracket in positions:
        positions.remove(bracket)
