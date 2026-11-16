import os
import json
import time
from datetime import datetime, timezone, timedelta
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = str(os.environ.get("TELEGRAM_CHAT_ID", "")).strip()

GEMINI_API_KEYS = [
    k.strip() for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("GEMINI_API_KEY_2", "")
    ] if k and k.strip()
]

BACKUP_AI_API_KEY = os.environ.get("BACKUP_AI_API_KEY", "")
BACKUP_AI_URL = os.environ.get("BACKUP_AI_URL", "https://api.groq.com/openai/v1/chat/completions")
BACKUP_AI_MODEL = os.environ.get("BACKUP_AI_MODEL", "llama-3.3-70b-versatile")

CONFIG_FILE = "config.json"
WIB = timezone(timedelta(hours=7))

def now_wib_str():
    return datetime.now(WIB).strftime("%d/%m %H:%M WIB")

def load_config():
    default_cfg = {
        "live_trading": False,
        "tp": 0.60,
        "sl": 0.23,
        "strategy": (
            "1. Volatilitas & Batas Candle: Panjang candle wajar hingga 35 poin (0.35). Tolak entry jika ATR > 0.35 atau candle > 0.42 (sangat ekstrem), atau market terlalu lambat (ATR < 0.065). "
            "2. Market vs Limit Order: Jika candle 24-35 poin, utamakan LIMIT ORDER di area tengah candle (retracement 40-50% / EMA 9) agar SL 0.23 aman di balik ekor candle. Jika momentum dari S/R kunci sangat kuat dan SL 0.23 dinilai aman, MARKET ORDER diperbolehkan. "
            "3. Dominasi Struktur 5m & 15m: Dilarang melawan struktur 5m/15m yang sedang terbentuk meski 1H berlawanan. "
            "4. Jalur TP 0.60 Bersih dari halangan S/R besar. "
            "5. Konfirmasi Candlestick, Volume, SMI & Spot CVD (5m & 15m) wajib searah."
        ),
        "last_update_id": 0,
        "pending_order": None,
        "active_trade": None,
        "stats": {
            "total_closed": 0,
            "tp_hit": 0,
            "sl_hit": 0,
            "bep_hit": 0,
            "cancelled_limits": 0,
            "net_points": 0.0
        }
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                loaded = json.load(f)
                default_cfg.update(loaded)
                if "stats" not in default_cfg or not isinstance(default_cfg["stats"], dict):
                    default_cfg["stats"] = {"total_closed": 0, "tp_hit": 0, "sl_hit": 0, "bep_hit": 0, "cancelled_limits": 0, "net_points": 0.0}
                default_cfg["stats"].setdefault("cancelled_limits", 0)
                default_cfg.setdefault("pending_order", None)
        except Exception:
            pass
    return default_cfg

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def send_telegram(text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Gagal kirim Telegram: {e}")

def format_stats_text(cfg):
    s = cfg.get("stats", {})
    total = s.get("total_closed", 0)
    tp_hit = s.get("tp_hit", 0)
    sl_hit = s.get("sl_hit", 0)
    bep_hit = s.get("bep_hit", 0)
    cancelled = s.get("cancelled_limits", 0)
    net = round(s.get("net_points", 0.0), 3)
    win_rate = round((tp_hit / total) * 100, 1) if total > 0 else 0.0
    non_loss_rate = round(((tp_hit + bep_hit) / total) * 100, 1) if total > 0 else 0.0
    
    return (
        f"📊 *EVALUASI KINERJA SINYAL*\n"
        f"• Total Trade Selesai: `{total} trade`\n"
        f"• ✅ Kena TP: `{tp_hit}`\n"
        f"• 🛡️ Kena SL di Entry (1:1 BEP): `{bep_hit}`\n"
        f"• ❌ Kena SL Awal: `{sl_hit}`\n"
        f"• 🚫 Limit Dibatalkan (Terlewat): `{cancelled}`\n"
        f"• Win Rate Murni: `{win_rate}%` | Anti-Loss: `{non_loss_rate}%`\n"
        f"• Akumulasi Poin Bersih: `{net:+} poin`"
    )

def send_control_menu(cfg, header="🎛️ *PANEL KENDALI ARGON BOT*"):
    status_trade = "🟢 ON (LIVE)" if cfg["live_trading"] else "🔴 OFF (Signal Only)"
    toggle_label = "🔴 Matikan Auto-Trading" if cfg["live_trading"] else "🟢 Aktifkan Auto-Trading"
    
    active = cfg.get("active_trade")
    pending = cfg.get("pending_order")
    if active:
        sl_status = "🛡️ Sudah pindah ke Entry (BEP)" if active.get("bep_moved") else f"SL Awal (`${active['sl_price']}`)"
        pos_info = (
            f"📌 *POSISI AKTIF:* `{active['direction']}` ({active.get('order_type', 'MARKET')}) @ `${active['entry_price']}`\n"
            f"   Target TP: `${active['tp_price']}` | {sl_status}"
        )
    elif pending:
        pos_info = (
            f"⏳ *LIMIT ORDER MENUNGGU:* `{pending['direction']}` @ `${pending['limit_price']}`\n"
            f"   TP: `${pending['tp_price']}` | SL: `${pending['sl_price']}`"
        )
    else:
        pos_info = f"📌 *STATUS POSISI:* `Kosong (API Google: {len(GEMINI_API_KEYS)} akun | Max ATR: 0.35)`"

    text = (
        f"{header}\n\n"
        f"• *Mode Eksekusi:* `{status_trade}`\n"
        f"• *Target TP / SL:* `+{cfg['tp']}` / `-{cfg['sl']} poin`\n"
        f"{pos_info}\n\n"
        f"{format_stats_text(cfg)}"
    )
    
    keyboard = {
        "inline_keyboard": [
            [{"text": toggle_label, "callback_data": "toggle_trading"}],
            [
                {"text": "📊 Cek Sinyal Sekarang", "callback_data": "scan_now"},
                {"text": "📈 Lihat Evaluasi", "callback_data": "show_stats"}
            ],
            [
                {"text": "✏️ Panduan Perintah", "callback_data": "help_edit"},
                {"text": "🔄 Refresh Menu", "callback_data": "show_menu"}
            ]
        ]
    }
    send_telegram(text, reply_markup=keyboard)

def process_telegram_commands(cfg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"offset": cfg.get("last_update_id", 0) + 1, "timeout": 5}
    
    try:
        res = requests.get(url, params=params, timeout=15).json()
    except Exception as e:
        print(f"Gagal cek perintah Telegram: {e}")
        return cfg, False

    if not res.get("ok"):
        return cfg, False

    menu_requested = False
    manual_scan_requested = False

    for update in res.get("result", []):
        cfg["last_update_id"] = update["update_id"]
        
        if "callback_query" in update:
            cb = update["callback_query"]
            if str(cb["from"]["id"]) != TELEGRAM_CHAT_ID:
                continue
                
            try:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                    json={"callback_query_id": cb["id"]}, timeout=10
                )
            except Exception:
                pass
            
            action = cb.get("data", "")
            if action == "toggle_trading":
                cfg["live_trading"] = not cfg["live_trading"]
                send_control_menu(cfg, header="✅ *Status Auto-Trading Diperbarui!*")
            elif action == "show_menu":
                send_control_menu(cfg)
            elif action == "show_stats":
                send_telegram(format_stats_text(cfg))
            elif action == "help_edit":
                help_text = (
                    "📝 *PANDUAN PERINTAH TELEGRAM*\n\n"
                    "• `/menu` — Membuka panel tombol kendali\n"
                    "• `/cek` — Audit market 6 gerbang / cek posisi & limit order\n"
                    "• `/stats` — Melihat rekap evaluasi TP, SL, BEP, & Limit Batal\n"
                    "• `/tp 0.60` — Mengubah target Take Profit (poin)\n"
                    "• `/sl 0.23` — Mengubah batas Stop Loss (poin)\n"
                    "• `/strategi [aturan]` — Mengubah aturan strategi AI\n"
                    "• `/reset_trade` — Menghapus posisi aktif / limit order menunggu\n"
                    "• `/reset_stats` — Mengulang hitungan statistik dari 0"
                )
                send_telegram(help_text)
            elif action == "scan_now":
                manual_scan_requested = True

        elif "message" in update and "text" in update["message"]:
            msg = update["message"]
            if str(msg["chat"]["id"]) != TELEGRAM_CHAT_ID:
                continue
                
            text = msg["text"].strip()
            lower_text = text.lower()
            
            if lower_text in ["/start", "/menu", "menu"]:
                menu_requested = True
            elif lower_text in ["/cek", "cek", "/scan"]:
                manual_scan_requested = True
            elif lower_text in ["/stats", "stats"]:
                send_telegram(format_stats_text(cfg))
            elif lower_text == "/reset_trade":
                cfg["active_trade"] = None
                cfg["pending_order"] = None
                send_telegram("🗑️ Posisi aktif & pending limit order dihapus dari memori.")
            elif lower_text == "/reset_stats":
                cfg["stats"] = {"total_closed": 0, "tp_hit": 0, "sl_hit": 0, "bep_hit": 0, "cancelled_limits": 0, "net_points": 0.0}
                send_telegram("🔄 Statistik evaluasi berhasil direset ke 0.")
            elif lower_text.startswith("/tp "):
                try:
                    val = float(text.split(" ", 1)[1].replace(",", "."))
                    cfg["tp"] = val
                    send_telegram(f"✅ Take Profit diubah menjadi *+{val} poin*.")
                except ValueError:
                    send_telegram("⚠️ Format salah. Contoh: `/tp 0.60`")
            elif lower_text.startswith("/sl "):
                try:
                    val = float(text.split(" ", 1)[1].replace(",", "."))
                    cfg["sl"] = val
                    send_telegram(f"✅ Stop Loss diubah menjadi *-{val} poin*.")
                except ValueError:
                    send_telegram("⚠️ Format salah. Contoh: `/sl 0.23`")
            elif lower_text == "/trading on":
                cfg["live_trading"] = True
                send_telegram("🟢 Mode Live Trading: *AKTIF (ON)*")
            elif lower_text == "/trading off":
                cfg["live_trading"] = False
                send_telegram("🔴 Mode Live Trading: *NONAKTIF (OFF / Dry Run)*")
            elif lower_text.startswith("/strategi "):
                new_strat = text.split(" ", 1)[1].strip()
                if new_strat:
                    cfg["strategy"] = new_strat
                    send_telegram(f"✅ *Strategi AI Diperbarui:*\n_{new_strat}_")

    if menu_requested:
        send_control_menu(cfg)

    return cfg, manual_scan_requested

def calc_ema_series(values, period):
    k = 2 / (period + 1)
    ema_list = [values[0]]
    for v in values[1:]:
        ema_list.append(v * k + ema_list[-1] * (1 - k))
    return ema_list

def calc_atr(highs, lows, closes, period=14):
    trs = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            trs.append(tr)
    atr_series = calc_ema_series(trs, period)
    return round(atr_series[-1], 4)

def calc_smi_series(highs, lows, closes, length=10, smooth1=3, smooth2=3):
    rel_diff = []
    hl_range = []
    for i in range(len(closes)):
        start = max(0, i - length + 1)
        hh = max(highs[start:i+1])
        ll = min(lows[start:i+1])
        mid = (hh + ll) / 2.0
        rel_diff.append(closes[i] - mid)
        hl_range.append(hh - ll)
    
    d1 = calc_ema_series(rel_diff, smooth1)
    d2 = calc_ema_series(d1, smooth2)
    r1 = calc_ema_series(hl_range, smooth1)
    r2 = calc_ema_series(r1, smooth2)
    
    smi_vals = []
    for num, den in zip(d2, r2):
        if den != 0:
            smi_vals.append((num / (den / 2.0)) * 100.0)
        else:
            smi_vals.append(0.0)
    smi_sig = calc_ema_series(smi_vals, smooth2)
    return round(smi_vals[-1], 2), round(smi_sig[-1], 2)

def detect_structure(highs, lows, lookback=24):
    sub_h = highs[-lookback:]
    sub_l = lows[-lookback:]
    mid = len(sub_h) // 2
    
    prev_swing_high = max(sub_h[:mid])
    last_swing_high = max(sub_h[mid:])
    prev_swing_low = min(sub_l[:mid])
    last_swing_low = min(sub_l[mid:])
    
    if last_swing_high > prev_swing_high and last_swing_low > prev_swing_low:
        return 1.0, "UPTREND (HH/HL)", round(last_swing_high, 3), round(last_swing_low, 3)
    elif last_swing_high < prev_swing_high and last_swing_low < prev_swing_low:
        return -1.0, "DOWNTREND (LH/LL)", round(last_swing_high, 3), round(last_swing_low, 3)
    else:
        return 0.0, "SIDEWAYS / TRANSISI", round(last_swing_high, 3), round(last_swing_low, 3)

def analyze_candle_anatomy(o, h, l, c, v, avg_v):
    total_range = max(h - l, 0.001)
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    
    body_pct = round((body / total_range) * 100, 1)
    upper_wick_pct = round((upper_wick / total_range) * 100, 1)
    lower_wick_pct = round((lower_wick / total_range) * 100, 1)
    vol_ratio = round(v / avg_v, 2) if avg_v > 0 else 1.0
    
    direction = "BULLISH" if c > o else ("BEARISH" if c < o else "DOJI")
    pattern = "Normal"
    if body_pct <= 25:
        pattern = "Doji / Indecision"
    elif lower_wick_pct >= 50 and c >= o:
        pattern = "Bullish Rejection Pinbar"
    elif upper_wick_pct >= 50 and c <= o:
        pattern = "Bearish Rejection Pinbar"
    elif body_pct >= 65 and direction == "BULLISH":
        pattern = "Strong Bullish Momentum"
    elif body_pct >= 65 and direction == "BEARISH":
        pattern = "Strong Bearish Momentum"
        
    return {
        "dir": direction,
        "high": round(h, 3),
        "low": round(l, 3),
        "mid": round((h + l) / 2.0, 3),
        "range": round(total_range, 3),
        "body_pct": body_pct,
        "upper_wick_pct": upper_wick_pct,
        "lower_wick_pct": lower_wick_pct,
        "vol_ratio": vol_ratio,
        "pattern": pattern
    }

def fetch_market_data():
    headers = {'Accept': 'application/json', 'User-Agent': 'Argon-Bot/4.0'}
    
    url_5m = "https://data-api.binance.vision/api/v3/klines?symbol=SOLUSDT&interval=5m&limit=220"
    res_5m = requests.get(url_5m, headers=headers, timeout=15)
    if res_5m.status_code != 200:
        raise Exception(f"Gagal tarik data 5m Binance: HTTP {res_5m.status_code}")
    k5 = res_5m.json()
    
    open_times = [int(k[0]) for k in k5]
    opens = [float(k[1]) for k in k5]
    highs = [float(k[2]) for k in k5]
    lows = [float(k[3]) for k in k5]
    closes = [float(k[4]) for k in k5]
    vols = [float(k[5]) for k in k5]
    quote_vols = [float(k[7]) for k in k5]
    taker_buy_quotes = [float(k[10]) for k in k5]
    
    current_price = closes[-1]
    latest_candle_time = open_times[-1]
    
    ema9 = round(calc_ema_series(closes, 9)[-1], 3)
    ema10 = round(calc_ema_series(closes, 10)[-1], 3)
    ema20 = round(calc_ema_series(closes, 20)[-1], 3)
    ema30 = round(calc_ema_series(closes, 30)[-1], 3)
    ema50 = round(calc_ema_series(closes, 50)[-1], 3)
    ema200 = round(calc_ema_series(closes, 200)[-1], 3)
    atr_5m = calc_atr(highs, lows, closes, 14)
    
    win20 = closes[-20:]
    bb_mid_val = sum(win20) / 20.0
    std_dev = (sum((x - bb_mid_val) ** 2 for x in win20) / 20.0) ** 0.5
    bb_upper = round(bb_mid_val + 2 * std_dev, 3)
    bb_lower = round(bb_mid_val - 2 * std_dev, 3)
    bb_mid = round(bb_mid_val, 3)
    bb_width_pct = round(((bb_upper - bb_lower) / current_price) * 100, 3)
    
    smi_5m, smi_sig_5m = calc_smi_series(highs, lows, closes, 10, 3, 3)
    struct_5m, struct_5m_label, sh_5m, sl_5m = detect_structure(highs, lows, 24)
    
    deltas_usdt = [2 * tbq - qv for tbq, qv in zip(taker_buy_quotes, quote_vols)]
    cvd_5m = round(deltas_usdt[-1], 0)
    cvd_15m = round(sum(deltas_usdt[-3:]), 0)
    cvd_1h = round(sum(deltas_usdt[-12:]), 0)
    
    avg_vol_20 = sum(vols[-21:-1]) / 20.0
    prev_candle_anatomy = analyze_candle_anatomy(opens[-2], highs[-2], lows[-2], closes[-2], vols[-2], avg_vol_20)
    curr_candle_anatomy = analyze_candle_anatomy(opens[-1], highs[-1], lows[-1], closes[-1], vols[-1], avg_vol_20)
    
    struct_15m, struct_15m_label, sh_15m, sl_15m = 0.0, "TIDAK TERSEDIA", sh_5m, sl_5m
    ema9_15m, ema20_15m, ema50_15m, ema200_15m = ema9, ema20, ema50, ema200
    smi_15m, smi_sig_15m = smi_5m, smi_sig_5m
    atr_15m = atr_5m
    try:
        url_15m = "https://data-api.binance.vision/api/v3/klines?symbol=SOLUSDT&interval=15m&limit=100"
        res_15m = requests.get(url_15m, headers=headers, timeout=10)
        if res_15m.status_code == 200:
            k15 = res_15m.json()
            h15 = [float(k[2]) for k in k15]
            l15 = [float(k[3]) for k in k15]
            c15 = [float(k[4]) for k in k15]
            struct_15m, struct_15m_label, sh_15m, sl_15m = detect_structure(h15, l15, 20)
            ema9_15m = round(calc_ema_series(c15, 9)[-1], 3)
            ema20_15m = round(calc_ema_series(c15, 20)[-1], 3)
            ema50_15m = round(calc_ema_series(c15, 50)[-1], 3)
            ema200_15m = round(calc_ema_series(c15, 200)[-1], 3)
            smi_15m, smi_sig_15m = calc_smi_series(h15, l15, c15, 10, 3, 3)
            atr_15m = calc_atr(h15, l15, c15, 14)
    except Exception:
        pass

    struct_1h, struct_1h_label, sh_1h, sl_1h = 0.0, "TIDAK TERSEDIA", sh_15m, sl_15m
    ema20_1h, ema50_1h = ema20_15m, ema50_15m
    try:
        url_1h = "https://data-api.binance.vision/api/v3/klines?symbol=SOLUSDT&interval=1h&limit=60"
        res_1h = requests.get(url_1h, headers=headers, timeout=10)
        if res_1h.status_code == 200:
            k1h = res_1h.json()
            h1h = [float(k[2]) for k in k1h]
            l1h = [float(k[3]) for k in k1h]
            c1h = [float(k[4]) for k in k1h]
            struct_1h, struct_1h_label, sh_1h, sl_1h = detect_structure(h1h, l1h, 24)
            ema20_1h = round(calc_ema_series(c1h, 20)[-1], 3)
            ema50_1h = round(calc_ema_series(c1h, 50)[-1], 3)
    except Exception:
        pass

    last_candles = [
        {"o": round(opens[i], 2), "h": round(highs[i], 2), "l": round(lows[i], 2), "c": round(closes[i], 2), "cvd_usd": round(deltas_usdt[i], 0)}
        for i in range(-6, 0)
    ]
    
    candle_history = [
        {"t": open_times[i], "h": highs[i], "l": lows[i], "c": closes[i]}
        for i in range(-40, 0)
    ]

    metrics = {
        "price": current_price,
        "latest_candle_time": latest_candle_time,
        "candle_history": candle_history,
        "atr_5m": atr_5m, "atr_15m": atr_15m, "bb_width_pct": bb_width_pct,
        "ema9": ema9, "ema10": ema10, "ema20": ema20, "ema30": ema30, "ema50": ema50, "ema200": ema200,
        "ema9_15m": ema9_15m, "ema20_15m": ema20_15m, "ema50_15m": ema50_15m, "ema200_15m": ema200_15m,
        "ema20_1h": ema20_1h, "ema50_1h": ema50_1h,
        "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower,
        "smi": smi_5m, "smi_signal": smi_sig_5m,
        "smi_15m": smi_15m, "smi_sig_15m": smi_sig_15m,
        "struct_5m": struct_5m, "struct_5m_label": struct_5m_label, "sh_5m": sh_5m, "sl_5m": sl_5m,
        "struct_15m": struct_15m, "struct_15m_label": struct_15m_label, "sh_15m": sh_15m, "sl_15m": sl_15m,
        "struct_1h": struct_1h, "struct_1h_label": struct_1h_label, "sh_1h": sh_1h, "sl_1h": sl_1h,
        "cvd_5m": cvd_5m, "cvd_15m": cvd_15m, "cvd_1h": cvd_1h,
        "prev_candle": prev_candle_anatomy,
        "curr_candle": curr_candle_anatomy
    }
    
    summary = (
        f"Asset: SOL/USDT | Current Price: ${current_price}\n"
        f"Volatility -> 5M ATR(14): {atr_5m} pts (Limit Wajar: 0.35 pts) | 15M ATR(14): {atr_15m} pts | BB Width: {bb_width_pct}%\n"
        f"Multi-Timeframe Structure:\n"
        f"  - 5M Structure: {struct_5m_label} (Swing High: ${sh_5m}, Swing Low: ${sl_5m})\n"
        f"  - 15M Structure: {struct_15m_label} (Swing High: ${sh_15m}, Swing Low: ${sl_15m})\n"
        f"  - 1H Macro Trend: {struct_1h_label} (Swing High: ${sh_1h}, Swing Low: ${sl_1h}, EMA20: ${ema20_1h}, EMA50: ${ema50_1h})\n"
        f"5M EMAs -> EMA9: ${ema9} | EMA10: ${ema10} | EMA20: ${ema20} | EMA30: ${ema30} | EMA50: ${ema50} | EMA200: ${ema200}\n"
        f"15M EMAs -> EMA9: ${ema9_15m} | EMA20: ${ema20_15m} | EMA50: ${ema50_15m} | EMA200: ${ema200_15m}\n"
        f"Bollinger Bands (5M) -> Upper: ${bb_upper} | Mid: ${bb_mid} | Lower: ${bb_lower}\n"
        f"Momentum (SMI) -> 5M SMI: {smi_5m} (Sig: {smi_sig_5m}) | 15M SMI: {smi_15m} (Sig: {smi_sig_15m})\n"
        f"Spot Order Flow (CVD USDT) -> 5m: ${cvd_5m:+,.0f} | 15m: ${cvd_15m:+,.0f} | 1h: ${cvd_1h:+,.0f}\n"
        f"Candlestick Anatomy -> Prev Closed 5M: {json.dumps(prev_candle_anatomy)} | Current 5M: {json.dumps(curr_candle_anatomy)}\n"
        f"Last 6 Candles (5m): {json.dumps(last_candles)}"
    )
    return current_price, summary, metrics

def evaluate_quant_gates(m, cfg):
    price = m["price"]
    tp_dist = float(cfg["tp"])
    sl_dist = float(cfg["sl"])
    atr_5m = m["atr_5m"]
    
    # Batas panjang candle wajar dilonggarkan hingga 35 poin (0.35)
    max_safe_atr = 0.35
    max_candle_rng = 0.42
    min_viable_atr = 0.065
    
    candle_rng = max(m["curr_candle"]["range"], m["prev_candle"]["range"])
    prefer_limit = (atr_5m > 0.24 or candle_rng > 0.24)
    
    vol_status = "OPTIMAL"
    if prefer_limit:
        vol_note = f"ATR 5m ({atr_5m}) & Range ({candle_rng}) aktif dalam batas wajar (<=0.35). Disarankan LIMIT ORDER ke tengah candle/EMA9 agar SL {sl_dist} aman, atau MARKET jika momentum S/R sangat kuat."
    else:
        vol_note = f"ATR 5m ({atr_5m}) & Range ({candle_rng}) tenang & ideal untuk SL {sl_dist} & TP {tp_dist}."
        
    allow_long = True
    allow_short = True
    
    if atr_5m > max_safe_atr or candle_rng > max_candle_rng:
        vol_status = "TERLALU_EKSTREM"
        vol_note = f"Volatilitas di luar batas wajar (ATR 5m={atr_5m} > 0.35 atau Range={candle_rng} > 0.42). SL {sl_dist} terlalu berisiko."
        allow_long = False
        allow_short = False
    elif atr_5m < min_viable_atr and m["bb_width_pct"] < 0.35:
        vol_status = "TERLALU_LAMBAT"
        vol_note = f"Market terlalu lambat/sepi (ATR 5m={atr_5m}, BB Width={m['bb_width_pct']}%). Sulit menjangkau TP {tp_dist}."
        allow_long = False
        allow_short = False

    s5 = m["struct_5m"]
    s15 = m["struct_15m"]
    struct_note = f"5M: {m['struct_5m_label']} | 15M: {m['struct_15m_label']} | 1H: {m['struct_1h_label']}"
    
    if s5 == 1.0 or s15 == 1.0:
        allow_short = False
        struct_note += " -> SHORT diblokir karena 5m/15m sedang membentuk struktur naik (HH/HL)."
    if s5 == -1.0 or s15 == -1.0:
        allow_long = False
        struct_note += " -> LONG diblokir karena 5m/15m sedang membentuk struktur turun (LH/LL)."
    if s5 == 0.0 and s15 == 0.0:
        if price > m["bb_lower"] + (m["bb_upper"] - m["bb_lower"]) * 0.28:
            allow_long = False
        if price < m["bb_upper"] - (m["bb_upper"] - m["bb_lower"]) * 0.28:
            allow_short = False
        struct_note += " -> Pasar sideways, entry hanya valid di tepi ekstrem Bollinger Bands."

    key_levels = [
        m["ema9"], m["ema20"], m["ema50"], m["ema20_15m"],
        m["bb_upper"], m["bb_mid"], m["bb_lower"],
        m["sh_5m"], m["sl_5m"], m["sh_15m"], m["sl_15m"]
    ]
    nearest_dist = min(abs(price - lvl) for lvl in key_levels)
    # Jika memakai Limit Order ke tengah candle, jangkauan area POI lebih fleksibel
    max_poi_dist = max(0.20, round(atr_5m * 1.25, 3))
    poi_valid = nearest_dist <= max_poi_dist
    poi_note = (
        f"Valid (jarak {round(nearest_dist, 3)} poin dari level kunci terdekat)"
        if poi_valid else
        f"Tidak Valid / No Man's Land (jarak {round(nearest_dist, 3)} poin dari level teknikal terdekat)"
    )
    if not poi_valid:
        allow_long = False
        allow_short = False

    res_levels = {
        "Swing High 5m": m["sh_5m"],
        "Swing High 15m": m["sh_15m"],
        "Swing High 1H": m["sh_1h"],
        "EMA 200 (5m)": m["ema200"],
        "EMA 200 (15m)": m["ema200_15m"],
        "Upper BB (5m)": m["bb_upper"]
    }
    sup_levels = {
        "Swing Low 5m": m["sl_5m"],
        "Swing Low 15m": m["sl_15m"],
        "Swing Low 1H": m["sl_1h"],
        "EMA 200 (5m)": m["ema200"],
        "EMA 200 (15m)": m["ema200_15m"],
        "Lower BB (5m)": m["bb_lower"]
    }
    
    min_clear_room = round(tp_dist * 0.70, 3)
    long_obstacles = [
        f"{name} (${lvl}, jarak +{round(lvl - price, 3)})"
        for name, lvl in res_levels.items()
        if 0.08 < (lvl - price) < min_clear_room
    ]
    short_obstacles = [
        f"{name} (${lvl}, jarak -{round(price - lvl, 3)})"
        for name, lvl in sup_levels.items()
        if 0.08 < (price - lvl) < min_clear_room
    ]
    
    if long_obstacles:
        allow_long = False
    if short_obstacles:
        allow_short = False

    # Hitung titik rekomendasi Limit Order yang presisi (tengah candle / EMA 9)
    active_c = m["curr_candle"] if m["curr_candle"]["range"] >= m["prev_candle"]["range"] else m["prev_candle"]
    suggested_limit_long = round(min(price - 0.05, max(active_c["mid"], m["ema9"])), 3)
    suggested_limit_short = round(max(price + 0.05, min(active_c["mid"], m["ema9"])), 3)

    return {
        "vol_status": vol_status,
        "vol_note": vol_note,
        "prefer_limit": prefer_limit,
        "suggested_limit_long": suggested_limit_long,
        "suggested_limit_short": suggested_limit_short,
        "struct_note": struct_note,
        "poi_valid": poi_valid,
        "poi_note": poi_note,
        "long_obstacles": long_obstacles,
        "short_obstacles": short_obstacles,
        "allow_long": allow_long,
        "allow_short": allow_short
    }

def monitor_pending_limit_order(cfg, metrics):
    """
    Memantau Pending Limit Order:
    - Jika harga menjauh 20-23 poin (0.21) sebelum menyentuh limit -> CANCEL otomatis (terlewat).
    - Jika menyentuh titik limit -> Ubah menjadi ACTIVE TRADE dan pantau TP/SL/BEP.
    - Jika lebih dari 3 candle (15 menit) tidak tersentuh -> CANCEL kedaluwarsa.
    """
    pending = cfg.get("pending_order")
    if not pending:
        return cfg, "NO_PENDING", None

    direction = pending["direction"]
    limit_p = float(pending["limit_price"])
    tp_p = float(pending["tp_price"])
    sl_p = float(pending["sl_price"])
    sl_dist = float(pending["initial_sl_dist"])
    created_time = int(pending["created_open_time"])
    curr_price = metrics["price"]

    relevant_candles = [
        c for c in metrics.get("candle_history", [])
        if c["t"] >= created_time
    ]
    if not relevant_candles:
        relevant_candles = [{"t": created_time, "h": curr_price, "l": curr_price, "c": curr_price}]

    # Cek secara kronologis setiap candle sejak limit order dipasang
    for idx, c in enumerate(relevant_candles):
        bar_high = curr_price if c["t"] == created_time else c["h"]
        bar_low = curr_price if c["t"] == created_time else c["l"]

        if direction == "LONG":
            # 1. Cek apakah harga sudah lari menjauh >= 0.21 poin (21 poin) ke atas tanpa jemput limit
            if (bar_high - limit_p) >= 0.21 and bar_low > limit_p:
                cfg["pending_order"] = None
                cfg["stats"]["cancelled_limits"] += 1
                msg = (
                    f"🚫 *LIMIT ORDER DIBATALKAN (HARGA TERLEWAT)*\n\n"
                    f"• Rencana: `LONG LIMIT` @ `${limit_p}`\n"
                    f"• Harga Tertinggi: `${bar_high}` (Sudah menjauh `+{round(bar_high - limit_p, 3)} poin` tanpa menjemput entry)\n"
                    f"• Status: Order dibatalkan otomatis agar tidak mengejar harga."
                )
                return cfg, "CANCELLED_MISSED", msg

            # 2. Cek apakah harga turun menjemput titik Limit Order (Filled!)
            if c["t"] > created_time and bar_low <= limit_p:
                cfg["pending_order"] = None
                bep_trigger = round(limit_p + sl_dist, 3)
                cfg["active_trade"] = {
                    "direction": "LONG",
                    "order_type": "LIMIT",
                    "entry_price": limit_p,
                    "tp_price": tp_p,
                    "sl_price": sl_p,
                    "initial_sl_dist": sl_dist,
                    "bep_trigger_price": bep_trigger,
                    "bep_moved": False,
                    "entry_open_time": c["t"],
                    "entry_time": now_wib_str(),
                    "reason": pending.get("reason", "-")
                }
                msg = (
                    f"✅ *LIMIT ORDER TEREKSEKUSI (FILLED): LONG*\n\n"
                    f"• Harga Entry Jemputan: `${limit_p}`\n"
                    f"• Target TP: `${tp_p}` | Stop Loss: `${sl_p}`\n"
                    f"• Target 1:1 Pindah SL: `${bep_trigger}`\n"
                    f"• Status: Posisi kini **AKTIF** dipantau oleh bot."
                )
                return cfg, "FILLED", msg

        elif direction == "SHORT":
            # 1. Cek apakah harga sudah jatuh menjauh >= 0.21 poin (21 poin) ke bawah tanpa jemput limit
            if (limit_p - bar_low) >= 0.21 and bar_high < limit_p:
                cfg["pending_order"] = None
                cfg["stats"]["cancelled_limits"] += 1
                msg = (
                    f"🚫 *LIMIT ORDER DIBATALKAN (HARGA TERLEWAT)*\n\n"
                    f"• Rencana: `SHORT LIMIT` @ `${limit_p}`\n"
                    f"• Harga Terendah: `${bar_low}` (Sudah menjauh `-{round(limit_p - bar_low, 3)} poin` tanpa menjemput entry)\n"
                    f"• Status: Order dibatalkan otomatis agar tidak mengejar harga."
                )
                return cfg, "CANCELLED_MISSED", msg

            # 2. Cek apakah harga naik menjemput titik Limit Order (Filled!)
            if c["t"] > created_time and bar_high >= limit_p:
                cfg["pending_order"] = None
                bep_trigger = round(limit_p - sl_dist, 3)
                cfg["active_trade"] = {
                    "direction": "SHORT",
                    "order_type": "LIMIT",
                    "entry_price": limit_p,
                    "tp_price": tp_p,
                    "sl_price": sl_p,
                    "initial_sl_dist": sl_dist,
                    "bep_trigger_price": bep_trigger,
                    "bep_moved": False,
                    "entry_open_time": c["t"],
                    "entry_time": now_wib_str(),
                    "reason": pending.get("reason", "-")
                }
                msg = (
                    f"✅ *LIMIT ORDER TEREKSEKUSI (FILLED): SHORT*\n\n"
                    f"• Harga Entry Jemputan: `${limit_p}`\n"
                    f"• Target TP: `${tp_p}` | Stop Loss: `${sl_p}`\n"
                    f"• Target 1:1 Pindah SL: `${bep_trigger}`\n"
                    f"• Status: Posisi kini **AKTIF** dipantau oleh bot."
                )
                return cfg, "FILLED", msg

    # 3. Cek jika sudah lewat > 3 candle (15 menit) tidak tersentuh juga -> Kedaluwarsa
    if len(relevant_candles) > 4:
        cfg["pending_order"] = None
        cfg["stats"]["cancelled_limits"] += 1
        msg = (
            f"⌛ *LIMIT ORDER KEDALUWARSA (> 15 MENIT)*\n\n"
            f"• Rencana: `{direction} LIMIT` @ `${limit_p}`\n"
            f"• Harga Sekarang: `${curr_price}`\n"
            f"• Status: Setup lama dibatalkan otomatis untuk mencari struktur baru."
        )
        return cfg, "CANCELLED_EXPIRED", msg

    dist_now = round(abs(curr_price - limit_p), 3)
    wait_msg = (
        f"⏳ *LIMIT ORDER MASIH MENUNGGU JEMPUTAN*\n\n"
        f"• Rencana: `{direction} LIMIT` @ `${limit_p}`\n"
        f"• Harga Sekarang: `${curr_price}` (Jarak ke Limit: `{dist_now} poin`, batas batal: `0.21 poin`)\n"
        f"• TP: `${tp_p}` | SL: `${sl_p}`"
    )
    return cfg, "WAITING_FILL", wait_msg

def monitor_active_trade(cfg, metrics):
    trade = cfg.get("active_trade")
    if not trade:
        return cfg, "NO_TRADE", None

    direction = trade["direction"]
    entry = float(trade["entry_price"])
    tp_price = float(trade["tp_price"])
    sl_price = float(trade["sl_price"])
    bep_trigger = float(trade["bep_trigger_price"])
    bep_moved = bool(trade.get("bep_moved", False))
    entry_open_time = int(trade.get("entry_open_time", 0))
    
    curr_price = metrics["price"]
    tp_dist = round(abs(tp_price - entry), 3)
    sl_dist = round(float(trade.get("initial_sl_dist", cfg["sl"])), 3)
    stats = cfg["stats"]
    alerts = []

    relevant_candles = [
        c for c in metrics.get("candle_history", [])
        if c["t"] >= entry_open_time
    ]
    if not relevant_candles:
        relevant_candles = [{"t": entry_open_time + 1, "h": curr_price, "l": curr_price, "c": curr_price}]

    for c in relevant_candles:
        if c["t"] == entry_open_time and trade.get("order_type", "MARKET") == "MARKET":
            bar_high = curr_price
            bar_low = curr_price
        else:
            bar_high = c["h"]
            bar_low = c["l"]

        if direction == "LONG":
            if bar_low <= sl_price:
                cfg["active_trade"] = None
                stats["total_closed"] += 1
                if bep_moved:
                    stats["bep_hit"] += 1
                    alerts.append(
                        f"🛡️ *POSISI DITUTUP: SL DI AREA ENTRY (1:1 BEP)*\n\n"
                        f"• Arah: `LONG` @ `${entry}`\n"
                        f"• Harga Tersentuh: `${bar_low}`\n"
                        f"• Hasil: `0.00 poin (Aman / Tanpa Risiko)`\n\n"
                        f"{format_stats_text(cfg)}"
                    )
                    return cfg, "CLOSED_BEP", "\n\n---\n\n".join(alerts)
                else:
                    stats["sl_hit"] += 1
                    stats["net_points"] = round(stats["net_points"] - sl_dist, 3)
                    alerts.append(
                        f"❌ *PERINGATAN: TERKENA STOP LOSS*\n\n"
                        f"• Arah: `LONG` @ `${entry}`\n"
                        f"• Batas SL: `${sl_price}` (Tersentuh: `${bar_low}`)\n"
                        f"• Hasil: `-{sl_dist} poin`\n\n"
                        f"{format_stats_text(cfg)}"
                    )
                    return cfg, "CLOSED_SL", "\n\n---\n\n".join(alerts)

            if bar_high >= tp_price:
                cfg["active_trade"] = None
                stats["total_closed"] += 1
                stats["tp_hit"] += 1
                stats["net_points"] = round(stats["net_points"] + tp_dist, 3)
                alerts.append(
                    f"✅ *SELAMAT: TARGET TAKE PROFIT TERCAPAI!*\n\n"
                    f"• Arah: `LONG` @ `${entry}`\n"
                    f"• Target TP: `${tp_price}` (Tersentuh: `${bar_high}`)\n"
                    f"• Profit: `+{tp_dist} poin`\n\n"
                    f"{format_stats_text(cfg)}"
                )
                return cfg, "CLOSED_TP", "\n\n---\n\n".join(alerts)

            if not bep_moved and bar_high >= bep_trigger:
                bep_moved = True
                sl_price = entry
                trade["bep_moved"] = True
                trade["sl_price"] = entry
                cfg["active_trade"] = trade
                alerts.append(
                    f"🔔 *PENGINGAT 1:1 RISK:REWARD — PINDAH SL KE ENTRY!*\n\n"
                    f"• Posisi Aktif: `LONG` @ `${entry}`\n"
                    f"• Harga Mencapai: `${bar_high}` (Target +1R `${bep_trigger}` tercapai)\n"
                    f"• 👉 *Tindakan:* Geser Stop Loss Anda ke area Entry (`${entry}`) agar posisi ini **BEBAS RISIKO (BEP)**!\n"
                    f"• Target TP Akhir Tetap: `${tp_price}` (`+{tp_dist} poin`)"
                )

        elif direction == "SHORT":
            if bar_high >= sl_price:
                cfg["active_trade"] = None
                stats["total_closed"] += 1
                if bep_moved:
                    stats["bep_hit"] += 1
                    alerts.append(
                        f"🛡️ *POSISI DITUTUP: SL DI AREA ENTRY (1:1 BEP)*\n\n"
                        f"• Arah: `SHORT` @ `${entry}`\n"
                        f"• Harga Tersentuh: `${bar_high}`\n"
                        f"• Hasil: `0.00 poin (Aman / Tanpa Risiko)`\n\n"
                        f"{format_stats_text(cfg)}"
                    )
                    return cfg, "CLOSED_BEP", "\n\n---\n\n".join(alerts)
                else:
                    stats["sl_hit"] += 1
                    stats["net_points"] = round(stats["net_points"] - sl_dist, 3)
                    alerts.append(
                        f"❌ *PERINGATAN: TERKENA STOP LOSS*\n\n"
                        f"• Arah: `SHORT` @ `${entry}`\n"
                        f"• Batas SL: `${sl_price}` (Tersentuh: `${bar_high}`)\n"
                        f"• Hasil: `-{sl_dist} poin`\n\n"
                        f"{format_stats_text(cfg)}"
                    )
                    return cfg, "CLOSED_SL", "\n\n---\n\n".join(alerts)

            if bar_low <= tp_price:
                cfg["active_trade"] = None
                stats["total_closed"] += 1
                stats["tp_hit"] += 1
                stats["net_points"] = round(stats["net_points"] + tp_dist, 3)
                alerts.append(
                    f"✅ *SELAMAT: TARGET TAKE PROFIT TERCAPAI!*\n\n"
                    f"• Arah: `SHORT` @ `${entry}`\n"
                    f"• Target TP: `${tp_price}` (Tersentuh: `${bar_low}`)\n"
                    f"• Profit: `+{tp_dist} poin`\n\n"
                    f"{format_stats_text(cfg)}"
                )
                return cfg, "CLOSED_TP", "\n\n---\n\n".join(alerts)

            if not bep_moved and bar_low <= bep_trigger:
                bep_moved = True
                sl_price = entry
                trade["bep_moved"] = True
                trade["sl_price"] = entry
                cfg["active_trade"] = trade
                alerts.append(
                    f"🔔 *PENGINGAT 1:1 RISK:REWARD — PINDAH SL KE ENTRY!*\n\n"
                    f"• Posisi Aktif: `SHORT` @ `${entry}`\n"
                    f"• Harga Mencapai: `${bar_low}` (Target +1R `${bep_trigger}` tercapai)\n"
                    f"• 👉 *Tindakan:* Geser Stop Loss Anda ke area Entry (`${entry}`) agar posisi ini **BEBAS RISIKO (BEP)**!\n"
                    f"• Target TP Akhir Tetap: `${tp_price}` (`+{tp_dist} poin`)"
                )

    if alerts:
        return cfg, "MOVED_BEP", "\n\n---\n\n".join(alerts)

    floating = round((curr_price - entry) if direction == "LONG" else (entry - curr_price), 3)
    sl_note = f"🛡️ Sudah di Entry (`${entry}`)" if bep_moved else f"`${sl_price}`"
    status_msg = (
        f"⏳ *POSISI MASIH BERJALAN (MEMORI AKTIF)*\n\n"
        f"• Posisi: `{direction}` ({trade.get('order_type', 'MARKET')}) sejak `{trade.get('entry_time', '-')}`\n"
        f"• Harga Entry: `${entry}` | Harga Sekarang: `${curr_price}` (`{floating:+} poin`)\n"
        f"• Target TP: `${tp_price}`\n"
        f"• Stop Loss: {sl_note}\n"
        f"• Trigger 1:1 BEP: `${bep_trigger}` ({'Tercapai ✅' if bep_moved else 'Menunggu'})\n"
        f"• Alasan Entry: _{trade.get('reason', '-')}_"
    )
    return cfg, "STILL_RUNNING", status_msg

def build_prompt(current_price, market_summary, gates, cfg):
    tp_val = cfg['tp']
    sl_val = cfg['sl']
    return f"""
    You are an elite institutional quantitative crypto futures analyst for SOL/USDT (5m & 15m momentum execution).
    Default decision MUST be "WAIT" unless ALL 6 gates pass cleanly. Keep text concise and sharp.

    LIVE DATA:
    {market_summary}

    QUANTITATIVE GATES:
    - Volatility & Candle Size (Max 0.35): {gates['vol_status']} ({gates['vol_note']})
    - Suggested Limit Order Levels (Mid-Candle / EMA9): LONG Limit=${gates['suggested_limit_long']} | SHORT Limit=${gates['suggested_limit_short']}
    - Structure: {gates['struct_note']}
    - POI: {gates['poi_note']}
    - Obstacles LONG: {gates['long_obstacles'] or 'Clear'} | SHORT: {gates['short_obstacles'] or 'Clear'}
    - Permissions: allow_long={gates['allow_long']}, allow_short={gates['allow_short']}

    STRATEGY: {cfg['strategy']}

    EXECUTION ORDER TYPE RULES (MARKET vs LIMIT):
    - If recent candle range is wide (0.24 to 0.35 pts), prefer "LIMIT" order near mid-candle / EMA 9 so SL ({sl_val} pts) is safely tucked behind the candle's wick!
    - HOWEVER, if momentum is launching cleanly from a major Support/Resistance or EMA cluster with strong volume/CVD and low risk of pulling back > {sl_val} pts, you MAY choose "MARKET" order even on candle close.

    Output strictly valid compact JSON (no markdown fences, max 16 words per field):
    {{
      "signal": "WAIT" | "LONG" | "SHORT",
      "order_type": "MARKET" | "LIMIT",
      "entry_price": <number: current_price for MARKET, or precise limit_price for LIMIT>,
      "market_regime": "TRENDING" | "SIDEWAYS" | "CHOPPY_EXTREME",
      "audit_6_gates": {{
        "gate1_volatility_sl": "<Lulus/Gagal + singkat>",
        "gate2_mtf_structure": "<Lulus/Gagal + singkat>",
        "gate3_entry_zone_poi": "<Lulus/Gagal + alasan Market/Limit & SL>",
        "gate4_tp_clearance": "<Lulus/Gagal + singkat>",
        "gate5_candlestick_vol": "<Lulus/Gagal + singkat>",
        "gate6_smi_cvd": "<Lulus/Gagal + singkat>"
      }},
      "reasoning": "<Kesimpulan singkat Bahasa Indonesia>"
    }}
    """

def extract_json_safely(raw_text):
    clean = raw_text.replace("```json", "").replace("```", "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        clean = clean[start:end+1]
    return json.loads(clean)

def call_gemini(model_name, prompt, api_key):
    clean_name = model_name.replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_name}:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.15, "maxOutputTokens": 900}
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=45)
    data = response.json()
    
    if response.status_code != 200:
        error_msg = data.get('error', {}).get('message', str(data))
        raise Exception(f"[{clean_name}] HTTP {response.status_code}: {error_msg}")
        
    return data['candidates'][0]['content']['parts'][0]['text']

