"""
core/monitoring.py - Bar Processing, Indicator Updates, and Data Recording
Ported from ib_deployment_v4.py lines 1735-2095
Made strategy-agnostic to support Bollinger, Trend, and future strategies.
"""
import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime
import pytz

from core.account import add_to_live_tracker
from core.execution import check_entries, check_exits


def resample_data(df, timeframe_mins):
    """
    Resample 1-minute OHLCV data into arbitrary minute timeframe.
    Args:
        df: 1-minute DataFrame with datetime index.
        timeframe_mins: Target timeframe in minutes.
    Returns:
        DataFrame resampled and aggregated correctly.
    """
    if timeframe_mins <= 1:
        return df.copy()

    # Rule: Sum volume, first open, max high, min low, last close
    logic = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }

    # Use closed='right', label='right' to match IB bar behavior (e.g. 10:00 bar contains 09:30-10:00)
    resampled = df.resample(f'{timeframe_mins}min', closed='right', label='right').agg(logic)
    return resampled.dropna()


def _indicators_ready(data):
    """Check if indicators have been calculated (strategy-agnostic).
    Returns True if the data has any indicator columns beyond OHLCV.
    """
    base_cols = {'open', 'high', 'low', 'close', 'volume'}
    indicator_cols = set(data.columns) - base_cols
    return len(indicator_cols) > 0


def update_indicators(strategy, data):
    """Update indicators and filters on the global data DataFrame.
    Handles resampling correctly — prevents stale force_exit values across day boundaries.
    Fixed: Now supports higher timeframes by resampling before calculation.
    """
    timeframe = getattr(strategy, 'timeframe', 1)
    min_bars = strategy.min_bars_required
    
    if len(data) < min_bars:
        return

    # 1. Prepare Data for Calculation
    if timeframe > 1:
        # Resample for HTF calculation
        data_to_calc = resample_data(data, timeframe)
    else:
        data_to_calc = data.copy()

    if len(data_to_calc) < 2: # Need at least some history
        return

    # 2. Calculate Indicators on correct periodicity
    data_with_indicators = strategy.calculate_indicators(data_to_calc)
    
    # 3. Apply filters
    data_with_filters = strategy.apply_filters(data_with_indicators)

    # 4. Map back to 1-minute bars
    # Copy ALL indicator and filter columns back
    base_cols = {'open', 'high', 'low', 'close', 'volume'}
    new_cols = [col for col in data_with_filters.columns if col not in base_cols]
    
    for col in new_cols:
        # For force_exit, we only want to map exactly OR ffill if logical
        if col in ['force_exit', 'force_exit_rth']:
            data[col] = False # Reset first
            # Map exactly to the boundary rows
            matching = data.index.intersection(data_with_filters.index)
            if len(matching) > 0:
                data.loc[matching, col] = data_with_filters.loc[matching, col]
        else:
            # For most indicators (SMA, ATR, volume_filter), forward-fill is correct
            # Reindex to 1-min index and ffill
            data[col] = data_with_filters[col].reindex(data.index, method='ffill')


def save_live_data_row(output_dir, timestamp, row, full_df):
    """Save live data row to CSV for backtest comparison."""
    try:
        csv_path = os.path.join(output_dir, 'live_data.csv')
        file_exists = os.path.isfile(csv_path)

        # Dynamically include all available columns
        base_cols = ['open', 'high', 'low', 'close', 'volume']
        extra_cols = ['upper', 'lower', 'mid', 'atr_ts', 'atr', 'donchian_high', 'donchian_low',
                      'in_rth', 'in_maintenance', 'volume_filter', 'atr_filter',
                      'force_exit', 'force_exit_rth']

        row_data = {}
        for col in base_cols + extra_cols:
            val = row.get(col, '') if isinstance(row, dict) else getattr(row, col, '')
            if val != '':
                row_data[col] = val

        row_series = pd.Series(row_data, name=timestamp)

        if not file_exists:
            row_series.to_frame().T.to_csv(csv_path, mode='w', header=True)
        else:
            row_series.to_frame().T.to_csv(csv_path, mode='a', header=False)
    except Exception as e:
        logging.error(f"Failed to save live data row: {e}")

