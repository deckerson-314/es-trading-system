"""
core/account.py - Account Summary & Utility Functions
Ported from ib_deployment_v4.py lines 649-820
"""
import logging
from datetime import datetime
import pytz

EASTERN = pytz.timezone('US/Eastern')


def format_duration(seconds):
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def get_account_summary(ib, data=None, contract=None, portfolio_realized_pnl=None):
    """Get account summary with fallback logic for PnL calculation."""
    try:
        account_values = ib.accountValues()
        summary = {}

        for av in account_values:
            tag = getattr(av, 'tag', getattr(av, 'key', None))
            value = getattr(av, 'value', getattr(av, 'val', None))

            if tag and value is not None:
                tag_upper = tag.upper() if tag else ''
                if any(kw in tag_upper for kw in ['NETLIQUIDATION', 'CASH', 'BUYINGPOWER',
                       'GROSSPOSITION', 'AVAILABLEFUNDS', 'REALIZEDPNL', 'UNREALIZEDPNL']):
                    try:
                        val = float(value) if value else 0.0
                        
                        # Store raw tag
                        summary[tag] = val
                        
                        # Normalize common tags to canonical names
                        # RULE: Prefer exact tag match 'NetLiquidation' or non-zero value
                        if 'NETLIQUIDATION' in tag_upper:
                            if tag == 'NetLiquidation' or summary.get('NetLiquidation', 0) == 0:
                                summary['NetLiquidation'] = val
                        if 'CASH' in tag_upper and ('TOTAL' in tag_upper or 'BALANCE' in tag_upper):
                            if summary.get('TotalCashValue', 0) == 0:
                                summary['TotalCashValue'] = val
                        if 'BUYINGPOWER' in tag_upper:
                            summary['BuyingPower'] = val
                        if 'REALIZEDPNL' in tag_upper:
                            if val != 0 or summary.get('RealizedPNL', 0) == 0:
                                summary['RealizedPNL'] = val
                        if 'UNREALIZEDPNL' in tag_upper:
                            if val != 0 or summary.get('UnrealizedPNL', 0) == 0:
                                summary['UnrealizedPNL'] = val
                    except (ValueError, TypeError):
                        pass

        # Get ES positions and calculate PnL 
        positions_list = ib.positions()
        es_positions = [p for p in positions_list if p.contract.symbol == 'ES']
        current_price = data['close'].iloc[-1] if data is not None and len(data) > 0 else 0

        total_unrealized_pnl = 0
        total_realized_pnl = 0

        for p in es_positions:
            # Unrealized PnL with manual fallback
            unrealized = getattr(p, 'unrealizedPNL', None) or getattr(p, 'unrealizedPnl', None) or 0
            if unrealized == 0 and current_price > 0:
                try:
                    avg_price = getattr(p, 'averageCost', 0) or getattr(p, 'avgCost', 0)
                    contract_multiplier = 50
                    if avg_price > 20000 and p.position != 0:
                        avg_price = avg_price / contract_multiplier / abs(p.position)
                    if avg_price > 0:
                        unrealized = (current_price - avg_price) * p.position * contract_multiplier
                except Exception:
                    pass
            total_unrealized_pnl += unrealized or 0

            # Realized PnL
            realized = getattr(p, 'realizedPNL', None) or getattr(p, 'realizedPnl', None) or 0
            total_realized_pnl += realized

        # Account-level realized PnL must come from Account Summary tags (or ES position sum),
        # not from a single PortfolioItem line — that field tracks contract-level / day slice and
        # often tracks unrealized movement in paper, which made the top "Realized" box misleading.
        if summary.get('RealizedPNL', 0) == 0 and total_realized_pnl:
            summary['RealizedPNL'] = total_realized_pnl
        if portfolio_realized_pnl is not None:
            summary['ContractRealizedPNL'] = portfolio_realized_pnl

        if summary.get('UnrealizedPNL', 0) == 0 and total_unrealized_pnl != 0:
            summary['UnrealizedPNL'] = total_unrealized_pnl

        summary['ES_Positions'] = len(es_positions)
        return summary
    except Exception as e:
        logging.debug(f"Error getting account summary: {e}")
        return {}


def add_to_live_tracker(live_tracker, event_type, message, max_entries=200):
    """Add an event to the live tracker ring buffer."""
    timestamp = datetime.now(EASTERN).strftime('%Y-%m-%d %H:%M:%S')
    live_tracker.append({
        'timestamp': timestamp,
        'type': event_type,
        'message': message
    })
    if len(live_tracker) > max_entries:
        del live_tracker[:-max_entries]


def add_error(error_log, error_msg, max_entries=100):
    """Add an error to the error log ring buffer."""
    timestamp = datetime.now(EASTERN).strftime('%Y-%m-%d %H:%M:%S')
    error_log.append({
        'timestamp': timestamp,
        'error': error_msg
    })
    if len(error_log) > max_entries:
        del error_log[:-max_entries]
