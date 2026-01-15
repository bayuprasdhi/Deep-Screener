import streamlit as st
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import time
import requests

st.set_page_config(page_title="SCALPIFY V1", layout="wide", page_icon="🚀")

st.title("🚀 SCALPIFY - Smart Trading Screener V1")
st.markdown("**Bybit Perpetual Futures Scanner**")

st.sidebar.header("⚙️ Configuration")

timeframe = st.sidebar.selectbox(
    "Timeframe",
    options=['1m', '5m', '15m', '30m', '1h', '4h'],
    index=2
)

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Slow Signal (Trend)")
slow_fast = st.sidebar.number_input("Fast MA", value=70, min_value=1, max_value=200, key="slow_fast")
slow_slow = st.sidebar.number_input("Slow MA", value=110, min_value=1, max_value=200, key="slow_slow")
slow_signal = st.sidebar.number_input("Signal", value=9, min_value=1, max_value=50, key="slow_signal")
slow_avg = st.sidebar.number_input("Power Level Length", value=400, min_value=1, max_value=500, key="slow_avg")
slow_mult = st.sidebar.number_input("Power Level Mult", value=0.6, min_value=0.1, max_value=5.0, step=0.1, key="slow_mult")

st.sidebar.markdown("---")
st.sidebar.subheader("⚡ Fast Signal (Pullback)")
fast_fast = st.sidebar.number_input("Fast MA", value=7, min_value=1, max_value=200, key="fast_fast")
fast_slow = st.sidebar.number_input("Slow MA", value=11, min_value=1, max_value=200, key="fast_slow")
fast_signal = st.sidebar.number_input("Signal", value=9, min_value=1, max_value=50, key="fast_signal")

st.sidebar.markdown("---")
st.sidebar.subheader("🔄 Auto Refresh")
enable_auto_refresh = st.sidebar.checkbox("Enable Auto Refresh", value=False)
refresh_interval = st.sidebar.slider("Refresh Interval (minutes)", min_value=5, max_value=60, value=15, step=5)

st.sidebar.markdown("---")
st.sidebar.subheader("📱 Telegram Alert")
telegram_token = st.sidebar.text_input("Bot Token", type="password", help="Get from @BotFather")
telegram_chat_id = st.sidebar.text_input("Chat ID", help="Get from @userinfobot")
enable_alerts = st.sidebar.checkbox("Enable Telegram Alerts", value=False)

if 'last_update' not in st.session_state:
    st.session_state.last_update = None
if 'momentum_bull' not in st.session_state:
    st.session_state.momentum_bull = []
if 'momentum_bear' not in st.session_state:
    st.session_state.momentum_bear = []
if 'pullback_bull' not in st.session_state:
    st.session_state.pullback_bull = []
if 'pullback_bear' not in st.session_state:
    st.session_state.pullback_bear = []
if 'continuation_bull' not in st.session_state:
    st.session_state.continuation_bull = []
if 'continuation_bear' not in st.session_state:
    st.session_state.continuation_bear = []

def calculate_signal(df, fast, slow, signal):
    exp1 = df['close'].ewm(span=fast, adjust=False).mean()
    exp2 = df['close'].ewm(span=slow, adjust=False).mean()
    signal_line = exp1 - exp2
    return signal_line

def calculate_power_level(signal_line, avg_length, multiplier):
    abs_signal = signal_line.abs()
    avg_signal = abs_signal.rolling(window=avg_length).mean()
    power_level = avg_signal * multiplier
    return power_level.iloc[-1] if not power_level.empty else 0

def get_signal_color(current, previous):
    if current > 0:
        return 'lime' if current > previous else 'green'
    else:
        return 'maroon' if current < previous else 'red'

def get_htf_timeframes(ltf):
    htf_map = {
        '1m': ['5m', '15m'],
        '5m': ['15m', '30m'],
        '15m': ['1h', '4h'],
        '30m': ['1h', '4h'],
        '1h': ['4h', '1d'],
        '4h': ['1d', '1w']
    }
    return htf_map.get(ltf, ['1h', '4h'])

def send_telegram_alert(message):
    if not enable_alerts or not telegram_token or not telegram_chat_id:
        return
    
    try:
        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        data = {
            "chat_id": telegram_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, data=data, timeout=5)
    except:
        pass

def check_htf_alignment(exchange, symbol, tf_list, is_bullish):
    aligned_count = 0
    for htf in tf_list:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, htf, limit=600)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            slow_line = calculate_signal(df, slow_fast, slow_slow, slow_signal)
            slow_current = slow_line.iloc[-1]
            slow_power = calculate_power_level(slow_line, slow_avg, slow_mult)
            
            if is_bullish and slow_current > slow_power:
                aligned_count += 1
            elif not is_bullish and slow_current < -slow_power:
                aligned_count += 1
                
            time.sleep(0.1)
        except:
            continue
    
    return aligned_count

