"""
core/execution.py - Trade Entry & Exit Logic
Ported from ib_deployment_v4.py lines 2250-3185
"""
import logging
import traceback
import pandas as pd
import numpy as np
from datetime import datetime
from ib_insync import MarketOrder, StopOrder, LimitOrder
import pytz

from core.account import get_account_summary, format_duration, add_to_live_tracker


def check_entries(strategy, ib, contract, data, positions, params_dict, 
                  live_tracker, dashboard_state, send_email_fn, idx, latest_row):
    """Check entry signals and place bracket orders if triggered."""
    if len(positions) >= strategy.max_open_trades:
        return
    if len(data) < 2:
        return

    # Extra Safety: Check for active orders for this contract to prevent double entry
    active_orders = [t for t in ib.trades() if t.contract.conId == contract.conId and t.isActive()]
    if active_orders:
        logging.info(f"Entry blocked: {len(active_orders)} active orders already exist for {contract.localSymbol}")
        return

    # Defense-in-depth: Prevent duplicate entries from stacked event handlers.
    # If two bar handlers fire on the same bar (due to reconnection handler stacking),
    # block the second entry within 30 seconds of the first.
    now = datetime.now()
    if hasattr(check_entries, '_last_entry_time') and check_entries._last_entry_time is not None:
        elapsed = (now - check_entries._last_entry_time).total_seconds()
        if elapsed < 30:
            logging.warning(f"Entry blocked: duplicate entry attempt {elapsed:.1f}s after last entry (handler stacking guard)")
            return

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
            data_ind = strategy.calculate_indicators(data.copy())
            long_sig, short_sig = strategy.calculate_entry_signals(data_ind)
            if len(long_sig) >= 2 and len(short_sig) >= 2:
                enter_long = bool(long_sig.iloc[-2])
                enter_short = bool(short_sig.iloc[-2])
            else:
                return
        except Exception:
            return
    else:
        return

    if not (enter_long or enter_short):
        return

    direction = 1 if enter_long else -1
    action = 'BUY' if direction == 1 else 'SELL'
    qty = 1

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
        # Additional safety: ensure TP is not on the wrong side of entry
        if direction == 1 and tp > entry_price: valid_tp = True
        elif direction == -1 and tp < entry_price: valid_tp = True
        
        if not valid_tp:
            logging.warning(f"Invalid TP price {tp} relative to entry {entry_price}. TP disabled.")
            tp = None
    else:
        tp = None

    # Create bracket order with parent-child relationships and OCA group
    oca_group = f"bracket_{datetime.now().strftime('%M%S%f')}"
    entry_order = MarketOrder(action=action, totalQuantity=qty, transmit=False)
    check_entries._last_entry_time = datetime.now()  # Record entry time for dedup guard
    trade = ib.placeOrder(contract, entry_order)
    ib.sleep(1)

    entry_order_id = entry_order.orderId
    if entry_order_id == 0 and trade and trade.order:
        entry_order_id = trade.order.orderId
    if entry_order_id == 0:
        logging.error("Failed to get entry orderId, cannot create bracket")
        return

    # Stop loss (GTC for ES futures after-hours execution)
    stop_action = 'SELL' if direction == 1 else 'BUY'
    stop_order = StopOrder(
        action=stop_action, totalQuantity=qty, stopPrice=stop_price,
        parentId=entry_order_id, tif='GTC',
        ocaGroup=oca_group if tp is not None else None,
        ocaType=1 if tp is not None else None,
        transmit=False if tp is not None else True
    )

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
        ib.placeOrder(contract, stop_order)
        ib.placeOrder(contract, tp_order)
    else:
        ib.placeOrder(contract, stop_order)

    ib.sleep(0.5)

    entry_time = datetime.now()
    bracket = {
        'entry': entry_order, 'stopLoss': stop_order, 'takeProfit': tp_order,
        'direction': direction, 'position_dict': position_dict,
        'entry_time': entry_time, 'entry_price': entry_price
    }
    positions.append(bracket)

    # Entry email with risk/reward
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
    send_email_fn("BB Strategy - Trade OPEN", "\n".join(msg_lines))
    tp_str = f"${tp:.2f}" if tp else "None"
    logging.info(f"TRADE OPEN: {'LONG' if direction==1 else 'SHORT'} @ {entry_price:.2f}, "
                 f"SL: {stop_price:.2f}, TP: {tp_str}")
    
    # Double check order placement success
    ib.sleep(0.5)
    if stop_order and not ib.trades()[-1].isActive() and ib.trades()[-1].orderStatus.status == 'Rejected':
        logging.error(f"CRITICAL: Stop order REJECTED: {ib.trades()[-1].orderStatus.statusReason}")
        send_email_fn("CRITICAL ERROR: Stop Loss Rejected", 
                      f"Stop Loss for {'LONG' if direction==1 else 'SHORT'} @ {entry_price} was rejected.\n"
                      f"Reason: {ib.trades()[-1].orderStatus.statusReason}")
    add_to_live_tracker(live_tracker, 'trade',
        f"TRADE OPEN: {'LONG' if direction==1 else 'SHORT'} @ ${entry_price:.2f}, SL: ${stop_price:.2f}")


