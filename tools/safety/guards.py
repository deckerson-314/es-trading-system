import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from ib_insync import IB, MarketOrder, Order, Trade

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
        self.flattened_today = False
        self.flattened_date = None  # Track which date was flattened for daily reset
        
        # Max position limit (from strategy params)
        self.max_open_trades = 1  # Default
        for k, v in self.params.items():
            k_lower = k.lower()
            if 'max open' in k_lower or 'max position' in k_lower:
                try:
                    self.max_open_trades = int(float(v.get('value', 1)))
                except (ValueError, TypeError, AttributeError):
                    pass
        
        # Try to parse limits from params if provided
        strats = ['Bollinger', 'Trend'] # Add others if needed
        self.max_daily_loss = 0.0
        self.max_daily_profit = 0.0
        
        for k, v in self.params.items():
            k_lower = k.lower()
            if 'max daily loss' in k_lower:
                self.max_daily_loss = abs(float(v.get('value', 0.0)))
            elif 'max daily profit' in k_lower or 'daily target' in k_lower:
                self.max_daily_profit = abs(float(v.get('value', 0.0)))
                
        if self.max_daily_loss > 0:
            logging.info(f"🛡️ SecurityGuard initialized with Max Daily Loss: -${self.max_daily_loss:,.2f}")
        if self.max_daily_profit > 0:
            logging.info(f"🛡️ SecurityGuard initialized with Max Daily Profit: +${self.max_daily_profit:,.2f}")

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
            
        try:
            # 1. Check actual open positions in account
            es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
            has_open_position = any(abs(p.position) > 0 for p in es_positions)
            
            # 2. Get all known order IDs from our tracked brackets
            tracked_order_ids = set()
            for bracket in tracked_positions:
                for key in ['entry', 'stopLoss', 'takeProfit']:
                    order = bracket.get(key)
                    if order and hasattr(order, 'permId') and order.permId:
                        tracked_order_ids.add(order.permId)

            # 3. Analyze active trades
            for trade in ib.trades():
                order = trade.order
                if (trade.contract.conId == contract.conId and 
                    trade.isActive() and
                    hasattr(order, 'permId')):
                    
                    # If position is closed, ALL protective orders should be cancelled
                    is_orphaned = False
                    
                    if not has_open_position and not tracked_positions:
                        is_orphaned = True
                        
                    # If we DO have a position, but this order isn't in our tracked brackets
                    elif order.permId not in tracked_order_ids:
                        # Only target standalone orders (no parent ID), highly likely to be trailing updates
                        # OR orders whose parent is already filled
                        if not hasattr(order, 'parentId') or order.parentId == 0:
                            is_orphaned = True
                        else:
                            parent_filled = any(
                                p_trade.order.permId == order.parentId and p_trade.filled()
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
                    not hasattr(trade.order, 'parentId') or getattr(trade.order, 'parentId', 0) == 0):
                    try:
                        ib.cancelOrder(trade.order)
                        logging.info(f"🛡️ Cancelled excess entry order: {trade.order.orderId}")
                    except Exception as e:
                        logging.warning(f"Error cancelling excess entry: {e}")

    def check_daily_pnl(self, ib: IB, contract, account_summary: Dict[str, float], tracked_positions: List) -> bool:
        """
        Check if daily PnL has breached the Max Loss or Max Profit limits.
        If breached, flattens all positions and cancels all working orders for the contract.
        
        Returns True if a flatten occurred, False otherwise.
        """
        self._check_daily_reset()  # Auto-reset at midnight
        
        if contract is None or not ib.isConnected() or self.flattened_today:
            return False
            
        # Limits must be configured
        if self.max_daily_loss == 0 and self.max_daily_profit == 0:
            return False
            
        # Throttle checks slightly (e.g., every 5-10 seconds max)
        if (datetime.now() - self.last_pnl_check).total_seconds() < 5:
            return False
        self.last_pnl_check = datetime.now()

        # Calculate accurate Daily PnL (Realized + Unrealized)
        realized = float(account_summary.get('RealizedPNL', 0.0))
        unrealized = float(account_summary.get('UnrealizedPNL', 0.0))
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
            logging.error(f"🚨🚨 {reason} 🚨🚨")
            logging.error("Initiating emergency flatten procedure...")
            
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
                        mkt_order = MarketOrder(action, qty)
                        ib.placeOrder(contract, mkt_order)
                
                # 3. Clear tracked positions list reference
                tracked_positions.clear()
                self.flattened_today = True
                self.flattened_date = datetime.now().date()
                
                # 4. Notify User
                msg = (f"EMERGENCY FLATTEN TRIGGERED\n{'='*50}\n\n"
                       f"Reason: {reason}\n"
                       f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                       f"All active orders cancelled and positions closed.\n"
                       f"The bot will evaluate no further trades today.")
                send_email("Trading Bot - EMERGENCY FLATTEN", msg)
                
                return True
                
            except Exception as e:
                logging.error(f"Failed during flatten procedure: {e}")
                
        return False