def call_backup_ai(prompt):
    if not BACKUP_AI_API_KEY:
        raise Exception("BACKUP_AI_API_KEY belum diisi.")
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {BACKUP_AI_API_KEY}'}
    payload = {"model": BACKUP_AI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.15}
    response = requests.post(BACKUP_AI_URL, headers=headers, json=payload, timeout=45)
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"[Backup AI] HTTP {response.status_code}: {data}")
    return data['choices'][0]['message']['content']

def local_quant_fallback(m, gates, cfg):
    price = m["price"]
    signal = "WAIT"
    order_type = "LIMIT" if gates["prefer_limit"] else "MARKET"
    entry_p = price
    regime = "CHOPPY_EXTREME" if gates["vol_status"] != "OPTIMAL" else ("TRENDING" if m["struct_5m"] != 0 else "SIDEWAYS")
    reason = f"{gates['vol_note']} {gates['struct_note']} {gates['poi_note']}"

    c_prev = m["prev_candle"]
    c_curr = m["curr_candle"]
    strong_bull_candle = (c_prev["dir"] == "BULLISH" and c_prev["vol_ratio"] >= 1.0) or (c_curr["dir"] == "BULLISH" and c_curr["body_pct"] >= 55)
    strong_bear_candle = (c_prev["dir"] == "BEARISH" and c_prev["vol_ratio"] >= 1.0) or (c_curr["dir"] == "BEARISH" and c_curr["body_pct"] >= 55)

    if gates["allow_long"] and m["struct_5m"] == 1.0 and m["struct_15m"] == 1.0:
        if m["ema9"] > m["ema20"] > m["ema50"] and price > m["ema9"] and m["smi"] > m["smi_signal"] and m["cvd_15m"] > 0 and strong_bull_candle:
            signal = "LONG"
            entry_p = gates["suggested_limit_long"] if order_type == "LIMIT" else price
            reason = f"Lulus 6 gerbang ({order_type}): Uptrend 5m & 15m selaras, pantulan EMA 9 (${m['ema9']}), candle bullish kuat, SMI & CVD positif."
    elif gates["allow_short"] and m["struct_5m"] == -1.0 and m["struct_15m"] == -1.0:
        if m["ema9"] < m["ema20"] < m["ema50"] and price < m["ema9"] and m["smi"] < m["smi_signal"] and m["cvd_15m"] < 0 and strong_bear_candle:
            signal = "SHORT"
            entry_p = gates["suggested_limit_short"] if order_type == "LIMIT" else price
            reason = f"Lulus 6 gerbang ({order_type}): Downtrend 5m & 15m selaras, penolakan EMA 9 (${m['ema9']}), candle bearish kuat, SMI & CVD negatif."

    res = {
        "signal": signal,
        "order_type": order_type,
        "entry_price": entry_p,
        "market_regime": regime,
        "audit_6_gates": {
            "gate1_volatility_sl": gates["vol_note"],
            "gate2_mtf_structure": gates["struct_note"],
            "gate3_entry_zone_poi": f"{gates['poi_note']} | Mode: {order_type}",
            "gate4_tp_clearance": f"Halangan LONG: {gates['long_obstacles'] or 'Bersih'} | SHORT: {gates['short_obstacles'] or 'Bersih'}",
            "gate5_candlestick_vol": f"Prev: {c_prev['pattern']} (Vol {c_prev['vol_ratio']}x) | Curr: {c_curr['pattern']}",
            "gate6_smi_cvd": f"SMI 5m {m['smi']}/{m['smi_signal']}, CVD 15m ${m['cvd_15m']:+,.0f}"
        },
        "reasoning": reason
    }
    return res, "Argon-Quant-6Gate"

