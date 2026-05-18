"""
core/protection.py - Position Protection & Orphan Management
Ported from ib_deployment_v4.py lines 1575-3752
"""
import logging
import asyncio
import pandas as pd
from datetime import datetime
from ib_insync import MarketOrder, StopOrder, LimitOrder

from core.account import get_account_summary, add_to_live_tracker
import pytz


def _ib_refresh_open_orders(ib):
    """Ensure ib.trades() includes working orders after reconnect/restart."""
    try:
        ib.reqOpenOrders()
        ib.sleep(0.15)
    except Exception:
        pass


# IB "Inactive" (e.g. rejected bracket TP after OCA replace) is NOT in OrderStatus.DoneStates,
# but isActive() is often False — code that only scans isActive() leaves these on the blotter forever.
_IB_TERMINAL_BLOTTER = frozenset({"Filled", "Cancelled", "ApiCancelled"})


def trade_order_needs_flat_book_cancel(trade) -> bool:
    """True if we should send cancelOrder when intentionally flattening the book for a contract/account."""
    st = (getattr(trade.orderStatus, "status", None) or "").strip()
    if st in _IB_TERMINAL_BLOTTER:
        return False
    return True


def cancel_residual_orders_when_flat_on_contract(ib, contract, live_tracker=None) -> int:
    """
    When position size is 0 for ``contract``, cancel every non-terminal order on that conId.

    Catches **Inactive** take-profit / OCA legs that ``trade.isActive()`` skips.
    Returns number of cancelOrder calls issued (may include already-dead orders; errors swallowed).
    """
    if contract is None or not ib.isConnected():
        return 0
    try:
        _ib_refresh_open_orders(ib)
        pos = 0.0
        for p in ib.positions():
            if p.contract.conId == contract.conId:
                pos = float(p.position)
                break
        if abs(pos) > 1e-9:
            return 0
        n = 0
        for trade in list(ib.trades()):
            if trade.contract.conId != contract.conId:
                continue
            if not trade_order_needs_flat_book_cancel(trade):
                continue
            try:
                ib.cancelOrder(trade.order)
                n += 1
                logging.info(
                    "Flat-book cleanup (%s): cancelled %s %s permId=%s status=%s",
                    contract.localSymbol,
                    getattr(trade.order, "orderType", "?"),
                    getattr(trade.order, "action", "?"),
                    getattr(trade.order, "permId", 0),
                    getattr(trade.orderStatus, "status", ""),
                )
            except Exception as e:
                logging.debug(
                    "Flat-book cleanup skip permId=%s: %s",
                    getattr(trade.order, "permId", 0),
                    e,
                )
        if n and live_tracker:
            add_to_live_tracker(
                live_tracker,
                "info",
                f"Flat cleanup: removed {n} residual order(s) on {contract.localSymbol}",
            )
        return n
    except Exception as e:
        logging.error("cancel_residual_orders_when_flat_on_contract: %s", e)
        return 0


def cancel_residual_es_orders_when_no_es_position(ib, live_tracker=None) -> int:
    """When no ES contract has non-zero size, cancel every non-terminal ES order (any expiry)."""
    if not ib.isConnected():
        return 0
    try:
        _ib_refresh_open_orders(ib)
        if any(abs(float(p.position)) > 1e-9 for p in ib.positions() if p.contract.symbol == "ES"):
            return 0
        n = 0
        for trade in list(ib.trades()):
            if getattr(trade.contract, "symbol", None) != "ES":
                continue
            if not trade_order_needs_flat_book_cancel(trade):
                continue
            try:
                ib.cancelOrder(trade.order)
                n += 1
            except Exception:
                pass
        if n:
            logging.warning("No ES position: cancelled %s residual ES order(s)", n)
            if live_tracker:
                add_to_live_tracker(
                    live_tracker,
                    "warning",
                    f"No ES exposure: removed {n} residual ES order(s)",
                )
        return n
    except Exception as e:
        logging.error("cancel_residual_es_orders_when_no_es_position: %s", e)
        return 0


def _trade_non_terminal(trade) -> bool:
    try:
        if hasattr(trade, "isDone") and trade.isDone():
            return False
    except Exception:
        pass
    st = getattr(trade.orderStatus, "status", "") or ""
    return st not in ("Filled", "Cancelled", "Inactive", "ApiCancelled")


