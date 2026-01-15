import streamlit as st
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import time
import requests
import gc

# Page config
st.set_page_config(page_title="SCALPIFY V1", layout="wide", page_icon="🚀")

# Title
st.title("🚀 SCALPIFY - Smart Trading Screener V1")
st.markdown("**Gate.io Perpetual Futures Scanner**")

# ========== SIDEBAR SETTINGS ==========
st.sidebar.header("⚙️ Configuration")

# Timeframe selection
timeframe = st.sidebar.selectbox(
    "Timeframe",
    options=['1m', '5m', '15m', '30m', '1h', '4h'],
    index=2  # default M15
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
st.sidebar.subheader("📱 Telegram Alert")
telegram_token = st.sidebar.text_input("Bot Token", type="password", help="Get from @BotFather")
telegram_chat_id = st.sidebar.text_input("Chat ID", help="Get from @userinfobot")
enable_alerts = st.sidebar.checkbox("Enable Telegram Alerts", value=False)

# Auto refresh
auto_refresh = st.sidebar.checkbox("Auto Refresh (30 min)", value=False)

# Initialize session state
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

# ========== FUNCTIONS ==========

def calculate_signal(df, fast, slow, signal):
    """Calculate signal line (MACD LINE)"""
    exp1 = df['close'].ewm(span=fast, adjust=False).mean()
    exp2 = df['close'].ewm(span=slow, adjust=False).mean()
    signal_line = exp1 - exp2
    return signal_line

def calculate_power_level(signal_line, avg_length, multiplier):
    """Calculate power level threshold"""
    abs_signal = signal_line.abs()
    avg_signal = abs_signal.rolling(window=avg_length).mean()
    power_level = avg_signal * multiplier
    return power_level.iloc[-1] if not power_level.empty else 0

def get_signal_color(current, previous):
    """Determine signal color"""
    if current > 0:
        return 'lime' if current > previous else 'green'
    else:
        return 'maroon' if current < previous else 'red'

def send_telegram_alert(message):
    """Send alert to Telegram"""
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

def scan_market(exchange, tf, batch_size=5):
    """Scan all perpetual pairs - OPTIMIZED FOR STABILITY"""
    
    # Placeholders
    momentum_bull_container = st.empty()
    momentum_bear_container = st.empty()
    pullback_bull_container = st.empty()
    pullback_bear_container = st.empty()
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        # Get all perpetual markets
        markets = exchange.load_markets()
        
        # Filter: perpetual swap dengan settle USDT, exclude leverage tokens
        leverage_keywords = ['1000', '2X', '3X', '5X', '10X', 'BEAR', 'BULL', 'HEDGE', 'UP', 'DOWN']
        
        all_pairs = [
            symbol for symbol, market in markets.items()
            if market.get('swap') 
            and market.get('settle') == 'USDT'
            and market.get('active')
            and not any(keyword in symbol.upper() for keyword in leverage_keywords)
        ]
        
        # Scan ALL pairs (no limit)
        perpetual_pairs = all_pairs
        
        total_pairs = len(perpetual_pairs)
        status_text.text(f"Found {total_pairs} perpetual pairs to scan (excluding leverage tokens)...")
        
        momentum_bull = []
        momentum_bear = []
        pullback_bull = []
        pullback_bear = []
        scanned = 0
        errors = 0
        
        # Scan in SMALL batches (3 pairs per batch untuk avoid rate limit)
        for i in range(0, total_pairs, batch_size):
            batch = perpetual_pairs[i:i+batch_size]
            
            for symbol in batch:
                try:
                    # Fetch OHLCV - 420 candles (balance antara akurasi & stabilitas)
                    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=420)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    
                    # Skip pairs dengan data tidak cukup
                    if len(df) < 420:
                        continue
                    
                    # Calculate Slow Signal (Trend)
                    slow_line = calculate_signal(df, slow_fast, slow_slow, slow_signal)
                    slow_current = slow_line.iloc[-1]
                    slow_prev = slow_line.iloc[-2]
                    slow_power = calculate_power_level(slow_line, slow_avg, slow_mult)
                    slow_color = get_signal_color(slow_current, slow_prev)
                    
                    # Calculate Fast Signal (Pullback)
                    fast_line = calculate_signal(df, fast_fast, fast_slow, fast_signal)
                    fast_current = fast_line.iloc[-1]
                    fast_prev = fast_line.iloc[-2]
                    fast_color = get_signal_color(fast_current, fast_prev)
                    
                    # SCREENER 1: MOMENTUM FINDER
                    is_momentum_bull = (slow_current > 0 and
                                        slow_current > slow_power and
                                        slow_color == 'lime')
                    
                    is_momentum_bear = (slow_current < 0 and
                                        slow_current < -slow_power and
                                        slow_color == 'maroon')
                    
                    if is_momentum_bull and len(momentum_bull) < 50:  # Naikin limit jadi 50
                        momentum_bull.append(symbol)
                        if enable_alerts:
                            send_telegram_alert(
                                f"🟢 <b>MOMENTUM DETECTED</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Type: Bullish Breakout\n"
                                f"TF: {tf.upper()}\n"
                                f"Time: {datetime.now().strftime('%H:%M WIB')}"
                            )
                    
                    elif is_momentum_bear and len(momentum_bear) < 50:  # Naikin limit jadi 50
                        momentum_bear.append(symbol)
                        if enable_alerts:
                            send_telegram_alert(
                                f"🔴 <b>MOMENTUM DETECTED</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Type: Bearish Breakout\n"
                                f"TF: {tf.upper()}\n"
                                f"Time: {datetime.now().strftime('%H:%M WIB')}"
                            )
                    
                    # SCREENER 2: PULLBACK ENTRY FINDER
                    is_pullback_bull = (slow_current > slow_power and
                                        slow_color in ['lime', 'green'] and
                                        fast_current < 0)
                    
                    is_pullback_bear = (slow_current < -slow_power and
                                        slow_color in ['maroon', 'red'] and
                                        fast_current > 0)
                    
                    if is_pullback_bull and len(pullback_bull) < 50:  # Naikin limit jadi 50
                        pullback_bull.append(symbol)
                        if enable_alerts:
                            send_telegram_alert(
                                f"🎯 <b>PULLBACK ENTRY</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Type: Bullish Pullback\n"
                                f"TF: {tf.upper()}\n"
                                f"Action: Consider Long Entry\n"
                                f"Time: {datetime.now().strftime('%H:%M WIB')}"
                            )
                    
                    elif is_pullback_bear and len(pullback_bear) < 50:  # Naikin limit jadi 50
                        pullback_bear.append(symbol)
                        if enable_alerts:
                            send_telegram_alert(
                                f"🎯 <b>PULLBACK ENTRY</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Type: Bearish Pullback\n"
                                f"TF: {tf.upper()}\n"
                                f"Action: Consider Short Entry\n"
                                f"Time: {datetime.now().strftime('%H:%M WIB')}"
                            )
                    
                    # IMPORTANT: Slow down! Wait 0.2 seconds (bisa lebih cepat!)
                    time.sleep(0.5)
                
                except Exception as e:
                    errors += 1
                    # If too many errors, stop to avoid ban
                    if errors > 20:
                        status_text.error(f"⚠️ Too many errors ({errors}), stopping scan...")
                        break
                    time.sleep(0.5)  # Wait longer on error
                    continue
                
                scanned += 1
                progress = scanned / total_pairs
                progress_bar.progress(min(progress, 1.0))
                status_text.text(
                    f"Scanning: {scanned}/{total_pairs} (Errors: {errors}) | "
                    f"Momentum: {len(momentum_bull)}🟢 {len(momentum_bear)}🔴 | "
                    f"Pullback: {len(pullback_bull)}🎯 {len(pullback_bear)}🎯"
                )
                
                # Update display progressively (setiap 15 pairs)
                if scanned % 15 == 0:
                    display_results(
                        momentum_bull, momentum_bear,
                        pullback_bull, pullback_bear,
                        momentum_bull_container, momentum_bear_container,
                        pullback_bull_container, pullback_bear_container
                    )
                    # Clean memory every 15 scans
                    gc.collect()
                
                # Stop if all targets reached (50 each)
                if (len(momentum_bull) >= 50 and len(momentum_bear) >= 50 and
                    len(pullback_bull) >= 50 and len(pullback_bear) >= 50):
                    break
            
            # Stop if too many errors
            if errors > 20:
                break
                
            if (len(momentum_bull) >= 50 and len(momentum_bear) >= 50 and
                len(pullback_bull) >= 50 and len(pullback_bear) >= 50):
                break
        
        progress_bar.progress(1.0)
        status_text.text(f"✅ Scan complete! Scanned {scanned} pairs, {errors} errors")
        display_results(
            momentum_bull, momentum_bear,
            pullback_bull, pullback_bear,
            momentum_bull_container, momentum_bear_container,
            pullback_bull_container, pullback_bear_container
        )
        
        return momentum_bull, momentum_bear, pullback_bull, pullback_bear
    
    except Exception as e:
        st.error(f"Error during scan: {str(e)}")
        return [], [], [], []

