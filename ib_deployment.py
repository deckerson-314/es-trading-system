# ib_deployment.py - FINAL 2.13 — ORIGINAL STRATEGY + 1-MIN BARS + LIVE TRADING
# =============================================================================
# Revision History (Last 10):
# ------------------------------------------------
# 2.13 - Fixed NameError in on_bar_update by using new_row in check_exits call
# 2.12 - Fixed bracketOrder by adding limitPrice=0.0 for market entry; improved PNL logging in check_exits
# 2.11 - Fixed bracket order placement using BracketOrder; added retry for contract resolution; improved error handling and logging
# 2.10 - Fixed bracket order creation using ib.bracketOrder; handle trailing modifies; log PNL summaries to console; clean exit on interrupt
# 2.09 - Added live trading with bracket orders; handle fills and modifies; qualified contract; suppressed warnings
# 2.08 - Fixed BarData attribute access (open instead of open_) for reqHistoricalData bars
# 2.07 - Cast rolling window parameters to int to fix ValueError in pandas rolling
# 2.06 - Fixed timezone handling for historical and real-time bars using tz_convert and astimezone
# 2.05 - Updated exchange to 'CME' for ES futures resolution; safer date comparisons
# 2.04 - Added missing functions, fixed ATR TP, improved efficiency and timezone handling, switched to keepUpToDate for proper 1-min bars
# =============================================================================
import os
import pandas as pd
import numpy as np
import logging
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, time, date, timedelta
from threading import Timer
from ib_insync import IB, Future, util, BracketOrder
from dotenv import load_dotenv
import asyncio
import warnings
import pytz
import signal
import time as time_module  # Renamed to avoid conflict with datetime.time
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
load_dotenv()
EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_TO = os.getenv('EMAIL_TO')
EMAIL_PWD = os.getenv('EMAIL_PASSWORD')
if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PWD]):
    raise RuntimeError("Missing Gmail credentials in .env")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('ib_deployment.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
REVISION = "2.13"
logging.info(f"Starting ib_deployment.py - REVISION {REVISION}")
# =============================================================================
# PARAM FILE CHANGE AS REQUESTED
# =============================================================================
PARAM_CSV = r'Bollinger\parameters\BB_Strategy_Parameters_optimized_TWS.csv'
def load_params(csv_path):
    df = pd.read_csv(csv_path)
    d = {}
    for _, r in df.iterrows():
        name, val = r['Name'].strip(), r['Value']
        if isinstance(val, str):
            val = val.strip()
        if val in ('true', 'false'):
            d[name] = (val == 'true')
        elif str(val).lstrip('-').replace('.', '', 1).isdigit():
            d[name] = float(val)
        else:
            d[name] = val
    return d
params = load_params(PARAM_CSV)
logging.info(f"Loaded {len(params)} parameters from {PARAM_CSV}")
# =============================================================================
# DISPLAY PARAMETERS AS REQUESTED
# =============================================================================
logging.info("\n=== LOADED PARAMETERS ===")
for name, value in sorted(params.items()):
    logging.info(f"{name:45} = {value}")
# Extract Parameters (100% original — no changes)
max_open_trades = params.get('Max Open Trades', 1)
enable_long = params.get('Enable Long Trades', True)
enable_short = params.get('Enable Short Trades', True)
bb_length = int(params.get('Bollinger Band Length', 30))
bb_stddev = params.get('Bollinger Band StdDev', 2.0)
long_wick_touch = params.get('Long Entry on Wick Touch', False)
long_body_zone = params.get('Long Entry on Body in Zone', True)
long_trigger_pct = params.get('Long Trigger (% From Lower Band)', 0.0)
short_wick_touch = params.get('Short Entry on Wick Touch', False)
short_body_zone = params.get('Short Entry on Zone', True)
short_trigger_pct = params.get('Short Trigger (% From Upper Band)', 0.0)
initial_sl_pct = params.get('Initial Stop Loss (%)', 0.5)
enable_trailing = params.get('Enable Trailing Stop', True)
atr_length_ts = int(params.get('ATR Length for Trailing Stop', 26))
atr_mult_ts = params.get('ATR Multiplier for Trailing Stop', 3.0)
opposite_bb_tp = params.get('Opposite Bollinger Band TP', False)
fixed_atr_tp = params.get('Fixed ATR TP', False)
fixed_bb_entry_tp = params.get('Fixed BB at Entry TP', True)
atr_length_tp = int(params.get('ATR Length for TP', 26))
atr_mult_tp = params.get('ATR Multiplier for TP', 2.0)
min_atr_points = params.get('Min ATR Filter (Points)', 10.0)
enable_rth_filter = params.get('Enable RTH Filter', True)
rth_start_str = params.get('RTH Start (HH:MM)', '09:30')
rth_end_str = params.get('RTH End (HH:MM)', '16:00')
min_volume_multiplier = params.get('Min Volume Multiplier', 1.5)
trailing_delay = max(0, int(params.get('Trailing Delay (bars)', 5)))
# RTH parse
def parse_time(s):
    try:
        return datetime.strptime(s, '%H:%M').time()
    except:
        logging.warning(f"Bad time '{s}', using 09:30")
        return time(9, 30)
rth_start = parse_time(rth_start_str)
rth_end = parse_time(rth_end_str)
# 15-min Status Timer
class StatusTimer:
    def __init__(self):
        self.timer = None
    def _report(self):
        positions_list = ib.positions()
        pnl = sum(pos.unrealizedPNL for pos in positions_list if pos.contract.symbol == 'ES')
        msg = f"Status: {len(positions_list)} open position(s)\nUnrealized PNL: ${pnl:,.2f}"
        logging.info(msg)  # Log to console
        send_email("BB Strategy - 15-min Status", msg)
        self.start()
    def start(self):
        if self.timer:
            self.timer.cancel()
        self.timer = Timer(900, self._report)
        self.timer.start()
    def stop(self):
        if self.timer:
            self.timer.cancel()
status_timer = StatusTimer()
# Global State
ib = IB()
positions = []  # List of BracketOrder objects for open positions
data = pd.DataFrame(columns=['open','high','low','close','volume'])
bar_count = 0
bars = None
contract = None
# Define missing functions
def send_email(subject, body):
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_FROM, EMAIL_PWD)
            server.send_message(msg)
        logging.info(f"Email sent: {subject}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")
