"""
core/protection.py - Position Protection & Orphan Management
Ported from ib_deployment_v4.py lines 1575-3752
"""
import logging
import asyncio
from datetime import datetime
from ib_insync import MarketOrder, StopOrder, LimitOrder

from core.account import add_to_live_tracker


def cancel_all_pending(ib, contract, live_tracker=None):
    """Cancel pending orders, preserving protective orders (SL/TP) for open positions."""
    try:
        es_positions = []
        if contract:
            try:
                es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
            except:
                pass

        has_open = any(abs(p.position) > 0 for p in es_positions)

        if has_open:
            logging.info("Open position detected - preserving protective orders (SL/TP)")
            orders_to_cancel = []
            protective_orders = []

            try:
                for trade in ib.trades():
                    if contract and trade.contract.conId == contract.conId:
                        if trade.isActive() or (trade.orderStatus and
                            trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                            order = trade.order
                            is_stop = (isinstance(order, StopOrder) or
                                      (getattr(order, 'auxPrice', 0) > 0 and getattr(order, 'lmtPrice', 0) == 0))
                            is_limit = (isinstance(order, LimitOrder) or getattr(order, 'lmtPrice', 0) > 0)

                            if is_stop or is_limit:
                                protective_orders.append(trade)
                            else:
                                orders_to_cancel.append(trade)
            except Exception as e:
                logging.debug(f"Error checking orders: {e}")
                ib.reqGlobalCancel()
                return

            for trade in orders_to_cancel:
                try: ib.cancelOrder(trade.order)
                except: pass

            if orders_to_cancel:
                logging.info(f"Cancelled {len(orders_to_cancel)} non-protective, preserved {len(protective_orders)} protective")
        else:
            ib.reqGlobalCancel()
            logging.info("Cancelled all pending orders (no open positions)")
    except Exception as e:
        logging.warning(f"Error in cancel_all_pending: {e}, falling back to global cancel")
        ib.reqGlobalCancel()


def cleanup_orphaned_orders(ib, contract, positions):
    """Cancel active ES orders that don't belong to any tracked position."""
    if contract is None:
        return

    tracked_perm_ids = set()
    for bracket in positions:
        for key in ['entry', 'stopLoss', 'takeProfit']:
            order = bracket.get(key)
            if order and hasattr(order, 'permId') and order.permId != 0:
                tracked_perm_ids.add(order.permId)

    orphaned = []
    for trade in ib.trades():
        if trade.contract.conId == contract.conId and trade.isActive():
            if trade.order.permId not in tracked_perm_ids:
                # Check if parent is a filled entry (child of bracket)
                parent_id = getattr(trade.order, 'parentId', 0)
                if parent_id == 0 or parent_id not in tracked_perm_ids:
                    orphaned.append(trade)

    for trade in orphaned:
        try:
            ib.cancelOrder(trade.order)
            logging.info(f"Cancelled orphaned order: {trade.order.orderType} "
                        f"{trade.order.action} {trade.order.totalQuantity} "
                        f"(PermID: {trade.order.permId})")
        except Exception as e:
            logging.warning(f"Error cancelling orphaned order: {e}")


def close_orphaned_positions(ib, contract, positions, live_tracker=None):
    """Close positions that don't match any tracked bracket."""
    if contract is None:
        return

    es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
    for pos in es_positions:
        if pos.position == 0:
            continue

        # Check if this position is tracked
        is_tracked = False
        for bracket in positions:
            if bracket.get('direction') == (1 if pos.position > 0 else -1):
                is_tracked = True
                break

        if not is_tracked:
            logging.warning(f"ORPHANED POSITION: {pos.position} contracts, not tracked. Closing...")
            close_action = 'SELL' if pos.position > 0 else 'BUY'
            close_order = MarketOrder(action=close_action, totalQuantity=abs(pos.position), transmit=True)
            try:
                ib.placeOrder(contract, close_order)
                ib.sleep(2)
                logging.info("Orphaned position closed")
                if live_tracker:
                    add_to_live_tracker(live_tracker, 'warning',
                        f"Closed orphaned position: {pos.position} contracts")
            except Exception as e:
                logging.error(f"Failed to close orphaned position: {e}")


def protect_existing_positions(ib, contract, positions, strategy, data, live_tracker=None):
    """Add stop loss to any unprotected positions."""
    if contract is None or data is None or data.empty:
        return

    es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
    for pos in es_positions:
        if pos.position == 0:
            continue

        qty = abs(pos.position)
        direction = 1 if pos.position > 0 else -1

        # Check if position has an active stop
        has_stop = False
        for trade in ib.trades():
            order = trade.order
            is_stop = getattr(order, 'auxPrice', 0) > 0 and getattr(order, 'lmtPrice', 0) == 0
            if (trade.isActive() and is_stop and trade.contract.conId == contract.conId
                    and abs(order.totalQuantity) == qty):
                order_dir = 1 if order.action == 'SELL' else -1
                if order_dir == direction:
                    has_stop = True
                    break

        if not has_stop:
            logging.warning(f"UNPROTECTED POSITION: {qty} contracts. Adding stop loss...")
            current_price = data['close'].iloc[-1]
            pos_dict = strategy.setup_position(current_price, direction, data.iloc[-1], data)

            stop_order = StopOrder(
                action='SELL' if direction == 1 else 'BUY',
                totalQuantity=qty,
                stopPrice=round(pos_dict['stop'] * 4) / 4,
                tif='GTC', transmit=True
            )
            ib.placeOrder(contract, stop_order)
            logging.info(f"Re-created protective stop at {stop_order.stopPrice}")

            positions.append({
                'entry': MarketOrder(action='BUY' if direction == 1 else 'SELL', totalQuantity=qty),
                'stopLoss': stop_order, 'takeProfit': None,
                'direction': direction, 'position_dict': pos_dict,
                'entry_time': datetime.now(), 'entry_price': current_price
            })
            if live_tracker:
                add_to_live_tracker(live_tracker, 'warning',
                    f"Added protective stop at ${stop_order.stopPrice:.2f}")


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

        # Check if TP exists and is active
        tp_active = False
        if tp_order:
            for trade in ib.trades():
                if trade.order.permId == tp_order.permId and trade.contract.conId == contract.conId:
                    tp_active = trade.isActive() or (trade.orderStatus and
                        trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending'])
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

            if tp is None or tp == 0:
                continue

            tp = round(float(tp) * 4) / 4
            qty = 1
            stop_order = bracket.get('stopLoss')
            if stop_order and hasattr(stop_order, 'totalQuantity'):
                qty = abs(stop_order.totalQuantity)

            tp_action = 'SELL' if direction == 1 else 'BUY'
            new_tp_order = LimitOrder(
                action=tp_action, totalQuantity=qty, lmtPrice=tp,
                tif='GTC', transmit=True
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


async def periodic_protection_check(ib, contract, positions, strategy, data, live_tracker=None):
    """Every-60s async task: cleanup -> protect -> recreate TP."""
    while True:
        await asyncio.sleep(60)
        if ib.isConnected() and contract is not None:
            try:
                cleanup_orphaned_orders(ib, contract, positions)
                close_orphaned_positions(ib, contract, positions, live_tracker)
                protect_existing_positions(ib, contract, positions, strategy, data, live_tracker)
                check_and_recreate_tp_orders(ib, contract, positions, strategy, data, live_tracker)
            except Exception as e:
                logging.error(f"Error in periodic protection check: {e}")


def run_reconnection_safety_sequence(ib, contract, positions, strategy, data, live_tracker=None):
    """Post-reconnection safety: cleanup -> close orphans -> protect -> recreate TP."""
    logging.info("Running post-reconnection safety sequence...")
    cleanup_orphaned_orders(ib, contract, positions)
    close_orphaned_positions(ib, contract, positions, live_tracker)
    protect_existing_positions(ib, contract, positions, strategy, data, live_tracker)
    check_and_recreate_tp_orders(ib, contract, positions, strategy, data, live_tracker)
    logging.info("Safety sequence complete")