def _close_all_positions(reason_label, ib, contract, positions, data, 
                         live_tracker, send_email_fn, strategy=None, account_fn=None):
    """Helper: Close all tracked positions with market orders."""
    for bracket in positions[:]:
        try:
            entry_order = bracket['entry']
            entry_trade = None
            for trade in ib.trades():
                if trade.order.permId == entry_order.permId:
                    entry_trade = trade
                    break
            if not entry_trade or entry_trade.isActive():
                continue

            # Use bracket's contract if available, fallback to global
            bracket_contract = bracket.get('contract', contract)
            es_positions = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
            
            if not es_positions or es_positions[0].position == 0:
                positions.remove(bracket)
                continue

            actual_pos = es_positions[0].position
            actual_qty = abs(actual_pos)
            close_action = 'SELL' if actual_pos > 0 else 'BUY'

            # Cancel stop and TP
            for order in [bracket.get('stopLoss'), bracket.get('takeProfit')]:
                if order:
                    try: ib.cancelOrder(order)
                    except: pass

            close_order = MarketOrder(action=close_action, totalQuantity=actual_qty, transmit=True)
            close_trade = ib.placeOrder(bracket_contract, close_order)
            ib.sleep(2)

            if close_trade.orderStatus and close_trade.orderStatus.filled > 0:
                exit_price = close_trade.orderStatus.avgFillPrice
                direction = bracket.get('direction', 0)
                entry_price = bracket.get('entry_price', 0)
                pnl = (exit_price - entry_price) * direction * 50

                logging.info(f"Position closed ({reason_label}): Exit @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
                add_to_live_tracker(live_tracker, 'trade',
                    f"{reason_label} EXIT: @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")

            positions.remove(bracket)
        except Exception as e:
            logging.error(f"Error closing position ({reason_label}): {e}")
            logging.error(traceback.format_exc())

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
                    _close_all_positions("RTH End", ib, contract, positions, data, live_tracker, send_email_fn, account_fn=acct_fn)
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
                    _close_all_positions("Maintenance", ib, contract, positions, data, live_tracker, send_email_fn, account_fn=acct_fn)
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
        position_still_open = any(p.position != 0 for p in pos_for_bracket)
        
        if not position_still_open:
            _record_trade_close(ib, bracket_contract, bracket, entry_trade, stop_order, tp_order,
                               stop_trade, tp_trade, dir_, latest_row, positions,
                               completed_trades, live_tracker, send_email_fn, data)
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
                                      "Manual Close (PreSubmitted Stop)")
                continue

        # --- Strategy-Specific Signal Exit (The "Soft Exit") ---
        if allow_strategy_exit:
            try:
                exit_triggered, exit_reason, exit_price_hint = strategy.check_exit(bracket, latest_row, data)
                if exit_triggered:
                    logging.info(f"STRATEGY SIGNAL EXIT: {exit_reason} triggered @ {latest_row['close']:.2f}")
                    _force_close_position(ib, bracket_contract, bracket, positions, completed_trades,
                                          live_tracker, send_email_fn, entry_trade, latest_row['close'],
                                          f"Strategy Exit ({exit_reason})")
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

            stop_updated = strategy.update_trailing_stop(position_dict, latest_row, data)

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
                          live_tracker, send_email_fn, entry_trade, current_price, reason):
    """Force close a position with market order (PreSubmitted stop handler)."""
    try:
        # Cancel existing orders
        for order in [bracket.get('stopLoss'), bracket.get('takeProfit')]:
            if order:
                try: ib.cancelOrder(order)
                except: pass

        # Use bracket's contract for closing
        bracket_contract = bracket.get('contract', contract)
        es_pos = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
        if not es_pos or es_pos[0].position == 0:
            positions.remove(bracket)
            return

        actual_pos = es_pos[0].position
        close_action = 'SELL' if actual_pos > 0 else 'BUY'
        close_order = MarketOrder(action=close_action, totalQuantity=abs(actual_pos), transmit=True)
        close_trade = ib.placeOrder(bracket_contract, close_order)
        ib.sleep(3)

        # Check result
        es_after = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
        if not es_after or es_after[0].position == 0:
            entry_price = bracket.get('entry_price', 0)
            direction = 1 if actual_pos > 0 else -1
            exit_price = close_trade.fills[0].execution.price if close_trade.fills else current_price
            pnl = (exit_price - entry_price) * direction * 50 if entry_price else 0

            # Check commission report for accurate PnL
            if close_trade.fills:
                for f in close_trade.fills:
                    if f.commissionReport and hasattr(f.commissionReport, 'realizedPNL'):
                        pnl = f.commissionReport.realizedPNL
                        break

            msg = (f"TRADE CLOSE - {reason}\n{'='*50}\n"
                   f"Entry: ${entry_price:.2f}\nExit: ${exit_price:.2f}\nPNL: ${pnl:,.2f}")
            send_email_fn("BB Strategy - Trade CLOSE", msg)
            add_to_live_tracker(live_tracker, 'trade',
                f"CLOSE ({reason}): @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
            positions.remove(bracket)
    except Exception as e:
        logging.error(f"CRITICAL: Failed to force close: {e}")
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


def _record_trade_close(ib, contract, bracket, entry_trade, stop_order, tp_order,
                        stop_trade, tp_trade, dir_, latest_row, positions,
                        completed_trades, live_tracker, send_email_fn, data):
    """Record a completed trade and clean up."""
    # Determine exit reason
    exit_trade = None
    reason = 'Unknown'
    for trade in ib.trades():
        if tp_order and trade.order.permId == tp_order.permId and trade.filled():
            exit_trade = trade; reason = 'TP'; break
        elif trade.order.permId == stop_order.permId and trade.filled():
            exit_trade = trade; reason = 'Stop'; break

    entry_price = bracket.get('entry_price', 0)
    entry_time = bracket.get('entry_time')
    if not entry_price and entry_trade and entry_trade.fills:
        entry_price = entry_trade.fills[0].execution.price

    curr_stop = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0))
    tp_price = getattr(tp_order, 'lmtPrice', None) if tp_order else None
    qty = abs(stop_order.totalQuantity) if stop_order and hasattr(stop_order, 'totalQuantity') else 1

    if exit_trade and exit_trade.fills:
        exit_price = exit_trade.fills[0].execution.price
        pnl = 0
        for f in exit_trade.fills:
            if f.commissionReport and hasattr(f.commissionReport, 'realizedPNL'):
                pnl = f.commissionReport.realizedPNL; break
        if pnl == 0 and entry_price > 0:
            pnl = (exit_price - entry_price) * dir_ * 50
    else:
        exit_price = latest_row['close']
        pnl = (exit_price - entry_price) * dir_ * 50 if entry_price > 0 else 0

    # Duration
    exit_time = datetime.now()
    duration_str = format_duration((exit_time - entry_time).total_seconds()) if entry_time else "N/A"

    # Risk metrics
    contract_multiplier = 50
    risk_dollars = abs(entry_price - curr_stop) * contract_multiplier * qty
    reward_dollars = abs(entry_price - tp_price) * contract_multiplier * qty if tp_price else None
    rr_ratio = reward_dollars / risk_dollars if (tp_price and risk_dollars > 0) else None
    r_multiple = pnl / risk_dollars if risk_dollars > 0 else 0

    # Email
    account = get_account_summary(ib, data, contract)
    msg_lines = [
        f"TRADE CLOSE - {'LONG' if dir_==1 else 'SHORT'}",
        f"{'='*50}",
        f"Entry: ${entry_price:.2f}  |  Exit: ${exit_price:.2f}",
        f"Reason: {reason}  |  Duration: {duration_str}",
        f"SL: ${curr_stop:.2f} (Risk: ${risk_dollars:,.2f})",
        f"TP: ${tp_price:.2f} (Reward: ${reward_dollars:,.2f})" if tp_price else "TP: None",
        f"R:R: {rr_ratio:.2f}:1" if rr_ratio else "R:R: N/A",
        f"PNL: ${pnl:,.2f}  |  R-Multiple: {r_multiple:.2f}R",
        f"NetLiq: ${account.get('NetLiquidation', 0):,.2f}",
        f"Time: {exit_time.strftime('%Y-%m-%d %H:%M:%S')}"
    ]
    send_email_fn("BB Strategy - Trade CLOSE", "\n".join(msg_lines))
    logging.info(f"TRADE CLOSE: {reason} @ ${exit_price:.2f}, PNL: ${pnl:,.2f}, R: {r_multiple:.2f}")
    add_to_live_tracker(live_tracker, 'trade',
        f"CLOSE ({reason}): @ ${exit_price:.2f}, PNL: ${pnl:,.2f}, {r_multiple:.2f}R")

    # Record completed trade
    completed_trades.append({
        'exit_time': exit_time, 'entry_time': entry_time,
        'direction': 'LONG' if dir_ == 1 else 'SHORT',
        'qty': qty, 'entry_price': entry_price, 'exit_price': exit_price,
        'pnl': pnl, 'r_multiple': r_multiple, 'reason': reason,
        'duration': duration_str, 'initial_risk': risk_dollars,
        'initial_reward': reward_dollars
    })
    if len(completed_trades) > 50:
        del completed_trades[:-50]

    # Cancel orphaned orders from this bracket
    for order in [stop_order, tp_order]:
        if order:
            for trade in ib.trades():
                if trade.order.permId == order.permId and trade.contract.conId == contract.conId and trade.isActive():
                    try: ib.cancelOrder(order)
                    except: pass
                    break

    positions.remove(bracket)
