import os
import json
import time
from datetime import datetime, timezone, timedelta
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = str(os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

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
            "1. Volatilitas (ATR 5m): Tolak entry jika volatilitas terlalu ekstrem (SL 0.23 rawan tersapu noise) atau market terlalu mati untuk mengejar TP 0.60. "
            "2. Dominasi Struktur 5m & 15m: Walaupun tren 1H turun, DILARANG SHORT jika 5m/15m masih membentuk struktur naik (HH/HL), tunggu konfirmasi struktur jelas. "
            "3. Area Entry Presisi: Wajib entry di area kunci (EMA 9/20/50, BB extreme, atau breakout-retest struktur), dilarang entry di harga tanggung. "
            "4. Jalur TP Bersih: Pastikan tidak ada tembok Support/Resistance besar (Swing 5m/15m/1H atau EMA 200) yang menghalangi jalur menuju TP 0.60. "
            "5. Konfirmasi Candlestick & SL Aman: Wajib ada konfirmasi bentuk candle dengan volume kuat, dan posisi SL 0.23 terlindung di balik struktur/ekor candle. "
            "6. Momentum & Order Flow: SMI dan Spot CVD (5m & 15m) wajib searah."
        ),
        "last_update_id": 0,
        "active_trade": None,
        "stats": {
            "total_closed": 0,
            "tp_hit": 0,
            "sl_hit": 0,
            "bep_hit": 0,
            "net_points": 0.0
        }
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                loaded = json.load(f)
                default_cfg.update(loaded)
                if "stats" not in default_cfg or not isinstance(default_cfg["stats"], dict):
                    default_cfg["stats"] = {"total_closed": 0, "tp_hit": 0, "sl_hit": 0, "bep_hit": 0, "net_points": 0.0}
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
    net = round(s.get("net_points", 0.0), 3)
    win_rate = round((tp_hit / total) * 100, 1) if total > 0 else 0.0
    non_loss_rate = round(((tp_hit + bep_hit) / total) * 100, 1) if total > 0 else 0.0
    
    return (
        f"📊 *EVALUASI KINERJA SINYAL*\n"
        f"• Total Selesai: `{total} trade`\n"
        f"• ✅ Kena TP: `{tp_hit}`\n"
        f"• 🛡️ Kena SL di Entry (1:1 BEP): `{bep_hit}`\n"
        f"• ❌ Kena SL Awal: `{sl_hit}`\n"
        f"• Win Rate Murni: `{win_rate}%` | Anti-Loss: `{non_loss_rate}%`\n"
        f"• Akumulasi Poin Bersih: `{net:+} poin`"
    )

def send_control_menu(cfg, header="🎛️ *PANEL KENDALI ARGON BOT*"):
    status_trade = "🟢 ON (LIVE)" if cfg["live_trading"] else "🔴 OFF (Signal Only)"
    toggle_label = "🔴 Matikan Auto-Trading" if cfg["live_trading"] else "🟢 Aktifkan Auto-Trading"
    
    active = cfg.get("active_trade")
    if active:
        sl_status = "🛡️ Sudah pindah ke Entry (BEP)" if active.get("bep_moved") else f"SL Awal (`${active['sl_price']}`)"
        pos_info = (
            f"📌 *POSISI AKTIF:* `{active['direction']}` @ `${active['entry_price']}`\n"
            f"   Target TP: `${active['tp_price']}` | {sl_status}"
        )
    else:
        pos_info = "📌 *POSISI AKTIF:* `Tidak ada (Saringan 6 Gerbang Aktif)`"

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
                    "• `/cek` — Audit market 6 gerbang / cek posisi aktif\n"
                    "• `/stats` — Melihat rekap evaluasi TP, SL, dan 1:1 BEP\n"
                    "• `/tp 0.60` — Mengubah target Take Profit (poin)\n"
                    "• `/sl 0.23` — Mengubah batas Stop Loss (poin)\n"
                    "• `/strategi [aturan]` — Mengubah aturan strategi AI\n"
                    "• `/reset_trade` — Menghapus posisi aktif yang sedang dipantau\n"
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
                send_telegram("🗑️ Posisi aktif dihapus dari memori. Bot kembali memantau setup baru.")
            elif lower_text == "/reset_stats":
                cfg["stats"] = {"total_closed": 0, "tp_hit": 0, "sl_hit": 0, "bep_hit": 0, "net_points": 0.0}
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
        pattern = "Bullish Rejection Pinbar (Lower Wick Kuat)"
    elif upper_wick_pct >= 50 and c <= o:
        pattern = "Bearish Rejection Pinbar (Upper Wick Kuat)"
    elif body_pct >= 65 and direction == "BULLISH":
        pattern = "Strong Bullish Momentum Body"
    elif body_pct >= 65 and direction == "BEARISH":
        pattern = "Strong Bearish Momentum Body"
        
    return {
        "dir": direction,
        "range": round(total_range, 3),
        "body_pct": body_pct,
        "upper_wick_pct": upper_wick_pct,
        "lower_wick_pct": lower_wick_pct,
        "vol_ratio": vol_ratio,
        "pattern": pattern
    }