def display_results(mom_bull, mom_bear, pull_bull, pull_bear,
                    mom_bull_cont, mom_bear_cont, pull_bull_cont, pull_bear_cont):
    """Display all results"""
    
    # SECTION 1: MOMENTUM FINDER
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
    
    # SECTION 2: PULLBACK ENTRY FINDER
    with pull_bull_cont.container():
        st.markdown("### 🎯 PULLBACK ENTRY FINDER")
        st.markdown("#### 🟢 Bullish Pullback")
        if pull_bull:
            cols_per_row = 5
            for i in range(0, len(pull_bull), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    if i + j < len(pull_bull):
                        with col:
                            st.success(f"**{pull_bull[i+j]}**")
        else:
            st.info("No bullish pullback found")
    
    with pull_bear_cont.container():
        st.markdown("#### 🔴 Bearish Pullback")
        if pull_bear:
            cols_per_row = 5
            for i in range(0, len(pull_bear), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    if i + j < len(pull_bear):
                        with col:
                            st.error(f"**{pull_bear[i+j]}**")
        else:
            st.info("No bearish pullback found")

# ========== MAIN EXECUTION ==========

col1, col2 = st.columns([1, 3])

with col1:
    if st.button("🔄 Refresh Now", type="primary", use_container_width=True):
        with st.spinner(f"Scanning {timeframe.upper()} timeframe..."):
            exchange = ccxt.gateio({'enableRateLimit': True})
            mom_bull, mom_bear, pull_bull, pull_bear = scan_market(exchange, timeframe)
            st.session_state.momentum_bull = mom_bull
            st.session_state.momentum_bear = mom_bear
            st.session_state.pullback_bull = pull_bull
            st.session_state.pullback_bear = pull_bear
            st.session_state.last_update = datetime.now()

with col2:
    if st.session_state.last_update:
        st.info(f"📅 Last updated: {st.session_state.last_update.strftime('%Y-%m-%d %H:%M:%S')} | TF: {timeframe.upper()}")
    else:
        st.warning("Click 'Refresh Now' to start scanning")

# Auto refresh
if auto_refresh and st.session_state.last_update:
    time_diff = (datetime.now() - st.session_state.last_update).total_seconds()
    if time_diff >= 1800:
        st.rerun()

# Display stored results
if (st.session_state.momentum_bull or st.session_state.momentum_bear or
    st.session_state.pullback_bull or st.session_state.pullback_bear):
    mom_bull_cont = st.empty()
    mom_bear_cont = st.empty()
    pull_bull_cont = st.empty()
    pull_bear_cont = st.empty()
    display_results(
        st.session_state.momentum_bull,
        st.session_state.momentum_bear,
        st.session_state.pullback_bull,
        st.session_state.pullback_bear,
        mom_bull_cont, mom_bear_cont,
        pull_bull_cont, pull_bear_cont
    )

# Footer
st.markdown("---")
st.markdown("**SCALPIFY V1 - Gate.io Edition** | All perpetual pairs | Leverage tokens excluded")
