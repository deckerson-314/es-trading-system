"""
core/execution.py - Trade Entry & Exit Logic
Ported from ib_deployment_v4.py lines 2250-3185
"""
import logging
import traceback
import pandas as pd
import numpy as np
import os
from datetime import datetime
from core.charting import create_trade_chart
from ib_insync import MarketOrder, StopOrder, LimitOrder
import pytz

from core.account import get_account_summary, format_duration, add_to_live_tracker


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
        entry_order = MarketOrder(action=action, totalQuantity=qty, transmit=False)
        
        # Place entry order
        trade = ib.placeOrder(contract, entry_order)
        
        # --- ATOMIC TRACKING ---
        # Add to positions list IMMEDIATELY to prevent re-entrant checks from seeing empty list
        entry_time = datetime.now()
        bracket = {
            'entry': entry_order, 'stopLoss': None, 'takeProfit': None,
            'direction': direction, 'position_dict': position_dict,
            'entry_time': entry_time, 'entry_price': entry_price,
            'ocaGroup': oca_group # Store for protection logic
        }
        positions.append(bracket)

        # Wait brief moment for IB to assign OrderId/PermID
        ib.sleep(1)

        entry_order_id = entry_order.orderId
        if entry_order_id == 0 and trade and trade.order:
            entry_order_id = trade.order.orderId
        if entry_order_id == 0:
            logging.error("Failed to get entry orderId, cannot link bracket orders accurately")

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
    dir_str = 'L' if direction == 1 else 'S'
    subj = f"[BB] O: {dir_str} {qty}@{entry_price:.2f}"
    send_email_fn(subj, "\n".join(msg_lines))
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
            entry_trade = next((t for t in ib.trades() if t.order.permId == entry_order.permId), None)
            
            # If entry trade is not filled yet, cancel it
            if entry_trade and entry_trade.isActive():
                ib.cancelOrder(entry_trade.order)
                logging.info(f"Cancelled active entry order during {reason_label} exit")

            # Use bracket's contract if available, fallback to global
            bracket_contract = bracket.get('contract', contract)
            es_positions = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
            
            if not es_positions or es_positions[0].position == 0:
                if bracket in positions: positions.remove(bracket)
                continue

            actual_pos = es_positions[0].position
            actual_qty = abs(actual_pos)
            close_action = 'SELL' if actual_pos > 0 else 'BUY'

            # Cancel stop and TP
            for order in [bracket.get('stopLoss'), bracket.get('takeProfit')]:
                if order:
                    try: ib.cancelOrder(order)
                    except: pass

            if bracket in positions: positions.remove(bracket)

            close_order = MarketOrder(action=close_action, totalQuantity=actual_qty, transmit=True)
            close_trade = ib.placeOrder(bracket_contract, close_order)
            ib.sleep(1)

            logging.info(f"Tracked position closed ({reason_label}): {close_action} {actual_qty} {bracket_contract.localSymbol}")
            if live_tracker:
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
                               completed_trades, live_tracker, send_email_fn, data)
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
                                      "Manual Close (PreSubmitted Stop)", data=data)
                continue

        # --- Strategy-Specific Signal Exit (The "Soft Exit") ---
        if allow_strategy_exit:
            try:
                exit_triggered, exit_reason, exit_price_hint = strategy.check_exit(bracket, latest_row, data)
                if exit_triggered:
                    logging.info(f"STRATEGY SIGNAL EXIT: {exit_reason} triggered @ {latest_row['close']:.2f}")
                    _force_close_position(ib, bracket_contract, bracket, positions, completed_trades,
                                          live_tracker, send_email_fn, entry_trade, latest_row['close'],
                                          f"Strategy Exit ({exit_reason})", data=data)
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
                          live_tracker, send_email_fn, entry_trade, current_price, reason, data=None):
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
            _send_trade_close_notification(
                ib, bracket, dir_, entry_price, exit_price, pnl, qty, reason, 
                duration_str, exit_time, data, send_email_fn, live_tracker
            )
            
            # Record in completed trades for dashboard
            completed_trades.append({
                'exit_time': exit_time, 'entry_time': entry_time,
                'direction': 'LONG' if dir_ == 1 else 'SHORT',
                'qty': qty, 'entry_price': entry_price, 'exit_price': exit_price,
                'pnl': pnl, 'reason': reason, 'duration': duration_str
            })
            if len(completed_trades) > 50:
                del completed_trades[:-50]
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


