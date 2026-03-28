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
    Strategy-agnostic: works with any strategy that implements calculate_indicators() and apply_filters().
    """
    min_bars = strategy.min_bars_required
    if len(data) < min_bars:
        return

    data_with_indicators = strategy.calculate_indicators(data.copy())

    # Copy ALL indicator columns back (strategy-agnostic)
    base_cols = {'open', 'high', 'low', 'close', 'volume'}
    indicator_cols = [col for col in data_with_indicators.columns if col not in base_cols]
    for col in indicator_cols:
        data[col] = data_with_indicators[col]

    # Apply filters
    data_with_filters = strategy.apply_filters(data_with_indicators)

    # CRITICAL: force_exit/force_exit_rth must NOT be forward-filled (stale values across day boundaries)
    for col in ['force_exit', 'force_exit_rth']:
        if col in data_with_filters.columns:
            data[col] = False  # Reset first
            matching = data.index.intersection(data_with_filters.index)
            if len(matching) > 0:
                data.loc[matching, col] = data_with_filters.loc[matching, col]
            # For latest row without match, use most recent resampled bar
            if len(data) > 0 and data.index[-1] not in matching:
                latest_time = data.index[-1]
                earlier = data_with_filters[data_with_filters.index <= latest_time]
                if len(earlier) > 0:
                    data.loc[data.index[-1], col] = earlier[col].iloc[-1]

    # Other filter columns: forward-fill is OK
    for col in ['volume_filter', 'atr_filter', 'in_rth', 'in_maintenance']:
        if col in data_with_filters.columns:
            reindexed = data_with_filters[col].reindex(data.index, method='ffill')
            data[col] = reindexed.fillna(False)


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


def log_entry_criteria_status(strategy, positions, resampled_row, data_with_filters):
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

        if max_ok and in_rth and atr_filter and vol_filter and not in_maint:
            # Use strategy's check_entry if available (Bollinger), otherwise check_entry_signals
            if hasattr(strategy, 'check_entry'):
                triggered, direction, _ = strategy.check_entry(resampled_row, data_with_filters)
                enter_long = triggered and direction == 'Long'
                enter_short = triggered and direction == 'Short'
            elif hasattr(strategy, 'calculate_entry_signals') and data_with_filters is not None:
                try:
                    long_sig, short_sig = strategy.calculate_entry_signals(data_with_filters)
                    idx = resampled_row.name if hasattr(resampled_row, 'name') else None
                    if idx is not None and idx in data_with_filters.index:
                        loc = data_with_filters.index.get_loc(idx)
                        enter_long = bool(long_sig.iloc[loc]) if loc < len(long_sig) else False
                        enter_short = bool(short_sig.iloc[loc]) if loc < len(short_sig) else False
                except Exception:
                    pass

            if getattr(strategy, 'enable_long', True):
                long_reason = "Signal triggered" if enter_long else "No entry"
            else:
                long_reason = "Disabled"
            if getattr(strategy, 'enable_short', True):
                short_reason = "Signal triggered" if enter_short else "No entry"
            else:
                short_reason = "Disabled"
        else:
            if not max_ok: long_reason = short_reason = f"Max trades ({len(positions)}/{strategy.max_open_trades})"
            elif not in_rth: long_reason = short_reason = "Outside RTH"
            elif not atr_filter: long_reason = short_reason = "ATR filter failed"
            elif not vol_filter: long_reason = short_reason = f"Vol filter (vol={volume:,.0f})"
            elif in_maint: long_reason = short_reason = "Maintenance"

        parts = [
            f"MaxTr: {'✅' if max_ok else '❌'}",
            f"RTH: {'✅' if in_rth else '❌'}",
            f"ATR: {'✅' if atr_filter else '❌'}",
            f"Vol: {'✅' if vol_filter else '❌'}",
            f"Maint: {'✅' if not in_maint else '❌'}",
            f"Long: {'✅' if enter_long else '❌'} ({long_reason})",
            f"Short: {'✅' if enter_short else '❌'} ({short_reason})"
        ]

        # Strategy-specific price info
        upper_bb = resampled_row.get('upper', 0)
        lower_bb = resampled_row.get('lower', 0)
        if upper_bb > 0 and lower_bb > 0:
            parts.append(f"BB: L={lower_bb:.2f} | P={price:.2f} | U={upper_bb:.2f}")

        donchian_h = resampled_row.get('donchian_high', 0)
        donchian_l = resampled_row.get('donchian_low', 0)
        if donchian_h > 0 and donchian_l > 0:
            parts.append(f"DC: L={donchian_l:.2f} | P={price:.2f} | H={donchian_h:.2f}")

        criteria_str = ' | '.join(parts)
        logging.info(f"  Entry Criteria: {criteria_str}")
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
        if should_check and len(data) >= max(2, min_bars):
            data_ind = strategy.calculate_indicators(data.copy())
            try:
                data_filt = strategy.apply_filters(data_ind)
            except Exception:
                data_filt = data_ind

            if len(data_ind) >= 2:
                # Use COMPLETED bar (index -2) for signal checks
                completed_idx = data_ind.index[-2]
                completed_row = data_ind.iloc[-2]

                # Try to get filtered row
                if len(data_filt) > 0 and completed_idx in data_filt.index:
                    completed_row = data_filt.loc[completed_idx]
                else:
                    # Emergency filter fallback
                    logging.warning(f"Filter row missing for {completed_idx}. Using indicators with emergency defaults.")
                    completed_row = data_ind.iloc[-2].copy()
                    # Set safe defaults for missing filter columns
                    for col, default in [('volume_filter', False), ('atr_filter', True),
                                         ('in_rth', True), ('in_maintenance', False),
                                         ('avg_volume', 0)]:
                        if col not in completed_row:
                            completed_row[col] = default

                bar_info = (f"[{strategy.timeframe}-min] {completed_idx.strftime('%H:%M:%S')} | "
                           f"O: {completed_row.get('open', 0):.2f} H: {completed_row.get('high', 0):.2f} "
                           f"L: {completed_row.get('low', 0):.2f} C: {completed_row.get('close', 0):.2f} | "
                           f"Vol: {completed_row.get('volume', 0):,.0f}")
                logging.info(bar_info)

                # Filtered row for signal check
                filt_row = data_filt.loc[completed_idx] if (len(data_filt) > 0 and completed_idx in data_filt.index) else completed_row

                # Entry criteria logging and signal checks (strategy-agnostic)
                entry_criteria = ""
                if _indicators_ready(data):
                    entry_criteria = log_entry_criteria_status(strategy, positions, filt_row, data_filt)
                    save_live_data_row(output_dir, completed_idx, filt_row, data_filt)
                    check_entries(strategy, ib, contract, data, positions, {},
                                 live_tracker, dashboard_state, send_email_fn, completed_idx, filt_row)
                    check_exits(strategy, ib, contract, data, positions, completed_trades,
                               live_tracker, send_email_fn, completed_idx, filt_row, allow_strategy_exit=True)

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