def get_front_es_contract():
    for attempt in range(3):  # Retry up to 3 times
        try:
            temp_contract = Future('ES', '', 'CME', currency='USD')
            cds = ib.reqContractDetails(temp_contract)
            if not cds:
                raise ValueError("No ES contracts found")
            today = datetime.now().date()
            # Customary ES roll happens 8 days before expiration (3rd Friday)
            roll_cutoff = today + timedelta(days=8)
            future_cds = [cd for cd in cds if datetime.strptime(cd.contract.lastTradeDateOrContractMonth, '%Y%m%d').date() > roll_cutoff]
            if not future_cds:
                # Fallback to absolute front if no future contracts meetings criteria
                front_contract_details = sorted(cds, key=lambda cd: datetime.strptime(cd.contract.lastTradeDateOrContractMonth, '%Y%m%d'))[0]
                front = front_contract_details
            else:
                front = min(future_cds, key=lambda cd: datetime.strptime(cd.contract.lastTradeDateOrContractMonth, '%Y%m%d'))
            ib.qualifyContracts(front.contract)
            logging.info(f"Resolved front ES contract: {front.contract.conId} exp {front.contract.lastTradeDateOrContractMonth}")
            return front.contract
        except Exception as e:
            logging.error(f"Failed to resolve contract on attempt {attempt+1}: {e}")
            time_module.sleep(5)  # Wait before retry
    raise ValueError("Failed to resolve ES contract after retries")
def cancel_all_pending():
    ib.reqGlobalCancel()
    logging.info("Cancelled all pending orders")
# Real-Time Bar Handler
def on_bar_update(bars, hasNewBar):
    global data, bar_count
    if not hasNewBar:
        return
    bar = bars[-1]
    new_row = pd.Series({
        'open' : bar.open,
        'high' : bar.high,
        'low' : bar.low,
        'close' : bar.close,
        'volume' : bar.volume
    }, name=bar.date.astimezone(pytz.timezone('US/Eastern')))
    data = data._append(new_row)
    bar_count += 1
    logging.info(f"Bar received: {bar.date.strftime('%H:%M:%S')} | O: {bar.open:.2f} H: {bar.high:.2f} L: {bar.low:.2f} C: {bar.close:.2f} | Vol: {bar.volume}")
    update_indicators()
    check_entries(data.index[-1], new_row)
    check_exits(data.index[-1], new_row)