def _send_trade_close_notification(ib, bracket, dir_, entry_price, exit_price, pnl, qty, reason, 
                                   duration_str, exit_time, data, send_email_fn, live_tracker):
    """Unified helper for detailed trade closure reporting with analytics and charting."""
    entry_time = bracket.get('entry_time')
    stop_order = bracket.get('stopLoss')
    tp_order = bracket.get('takeProfit')
    curr_stop = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0)) if stop_order else 0
    tp_price = getattr(tp_order, 'lmtPrice', None) if tp_order else None

    # MFE / MAE Calculation
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

    # Risk metrics
    contract_multiplier = 50
    risk_dollars = abs(entry_price - curr_stop) * contract_multiplier * qty if curr_stop else 0
    reward_dollars = abs(entry_price - tp_price) * contract_multiplier * qty if tp_price else None
    rr_ratio = reward_dollars / risk_dollars if (reward_dollars and risk_dollars > 0) else None
    r_multiple = pnl / risk_dollars if risk_dollars > 0 else 0
    
    mfe_dollars = mfe_pts * contract_multiplier * qty
    mae_dollars = mae_pts * contract_multiplier * qty

    # Email Body Content
    account = get_account_summary(ib, data, bracket.get('contract'))
    msg_lines = [
        f"TRADE CLOSE - {reason.upper()}",
        f"{'='*60}",
        f"Signal:      {'LONG' if dir_==1 else 'SHORT'}",
        f"Volume:      {qty} contract(s)",
        f"Entry:       ${entry_price:.2f} ({entry_time.strftime('%H:%M:%S') if entry_time else 'N/A'})",
        f"Exit:        ${exit_price:.2f} ({exit_time.strftime('%H:%M:%S')})",
        f"Duration:    {duration_str}",
        f"Reason:      {reason}",
        f"",
        f"EXCURSION STATS",
        f"{'-'*30}",
        f"MFE (Max Fav): +${mfe_dollars:,.2f} (+{mfe_pts:.2f} pts)",
        f"MAE (Max Adv): ${mae_dollars:,.2f} ({mae_pts:.2f} pts)",
        f"",
        f"FINANCIAL PERFORMANCE",
        f"{'-'*30}",
        f"Net PnL:     ${pnl:,.2f}",
        f"R-Multiple:  {r_multiple:.2f}R",
        f"Initial Risk: ${risk_dollars:,.2f}",
        f"Risk/Reward: {rr_ratio:.2f}:1" if rr_ratio else "Risk/Reward: N/A",
        f"",
        f"ACCOUNT CONTEXT",
        f"{'-'*30}",
        f"Net Liquidity: ${account.get('NetLiquidation', 0):,.2f}",
        f"Session PnL:   ${account.get('RealizedPNL', 0):,.2f}",
        f"Equity Value:  ${account.get('EquityWithLoanValue', 0):,.2f}",
        f"Timestamp:     {exit_time.strftime('%Y-%m-%d %H:%M:%S')}"
    ]
    
    dir_code = "L" if dir_ == 1 else "S"
    # Subject [TR-P] etc is handled by main.py wrapper
    subj = f"C: {dir_code} {qty}@{exit_price:.2f} ({'+' if pnl>0 else ''}${pnl:.0f})"
    
    # Charting
    chart_path = os.path.join(os.getcwd(), 'temp', f'trade_chart_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png')
    chart_attached = False
    if data is not None and not data.empty:
        try:
            chart_attached = create_trade_chart(
                data, entry_time, exit_time, dir_code, chart_path,
                sl_price=curr_stop, tp_price=tp_price, entry_price=entry_price
            )
            if not chart_attached:
                logging.warning("create_trade_chart returned False")
        except Exception as e:
            logging.error(f"Chart generation failed: {e}")
            
    # Dispatch Email
    try:
        if chart_attached:
            send_email_fn(subj, "\n".join(msg_lines), attachment_path=chart_path)
        else:
            send_email_fn(subj, "\n".join(msg_lines))
    except Exception as e:
        logging.error(f"Failed to dispatch close email: {e}")


def _record_trade_close(ib, contract, bracket, entry_trade, stop_order, tp_order,
                        stop_trade, tp_trade, dir_, latest_row, positions,
                        completed_trades, live_tracker, send_email_fn, data, 
                        reason='Unknown'):
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
        
        # Final fallback: if position is closed but no fill found, it's external
        if reason in ['Unknown', 'Manual / External']:
            reason = 'Manual / External'

    entry_price = bracket.get('entry_price', 0)
    entry_time = bracket.get('entry_time')
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
        for f in reversed(ib.fills()):
            if f.contract.conId == contract.conId and hasattr(f, 'execution') and f.execution.side == expected_side:
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
    duration_str = format_duration((exit_time - entry_time).total_seconds()) if entry_time else "N/A"

    _send_trade_close_notification(
        ib, bracket, dir_, entry_price, exit_price, pnl, qty, reason, 
        duration_str, exit_time, data, send_email_fn, live_tracker
    )

    logging.info(f"TRADE CLOSE: {reason} @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
    add_to_live_tracker(live_tracker, 'trade',
        f"CLOSE ({reason}): @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
    
    # Risk calculation for completed record
    curr_stop = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0)) if stop_order else 0
    initial_risk = abs(entry_price - curr_stop) * 50 * qty if curr_stop else 0
    r_multiple = pnl / initial_risk if initial_risk > 0 else 0
    
    # Record completed trade
    completed_trades.append({
        'exit_time': exit_time, 'entry_time': entry_time,
        'direction': 'LONG' if dir_ == 1 else 'SHORT',
        'qty': qty, 'entry_price': entry_price, 'exit_price': exit_price,
        'pnl': pnl, 'r_multiple': r_multiple, 'reason': reason,
        'duration': duration_str
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

    if bracket in positions:
        positions.remove(bracket)