def analyze_market_with_fallback(current_price, market_summary, metrics, gates, cfg):
    prompt = build_prompt(current_price, market_summary, gates, cfg)
    model_priority = [
        "gemini-4-hydrogen",
        "gemma-4-31b-it",
        "gemma-4-26b-a4b-it",
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite-preview"
    ]

    ai_result = None
    used_engine = None

    for key_idx, api_key in enumerate(GEMINI_API_KEYS, start=1):
        for model_name in model_priority:
            try:
                raw = call_gemini(model_name, prompt, api_key)
                ai_result = extract_json_safely(raw)
                used_engine = f"{model_name} (Akun #{key_idx})"
                break
            except Exception as e:
                print(f"Lewati Akun#{key_idx} {model_name}: {e}")
        if ai_result is not None:
            break

    if ai_result is None and BACKUP_AI_API_KEY:
        try:
            raw = call_backup_ai(prompt)
            ai_result = extract_json_safely(raw)
            used_engine = f"Backup ({BACKUP_AI_MODEL})"
        except Exception as e:
            print(f"Lewati Backup AI: {e}")

    if ai_result is None:
        ai_result, used_engine = local_quant_fallback(metrics, gates, cfg)

    sig = str(ai_result.get("signal", "WAIT")).upper()
    if sig == "LONG" and not gates["allow_long"]:
        ai_result["signal"] = "WAIT"
        ai_result["reasoning"] = f"[Diblokir Saringan Ketat] {gates['vol_note']} {gates['struct_note']} {gates['poi_note']}"
    elif sig == "SHORT" and not gates["allow_short"]:
        ai_result["signal"] = "WAIT"
        ai_result["reasoning"] = f"[Diblokir Saringan Ketat] {gates['vol_note']} {gates['struct_note']} {gates['poi_note']}"

    return ai_result, used_engine

