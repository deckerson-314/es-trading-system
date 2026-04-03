import matplotlib
matplotlib.use('Agg')
import mplfinance as mpf
import pandas as pd
import os
import logging
from datetime import datetime, timedelta

def create_trade_chart(df: pd.DataFrame, entry_time: datetime, exit_time: datetime, 
                       direction: str, filepath: str, sl_price: float = None, 
                       tp_price: float = None, entry_price: float = None) -> bool:
    """Generates a candlestick chart with trade entry and exit arrows."""
    try:
        if df is None or len(df) == 0:
            logging.warning("Charting failed: Empty or None DataFrame provided.")
            return False
            
        # Ensure times are comparable with index
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.copy()
            df.index = pd.to_datetime(df.index)
            
        # Standardize to naive for comparison if index is naive, or vice versa
        if df.index.tz is not None and entry_time.tzinfo is None:
            # Localize inputs to index timezone using pandas Timestamp for .tz_localize support
            entry_time = pd.Timestamp(entry_time).tz_localize(df.index.tz)
            exit_time = pd.Timestamp(exit_time).tz_localize(df.index.tz)
        elif df.index.tz is None and entry_time.tzinfo is not None:
            # Strip timezone from inputs
            entry_time = entry_time.replace(tzinfo=None)
            exit_time = exit_time.replace(tzinfo=None)

        start_time = entry_time - timedelta(minutes=20)
        end_time = exit_time + timedelta(minutes=20)
        
        mask = (df.index >= start_time) & (df.index <= end_time)
        plot_df = df.loc[mask].copy()
        
        if plot_df.empty or len(plot_df) < 2:
            logging.warning(f"Charting failed: Filtered plot_df is too small ({len(plot_df)} bars) for range {start_time} to {end_time}")
            return False
            
        # Ensure required columns exist
        required = ['open', 'high', 'low', 'close']
        if not all(col in plot_df.columns.str.lower() for col in required):
            # Try to fix case
            plot_df.columns = [c.lower() for c in plot_df.columns]
            if not all(col in plot_df.columns for col in required):
                logging.error(f"Charting failed: Missing required OHLC columns. Found: {plot_df.columns}")
                return False

        entry_marker = pd.Series(index=plot_df.index, dtype=float)
        exit_marker = pd.Series(index=plot_df.index, dtype=float)
        
        try:
            entry_idx = plot_df.index.get_indexer([entry_time], method='nearest')[0]
            exit_idx = plot_df.index.get_indexer([exit_time], method='nearest')[0]
            
            entry_row = plot_df.iloc[entry_idx]
            exit_row = plot_df.iloc[exit_idx]
            
            # Dynamic offset based on ATR or price range
            price_range = plot_df['high'].max() - plot_df['low'].min()
            offset = max(1.0, price_range * 0.05) 
            
            is_long = str(direction).upper() in ['LONG', 'L', 'BUY', '1']
            
            if is_long:
                entry_marker.iloc[entry_idx] = entry_row['low'] - offset
                entry_marker_type, entry_color = '^', 'lime'
                exit_marker.iloc[exit_idx] = exit_row['high'] + offset
                exit_marker_type, exit_color = 'v', 'red'
            else:
                entry_marker.iloc[entry_idx] = entry_row['high'] + offset
                entry_marker_type, entry_color = 'v', 'red'
                exit_marker.iloc[exit_idx] = exit_row['low'] - offset
                exit_marker_type, exit_color = '^', 'lime'
                
            apds = [
                mpf.make_addplot(entry_marker, type='scatter', markersize=200, marker=entry_marker_type, color=entry_color),
                mpf.make_addplot(exit_marker, type='scatter', markersize=200, marker=exit_marker_type, color=exit_color)
            ]
            
            # 1. Add Indicators (Donchian/Bollinger) if they exist
            indicator_map = {
                'donchian_high': 'cyan', 'donchian_low': 'cyan', 'donchian_mid': 'blue',
                'upper_band': 'orange', 'lower_band': 'orange', 'mid_band': 'gray',
                'ema_200': 'darkred', 'vwap': 'purple'
            }
            for col, color in indicator_map.items():
                if col.lower() in plot_df.columns:
                    apds.append(mpf.make_addplot(plot_df[col.lower()], color=color, width=0.8, alpha=0.7))
            
            # 2. Setup Horizontal Lines (TP / SL / Entry)
            hlines_list = []
            hlines_colors = []
            if tp_price: 
                hlines_list.append(tp_price); hlines_colors.append('lime')
            if sl_price: 
                hlines_list.append(sl_price); hlines_colors.append('red')
            if entry_price: 
                hlines_list.append(entry_price); hlines_colors.append('blue')
                
            hlines_kwargs = {}
            if hlines_list:
                hlines_kwargs = dict(hlines=dict(hlines=hlines_list, colors=hlines_colors, linestyle='--', linewidths=1.0))

            mc = mpf.make_marketcolors(up='green', down='red', inherit=True)
            s = mpf.make_mpf_style(marketcolors=mc, gridstyle=':', y_on_right=True)
            
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            
            vkwargs = {'volume': True} if 'volume' in plot_df.columns else {}
            
            mpf.plot(plot_df, type='candle', addplot=apds, style=s,
                     title=f"Trade {direction} ({entry_time.strftime('%H:%M')} - {exit_time.strftime('%H:%M')})", 
                     savefig=dict(fname=filepath, dpi=120, bbox_inches='tight'), 
                     **hlines_kwargs, **vkwargs)
                     
            return True
        except Exception as e:
            logging.error(f"Error marking chart points: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return False
            
    except Exception as e:
        logging.error(f"Failed generating trade chart: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return False