def scan_market(exchange, tf, batch_size=10):
    momentum_bull_container = st.empty()
    momentum_bear_container = st.empty()
    pullback_bull_container = st.empty()
    pullback_bear_container = st.empty()
    continuation_bull_container = st.empty()
    continuation_bear_container = st.empty()
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        markets = exchange.load_markets()
        perpetual_pairs = [
            symbol for symbol, market in markets.items()
            if market.get('swap') and market.get('settle') == 'USDT' 
            and 'USDC' not in symbol and 'DAI' not in symbol
            and not any(char.isdigit() for char in symbol.split('/')[0])
        ]
        
        total_pairs = len(perpetual_pairs)
        status_text.text(f"Found {total_pairs} perpetual pairs to scan...")
        
        momentum_bull = []
        momentum_bear = []
        pullback_bull = []
        pullback_bear = []
        continuation_bull = []
        continuation_bear = []
        scanned = 0
        
        htf_list = get_htf_timeframes(tf)
        
        for i in range(0, total_pairs, batch_size):
            batch = perpetual_pairs[i:i+batch_size]
            
            for symbol in batch:
                try:
                    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=600)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    
                    slow_line = calculate_signal(df, slow_fast, slow_slow, slow_signal)
                    slow_current = slow_line.iloc[-1]
                    slow_prev = slow_line.iloc[-2]
                    slow_power = calculate_power_level(slow_line, slow_avg, slow_mult)
                    slow_color = get_signal_color(slow_current, slow_prev)
                    
                    fast_line = calculate_signal(df, fast_fast, fast_slow, fast_signal)
                    fast_current = fast_line.iloc[-1]
                    fast_prev = fast_line.iloc[-2]
                    fast_power = calculate_power_level(fast_line, slow_avg, slow_mult)
                    fast_color = get_signal_color(fast_current, fast_prev)
                    
                    is_momentum_bull = (slow_current > 0 and 
                                       slow_current > slow_power and 
                                       slow_color == 'lime')
                    
                    is_momentum_bear = (slow_current < 0 and 
                                       slow_current < -slow_power and 
                                       slow_color == 'maroon')
                    
                    if is_momentum_bull and len(momentum_bull) < 25:
                        momentum_bull.append(symbol)
                        if enable_alerts:
                            send_telegram_alert(
                                f"🟢 <b>MOMENTUM DETECTED</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Type: Bullish Breakout\n"
                                f"TF: {tf.upper()}\n"
                                f"Time: {datetime.now().strftime('%H:%M WIB')}"
                            )
                    
                    elif is_momentum_bear and len(momentum_bear) < 25:
                        momentum_bear.append(symbol)
                        if enable_alerts:
                            send_telegram_alert(
                                f"🔴 <b>MOMENTUM DETECTED</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Type: Bearish Breakout\n"
                                f"TF: {tf.upper()}\n"
                                f"Time: {datetime.now().strftime('%H:%M WIB')}"
                            )
                    
                    is_pullback_bull = (slow_current > slow_power and 
                                       slow_color in ['lime', 'green'] and
                                       fast_current < 0)
                    
                    is_pullback_bear = (slow_current < -slow_power and 
                                       slow_color in ['maroon', 'red'] and
                                       fast_current > 0)
                    
                    if is_pullback_bull and len(pullback_bull) < 25:
                        htf_aligned = check_htf_alignment(exchange, symbol, htf_list, True)
                        pullback_bull.append({
                            'symbol': symbol,
                            'htf_score': htf_aligned
                        })
                        if enable_alerts:
                            send_telegram_alert(
                                f"🎯 <b>PULLBACK ENTRY</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Type: Bullish Pullback\n"
                                f"HTF Confluence: {htf_aligned}/2\n"
                                f"TF: {tf.upper()}\n"
                                f"Action: Consider Long Entry\n"
                                f"Time: {datetime.now().strftime('%H:%M WIB')}"
                            )
                    
                    elif is_pullback_bear and len(pullback_bear) < 25:
                        htf_aligned = check_htf_alignment(exchange, symbol, htf_list, False)
                        pullback_bear.append({
                            'symbol': symbol,
                            'htf_score': htf_aligned
                        })
                        if enable_alerts:
                            send_telegram_alert(
                                f"🎯 <b>PULLBACK ENTRY</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Type: Bearish Pullback\n"
                                f"HTF Confluence: {htf_aligned}/2\n"
                                f"TF: {tf.upper()}\n"
                                f"Action: Consider Short Entry\n"
                                f"Time: {datetime.now().strftime('%H:%M WIB')}"
                            )
                    
                    is_continuation_bull = (slow_current > 0 and 
                                           slow_current > slow_power and 
                                           slow_color == 'lime' and
                                           fast_current > 0 and
                                           fast_current > fast_power and
                                           fast_color == 'lime')
                    
                    is_continuation_bear = (slow_current < 0 and 
                                           slow_current < -slow_power and 
                                           slow_color == 'maroon' and
                                           fast_current < 0 and
                                           fast_current < -fast_power and
                                           fast_color == 'maroon')
                    
                    if is_continuation_bull and len(continuation_bull) < 25:
                        continuation_bull.append(symbol)
                        if enable_alerts:
                            send_telegram_alert(
                                f"🚀 <b>CONTINUATION TREND</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Type: Bullish Continuation\n"
                                f"TF: {tf.upper()}\n"
                                f"Action: Strong Long Setup\n"
                                f"Time: {datetime.now().strftime('%H:%M WIB')}"
                            )
                    
                    elif is_continuation_bear and len(continuation_bear) < 25:
                        continuation_bear.append(symbol)
                        if enable_alerts:
                            send_telegram_alert(
                                f"🚀 <b>CONTINUATION TREND</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Type: Bearish Continuation\n"
                                f"TF: {tf.upper()}\n"
                                f"Action: Strong Short Setup\n"
                                f"Time: {datetime.now().strftime('%H:%M WIB')}"
                            )
                    
                    time.sleep(0.12)
                    
                except Exception as e:
                    continue
                
                scanned += 1
                progress = scanned / total_pairs
                progress_bar.progress(progress)
                status_text.text(
                    f"Scanning: {scanned}/{total_pairs} | "
                    f"Momentum: {len(momentum_bull)}🟢 {len(momentum_bear)}🔴 | "
                    f"Pullback: {len(pullback_bull)}🎯 {len(pullback_bear)}🎯 | "
                    f"Continuation: {len(continuation_bull)}🚀 {len(continuation_bear)}🚀"
                )
                
                if scanned % 10 == 0:
                    display_results(
                        momentum_bull, momentum_bear,
                        pullback_bull, pullback_bear,
                        continuation_bull, continuation_bear,
                        momentum_bull_container, momentum_bear_container,
                        pullback_bull_container, pullback_bear_container,
                        continuation_bull_container, continuation_bear_container
                    )
            
        progress_bar.progress(1.0)
        status_text.text(f"✅ Scan complete!")
        
        pullback_bull.sort(key=lambda x: x['htf_score'], reverse=True)
        pullback_bear.sort(key=lambda x: x['htf_score'], reverse=True)
        
        display_results(
            momentum_bull, momentum_bear,
            pullback_bull, pullback_bear,
            continuation_bull, continuation_bear,
            momentum_bull_container, momentum_bear_container,
            pullback_bull_container, pullback_bear_container,
            continuation_bull_container, continuation_bear_container
        )
        
        return momentum_bull, momentum_bear, pullback_bull, pullback_bear, continuation_bull, continuation_bear
        
    except Exception as e:
        st.error(f"Error during scan: {str(e)}")
        return [], [], [], [], [], []