def _order_looks_like_protective_stop(order) -> bool:
    """IB often delivers STP as generic Order(orderType='STP'), not StopOrder."""
    if isinstance(order, StopOrder):
        return True
    ot = str(getattr(order, "orderType", "") or "").upper()
    if "STP" in ot or ot in ("TRAIL", "TRAIL LIMIT", "TRAIL MIT"):
        return True
    try:
        ap = float(getattr(order, "auxPrice", 0) or 0)
        lp = float(getattr(order, "lmtPrice", 0) or 0)
        sp = float(getattr(order, "stopPrice", 0) or 0)
    except (TypeError, ValueError):
        return False
    if sp > 0 and abs(lp) < 1e-9:
        return True
    return ap > 0 and abs(lp) < 1e-9


def es_position_has_protective_exit_orders(ib, pos, refresh: bool = True) -> bool:
    """True if a working stop matches this ES exposure (used after restart when brackets are not in memory)."""
    if refresh:
        _ib_refresh_open_orders(ib)
    qty = abs(pos.position)
    direction = 1 if pos.position > 0 else -1
    need_action = "SELL" if direction == 1 else "BUY"
    cid = pos.contract.conId
    for trade in ib.trades():
        if trade.contract.conId != cid or not _trade_non_terminal(trade):
            continue
        order = trade.order
        if not _order_looks_like_protective_stop(order):
            continue
        if getattr(order, "action", "") != need_action:
            continue
        try:
            tq = abs(float(getattr(order, "totalQuantity", 0) or 0))
        except (TypeError, ValueError):
            continue
        if tq != qty:
            continue
        return True
    return False


def _open_position_on_contract(ib, con_id):
    for p in ib.positions():
        if p.contract.conId == con_id and p.position != 0:
            return p
    return None


def _order_likely_bracket_exit_leg(order, open_pos):
    """STP/LMT with parentId while exposure exists — do not cancel as API orphan."""
    if open_pos is None:
        return False
    pid = int(getattr(order, "parentId", 0) or 0)
    if pid == 0:
        return False
    ot = str(getattr(order, "orderType", "") or "").upper()
    if "STP" in ot or "TRAIL" in ot:
        return True
    if ot in ("LMT", "LIMIT") or float(getattr(order, "lmtPrice", 0) or 0) > 0:
        return True
    return False