def save_shadow_audit(output_dir, timestamp, action_log):
    """Save rejection events to daily shadow_audit_YYYYMMDD.json."""
    if not action_log:
        return
        
    try:
        # Only log 'Breakout Rejected' types for the auditor
        rejections = [entry for entry in action_log if entry.get('type') == 'Breakout Rejected']
        if not rejections:
            return
            
        date_str = timestamp.strftime('%Y%m%d') if hasattr(timestamp, 'strftime') else datetime.now().strftime('%Y%m%d')
        audit_path = os.path.join(output_dir, f'shadow_audit_{date_str}.json')
        
        # Load existing audit log
        audit_data = []
        if os.path.exists(audit_path):
            try:
                with open(audit_path, 'r') as f:
                    audit_data = json.load(f)
            except:
                pass
        
        # Add new rejections (avoiding duplicates if possible)
        for rej in rejections:
            # Convert timestamp to string if needed
            if hasattr(rej['timestamp'], 'strftime'):
                rej['timestamp'] = rej['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            
            # Simple deduplication: don't add if timestamp+direction already exists
            exists = any(item['timestamp'] == rej['timestamp'] and item['direction'] == rej['direction'] for item in audit_data)
            if not exists:
                audit_data.append(rej)
        
        # Save back
        with open(audit_path, 'w') as f:
            json.dump(audit_data, f, indent=2)
            
    except Exception as e:
        logging.error(f"Failed to save shadow audit: {e}")


def log_entry_criteria_status(strategy, positions, resampled_row, data_with_filters, output_dir=None):
    """Log entry criteria status with emoji indicators for each filter.
    Strategy-agnostic: uses strategy.check_entry() if available, otherwise basic filter checks.
    """
    try:
        price = resampled_row.get('close', 0)
        volume = resampled_row.get('volume', 0)

        max_ok = len(positions) < strategy.max_open_trades
        in_rth = resampled_row.get('in_rth', True)
        atr_filter = resampled_row.get('atr_filter', False)
        vol_filter = resampled_row.get('volume_filter', True)  # True by default for strategies without volume filter
        in_maint = resampled_row.get('in_maintenance', False)

        enter_long = enter_short = False
        long_reason = short_reason = ""
        action_log = None

        # 1. Strategy-Agnostic Global Filters (Positions, Maintenance, RTH)
        if not max_ok:
            long_reason = short_reason = f"Max trades ({len(positions)}/{strategy.max_open_trades})"
        elif in_maint:
            long_reason = short_reason = "Maintenance Filter"
        elif not in_rth:
            long_reason = short_reason = "Outside RTH"
        else:
            # 2. Strategy Signal and Filter Check
            if hasattr(strategy, 'check_entry'):
                triggered, direction, _ = strategy.check_entry(resampled_row, data_with_filters)
                enter_long = triggered and direction == 'Long'
                enter_short = triggered and direction == 'Short'
                long_reason = "Signal triggered" if enter_long else "No entry"
                short_reason = "Signal triggered" if enter_short else "No entry"
                
            elif hasattr(strategy, 'calculate_entry_signals') and data_with_filters is not None:
                try:
                    # Request Action Log (verbose=True)
                    sigs = strategy.calculate_entry_signals(data_with_filters, verbose=True)
                    
                    if len(sigs) == 3:
                        long_sig, short_sig, action_log = sigs
                    else:
                        long_sig, short_sig = sigs
                    
                    idx = resampled_row.name if hasattr(resampled_row, 'name') else None
                    if idx is not None and idx in data_with_filters.index:
                        loc = data_with_filters.index.get_loc(idx)
                        enter_long = bool(long_sig.iloc[loc]) if loc < len(long_sig) else False
                        enter_short = bool(short_sig.iloc[loc]) if loc < len(short_sig) else False
                        
                        # Extract rejection reasons from Action Log for this specific bar
                        if action_log:
                            bar_logs = [entry for entry in action_log if entry['timestamp'] == idx]
                            long_info = next((l for l in bar_logs if l['direction'] == 'LONG'), None)
                            short_info = next((l for l in bar_logs if l['direction'] == 'SHORT'), None)
                            
                            if long_info:
                                long_reason = " | ".join(long_info['reasons']) if long_info['reasons'] else "Signal triggered"
                            else:
                                long_reason = "No breakout"
                                
                            if short_info:
                                short_reason = " | ".join(short_info['reasons']) if short_info['reasons'] else "Signal triggered"
                            else:
                                short_reason = "No breakout"
                        else:
                            long_reason = "Signal triggered" if enter_long else "No entry"
                            short_reason = "Signal triggered" if enter_short else "No entry"
                            
                except Exception as e:
                    logging.debug(f"Error checking strategy signals: {e}")
                    long_reason = short_reason = "Error"

            # Check ATR and Volume failure if not already covered by strategy core
            if not enter_long and long_reason == "Signal triggered": # Logic error safety
                long_reason = "No signal"
            if not enter_short and short_reason == "Signal triggered":
                short_reason = "No signal"
                
            # If strategy didn't report ATR/Vol failure but they failed globally:
            if not (long_reason or short_reason):
                if not atr_filter: long_reason = short_reason = "ATR filter failed"
                elif not vol_filter: long_reason = short_reason = f"Vol filter (vol={volume:,.0f})"

        # 3. Build detailed parts using numerical values if available
        parts = []
        
        # Get numerical status from strategy if supports it
        num_status = {}
        if hasattr(strategy, 'get_indicator_status'):
            num_status = strategy.get_indicator_status(resampled_row)
            
        # Global Filters
        parts.append(f"MaxTr: {'✅' if max_ok else '❌'}")
        parts.append(f"RTH: {'✅' if in_rth else '❌'}")
        parts.append(f"Maint: {'✅' if not in_maint else '❌'}")
        
        # Numerical Filter Details
        if num_status:
            # Target columns for display
            if 'ADX' in num_status:
                s = num_status['ADX']
                parts.append(f"ADX: {'✅' if s['pass'] else '❌'} ({s['value']:.1f}/{s['threshold']:.1f})")
            
            if 'Volume' in num_status:
                s = num_status['Volume']
                # Compact volume display (k)
                parts.append(f"Vol: {'✅' if s['pass'] else '❌'} ({s['value']/1000:.1f}k/{s['threshold']/1000:.1f}k)")
                
            if 'RSI' in num_status:
                s = num_status['RSI']
                val = s['value']
                target = s['buy_threshold'] if not enter_short else s['sell_threshold']
                icon = '✅' if (s['pass_long'] or s['pass_short']) else '❌'
                parts.append(f"RSI: {icon} ({val:.1f})")

            if 'VWAP' in num_status:
                s = num_status['VWAP']
                icon = '✅' if (s['pass_long'] or s['pass_short']) else '❌'
                parts.append(f"VWAP: {icon}")

        else:
            # Fallback to simple emojis if no numerical status available
            parts.append(f"ATR: {'✅' if atr_filter else '❌'}")
            parts.append(f"Vol: {'✅' if vol_filter else '❌'}")

        # Final Signal Status
        parts.append(f"Long: {'✅' if enter_long else '❌'} ({long_reason})")
        parts.append(f"Short: {'✅' if enter_short else '❌'} ({short_reason})")

        criteria_str = ' | '.join(parts)
        logging.info(f"  Entry Criteria: {criteria_str}")
        
        # 4. Save to Shadow Auditor if breakouts were rejected
        if action_log and output_dir:
            save_shadow_audit(output_dir, resampled_row.name, action_log)

        return criteria_str
    except Exception as e:
        logging.debug(f"Error logging entry criteria: {e}")
        return ""


def on_bar_update_handler(bars, hasNewBar, *, strategy, ib, contract, data_ref,
                          positions, completed_trades, live_tracker, bar_log,
                          dashboard_state, send_email_fn, output_dir, last_data_receipt):
    """Full bar update handler with resampling, liveness detection, and signal checking.
    data_ref is a dict {'data': DataFrame} so we can mutate the reference.
    last_data_receipt is a dict {'time': datetime} for liveness tracking.
    Strategy-agnostic: works with any strategy implementing the base Strategy interface.
    """
    last_data_receipt['time'] = datetime.now()
    try:
        df = pd.DataFrame([(b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars],
                          columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        if df.empty:
            return

        df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_convert('US/Eastern')
        df.set_index('datetime', inplace=True)
        data = df[['open', 'high', 'low', 'close', 'volume']].copy()
        data_ref['data'] = data

        bar_time = data.index[-1]
        latest_row = data.iloc[-1]

        # Live vs delayed detection
        current_time = datetime.now(pytz.timezone('US/Eastern'))
        delay = (current_time - bar_time).total_seconds()
        delay_tag = " [LIVE]" if delay < 10 else (" [DELAYED]" if delay > 900 else "")

        update_type = " [NEW]" if hasNewBar else " [UPD]"
        log_msg = (f"[1-min bar]{update_type} {bar_time.strftime('%H:%M:%S')}{delay_tag} | "
                   f"O: {latest_row['open']:.2f} H: {latest_row['high']:.2f} "
                   f"L: {latest_row['low']:.2f} C: {latest_row['close']:.2f} | "
                   f"Vol: {latest_row['volume']:,.0f}")
        if hasNewBar:
            logging.info(log_msg)
        else:
            logging.debug(log_msg)

        # Dashboard price update
        if dashboard_state:
            dashboard_state.current_price = latest_row['close']

        # Resampled bar check
        should_check = False
        if strategy.timeframe == 1:
            should_check = hasNewBar
        elif strategy.timeframe > 1 and hasNewBar:
            total_min = bar_time.hour * 60 + bar_time.minute
            should_check = (total_min % strategy.timeframe == 0)

        # Update indicators
        update_indicators(strategy, data)

        min_bars = strategy.min_bars_required

        # Process completed bar
        if should_check and len(data) >= 2:
            # IMPORTANT: Re-calculate HTF indicators and filters to get the CORRECT aggregated OHLCV
            # for the reporting and signal boundary
            resampled_df = resample_data(data, strategy.timeframe)
            if len(resampled_df) < 2:
                return

            # Apply strategy logic to resampled data
            resampled_ind = strategy.calculate_indicators(resampled_df.copy())
            try:
                resampled_filt = strategy.apply_filters(resampled_ind)
            except Exception:
                resampled_filt = resampled_ind

            # Use COMPLETED HTF bar (index -2) for signal checks and reporting
            completed_idx = resampled_filt.index[-2]
            completed_row = resampled_filt.iloc[-2]

            bar_info = (f"[{strategy.timeframe}-min] {completed_idx.strftime('%H:%M:%S')} | "
                       f"O: {completed_row.get('open', 0):.2f} H: {completed_row.get('high', 0):.2f} "
                       f"L: {completed_row.get('low', 0):.2f} C: {completed_row.get('close', 0):.2f} | "
                       f"Vol: {completed_row.get('volume', 0):,.0f}")
            logging.info(bar_info)

            # Signal check on the proper HTF bar
            entry_criteria = ""
            if _indicators_ready(data): # Data already has indicators mapped back from update_indicators above
                # Note: We pass the resampled_filt to signal checker to ensure it sees HTF context
                entry_criteria = log_entry_criteria_status(strategy, positions, completed_row, resampled_filt, output_dir=output_dir)
                
                # Save data for audit (use the resampled row)
                save_live_data_row(output_dir, completed_idx, completed_row, resampled_filt)
                
                # Check entries using HTF bar
                check_entries(strategy, ib, contract, data, positions, {},
                             live_tracker, dashboard_state, send_email_fn, completed_idx, completed_row)
                
                # Check exits using HTF bar (for boundary exit signals)
                check_exits(strategy, ib, contract, data, positions, completed_trades,
                           live_tracker, send_email_fn, completed_idx, completed_row, allow_strategy_exit=True)

            # Bar log for dashboard
            bar_log.append({
                'timestamp': completed_idx.strftime('%H:%M:%S'),
                'bar_info': bar_info,
                'entry_criteria': entry_criteria
            })
            if len(bar_log) > 20:
                del bar_log[:-20]

        # Realtime safety exits (using latest bar, not resampled)
        if len(data) >= min_bars and _indicators_ready(data):
            check_exits(strategy, ib, contract, data, positions, completed_trades,
                       live_tracker, send_email_fn, data.index[-1], data.iloc[-1], allow_strategy_exit=False)

    except Exception as e:
        bar_time_str = "unknown"
        try:
            bar_time_str = bars[-1].date.strftime('%H:%M:%S')
        except:
            pass
        logging.error(f"Error in on_bar_update at {bar_time_str}: {type(e).__name__}: {e}", exc_info=True)