def fetch_market_data():
    headers = {'Accept': 'application/json', 'User-Agent': 'Argon-Bot/3.0'}
    
    # 1. Data 5 Menit (220 candle)
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
    
    # 2. Data 15 Menit (100 candle) — Krusial untuk konfirmasi struktur menengah
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

    # 3. Data 1 Jam (60 candle) — Konteks tren makro
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
        "curr_candle": curr_candle_anatomy,
        "last_2_high": max(highs[-2:]),
        "last_2_low": min(lows[-2:])
    }
    
    summary = (
        f"Asset: SOL/USDT | Current Price: ${current_price}\n"
        f"Volatility -> 5M ATR(14): {atr_5m} pts | 15M ATR(14): {atr_15m} pts | BB Width: {bb_width_pct}%\n"
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
    """
    Saringan Kuantitatif Keras sebelum AI mengambil keputusan:
    Memeriksa Volatilitas, Dominasi Struktur 5m/15m, Area POI, dan Halangan TP 0.60.
    """
    price = m["price"]
    tp_dist = float(cfg["tp"])
    sl_dist = float(cfg["sl"])
    atr_5m = m["atr_5m"]
    
    # 1. Evaluasi Volatilitas terhadap SL (0.23) & TP (0.60)
    max_safe_atr = round(sl_dist * 1.12, 3)  # ~0.258 pts
    max_candle_rng = round(sl_dist * 1.65, 3)  # ~0.380 pts
    min_viable_atr = 0.065
    
    vol_status = "OPTIMAL"
    vol_note = f"ATR 5m ({atr_5m}) ideal untuk SL {sl_dist} & TP {tp_dist}."
    allow_long = True
    allow_short = True
    
    if atr_5m > max_safe_atr or m["curr_candle"]["range"] > max_candle_rng or m["prev_candle"]["range"] > max_candle_rng:
        vol_status = "TERLALU_EKSTREM"
        vol_note = f"Volatilitas terlalu liar (ATR 5m={atr_5m}, Range={m['curr_candle']['range']}). SL {sl_dist} poin sangat rawan tersapu noise."
        allow_long = False
        allow_short = False
    elif atr_5m < min_viable_atr and m["bb_width_pct"] < 0.35:
        vol_status = "TERLALU_LAMBAT"
        vol_note = f"Market terlalu sepi/mati (ATR 5m={atr_5m}, BB Width={m['bb_width_pct']}%). Sulit menjangkau TP {tp_dist} poin."
        allow_long = False
        allow_short = False

    # 2. Dominasi Struktur 5m & 15m (Jangan lawan 5m/15m yang sedang membangun struktur)
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
        # Di pasar sideways murni, hanya izinkan pantulan di dekat batas luar BB / Swing
        if price > m["bb_lower"] + (m["bb_upper"] - m["bb_lower"]) * 0.25:
            allow_long = False
        if price < m["bb_upper"] - (m["bb_upper"] - m["bb_lower"]) * 0.25:
            allow_short = False
        struct_note += " -> Pasar sideways, entry dibatasi hanya di tepi ekstrem Bollinger Bands."

    # 3. Cek Area Entry (Point of Interest / POI) - Dilarang entry di ruang kosong
    key_levels = [
        m["ema9"], m["ema20"], m["ema50"], m["ema20_15m"],
        m["bb_upper"], m["bb_mid"], m["bb_lower"],
        m["sh_5m"], m["sl_5m"], m["sh_15m"], m["sl_15m"]
    ]
    nearest_dist = min(abs(price - lvl) for lvl in key_levels)
    max_poi_dist = max(0.14, round(atr_5m * 1.15, 3))
    poi_valid = nearest_dist <= max_poi_dist
    poi_note = (
        f"Valid (jarak {round(nearest_dist, 3)} poin dari level kunci terdekat)"
        if poi_valid else
        f"Tidak Valid / No Man's Land (jarak {round(nearest_dist, 3)} poin dari level teknikal terdekat, batas {max_poi_dist})"
    )
    if not poi_valid:
        allow_long = False
        allow_short = False

    # 4. Pemindai Halangan S/R Menuju Target TP (0.60 poin)
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
    
    # Cari penghalang signifikan yang jaraknya > 0.08 tapi < 72% dari target TP (0.43 poin)
    min_clear_room = round(tp_dist * 0.72, 3)
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

    return {
        "vol_status": vol_status,
        "vol_note": vol_note,
        "struct_note": struct_note,
        "poi_valid": poi_valid,
        "poi_note": poi_note,
        "long_obstacles": long_obstacles,
        "short_obstacles": short_obstacles,
        "allow_long": allow_long,
        "allow_short": allow_short
    }

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
        if c["t"] == entry_open_time:
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
        f"• Posisi: `{direction}` sejak `{trade.get('entry_time', '-')}`\n"
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
    Your job is to PROTECT CAPITAL and FILTER OUT low-probability trades. Your default decision MUST be "WAIT" unless ALL 6 analytical gates pass cleanly.

    LIVE MULTI-TIMEFRAME MARKET DATA:
    {market_summary}

    PRE-COMPUTED QUANTITATIVE GATE AUDIT:
    - Volatility Status: {gates['vol_status']} ({gates['vol_note']})
    - Structure Dominance Check: {gates['struct_note']}
    - Entry Zone (POI) Check: {gates['poi_note']}
    - Obstacles Blocking LONG TP (+{tp_val}): {gates['long_obstacles'] if gates['long_obstacles'] else 'Jalur bersih'}
    - Obstacles Blocking SHORT TP (-{tp_val}): {gates['short_obstacles'] if gates['short_obstacles'] else 'Jalur bersih'}
    - Hard Gate Permissions -> allow_long={gates['allow_long']}, allow_short={gates['allow_short']}

    USER STRATEGY RULES:
    {cfg['strategy']}

    STRICT DECISION RULES:
    1. If allow_long is false, you MUST NOT output LONG. If allow_short is false, you MUST NOT output SHORT.
    2. Even if 1H is bearish, if 5m or 15m is forming bullish structure (HH/HL), NEVER output SHORT—wait for clear 5m & 15m bearish structure confirmation. Same in reverse for LONG.
    3. Never enter at random mid-range prices. Explain the exact technical Point of Interest (POI) for entry and confirm why SL ({sl_val} pts) is structurally protected behind a candle wick or EMA/Swing level.
    4. Require clear candlestick confirmation (e.g., rejection pinbar, momentum close, or engulfing with volume >= 1.0x average). Reject weak Doji/indecision candles.
    5. Verify SMI crossover and Spot CVD (5m & 15m) momentum alignment.

    RISK MANAGEMENT:
    - LONG: take_profit = {round(current_price + tp_val, 3)}, stop_loss = {round(current_price - sl_val, 3)}
    - SHORT: take_profit = {round(current_price - tp_val, 3)}, stop_loss = {round(current_price + sl_val, 3)}

    Output strictly valid JSON without markdown fences:
    {{
      "signal": "WAIT" | "LONG" | "SHORT",
      "market_regime": "TRENDING" | "SIDEWAYS" | "CHOPPY_EXTREME",
      "audit_6_gates": {{
        "gate1_volatility_sl": "<Lulus/Gagal + alasan ATR vs SL 0.23>",
        "gate2_mtf_structure": "<Lulus/Gagal + keselarasan 5m, 15m, dan 1H>",
        "gate3_entry_zone_poi": "<Lulus/Gagal + area entry & posisi SL>",
        "gate4_tp_clearance": "<Lulus/Gagal + ada/tidaknya halangan S/R menuju TP 0.60>",
        "gate5_candlestick_vol": "<Lulus/Gagal + bentuk candle & rasio volume>",
        "gate6_smi_cvd": "<Lulus/Gagal + arah SMI & Spot CVD>"
      }},
      "entry_price": {current_price},
      "take_profit": <number>,
      "stop_loss": <number>,
      "reasoning": "<Kesimpulan tajam Bahasa Indonesia kenapa ENTRY valid di titik ini atau kenapa wajib WAIT>"
    }}
    """

def call_gemini(model_name, prompt):
    clean_name = model_name.replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_name}:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    data = response.json()
    
    if response.status_code != 200:
        error_msg = data.get('error', {}).get('message', str(data))
        raise Exception(f"[{clean_name}] HTTP {response.status_code}: {error_msg}")
        
    return data['candidates'][0]['content']['parts'][0]['text']

def discover_active_google_models():
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    blocked = ["2.5", "2.0", "1.5", "1.0", "embedding", "imagen", "veo", "tts", "aqa", "robotics", "computer-use", "deep-research", "vision", "live", "transcribe", "omni"]
    
    # Prioritas Utama: Gemini 4 Hydrogen sebagai otak #1
    candidates = [
        "gemini-4-hydrogen",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite-preview"
    ]
    
    try:
        res = requests.get(url, timeout=15).json()
        available = []
        for m in res.get("models", []):
            name = m.get("name", "").replace("models/", "")
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods and not any(b in name.lower() for b in blocked):
                available.append(name)
        
        for prefix in ["gemini-4-hydrogen", "gemini-4-argon", "gemini-3.8", "gemini-3.6", "gemini-3.5", "gemini-3.1", "gemma-3"]:
            for name in available:
                if name.startswith(prefix) and name not in candidates:
                    candidates.append(name)
    except Exception:
        for fallback in ["gemma-3-27b-it", "gemma-3-12b-it"]:
            if fallback not in candidates:
                candidates.append(fallback)
                
    return candidates[:8]

def call_backup_ai(prompt):
    if not BACKUP_AI_API_KEY:
        raise Exception("BACKUP_AI_API_KEY belum diisi.")
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {BACKUP_AI_API_KEY}'}
    payload = {"model": BACKUP_AI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.15}
    response = requests.post(BACKUP_AI_URL, headers=headers, json=payload, timeout=60)
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"[Backup AI] HTTP {response.status_code}: {data}")
    return data['choices'][0]['message']['content']

def local_quant_fallback(m, gates, cfg):
    price = m["price"]
    tp_val, sl_val = cfg["tp"], cfg["sl"]
    
    signal = "WAIT"
    regime = "CHOPPY_EXTREME" if gates["vol_status"] != "OPTIMAL" else ("TRENDING" if m["struct_5m"] != 0 else "SIDEWAYS")
    tp_p = round(price + tp_val, 3)
    sl_p = round(price - sl_val, 3)
    reason = f"Saringan ketat aktif: {gates['vol_note']} {gates['struct_note']}"

    c_prev = m["prev_candle"]
    c_curr = m["curr_candle"]
    strong_bull_candle = (c_prev["dir"] == "BULLISH" and c_prev["vol_ratio"] >= 1.0) or (c_curr["dir"] == "BULLISH" and c_curr["body_pct"] >= 55)
    strong_bear_candle = (c_prev["dir"] == "BEARISH" and c_prev["vol_ratio"] >= 1.0) or (c_curr["dir"] == "BEARISH" and c_curr["body_pct"] >= 55)

    if gates["allow_long"] and m["struct_5m"] == 1.0 and m["struct_15m"] == 1.0:
        if m["ema9"] > m["ema20"] > m["ema50"] and price > m["ema9"] and m["smi"] > m["smi_signal"] and m["cvd_15m"] > 0 and strong_bull_candle:
            signal = "LONG"
            reason = f"Lulus 6 gerbang kuantitatif: Struktur 5m & 15m selaras Uptrend, harga memantul di atas EMA 9 (${m['ema9']}), candle bullish terkonfirmasi, SMI & CVD 15m positif."
    elif gates["allow_short"] and m["struct_5m"] == -1.0 and m["struct_15m"] == -1.0:
        if m["ema9"] < m["ema20"] < m["ema50"] and price < m["ema9"] and m["smi"] < m["smi_signal"] and m["cvd_15m"] < 0 and strong_bear_candle:
            signal = "SHORT"
            tp_p = round(price - tp_val, 3)
            sl_p = round(price + sl_val, 3)
            reason = f"Lulus 6 gerbang kuantitatif: Struktur 5m & 15m selaras Downtrend, harga tertolak di bawah EMA 9 (${m['ema9']}), candle bearish terkonfirmasi, SMI & CVD 15m negatif."

    res = {
        "signal": signal,
        "market_regime": regime,
        "audit_6_gates": {
            "gate1_volatility_sl": gates["vol_note"],
            "gate2_mtf_structure": gates["struct_note"],
            "gate3_entry_zone_poi": gates["poi_note"],
            "gate4_tp_clearance": f"Halangan LONG: {gates['long_obstacles'] or 'Bersih'} | SHORT: {gates['short_obstacles'] or 'Bersih'}",
            "gate5_candlestick_vol": f"Prev: {c_prev['pattern']} (Vol {c_prev['vol_ratio']}x) | Curr: {c_curr['pattern']}",
            "gate6_smi_cvd": f"SMI 5m {m['smi']}/{m['smi_signal']}, CVD 15m ${m['cvd_15m']:+,.0f}"
        },
        "entry_price": price,
        "take_profit": tp_p,
        "stop_loss": sl_p,
        "reasoning": reason
    }
    return res, "Argon-Quant-6Gate"

def analyze_market_with_fallback(current_price, market_summary, metrics, gates, cfg):
    prompt = build_prompt(current_price, market_summary, gates, cfg)
    candidates = discover_active_google_models()

    ai_result = None
    used_engine = None

    for model_name in candidates:
        try:
            raw = call_gemini(model_name, prompt)
            clean = raw.replace("```json", "").replace("```", "").strip()
            ai_result = json.loads(clean)
            used_engine = model_name
            break
        except Exception as e:
            print(f"Lewati {model_name}: {e}")
            if "503" in str(e):
                time.sleep(2)

    if ai_result is None and BACKUP_AI_API_KEY:
        try:
            raw = call_backup_ai(prompt)
            clean = raw.replace("```json", "").replace("```", "").strip()
            ai_result = json.loads(clean)
            used_engine = f"Backup ({BACKUP_AI_MODEL})"
        except Exception as e:
            print(f"Lewati Backup AI: {e}")

    if ai_result is None:
        ai_result, used_engine = local_quant_fallback(metrics, gates, cfg)

    # Pengaman Mutlak Python: Jika saringan keras menolak arah tersebut, paksa WAIT
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
        
        if config.get("active_trade"):
            config, trade_status, trade_msg = monitor_active_trade(config, metrics)
            
            if trade_status in ["CLOSED_TP", "CLOSED_SL", "CLOSED_BEP", "MOVED_BEP"]:
                send_telegram(trade_msg)
            elif trade_status == "STILL_RUNNING" and is_manual_scan:
                send_telegram(trade_msg)
            else:
                print("Mode Hening: Posisi aktif masih berjalan normal.")
                
        else:
            gates = evaluate_quant_gates(metrics, config)
            ai_data, used_model = analyze_market_with_fallback(price, market_summary, metrics, gates, config)
            sig = str(ai_data.get("signal", "WAIT")).upper()
            audit = ai_data.get("audit_6_gates", {})
            reason = ai_data.get("reasoning", "-")
            regime = ai_data.get("market_regime", "-")
            
            if sig in ["LONG", "SHORT"]:
                tp_dist = float(config["tp"])
                sl_dist = float(config["sl"])
                tp_price = round(price + tp_dist, 3) if sig == "LONG" else round(price - tp_dist, 3)
                sl_price = round(price - sl_dist, 3) if sig == "LONG" else round(price + sl_dist, 3)
                bep_trigger = round(price + sl_dist, 3) if sig == "LONG" else round(price - sl_dist, 3)
                
                config["active_trade"] = {
                    "direction": sig,
                    "entry_price": price,
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                    "initial_sl_dist": sl_dist,
                    "bep_trigger_price": bep_trigger,
                    "bep_moved": False,
                    "entry_open_time": metrics["latest_candle_time"],
                    "entry_time": now_wib_str(),
                    "reason": reason
                }
                
                status_trade = "🟢 ON (LIVE)" if config["live_trading"] else "🔴 OFF (Dry Run)"
                msg = (
                    f"🚨 *SINYAL ENTRY TERKONFIRMASI (LOLOS 6 GERBANG): {sig}*\n"
                    f"🤖 Engine: `{used_model}` | Rezim: `{regime}`\n"
                    f"⚙️ Eksekusi: `{status_trade}`\n\n"
                    f"• *Entry:* `${price}`\n"
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
                
            else:
                if is_manual_scan:
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
                else:
                    print("Mode Hening: Setup belum lolos 6 gerbang (WAIT).")

    except Exception as e:
        print(f"Error siklus: {e}")
        if is_manual_scan:
            send_telegram(f"⚠️ *Argon System Warning*\n\n`{str(e)}`")

    save_config(config)