def cancel_all_pending(ib, contract, live_tracker=None):
    """Cancel pending orders surgically, preserving protective orders for specific contract."""
    try:
        # 1. Fetch fresh positions to avoid stale 'has_open' logic
        # We look for ALL ES positions to be safe during roll weeks
        es_positions = [p for p in ib.positions() if p.contract.symbol == 'ES']
        has_open = any(abs(p.position) > 0 for p in es_positions)

        # No ES exposure anywhere: remove ALL non-terminal ES orders (includes **Inactive** legs).
        if not has_open:
            cancel_residual_es_orders_when_no_es_position(ib, live_tracker)
            return

        # 2. Identify working orders when we still have ES risk on the book
        active_trades = [t for t in ib.trades() if t.isActive() or (t.orderStatus and 
                         t.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending'])]

        if not active_trades:
            return

        # 3. Surgical cancellation — only non-protective orders on the traded contract
        for trade in active_trades:
            # We ONLY touch orders for the contract being targeted if it HAS a position
            if contract and trade.contract.conId == contract.conId:
                order = trade.order
                is_protective = (isinstance(order, StopOrder) or isinstance(order, LimitOrder) or
                                getattr(order, 'auxPrice', 0) > 0 or getattr(order, 'lmtPrice', 0) > 0)
                
                # If it's a market order or something without prices, it's likely a target for cleanup
                if not is_protective:
                    logging.info(f"Surgical Cleanup: Cancelling non-protective order {trade.order.orderType} for {contract.localSymbol}")
                    ib.cancelOrder(trade.order)

    except Exception as e:
        logging.error(f"Error in surgical cancel_all_pending: {e}")


def cleanup_orphaned_orders(ib, contract, positions):
    """Cancel active ES orders that don't belong to any tracked position."""
    if contract is None:
        return

    _ib_refresh_open_orders(ib)

    tracked_perm_ids = set()
    tracked_order_ids = set()
    for bracket in positions:
        for key in ['entry', 'stopLoss', 'takeProfit']:
            order = bracket.get(key)
            if order:
                if hasattr(order, 'permId') and order.permId != 0:
                    tracked_perm_ids.add(order.permId)
                if hasattr(order, 'orderId') and order.orderId != 0:
                    tracked_order_ids.add(order.orderId)

    orphaned = []
    for trade in ib.trades():
        if trade.contract.conId == contract.conId and trade.isActive():
            perm_id = trade.order.permId
            order_id = trade.order.orderId
            parent_id = getattr(trade.order, 'parentId', 0)

            # Order is NOT orphaned if its PermID or OrderID is explicitly tracked
            if perm_id in tracked_perm_ids or order_id in tracked_order_ids:
                continue

            # Order is NOT orphaned if its parent OrderID is explicitly tracked
            if parent_id != 0 and parent_id in tracked_order_ids:
                continue
            
            # --- NEW: GRACE PERIOD FOR NEW ORDERS ---
            # If an order was JUST placed, its ID might not be in the positions list 
            # due to race conditions or IB delay. Skip if < 10s old.
            if trade.log:
                # First log entry is usually the creation time
                creation_time = trade.log[0].time
                if (datetime.now(pytz.utc) - creation_time).total_seconds() < 10:
                    logging.debug(f"Skipping orphan check for new order {order_id} ({(datetime.now(pytz.utc) - creation_time).total_seconds():.1f}s old)")
                    continue

            open_pos = _open_position_on_contract(ib, trade.contract.conId)
            if open_pos is not None and _order_likely_bracket_exit_leg(trade.order, open_pos):
                logging.info(
                    f"Skipping orphan cancel: {trade.order.orderType} perm={perm_id} "
                    f"parentId={parent_id} (open {trade.contract.localSymbol} — likely pre-restart bracket leg)"
                )
                continue

            # If no tracking match found, it's an orphan
            orphaned.append(trade)

    for trade in orphaned:
        try:
            ib.cancelOrder(trade.order)
            logging.info(f"Cancelled orphaned order: {trade.order.orderType} "
                        f"{trade.order.action} {trade.order.totalQuantity} "
                        f"(PermID: {trade.order.permId})")
        except Exception as e:
            logging.warning(f"Error cancelling orphaned order: {e}")

    cancel_residual_orders_when_flat_on_contract(ib, contract, None)


def close_orphaned_positions(ib, contract, positions, live_tracker=None, completed_trades=None, data=None):
    """Close positions that don't match any tracked bracket."""
    if contract is None:
        return

    _ib_refresh_open_orders(ib)

    # Filter for symbol ES to handle roll periods
    es_positions = [p for p in ib.positions() if p.contract.symbol == 'ES']
    for pos in es_positions:
        if pos.position == 0:
            continue

        # Check if this position is tracked (with correct direction and quantity)
        is_tracked = False
        for bracket in positions:
            bracket_dir = bracket.get('direction')
            # Check quantity via stopLoss or entry order
            bracket_qty = 0
            for k in ['stopLoss', 'entry', 'takeProfit']:
                if bracket.get(k) and hasattr(bracket[k], 'totalQuantity'):
                    bracket_qty = abs(bracket[k].totalQuantity)
                    break
            
            if bracket_dir == (1 if pos.position > 0 else -1) and bracket_qty == abs(pos.position):
                is_tracked = True
                break

        if not is_tracked:
            if es_position_has_protective_exit_orders(ib, pos, refresh=False):
                logging.info(
                    f"Skipping orphan close: {pos.position} {pos.contract.localSymbol} has working protective "
                    f"orders on IB but no in-memory bracket (restart). Leaving position intact."
                )
                continue
            logging.warning(f"ORPHANED POSITION: {pos.position} contracts, not tracked. Closing...")
            close_action = 'SELL' if pos.position > 0 else 'BUY'
            close_order = MarketOrder(action=close_action, totalQuantity=abs(pos.position), transmit=True)
            try:
                # CRITICAL: Use the position's OWN contract (March/June/etc); IB rejects market orders
                # without exchange (Error 321).
                cc = pos.contract
                if not getattr(cc, 'exchange', None):
                    cc.exchange = 'CME'
                close_trade = ib.placeOrder(cc, close_order)
                ib.sleep(2)  # Wait slightly longer for fill
                logging.info(f"Orphaned {pos.contract.localSymbol} position closed")
                if live_tracker:
                    add_to_live_tracker(live_tracker, 'warning',
                        f"Closed orphaned position: {pos.position} contracts")
                        
                # --- NEW: Record orphaned closure to dashboard ---
                if completed_trades is not None:
                    exit_price = close_trade.fills[0].execution.price if close_trade and close_trade.fills else (data['close'].iloc[-1] if data is not None and not data.empty else 0)
                    pnl = 0
                    if close_trade and close_trade.fills:
                        for f in close_trade.fills:
                            if f.commissionReport and hasattr(f.commissionReport, 'realizedPNL'):
                                pnl = f.commissionReport.realizedPNL; break

                    entry_price = getattr(pos, 'avgCost', 0) / 50.0  # ES multiplier
                    completed_trades.append({
                        'exit_time': datetime.now(), 'entry_time': None,
                        'direction': 'LONG' if pos.position > 0 else 'SHORT',
                        'qty': abs(pos.position), 'entry_price': entry_price, 'exit_price': exit_price,
                        'pnl': pnl, 'r_multiple': 0, 'reason': 'Orphan Auto-Close',
                        'duration': 'Auto-Closed',
                        'stop_at_close': None, 'tp_at_close': None,
                    })
                    if len(completed_trades) > 1000:
                        del completed_trades[:-1000]

            except Exception as e:
                logging.error(f"Failed to close orphaned position: {e}")


def protect_existing_positions(ib, contract, positions, strategy, data, live_tracker=None):
    """Add stop loss to any unprotected positions."""
    if contract is None or data is None or data.empty:
        return

    # Look for ALL ES positions to ensure legacy ones stay protected during roll
    try:
        es_pos_list = [p for p in ib.positions() if p.contract.symbol == 'ES']
    except Exception as e:
        logging.error(f"Error fetching positions in protect_existing: {e}")
        return

    _ib_refresh_open_orders(ib)

    for pos in es_pos_list:
        if pos.position == 0:
            continue
            
        qty = abs(pos.position)
        direction = 1 if pos.position > 0 else -1

        if es_position_has_protective_exit_orders(ib, pos, refresh=False):
            continue

        logging.warning(f"UNPROTECTED POSITION: {qty} {pos.contract.localSymbol} contracts. Adding stop loss...")
            
        # baseline for SL: Use position's avgCost if it's a legacy contract, 
        # otherwise use current market price.
        avg_cost = getattr(pos, 'avgCost', 0) / 50.0  # Convert to index points
        if avg_cost <= 0:
            avg_cost = data['close'].iloc[-1]
        
        # Strategy expects current_price to calculate distances
        pos_dict = strategy.setup_position(avg_cost, direction, data.iloc[-1], data)

        if pd.isna(pos_dict['stop']) or pos_dict['stop'] <= 0:
            logging.error(f"Cannot recreate stop: Invalid stop price calculated.")
            continue

        # Clamp stop loss to ensure validity against current market price
        calc_stop = float(pos_dict['stop'])
        curr_px = float(data['close'].iloc[-1])
        if direction == 1:
            valid_stop = min(calc_stop, curr_px - 0.25)
        else:
            valid_stop = max(calc_stop, curr_px + 0.25)

        oca_group = f"bracket_{pos.contract.conId}_{direction}"
        stop_order = StopOrder(
            action='SELL' if direction == 1 else 'BUY',
            totalQuantity=qty,
            stopPrice=round(valid_stop * 4) / 4,
            ocaGroup=oca_group, ocaType=1,
            tif='GTC', transmit=True
        )
        
        # Place on the SPECIFIC contract of the position (March or June)
        try:
            # Ensure exchange is set for validation
            pos.contract.exchange = 'CME'
            ib.placeOrder(pos.contract, stop_order)
            sl_px = getattr(stop_order, "stopPrice", None) or getattr(stop_order, "auxPrice", None)
            logging.info(f"Re-protected {pos.contract.localSymbol} at SL: {sl_px}")
            
            # Update internal tracking
            positions.append({
                'entry': MarketOrder(action='BUY' if direction == 1 else 'SELL', totalQuantity=qty),
                'stopLoss': stop_order, 'takeProfit': None,
                'direction': direction, 'position_dict': pos_dict,
                'entry_time': datetime.now(), 'entry_price': avg_cost,
                'contract': pos.contract # Store the specific contract
            })
            if live_tracker:
                add_to_live_tracker(live_tracker, 'warning',
                    f"Added protective stop for {pos.contract.localSymbol} at ${float(sl_px):,.2f}")
        except Exception as e:
            logging.error(f"Failed to place protective order for legacy contract: {e}")


def enforce_stop_invariant(ib, positions, strategy, data, live_tracker=None):
    """
    Hard safety invariant:
    Every open ES position must have at least one active stop order on the same contract/side/qty.
    """
    if not ib.isConnected() or data is None or data.empty:
        return
    try:
        es_open = [p for p in ib.positions() if p.contract.symbol == 'ES' and p.position != 0]
    except Exception as e:
        logging.error(f"Failed to fetch positions for stop invariant: {e}")
        return

    if not es_open:
        return

    _ib_refresh_open_orders(ib)

    for pos in es_open:
        qty = abs(pos.position)
        direction = 1 if pos.position > 0 else -1
        if es_position_has_protective_exit_orders(ib, pos, refresh=False):
            continue

        logging.error(
            f"STOP INVARIANT BREACH: {qty} {pos.contract.localSymbol} has no active stop. Re-protecting now."
        )
        protect_existing_positions(ib, pos.contract, positions, strategy, data, live_tracker=live_tracker)


def check_and_recreate_tp_orders(ib, contract, positions, strategy, data, live_tracker=None):
    """Recreate missing TP orders for tracked positions that should have one."""
    if contract is None or data is None or data.empty:
        return

    for bracket in positions[:]:
        direction = bracket.get('direction', 0)
        tp_order = bracket.get('takeProfit')

        # Skip if no TP expected
        if not getattr(strategy, 'opposite_bb_tp', False) and not bracket.get('position_dict', {}).get('tp'):
            continue

        # 1. Check if TP handle in bracket is active
        tp_active = False
        if tp_order:
            for trade in ib.trades():
                if trade.order.permId == tp_order.permId and trade.contract.conId == contract.conId:
                    tp_active = trade.isActive() or (trade.orderStatus and
                        trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending'])
                    break

        # 2. Safety: Look for ANY active Limit order for this contract with correct parentId
        if not tp_active:
            entry_order = bracket.get('entry')
            entry_id = entry_order.orderId if entry_order and hasattr(entry_order, 'orderId') else 0
            
            for trade in ib.trades():
                if trade.contract.conId == contract.conId and trade.isActive():
                    order = trade.order
                    is_limit = isinstance(order, LimitOrder) or getattr(order, 'lmtPrice', 0) > 0
                    
                    # Match by parentId (strongest link)
                    if is_limit and entry_id != 0 and getattr(order, 'parentId', 0) == entry_id:
                        tp_active = True
                        bracket['takeProfit'] = order # Repair the handle
                        logging.info(f"Repaired TP handle for tracked position (parent link: {entry_id})")
                        break
                    
                    # Match by Action and Quantity (fallback for when parentId is lost or not yet assigned)
                    action = 'SELL' if direction == 1 else 'BUY'
                    if (is_limit and order.action == action and 
                        abs(order.totalQuantity) == 1 and # Adjust if handling multi-lot
                        trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                        tp_active = True
                        bracket['takeProfit'] = order
                        logging.debug(f"Assumed active order {order.permId} is the TP for bracket")
                        break

        if tp_active:
            continue

        # TP is missing — recreate it
        try:
            current_price = data['close'].iloc[-1]

            # Calculate TP from strategy
            if getattr(strategy, 'opposite_bb_tp', False) and 'upper' in data.columns:
                tp = data['upper'].iloc[-1] if direction == 1 else data['lower'].iloc[-1]
            else:
                pos_dict = bracket.get('position_dict', {})
                tp = pos_dict.get('tp')

            if tp is None or pd.isna(tp) or tp <= 0:
                continue

            tp = round(float(tp) * 4) / 4
            
            # Final sanity check: TP must be on the correct side of current price
            if (direction == 1 and tp <= current_price) or (direction == -1 and tp >= current_price):
                logging.warning(f"Skipping TP recreation: price {tp} is already reached or on wrong side of {current_price}")
                continue
            qty = 1
            stop_order = bracket.get('stopLoss')
            if stop_order and hasattr(stop_order, 'totalQuantity'):
                qty = abs(stop_order.totalQuantity)

            tp_action = 'SELL' if direction == 1 else 'BUY'
            
            # Deterministic group naming to ensure linkage with existing SL
            oca_group = bracket.get('ocaGroup', f"bracket_{contract.conId}_{direction}")
            
            new_tp_order = LimitOrder(
                action=tp_action, totalQuantity=qty, lmtPrice=tp,
                tif='GTC', ocaGroup=oca_group, ocaType=1, transmit=True
            )

            logging.info(f"Recreating TP order: {tp_action} {qty} @ {tp:.2f}")
            tp_trade = ib.placeOrder(contract, new_tp_order)
            ib.sleep(0.5)

            # Verify active
            if tp_trade and tp_trade.order:
                is_active = tp_trade.isActive() or (tp_trade.orderStatus and
                    tp_trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending'])
                if is_active:
                    bracket['takeProfit'] = new_tp_order
                    logging.info(f"Successfully recreated TP at {tp:.2f}")
                    if live_tracker:
                        add_to_live_tracker(live_tracker, 'order', f"Recreated TP at ${tp:.2f}")
                else:
                    logging.error("Failed to recreate TP - order not active")
        except Exception as e:
            logging.error(f"Error recreating TP: {e}")


def reconcile_positions(ib, contract, positions, live_tracker=None, 
                        completed_trades=None, send_email_fn=None, data=None, strategy=None):
    """
    SELF-HEALING: Sync internal 'positions' list with actual IBKR positions.
    Purges 'Ghost Brackets' that exist in our tracking but not in TWS.
    """
    if not ib.isConnected():
        return

    # Import lazy-load to avoid circular dependency
    from core.execution import _record_trade_close

    try:
        # 1. Get all actual ES positions
        # Use symbol 'ES' to handle roll-over contracts safely
        actual_es_pos = [p for p in ib.positions() if p.contract.symbol == 'ES']
        
        # 2. Iterate through our internal tracking list
        for bracket in positions[:]:
            direction = bracket.get('direction')
            qty = 0
            # Resolve quantity from available order handles
            for k in ['stopLoss', 'entry', 'takeProfit']:
                if bracket.get(k) and hasattr(bracket[k], 'totalQuantity'):
                    qty = abs(bracket[k].totalQuantity)
                    break
            
            # Find matching actual position
            match = next((p for p in actual_es_pos 
                        if (1 if p.position > 0 else -1) == direction and abs(p.position) == qty), None)
            
            if match is None:
                # 30-SECOND GRACE PERIOD: 
                # Don't immediately purge. A fill might have just happened and we're waiting for the event.
                first_missing = bracket.get('first_missing_time')
                if first_missing is None:
                    bracket['first_missing_time'] = datetime.now()
                    continue # Wait for next cycle
                
                missing_duration = (datetime.now() - first_missing).total_seconds()
                if missing_duration < 30:
                    logging.debug(f"Position {direction} missing from TWS for {missing_duration:.1f}s. Waiting for grace period...")
                    continue

                # This is a GHOST BRACKET (tracked but not in TWS for > 30s)
                logging.warning(f"GHOST POSITION DETECTED: Tracked {'LONG' if direction==1 else 'SHORT'} "
                             f"({qty} contracts) but not found in TWS for {missing_duration:.1f}s. Recording as Manual Close...")
                
                # Cleanup associated orders immediately to prevent 'improper price' storm
                for order_key in ['stopLoss', 'takeProfit']:
                    order = bracket.get(order_key)
                    if order:
                        # Find and cancel any active trades for this order
                        for trade in ib.trades():
                            if trade.order.permId == getattr(order, 'permId', 0) and trade.isActive():
                                try:
                                    ib.cancelOrder(trade.order)
                                    logging.info(f"Cancelled orphaned {order_key} for ghost bracket: {trade.order.permId}")
                                except: pass

                # Record the trade as "Unknown" (triggers deep-search in execution.py)
                try:
                    # Mock row for price discovery
                    latest_row = {'close': 0}
                    if data is not None and not data.empty:
                        latest_row = data.iloc[-1]
                    
                    _record_trade_close(
                        ib, contract, bracket, 
                        bracket.get('entry'), bracket.get('stopLoss'), bracket.get('takeProfit'),
                        None, None, direction, latest_row, positions,
                        completed_trades, live_tracker, send_email_fn, data,
                        reason='Unknown', strategy=strategy
                    )
                except Exception as e:
                    logging.error(f"Failed to record ghost bracket closure: {e}")

                if bracket in positions:
                    positions.remove(bracket)
                if live_tracker:
                    add_to_live_tracker(live_tracker, 'warning', f"Purged ghost position ({qty} contracts)")
            else:
                # Position found in TWS - reset the missing timer
                bracket.pop('first_missing_time', None)

    except Exception as e:
        logging.error(f"Error in reconcile_positions: {e}")


async def periodic_protection_check(ib, contract, positions, strategy, data, live_tracker=None, 
                                 send_email_fn=None, close_all_fn=None, completed_trades=None):
    """Every-20s async task: maintenance -> cleanup -> protect -> stop invariant -> recreate TP."""
    from core.execution import prune_dead_brackets

    while True:
        await asyncio.sleep(20)
        if not ib.isConnected() or contract is None:
            continue
            
        try:
            prune_dead_brackets(ib, contract, positions, live_tracker)
            # --- 1. Maintenance & RTH Force Exit Check (Robust Safety) ---
            # We recreate a dummy single-row DF to check current filters
            if strategy and hasattr(strategy, 'apply_filters'):
                now_et = datetime.now(pytz.timezone('US/Eastern'))
                dummy_df = pd.DataFrame(index=[now_et])
                # Fill with enough dummy data to avoid strategy crashes
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    dummy_df[col] = 0
                
                try:
                    # Apply filters to current time
                    filtered = strategy.apply_filters(dummy_df)
                    
                    # Also reconcile positions with TWS every minute
                    reconcile_positions(ib, contract, positions, live_tracker, 
                                      completed_trades=completed_trades, send_email_fn=send_email_fn, data=data, strategy=strategy)
                    if not filtered.empty:
                        row = filtered.iloc[0]
                        force_maint = row.get('force_exit', False)
                        force_rth = row.get('force_exit_rth', False)
                        
                        if force_maint or force_rth:
                            reason = "Maintenance" if force_maint else "RTH End"
                            # Check if ANY ES position exists (tracked or orphaned)
                            es_pos = [p for p in ib.positions() if p.contract.symbol == 'ES' and p.position != 0]
                            if es_pos or positions:
                                if close_all_fn and send_email_fn:
                                    logging.warning(f"⚠️ {reason.upper()} APPROACHING (Periodic Check) - Closing all ES positions")
                                    acct_fn = lambda: get_account_summary(ib, data, contract)
                                    close_all_fn(
                                        reason, ib, contract, positions, data,
                                        live_tracker, send_email_fn, strategy=strategy,
                                        account_fn=acct_fn, completed_trades=completed_trades,
                                    )
                except Exception as e:
                    logging.error(f"Error checking maintenance in periodic loop: {e}")

            # --- 2. Standard Protection Checks ---
            cleanup_orphaned_orders(ib, contract, positions)
            close_orphaned_positions(ib, contract, positions, live_tracker, completed_trades, data)
            protect_existing_positions(ib, contract, positions, strategy, data, live_tracker)
            enforce_stop_invariant(ib, positions, strategy, data, live_tracker)
            check_and_recreate_tp_orders(ib, contract, positions, strategy, data, live_tracker)
        except Exception as e:
            logging.error(f"Error in periodic protection check: {e}")


def run_reconnection_safety_sequence(ib, contract, positions, strategy, data, live_tracker=None, completed_trades=None):
    """Post-reconnection safety: reconcile -> cleanup -> close orphans -> protect -> recreate TP."""
    logging.info("Running post-reconnection safety sequence...")
    # 0. Sync internal state with reality (THE STABILITY FIX)
    reconcile_positions(ib, contract, positions, live_tracker, strategy=strategy)
    
    # 1. Standard safety checks
    cleanup_orphaned_orders(ib, contract, positions)
    close_orphaned_positions(ib, contract, positions, live_tracker, completed_trades, data)
    protect_existing_positions(ib, contract, positions, strategy, data, live_tracker)
    enforce_stop_invariant(ib, positions, strategy, data, live_tracker)
    check_and_recreate_tp_orders(ib, contract, positions, strategy, data, live_tracker)
    logging.info("Safety sequence complete")