if __name__ == "__main__":
    config = load_config()
    config, is_manual_scan = process_telegram_commands(config)
    
    try:
        price, market_summary, metrics = fetch_market_data()
        
        # 1. Jika ada PENDING LIMIT ORDER, pantau terlebih dahulu
        if config.get("pending_order"):
            config, limit_status, limit_msg = monitor_pending_limit_order(config, metrics)
            if limit_status in ["CANCELLED_MISSED", "CANCELLED_EXPIRED", "FILLED"]:
                send_telegram(limit_msg)
            elif limit_status == "WAITING_FILL" and is_manual_scan:
                send_telegram(limit_msg)
            else:
                print("Mode Hening: Limit order masih menunggu jemputan harga.")

        # 2. Jika ada POSISI AKTIF (baik dari Market maupun Limit yang baru saja Filled), pantau TP/SL/BEP
        elif config.get("active_trade"):
            config, trade_status, trade_msg = monitor_active_trade(config, metrics)
            if trade_status in ["CLOSED_TP", "CLOSED_SL", "CLOSED_BEP", "MOVED_BEP"]:
                send_telegram(trade_msg)
            elif trade_status == "STILL_RUNNING" and is_manual_scan:
                send_telegram(trade_msg)
            else:
                print("Mode Hening: Posisi aktif masih berjalan normal.")
                
        # 3. Jika tidak ada posisi maupun limit order, evaluasi setup baru
        else:
            gates = evaluate_quant_gates(metrics, config)
            
            if not gates["allow_long"] and not gates["allow_short"] and not is_manual_scan:
                print(f"Hemat Kuota AI (Mode Hening): Saringan awal menolak peluang -> {gates['vol_note']} | {gates['struct_note']}")
            else:
                ai_data, used_model = analyze_market_with_fallback(price, market_summary, metrics, gates, config)
                sig = str(ai_data.get("signal", "WAIT")).upper()
                order_type = str(ai_data.get("order_type", "MARKET")).upper()
                if order_type not in ["MARKET", "LIMIT"]:
                    order_type = "LIMIT" if gates["prefer_limit"] else "MARKET"
                    
                audit = ai_data.get("audit_6_gates", {})
                reason = ai_data.get("reasoning", "-")
                regime = ai_data.get("market_regime", "-")
                
                if sig in ["LONG", "SHORT"]:
                    tp_dist = float(config["tp"])
                    sl_dist = float(config["sl"])
                    
                    # Tentukan harga entry valid (Market vs Limit)
                    if order_type == "LIMIT":
                        raw_entry = float(ai_data.get("entry_price", 0))
                        if sig == "LONG":
                            entry_p = raw_entry if (price - 0.19) <= raw_entry < price else gates["suggested_limit_long"]
                        else:
                            entry_p = raw_entry if price < raw_entry <= (price + 0.19) else gates["suggested_limit_short"]
                    else:
                        entry_p = price

                    tp_price = round(entry_p + tp_dist, 3) if sig == "LONG" else round(entry_p - tp_dist, 3)
                    sl_price = round(entry_p - sl_dist, 3) if sig == "LONG" else round(entry_p + sl_dist, 3)
                    bep_trigger = round(entry_p + sl_dist, 3) if sig == "LONG" else round(entry_p - sl_dist, 3)
                    status_trade = "🟢 ON (LIVE)" if config["live_trading"] else "🔴 OFF (Dry Run)"

                    if order_type == "LIMIT":
                        config["pending_order"] = {
                            "direction": sig,
                            "limit_price": entry_p,
                            "tp_price": tp_price,
                            "sl_price": sl_price,
                            "initial_sl_dist": sl_dist,
                            "created_open_time": metrics["latest_candle_time"],
                            "created_time": now_wib_str(),
                            "reason": reason
                        }
                        msg = (
                            f"🎯 *SINYAL LIMIT ORDER (JEMPUT TENGAH CANDLE): {sig} LIMIT*\n"
                            f"🤖 Engine: `{used_model}` | Rezim: `{regime}`\n"
                            f"⚙️ Eksekusi: `{status_trade}`\n\n"
                            f"• *Harga Market Sekarang:* `${price}`\n"
                            f"• *Pasang Limit Entry di:* `${entry_p}`\n"
                            f"• *Take Profit:* `${tp_price}` (`+{tp_dist} poin`)\n"
                            f"• *Stop Loss:* `${sl_price}` (`-{sl_dist} poin`)\n"
                            f"• *Batas Batal Otomatis:* Jika harga menjauh `0.21 poin` tanpa menjemput limit\n\n"
                            f"🔍 *Audit 6 Gerbang Strategi:*\n"
                            f"1️⃣ Volatilitas & SL: {audit.get('gate1_volatility_sl', '-')}\n"
                            f"2️⃣ Struktur 5m/15m/1H: {audit.get('gate2_mtf_structure', '-')}\n"
                            f"3️⃣ Area Entry & SL: {audit.get('gate3_entry_zone_poi', '-')}\n"
                            f"4️⃣ Jalur TP 0.60: {audit.get('gate4_tp_clearance', '-')}\n"
                            f"5️⃣ Candle & Volume: {audit.get('gate5_candlestick_vol', '-')}\n"
                            f"6️⃣ SMI & Spot CVD: {audit.get('gate6_smi_cvd', '-')}\n\n"
                            f"💡 *Kesimpulan:* {reason}"
                        )
                        send_telegram(msg)
                    else:
                        config["active_trade"] = {
                            "direction": sig,
                            "order_type": "MARKET",
                            "entry_price": entry_p,
                            "tp_price": tp_price,
                            "sl_price": sl_price,
                            "initial_sl_dist": sl_dist,
                            "bep_trigger_price": bep_trigger,
                            "bep_moved": False,
                            "entry_open_time": metrics["latest_candle_time"],
                            "entry_time": now_wib_str(),
                            "reason": reason
                        }
                        msg = (
                            f"🚨 *SINYAL MARKET ORDER TERKONFIRMASI: {sig}*\n"
                            f"🤖 Engine: `{used_model}` | Rezim: `{regime}`\n"
                            f"⚙️ Eksekusi: `{status_trade}`\n\n"
                            f"• *Entry Langsung:* `${entry_p}`\n"
                            f"• *Take Profit:* `${tp_price}` (`+{tp_dist} poin`)\n"
                            f"• *Stop Loss:* `${sl_price}` (`-{sl_dist} poin`)\n"
                            f"• *Target 1:1 Pindah SL:* `${bep_trigger}`\n\n"
                            f"🔍 *Audit 6 Gerbang Strategi:*\n"
                            f"1️⃣ Volatilitas & SL: {audit.get('gate1_volatility_sl', '-')}\n"
                            f"2️⃣ Struktur 5m/15m/1H: {audit.get('gate2_mtf_structure', '-')}\n"
                            f"3️⃣ Area Entry & SL: {audit.get('gate3_entry_zone_poi', '-')}\n"
                            f"4️⃣ Jalur TP 0.60: {audit.get('gate4_tp_clearance', '-')}\n"
                            f"5️⃣ Candle & Volume: {audit.get('gate5_candlestick_vol', '-')}\n"
                            f"6️⃣ SMI & Spot CVD: {audit.get('gate6_smi_cvd', '-')}\n\n"
                            f"💡 *Kesimpulan:* {reason}"
                        )
                        send_telegram(msg)
                    
                elif is_manual_scan:
                    msg = (
                        f"⏸️ *STATUS: WAIT (DISARING OLEH 6 GERBANG)*\n"
                        f"🤖 Engine: `{used_model}` | Rezim: `{regime}`\n"
                        f"💲 Harga SOL Saat Ini: `${price}` (ATR 5m: `{metrics['atr_5m']}`)\n\n"
                        f"🔍 *Hasil Audit 6 Gerbang:*\n"
                        f"1️⃣ Volatilitas & SL: {audit.get('gate1_volatility_sl', '-')}\n"
                        f"2️⃣ Struktur 5m/15m/1H: {audit.get('gate2_mtf_structure', '-')}\n"
                        f"3️⃣ Area Entry & SL: {audit.get('gate3_entry_zone_poi', '-')}\n"
                        f"4️⃣ Jalur TP 0.60: {audit.get('gate4_tp_clearance', '-')}\n"
                        f"5️⃣ Candle & Volume: {audit.get('gate5_candlestick_vol', '-')}\n"
                        f"6️⃣ SMI & Spot CVD: {audit.get('gate6_smi_cvd', '-')}\n\n"
                        f"💡 *Alasan Menunggu:* {reason}"
                    )
                    send_telegram(msg)

    except Exception as e:
        print(f"Error siklus: {e}")
        if is_manual_scan:
            send_telegram(f"⚠️ *Argon System Warning*\n\n`{str(e)}`")

    save_config(config)