def display_results(mom_bull, mom_bear, pull_bull, pull_bear, cont_bull, cont_bear,
                   mom_bull_cont, mom_bear_cont, pull_bull_cont, pull_bear_cont,
                   cont_bull_cont, cont_bear_cont):
    
    with mom_bull_cont.container():
        st.markdown("### 📊 MOMENTUM FINDER")
        st.markdown("#### 🟢 Bullish Breakout")
        if mom_bull:
            cols_per_row = 5
            for i in range(0, len(mom_bull), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    if i + j < len(mom_bull):
                        with col:
                            st.success(f"**{mom_bull[i+j]}**")
        else:
            st.info("No bullish momentum found")
    
    with mom_bear_cont.container():
        st.markdown("#### 🔴 Bearish Breakout")
        if mom_bear:
            cols_per_row = 5
            for i in range(0, len(mom_bear), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    if i + j < len(mom_bear):
                        with col:
                            st.error(f"**{mom_bear[i+j]}**")
        else:
            st.info("No bearish momentum found")
    
    st.markdown("---")
    
    with pull_bull_cont.container():
        st.markdown("### 🎯 PULLBACK ENTRY FINDER")
        st.markdown("#### 🟢 Bullish Pullback (HTF Sorted)")
        if pull_bull:
            cols_per_row = 5
            for i in range(0, len(pull_bull), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    if i + j < len(pull_bull):
                        pair_data = pull_bull[i+j]
                        symbol = pair_data['symbol']
                        score = pair_data['htf_score']
                        
                        if score == 2:
                            color_shade = "#00FF00"
                        elif score == 1:
                            color_shade = "#90EE90"
                        else:
                            color_shade = "#D3FFD3"
                        
                        with col:
                            st.markdown(
                                f'<div style="background-color: {color_shade}; '
                                f'padding: 10px; border-radius: 5px; text-align: center; '
                                f'font-weight: bold; color: black;">{symbol}</div>',
                                unsafe_allow_html=True
                            )
        else:
            st.info("No bullish pullback found")
    
    with pull_bear_cont.container():
        st.markdown("#### 🔴 Bearish Pullback (HTF Sorted)")
        if pull_bear:
            cols_per_row = 5
            for i in range(0, len(pull_bear), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    if i + j < len(pull_bear):
                        pair_data = pull_bear[i+j]
                        symbol = pair_data['symbol']
                        score = pair_data['htf_score']
                        
                        if score == 2:
                            color_shade = "#FF0000"
                        elif score == 1:
                            color_shade = "#FF6B6B"
                        else:
                            color_shade = "#FFB3B3"
                        
                        with col:
                            st.markdown(
                                f'<div style="background-color: {color_shade}; '
                                f'padding: 10px; border-radius: 5px; text-align: center; '
                                f'font-weight: bold; color: white;">{symbol}</div>',
                                unsafe_allow_html=True
                            )
        else:
            st.info("No bearish pullback found")
    
    st.markdown("---")
    
    with cont_bull_cont.container():
        st.markdown("### 🚀 CONTINUATION (FOLLOW TREND)")
        st.markdown("#### 🟢 Bullish Continuation")
        if cont_bull:
            cols_per_row = 5
            for i in range(0, len(cont_bull), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    if i + j < len(cont_bull):
                        with col:
                            st.success(f"**{cont_bull[i+j]}**")
        else:
            st.info("No bullish continuation found")
    
    with cont_bear_cont.container():
        st.markdown("#### 🔴 Bearish Continuation")
        if cont_bear:
            cols_per_row = 5
            for i in range(0, len(cont_bear), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    if i + j < len(cont_bear):
                        with col:
                            st.error(f"**{cont_bear[i+j]}**")
        else:
            st.info("No bearish continuation found")

col1, col2, col3 = st.columns([1, 2, 1])

with col1:
    if st.button("🔄 Refresh Now", type="primary", use_container_width=True):
        with st.spinner(f"Scanning {timeframe.upper()} timeframe..."):
            exchange = ccxt.gateio({'enableRateLimit': True})
            mom_bull, mom_bear, pull_bull, pull_bear, cont_bull, cont_bear = scan_market(exchange, timeframe)
            st.session_state.momentum_bull = mom_bull
            st.session_state.momentum_bear = mom_bear
            st.session_state.pullback_bull = pull_bull
            st.session_state.pullback_bear = pull_bear
            st.session_state.continuation_bull = cont_bull
            st.session_state.continuation_bear = cont_bear
            st.session_state.last_update = datetime.now()

with col2:
    if st.session_state.last_update:
        time_diff = (datetime.now() - st.session_state.last_update).total_seconds()
        next_refresh = refresh_interval * 60 - time_diff
        if enable_auto_refresh and next_refresh > 0:
            mins = int(next_refresh // 60)
            secs = int(next_refresh % 60)
            st.info(f"📅 Last: {st.session_state.last_update.strftime('%H:%M:%S')} | TF: {timeframe.upper()} | Next refresh: {mins}m {secs}s")
        else:
            st.info(f"📅 Last updated: {st.session_state.last_update.strftime('%Y-%m-%d %H:%M:%S')} | TF: {timeframe.upper()}")
    else:
        st.warning("Click Refresh Now to start scanning")

with col3:
    if enable_auto_refresh and st.session_state.last_update:
        time_diff = (datetime.now() - st.session_state.last_update).total_seconds()
        if time_diff >= refresh_interval * 60:
            st.rerun()

if (st.session_state.momentum_bull or st.session_state.momentum_bear or
    st.session_state.pullback_bull or st.session_state.pullback_bear or
    st.session_state.continuation_bull or st.session_state.continuation_bear):
    mom_bull_cont = st.empty()
    mom_bear_cont = st.empty()
    pull_bull_cont = st.empty()
    pull_bear_cont = st.empty()
    cont_bull_cont = st.empty()
    cont_bear_cont = st.empty()
    display_results(
        st.session_state.momentum_bull,
        st.session_state.momentum_bear,
        st.session_state.pullback_bull,
        st.session_state.pullback_bear,
        st.session_state.continuation_bull,
        st.session_state.continuation_bear,
        mom_bull_cont, mom_bear_cont,
        pull_bull_cont, pull_bear_cont,
        cont_bull_cont, cont_bear_cont
    )

st.markdown("---")
st.markdown("**SCALPIFY V1** | Rate limit compliant | Perpetual USDT pairs only")