# Indicators & Filters
def update_indicators():
    data['mid'] = data['close'].rolling(bb_length).mean()
    data['std'] = data['close'].rolling(bb_length).std()
    data['upper'] = data['mid'] + data['std'] * bb_stddev
    data['lower'] = data['mid'] - data['std'] * bb_stddev
    high_low = data['high'] - data['low']
    high_close = (data['high'] - data['close'].shift()).abs()
    low_close = (data['low'] - data['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    tr = tr.dropna()
    if len(tr) == 0:
        return
    data['atr_ts'] = tr.rolling(atr_length_ts).mean()
    if fixed_atr_tp:
        data['atr_tp'] = tr.rolling(atr_length_tp).mean()
    latest = data.iloc[-1]
    vol_mean = data['volume'].rolling(50).mean().iloc[-1]
    if pd.isna(vol_mean):
        data.at[data.index[-1], 'volume_filter'] = False
    else:
        data.at[data.index[-1], 'volume_filter'] = latest['volume'] >= vol_mean * min_volume_multiplier
    data.at[data.index[-1], 'atr_filter'] = latest['atr_ts'] >= min_atr_points if 'atr_ts' in latest else False
    cur_idx = data.index[-1]
    tz = pytz.timezone('US/Eastern')
    cur_time = cur_idx.astimezone(tz).time()
    data.at[data.index[-1], 'in_rth'] = (cur_time >= rth_start and cur_time <= rth_end) if enable_rth_filter else True
# Entry Logic
def check_entries(idx, new_row):
    if len(positions) >= max_open_trades:
        return
    latest = data.iloc[-1]
    if not (latest['in_rth'] and latest['atr_filter'] and latest['volume_filter']):
        return
    enter_long = enter_short = False
    if enable_long:
        trig = data['lower'].iloc[-1] * (1 - long_trigger_pct / 100)
        if (long_wick_touch and new_row['low'] <= trig) or (long_body_zone and new_row['close'] <= trig):
            enter_long = True
    if enable_short:
        trig = data['upper'].iloc[-1] * (1 + short_trigger_pct / 100)
        if (short_wick_touch and new_row['high'] >= trig) or (short_body_zone and new_row['close'] >= trig):
            enter_short = True
    if not (enter_long or enter_short):
        return
    direction = 1 if enter_long else -1
    action = 'BUY' if direction == 1 else 'SELL'
    qty = 1  # Assuming 1 contract; adjust as needed
    stop_price = new_row['close'] * (1 - direction * initial_sl_pct / 100)
    tp = None
    if fixed_atr_tp and 'atr_tp' in data.columns:
        atr_val = data['atr_tp'].iloc[-1]
        if not pd.isna(atr_val):
            tp = new_row['close'] + direction * atr_val * atr_mult_tp
    elif fixed_bb_entry_tp:
        tp = data['upper'].iloc[-1] if direction == 1 else data['lower'].iloc[-1]
    bracket = ib.bracketOrder(action, qty, limitPrice=0.0, stopLossPrice=stop_price, takeProfitPrice=tp)
    for o in bracket:
        ib.placeOrder(contract, o)
    positions.append(bracket)
    tp_str = f"{tp:.2f}" if tp is not None else "None"
    msg = (f"TRADE OPEN - {'LONG' if direction==1 else 'SHORT'}\n"
           f"Entry Order ID: {bracket.entry.permId}\nStop: {stop_price:.2f}\nTP: {tp_str}")
    send_email("BB Strategy - Trade OPEN", msg)
    logging.info(msg.replace('\n', ' | '))
    if len(positions) == 1:
        status_timer.start()
# Exit Logic (for manual closes or trailing updates)
def check_exits(idx, new_row):
    for bracket in positions[:]:
        entry_trade = ib.trades()[bracket.entry.permId] if bracket.entry.permId in [t.order.permId for t in ib.trades()] else None
        if not entry_trade or entry_trade.isActive():
            continue
        # Get direction from entry
        fill = entry_trade.fills[0].execution if entry_trade.fills else None
        if not fill:
            continue
        dir_ = 1 if fill.side == 'BOT' else -1
        # Trailing stop update if enabled and after delay
        if enable_trailing and bar_count >= trailing_delay:
            stop_order = bracket.stopLoss  # Stop loss order in bracket
            if stop_order.isActive():
                atr = data['atr_ts'].iloc[-1]
                peak = new_row['high'] if dir_ == 1 else new_row['low']
                new_stop = peak - dir_ * atr * atr_mult_ts
                current_stop = stop_order.auxPrice
                if (dir_ == 1 and new_stop > current_stop) or (dir_ == -1 and new_stop < current_stop):
                    stop_order.auxPrice = new_stop
                    ib.placeOrder(contract, stop_order)
                    logging.info(f"Updated trailing stop for trade {bracket.entry.permId} to {new_stop:.2f}")
        # Check if position closed
        if not any(t.contract.conId == contract.conId for t in ib.positions()):
            pnl = sum(f.realizedPNL for f in entry_trade.fills)
            reason = 'TP' if bracket.takeProfit.filled() else 'Stop' if bracket.stopLoss.filled() else 'Unknown'
            exit_price = bracket.takeProfit.avgFillPrice if bracket.takeProfit.filled() else bracket.stopLoss.avgFillPrice
            msg = (f"TRADE CLOSE - {'LONG' if dir_==1 else 'SHORT'}\n"
                   f"Exit: {exit_price:.2f}\nReason: {reason}\nPNL: {pnl:,.2f}")
            send_email("BB Strategy - Trade CLOSE", msg)
            logging.info(msg.replace('\n', ' | '))
            positions.remove(bracket)
            if not positions:
                status_timer.stop()
# Ensure connected and subscribed
def ensure_connected_and_subscribed():
    global contract, bars, data, bar_count
    if not ib.isConnected():
        logging.warning("RECONNECTING TO TWS...")
        ib.connect('127.0.0.1', 7497, clientId=100)
        ib.sleep(3)
    if contract is None:
        contract = get_front_es_contract()
    if bars:
        bars.updateEvent -= on_bar_update
        ib.cancelHistoricalData(bars)
        bars = None
        ib.sleep(1)
    bars = ib.reqHistoricalData(
        contract,
        endDateTime='',
        durationStr='5400 S',
        barSizeSetting='1 min',
        whatToShow='TRADES',
        useRTH=False,
        formatDate=1,
        keepUpToDate=True
    )
    hist_df = util.df(bars)
    if hist_df is not None and not hist_df.empty:
        hist_df.rename(columns={'date': 'datetime'}, inplace=True)
        hist_df['datetime'] = pd.to_datetime(hist_df['datetime']).dt.tz_convert('US/Eastern')
        hist_df.set_index('datetime', inplace=True)
        data = hist_df[['open', 'high', 'low', 'close', 'volume']].copy()  # Copy to avoid SettingWithCopy
        bar_count = len(data)
        logging.info(f"PRE-FILLED WITH {bar_count} HISTORICAL 1-MIN BARS. LATEST: {data.index[-1]}")
        update_indicators()
    else:
        logging.warning("NO INITIAL HISTORICAL DATA.")
    bars.updateEvent += on_bar_update
    logging.info("REAL-TIME 1-MIN BARS SUBSCRIBED VIA KEEPUPTODATE")
# Clean exit handler
def clean_exit(signum, frame):
    logging.info("Interrupt received, shutting down...")
    status_timer.stop()
    if ib.isConnected():
        ib.disconnect()
    exit(0)
signal.signal(signal.SIGINT, clean_exit)
signal.signal(signal.SIGTERM, clean_exit)
# MAIN LOOP — NO MORE ib.run(watchdog()) CRASH
async def main():
    global contract
    await ib.connectAsync('127.0.0.1', 7497, clientId=100)
    contract = get_front_es_contract()
    cancel_all_pending()
    ensure_connected_and_subscribed()
    # This is the correct way — no crash on disconnect
    while True:
        if not ib.isConnected():
            ensure_connected_and_subscribed()
        await asyncio.sleep(10)
if __name__ == '__main__':
    util.patchAsyncio()
    asyncio.run(main())