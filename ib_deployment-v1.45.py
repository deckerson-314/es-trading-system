# ib_deployment.py - Bollinger Band Live Trading with IB (REAL ORDERS + REAL PNL)
# =============================================================================
# REVISION: 1.45
# =============================================================================
# Revision History (Last 10):
# ------------------------------------------------
# 1.45 - Fixed syntax error: 'a' → 'else'
# 1.44 - Fixed execDetailsEvent
# 1.43 - REAL ORDERS + REAL PNL
# 1.42 - useRTH=False
# =============================================================================

import os
import pandas as pd
import numpy as np
import logging
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, time
from threading import Timer
from ib_insync import IB, Future, util, LimitOrder, StopOrder
from dotenv import load_dotenv
import asyncio
import warnings
import pytz

# Suppress pandas FutureWarning
warnings.filterwarnings("ignore", category=FutureWarning)

# Load .env
load_dotenv()

EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_TO   = os.getenv('EMAIL_TO')
EMAIL_PWD  = os.getenv('EMAIL_PASSWORD')

if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PWD]):
    raise RuntimeError("Missing Gmail credentials in .env")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('ib_deployment.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Print Revision
REVISION = "1.45"
logging.info(f"Starting ib_deployment.py - REVISION {REVISION}")

# Load Parameters
PARAM_CSV = r'Bollinger\parameters\BB_Strategy_Parameters_optimized.csv'

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
            d[name] = int(float(val))
        else:
            d[name] = val
    return d

params = load_params(PARAM_CSV)
logging.info(f"Loaded {len(params)} parameters from {PARAM_CSV}")

# Print Parameters (for double-check)
logging.info("\n=== LOADED PARAMETERS ===")
for name, value in params.items():
    logging.info(f"{name:45} = {value}")

# Extract Parameters
max_open_trades       = params.get('Max Open Trades', 1)
enable_long           = params.get('Enable Long Trades', True)
enable_short          = params.get('Enable Short Trades', True)
bb_length             = params.get('Bollinger Band Length', 30)
bb_stddev             = params.get('Bollinger Band StdDev', 2.0)
long_wick_touch       = params.get('Long Entry on Wick Touch', False)
long_body_zone        = params.get('Long Entry on Body in Zone', True)
long_trigger_pct      = params.get('Long Trigger (% From Lower Band)', 0.0)
short_wick_touch      = params.get('Short Entry on Wick Touch', False)
short_body_zone       = params.get('Short Entry on Body in Zone', True)
short_trigger_pct     = params.get('Short Trigger (% From Upper Band)', 0.0)
initial_sl_pct        = params.get('Initial Stop Loss (%)', 0.5)
enable_trailing       = params.get('Enable Trailing Stop', True)
atr_length_ts         = params.get('ATR Length for Trailing Stop', 26)
atr_mult_ts           = params.get('ATR Multiplier for Trailing Stop', 3.0)
opposite_bb_tp        = params.get('Opposite Bollinger Band TP', False)
fixed_atr_tp          = params.get('Fixed ATR TP', False)
fixed_bb_entry_tp     = params.get('Fixed BB at Entry TP', True)
atr_length_tp         = params.get('ATR Length for TP', 26)
atr_mult_tp           = params.get('ATR Multiplier for TP', 2.0)
min_atr_points        = params.get('Min ATR Filter (Points)', 10.0)
enable_rth_filter     = params.get('Enable RTH Filter', True)
rth_start_str         = params.get('RTH Start (HH:MM)', '09:30')
rth_end_str           = params.get('RTH End (HH:MM)', '16:00')
min_volume_multiplier = params.get('Min Volume Multiplier', 1.5)
timeframe             = max(1, int(params.get('Timeframe (minutes)', 1)))
trailing_delay        = max(0, int(params.get('Trailing Delay (bars)', 5)))

# RTH parse
def parse_time(s):
    try:
        return datetime.strptime(s, '%H:%M').time()
    except:
        logging.warning(f"Bad time '{s}', using 09:30")
        return time(9, 30)

rth_start = parse_time(rth_start_str)
rth_end   = parse_time(rth_end_str)

# Email Alert
def send_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_FROM, EMAIL_PWD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        logging.info(f"Email sent: {subject}")
    except Exception as e:
        logging.error(f"Email failed: {e}")

# 15-min Status Timer
class StatusTimer:
    def __init__(self):
        self.timer = None
    def _report(self):
        pnl = sum((data['close'].iloc[-1] - p['entry_price']) * p['direction'] * 50
                  for p in positions)
        msg = f"Status: {len(positions)} open position(s)\nUnrealized PNL: ${pnl:,.2f}"
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
positions = []
data = pd.DataFrame(columns=['open','high','low','close','volume'])
bar_count = 0
active_order = None

# === REAL ORDER EXECUTION ===
def place_bracket_order(direction, entry_price, stop_price, tp_price):
    global active_order
    if active_order:
        ib.cancelOrder(active_order)
        ib.sleep(1)

    qty = 1
    action = 'BUY' if direction == 1 else 'SELL'

    # === ROUND TO 0.25 (ES TICK SIZE) ===
    entry_price = round(entry_price * 4) / 4
    stop_price = round(stop_price * 4) / 4
    tp_price = round(tp_price * 4) / 4

    parent = LimitOrder(
        action=action,
        totalQuantity=qty,
        lmtPrice=entry_price,
        tif='DAY',
        transmit=False
    )

    stop = StopOrder(
        action='SELL' if direction == 1 else 'BUY',
        totalQuantity=qty,
        stopPrice=stop_price,
        parentId=parent.orderId,
        tif='DAY',
        transmit=False
    )

    tp = LimitOrder(
        action='SELL' if direction == 1 else 'BUY',
        totalQuantity=qty,
        lmtPrice=tp_price,
        parentId=parent.orderId,
        tif='DAY',
        transmit=True
    )

    ib.placeOrder(contract, parent)
    ib.placeOrder(contract, stop)
    ib.placeOrder(contract, tp)

    active_order = parent
    logging.info(f"REAL BRACKET ORDER PLACED: {action} {qty} @ {entry_price:.2f} | SL: {stop_price:.2f} | TP: {tp_price:.2f}")

# === TRADE FILL CALLBACK ===
def on_exec_details(reqId, contract, execution):
    if execution.side in ['BOT', 'SLD']:
        fill_price = execution.price
        action = 'BUY' if execution.side == 'BOT' else 'SELL'
        pnl = (fill_price - execution.avgPrice) * (1 if action == 'BUY' else -1) * 50
        logging.info(f"TRADE FILLED: {action} @ {fill_price:.2f} | PNL: ${pnl:,.2f}")
        send_email("BB Strategy - TRADE FILLED", f"PNL: ${pnl:,.2f}")

# Real-Time Bar Handler
def on_bar_update(bars, hasNewBar):
    global data, bar_count
    if not hasNewBar:
        return
    bar = bars[-1]
    new_row = pd.Series({
        'datetime': bar.time,
        'open'    : bar.open_,
        'high'    : bar.high,
        'low'     : bar.low,
        'close'   : bar.close,
        'volume'  : bar.volume
    })
    data = pd.concat([data, new_row.to_frame().T]).set_index('datetime')
    bar_count += 1

    logging.info(f"Bar received: {bar.time.strftime('%H:%M:%S')} | O: {bar.open_:.2f} H: {bar.high:.2f} L: {bar.low:.2f} C: {bar.close:.2f} | Vol: {bar.volume}")

    update_indicators()
    check_entries(bar.time, new_row)
    check_exits(bar.time, new_row)

# Indicators & Filters
def update_indicators():
    data['mid']   = data['close'].rolling(bb_length).mean()
    data['std']   = data['close'].rolling(bb_length).std()
    data['upper'] = data['mid'] + data['std'] * bb_stddev
    data['lower'] = data['mid'] - data['std'] * bb_stddev

    high_low   = data['high'] - data['low']
    high_close = (data['high'] - data['close'].shift()).abs()
    low_close  = (data['low']  - data['close'].shift()).abs()

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    tr = tr.dropna()

    if len(tr) == 0:
        return

    data['atr_ts'] = tr.rolling(atr_length_ts).mean()

    latest = data.iloc[-1]
    data.at[data.index[-1], 'volume_filter'] = latest['volume'] >= data['volume'].rolling(50).mean().iloc[-1] * min_volume_multiplier
    data.at[data.index[-1], 'atr_filter']    = latest['atr_ts'] >= min_atr_points
    cur_time = data.index[-1].time()
    data.at[data.index[-1], 'in_rth'] = cur_time >= rth_start and cur_time <= rth_end if enable_rth_filter else True

# Entry Logic
def check_entries(idx, row):
    if len(positions) >= max_open_trades or active_order:
        return

    latest = data.iloc[-1]
    if not (latest['in_rth'] and latest['atr_filter'] and latest['volume_filter']):
        return

    enter_long = enter_short = False
    if enable_long:
        trig = data['lower'].iloc[-1] * (1 - long_trigger_pct / 100)
        if (long_wick_touch and row['low'] <= trig) or (long_body_zone and row['close'] <= trig):
            enter_long = True
    if enable_short:
        trig = data['upper'].iloc[-1] * (1 + short_trigger_pct / 100)
        if (short_wick_touch and row['high'] >= trig) or (short_body_zone and row['close'] >= trig):
            enter_short = True

    if not (enter_long or enter_short):
        return

    direction = 1 if enter_long else -1
    entry = row['close']
    stop  = entry * (1 - direction * initial_sl_pct / 100)
    tp    = data['upper'].iloc[-1] if direction == 1 else data['lower'].iloc[-1]

    place_bracket_order(direction, entry, stop, tp)

    tp_str = f"{tp:.2f}" if tp is not None else "None"
    msg = (f"TRADE OPEN - {'LONG' if direction==1 else 'SHORT'}\n"
           f"Entry: {entry:.2f}\nStop: {stop:.2f}\nTP: {tp_str}")
    send_email("BB Strategy - Trade OPEN", msg)

    if len(positions) == 1:
        status_timer.start()

# Exit Logic
def check_exits(idx, row):
    for pos in positions[:]:
        dir_ = pos['direction']
        if dir_ == 1:
            pos['max_high'] = max(pos['max_high'], row['high'])
        else:
            pos['min_low'] = min(pos['min_low'], row['low'])

        pos['bars_held'] += 1

        if enable_trailing and pos['bars_held'] >= trailing_delay:
            atr = data['atr_ts'].iloc[-1]
            if dir_ == 1:
                new_stop = pos['max_high'] - atr * atr_mult_ts
                pos['stop'] = max(pos['stop'], new_stop)
            else:
                new_stop = pos['min_low'] + atr * atr_mult_ts
                pos['stop'] = min(pos['stop'], new_stop)

        pos['stop_history'].append((idx, pos['stop']))

        cand = []
        if dir_ == 1 and row['low'] <= pos['stop']:
            cand.append(('Stop', pos['stop']))
        elif dir_ == -1 and row['high'] >= pos['stop']:
            cand.append(('Stop', pos['stop']))
        if opposite_bb_tp:
            if dir_ == 1 and row['high'] >= data['upper'].iloc[-1]:
                cand.append(('TP Opp BB', data['upper'].iloc[-1]))
            if dir_ == -1 and row['low'] <= data['lower'].iloc[-1]:
                cand.append(('TP Opp BB', data['lower'].iloc[-1]))
        if fixed_atr_tp and pos['tp'] is not None:
            if dir_ == 1 and row['high'] >= pos['tp']:
                cand.append(('TP ATR', pos['tp']))
            if dir_ == -1 and row['low'] <= pos['tp']:
                cand.append(('TP ATR', pos['tp']))
        if fixed_bb_entry_tp and pos['tp'] is not None:
            if dir_ == 1 and row['high'] >= pos['tp']:
                cand.append(('TP BB', pos['tp']))
            if dir_ == -1 and row['low'] <= pos['tp']:
                cand.append(('TP BB', pos['tp']))

        if cand:
            cand.sort(key=lambda x: abs(x[1] - pos['entry_price']))
            reason, price = cand[0]
            pnl = (price - pos['entry_price']) * dir_ * 50
            msg = (f"TRADE CLOSE - {'LONG' if dir_==1 else 'SHORT'}\n"
                   f"Exit: {price:.2f}\nReason: {reason}\nPNL: {pnl:,.2f}")
            send_email("BB Strategy - Trade CLOSE", msg)
            logging.info(msg.replace('\n', ' | '))
            pos.update({'exit_time': idx, 'exit_price': price, 'pnl': pnl, 'reason': reason})
            positions.remove(pos)

            if not positions:
                status_timer.stop()

# Main
async def main():
    logging.info("Connecting to TWS (paper port 7497)...")
    await ib.connectAsync('127.0.0.1', 7497, clientId=100)

    generic_contract = Future(symbol='ES', exchange='CME', currency='USD')
    contracts = await ib.reqContractDetailsAsync(generic_contract)
    
    if not contracts:
        logging.error("No ES contracts found!")
        raise RuntimeError("ES data not accessible")

    global contract
    contract = sorted(contracts, key=lambda c: c.contract.lastTradeDateOrContractMonth)[0].contract
    logging.info(f"Using ES: {contract.localSymbol} | Exp: {contract.lastTradeDateOrContractMonth}")

    logging.info("Fetching 90 minutes of historical 1-min bars (including overnight)...")
    hist_bars = ib.reqHistoricalData(
        contract,
        endDateTime='',
        durationStr='5400 S',
        barSizeSetting='1 min',
        whatToShow='TRADES',
        useRTH=False,
        formatDate=1
    )

    global data, bar_count
    if hist_bars:
        hist_df = util.df(hist_bars)
        hist_df = hist_df[['date', 'open', 'high', 'low', 'close', 'volume']]
        hist_df.rename(columns={'date': 'datetime'}, inplace=True)
        hist_df.set_index('datetime', inplace=True)
        data = hist_df.copy()
        bar_count = len(data)
        logging.info(f"Pre-filled with {bar_count} historical bars. Latest: {data.index[-1]}")
        update_indicators()
    else:
        logging.warning("No historical data received. Starting from scratch.")

    # === SUBSCRIBE TO TRADE FILLS ===
    ib.execDetailsEvent += on_exec_details

    bars = ib.reqRealTimeBars(contract, 60, 'TRADES', False)
    bars.updateEvent += on_bar_update

    logging.info("REAL TRADING MODE ACTIVE — ORDERS WILL BE PLACED IN TWS")
    await asyncio.Event().wait()

if __name__ == '__main__':
    util.patchAsyncio()
    ib.run(main())