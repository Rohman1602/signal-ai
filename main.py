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
        "bot_paused": False,
        "live_trading": False,
        "tp": 0.60,
        "sl": 0.23,
        "strategy": (
            "1. Deteksi Rezim Pasti (ADX 14 + Chop EMA 200): Pastikan pasar TRENDING atau SIDEWAYS. "
            "2. Mode TRENDING: Wajib ikuti struktur (HH/HL untuk LONG, LH/LL untuk SHORT) dan pantulan presisi pada EMA 99 (5m/15m) atau EMA 20/21/50. "
            "3. Mode SIDEWAYS: Hentikan EMA sebagai acuan utama; gunakan peta Support/Resistance 24 jam + SMI jenuh jual/beli + candle konfirmasi. "
            "4. Anti-Pisau Jatuh: Dilarang LONG saat harga/candle masih turun tanpa konfirmasi bullish; dilarang SHORT saat harga/candle masih naik tanpa konfirmasi bearish."
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
                default_cfg.setdefault("bot_paused", False)
        except Exception:
            pass
    return default_cfg

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def register_bot_commands():
    """Mendaftarkan tombol menu perintah resmi ke Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
    commands = [
        {"command": "menu", "description": "Buka panel kendali utama"},
        {"command": "cek", "description": "Audit pasar 24 jam & cek posisi"},
        {"command": "pause", "description": "Jeda pencarian sinyal sementara"},
        {"command": "resume", "description": "Aktifkan kembali pencarian sinyal"},
        {"command": "stats", "description": "Lihat evaluasi TP, SL, dan 1:1 BEP"},
        {"command": "reset_trade", "description": "Hapus posisi aktif / pending limit"}
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=10)
    except Exception:
        pass

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
        f"• 🚫 Limit Dibatalkan: `{cancelled}`\n"
        f"• Win Rate Murni: `{win_rate}%` | Anti-Loss: `{non_loss_rate}%`\n"
        f"• Akumulasi Poin Bersih: `{net:+} poin`"
    )

def send_control_menu(cfg, header="🎛️ *PANEL KENDALI ARGON PRO*"):
    is_paused = bool(cfg.get("bot_paused", False))
    status_bot = "⏸️ PAUSED (Sinyal Dijeda)" if is_paused else "▶️ AKTIF (Memantau Pasar)"
    pause_btn = "▶️ Lanjutkan Sinyal (Resume)" if is_paused else "⏸️ Jeda Sinyal (Pause)"
    
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
        pos_info = f"📌 *STATUS POSISI:* `Kosong (Peta 24J + EMA 99 + ADX/SMI)`"

    text = (
        f"{header}\n\n"
        f"• *Status Scanner:* `{status_bot}`\n"
        f"• *Mode Eksekusi:* `{status_trade}`\n"
        f"• *Target TP / SL:* `+{cfg['tp']}` / `-{cfg['sl']} poin`\n"
        f"{pos_info}\n\n"
        f"{format_stats_text(cfg)}"
    )
    
    keyboard = {
        "inline_keyboard": [
            [{"text": pause_btn, "callback_data": "toggle_pause"}],
            [{"text": toggle_label, "callback_data": "toggle_trading"}],
            [
                {"text": "📊 Cek Pasar 24J", "callback_data": "scan_now"},
                {"text": "📈 Evaluasi", "callback_data": "show_stats"}
            ],
            [
                {"text": "✏️ Panduan", "callback_data": "help_edit"},
                {"text": "🔄 Refresh", "callback_data": "show_menu"}
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
            if action == "toggle_pause":
                cfg["bot_paused"] = not bool(cfg.get("bot_paused", False))
                state_txt = "⏸️ *Bot Dijeda (PAUSED)* — Tidak akan mengirim sinyal baru." if cfg["bot_paused"] else "▶️ *Bot Diaktifkan Kembali (RESUMED)*!"
                send_control_menu(cfg, header=state_txt)
            elif action == "toggle_trading":
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
                    "• `/pause` — Menghentikan pencarian sinyal sementara\n"
                    "• `/resume` — Melanjutkan pencarian sinyal\n"
                    "• `/cek` — Audit peta 24 jam / cek posisi aktif\n"
                    "• `/stats` — Melihat rekap evaluasi TP, SL, & BEP\n"
                    "• `/tp 0.60` | `/sl 0.23` — Ubah target TP / SL\n"
                    "• `/reset_trade` — Hapus posisi aktif / limit menunggu"
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
                register_bot_commands()
                menu_requested = True
            elif lower_text in ["/pause", "pause"]:
                cfg["bot_paused"] = True
                send_control_menu(cfg, header="⏸️ *Pencarian Sinyal Dijeda (PAUSED)*")
            elif lower_text in ["/resume", "resume"]:
                cfg["bot_paused"] = False
                send_control_menu(cfg, header="▶️ *Pencarian Sinyal Diaktifkan (RESUMED)*")
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

def calc_adx(highs, lows, closes, period=14):
    """Menghitung ADX(14) untuk membedakan tren kuat vs pasar sideways secara objektif."""
    if len(closes) < period + 2:
        return 20.0
    plus_dm, minus_dm, tr_list = [0.0], [0.0], [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
        
    tr_s = calc_ema_series(tr_list, period)
    pdm_s = calc_ema_series(plus_dm, period)
    mdm_s = calc_ema_series(minus_dm, period)
    
    dx_list = []
    for tr_v, p_v, m_v in zip(tr_s, pdm_s, mdm_s):
        if tr_v == 0:
            dx_list.append(0.0)
            continue
        p_di = (p_v / tr_v) * 100.0
        m_di = (m_v / tr_v) * 100.0
        denom = p_di + m_di
        dx_list.append((abs(p_di - m_di) / denom) * 100.0 if denom > 0 else 0.0)
        
    adx_series = calc_ema_series(dx_list, period)
    return round(adx_series[-1], 1)

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
    return round(smi_vals[-1], 2), round(smi_sig[-1], 2), round(smi_vals[-2], 2)

def detect_swing_levels(highs, lows, closes, lookback=36):
    """Mendeteksi struktur swing (HH/HL vs LH/LL) dan level S/R penting dari data historis lebar."""
    sub_h = highs[-lookback:]
    sub_l = lows[-lookback:]
    third = len(sub_h) // 3
    
    h1, h2, h3 = max(sub_h[:third]), max(sub_h[third:2*third]), max(sub_h[2*third:])
    l1, l2, l3 = min(sub_l[:third]), min(sub_l[third:2*third]), min(sub_l[2*third:])
    
    # Cek apakah terbentuk Lower High (LH) atau Higher Low (HL) yang valid
    if h3 > h2 and l3 > l2 and closes[-1] > l3:
        return 1.0, "UPTREND (HH/HL)", round(h3, 3), round(l3, 3)
    elif h3 < h2 and l3 < l2 and closes[-1] < h3:
        return -1.0, "DOWNTREND (LH/LL)", round(h3, 3), round(l3, 3)
    elif h3 < h2 and closes[-1] < h3:
        return -0.5, "BEARISH LOWER HIGH (LH)", round(h3, 3), round(l3, 3)
    elif l3 > l2 and closes[-1] > l3:
        return 0.5, "BULLISH HIGHER LOW (HL)", round(h3, 3), round(l3, 3)
    else:
        return 0.0, "RANGE / SIDEWAYS", round(max(h2, h3), 3), round(min(l2, l3), 3)

def map_24h_key_zones(highs_5m, lows_5m, closes_5m):
    """Memetakan peta area penting 24 jam penuh (288 candle 5m) seperti trader profesional."""
    day_high = round(max(highs_5m), 3)
    day_low = round(min(lows_5m), 3)
    day_mid = round((day_high + day_low) / 2.0, 3)
    
    # Cari cluster penolakan (swing pivot) dalam 24 jam terakhir
    pivot_highs = []
    pivot_lows = []
    for i in range(4, len(highs_5m) - 4):
        if highs_5m[i] == max(highs_5m[i-4:i+5]):
            pivot_highs.append(highs_5m[i])
        if lows_5m[i] == min(lows_5m[i-4:i+5]):
            pivot_lows.append(lows_5m[i])
            
    # Kelompokkan zona dengan jarak <= 0.18 poin untuk menemukan area yang diuji berkali-kali
    def cluster_zones(levels):
        if not levels:
            return []
        levels = sorted(levels)
        clusters = [[levels[0]]]
        for lv in levels[1:]:
            if abs(lv - clusters[-1][-1]) <= 0.18:
                clusters[-1].append(lv)
            else:
                clusters.append([lv])
        # Urutkan berdasarkan seberapa sering zona tersebut memantulkan harga
        ranked = sorted(clusters, key=lambda c: len(c), reverse=True)
        return [(round(sum(c)/len(c), 3), len(c)) for c in ranked[:4]]

    major_res_zones = cluster_zones(pivot_highs)
    major_sup_zones = cluster_zones(pivot_lows)
    
    return {
        "day_high": day_high,
        "day_low": day_low,
        "day_mid": day_mid,
        "major_res_zones": major_res_zones,
        "major_sup_zones": major_sup_zones
    }

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
    if body_pct <= 22:
        pattern = "Doji / Indecision"
    elif lower_wick_pct >= 42 and c >= o:
        pattern = "Bullish Rejection Pinbar"
    elif upper_wick_pct >= 42 and c <= o:
        pattern = "Bearish Rejection Pinbar"
    elif body_pct >= 55 and direction == "BULLISH":
        pattern = "Strong Bullish Confirmation"
    elif body_pct >= 55 and direction == "BEARISH":
        pattern = "Strong Bearish Confirmation"
        
    return {
        "dir": direction,
        "open": round(o, 3),
        "close": round(c, 3),
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
    headers = {'Accept': 'application/json', 'User-Agent': 'Argon-Pro/5.0'}
    
    # Tarik 288 candle 5m = 24 JAM PENUH (1 hari) untuk peta area kunci yang luas
    url_5m = "https://data-api.binance.vision/api/v3/klines?symbol=SOLUSDT&interval=5m&limit=288"
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
    ema20 = round(calc_ema_series(closes, 20)[-1], 3)
    ema21 = round(calc_ema_series(closes, 21)[-1], 3)
    ema50 = round(calc_ema_series(closes, 50)[-1], 3)
    ema99_series = calc_ema_series(closes, 99)
    ema99 = round(ema99_series[-1], 3)
    ema200_series = calc_ema_series(closes, 200)
    ema200 = round(ema200_series[-1], 3)
    
    # Hitung berapa kali harga bolak-balik memotong EMA 200 dalam 36 candle (3 jam terakhir)
    ema200_crosses = 0
    for i in range(-36, -1):
        prev_above = closes[i] > ema200_series[i]
        curr_above = closes[i+1] > ema200_series[i+1]
        if prev_above != curr_above:
            ema200_crosses += 1
            
    atr_5m = calc_atr(highs, lows, closes, 14)
    adx_5m = calc_adx(highs, lows, closes, 14)
    
    win20 = closes[-20:]
    bb_mid_val = sum(win20) / 20.0
    std_dev = (sum((x - bb_mid_val) ** 2 for x in win20) / 20.0) ** 0.5
    bb_upper = round(bb_mid_val + 2 * std_dev, 3)
    bb_lower = round(bb_mid_val - 2 * std_dev, 3)
    bb_mid = round(bb_mid_val, 3)
    bb_width_pct = round(((bb_upper - bb_lower) / current_price) * 100, 3)
    
    smi_5m, smi_sig_5m, smi_5m_prev = calc_smi_series(highs, lows, closes, 10, 3, 3)
    struct_5m, struct_5m_label, sh_5m, sl_5m = detect_swing_levels(highs, lows, closes, 36)
    day_map = map_24h_key_zones(highs, lows, closes)
    
    deltas_usdt = [2 * tbq - qv for tbq, qv in zip(taker_buy_quotes, quote_vols)]
    cvd_5m = round(deltas_usdt[-1], 0)
    cvd_15m = round(sum(deltas_usdt[-3:]), 0)
    cvd_1h = round(sum(deltas_usdt[-12:]), 0)
    
    avg_vol_20 = sum(vols[-21:-1]) / 20.0
    prev2_candle_anatomy = analyze_candle_anatomy(opens[-3], highs[-3], lows[-3], closes[-3], vols[-3], avg_vol_20)
    prev_candle_anatomy = analyze_candle_anatomy(opens[-2], highs[-2], lows[-2], closes[-2], vols[-2], avg_vol_20)
    curr_candle_anatomy = analyze_candle_anatomy(opens[-1], highs[-1], lows[-1], closes[-1], vols[-1], avg_vol_20)
    
    # Data 15m (120 candle = 30 jam) untuk EMA 99 15m, ADX 15m, dan SMI 15m
    struct_15m, struct_15m_label, sh_15m, sl_15m = 0.0, "TIDAK TERSEDIA", sh_5m, sl_5m
    ema20_15m, ema50_15m, ema99_15m, ema200_15m = ema20, ema50, ema99, ema200
    smi_15m, smi_sig_15m, smi_15m_prev = smi_5m, smi_sig_5m, smi_5m_prev
    adx_15m = adx_5m
    try:
        url_15m = "https://data-api.binance.vision/api/v3/klines?symbol=SOLUSDT&interval=15m&limit=150"
        res_15m = requests.get(url_15m, headers=headers, timeout=10)
        if res_15m.status_code == 200:
            k15 = res_15m.json()
            h15 = [float(k[2]) for k in k15]
            l15 = [float(k[3]) for k in k15]
            c15 = [float(k[4]) for k in k15]
            struct_15m, struct_15m_label, sh_15m, sl_15m = detect_swing_levels(h15, l15, c15, 24)
            ema20_15m = round(calc_ema_series(c15, 20)[-1], 3)
            ema50_15m = round(calc_ema_series(c15, 50)[-1], 3)
            ema99_15m = round(calc_ema_series(c15, 99)[-1], 3)
            ema200_15m = round(calc_ema_series(c15, 200)[-1], 3)
            smi_15m, smi_sig_15m, smi_15m_prev = calc_smi_series(h15, l15, c15, 10, 3, 3)
            adx_15m = calc_adx(h15, l15, c15, 14)
    except Exception:
        pass

    struct_1h, struct_1h_label, sh_1h, sl_1h = 0.0, "TIDAK TERSEDIA", sh_15m, sl_15m
    try:
        url_1h = "https://data-api.binance.vision/api/v3/klines?symbol=SOLUSDT&interval=1h&limit=60"
        res_1h = requests.get(url_1h, headers=headers, timeout=10)
        if res_1h.status_code == 200:
            k1h = res_1h.json()
            h1h = [float(k[2]) for k in k1h]
            l1h = [float(k[3]) for k in k1h]
            c1h = [float(k[4]) for k in k1h]
            struct_1h, struct_1h_label, sh_1h, sl_1h = detect_swing_levels(h1h, l1h, c1h, 24)
    except Exception:
        pass

    last_candles = [
        {"o": round(opens[i], 2), "h": round(highs[i], 2), "l": round(lows[i], 2), "c": round(closes[i], 2), "cvd": round(deltas_usdt[i], 0)}
        for i in range(-8, 0)
    ]
    
    candle_history = [
        {"t": open_times[i], "h": highs[i], "l": lows[i], "c": closes[i]}
        for i in range(-40, 0)
    ]

    metrics = {
        "price": current_price,
        "latest_candle_time": latest_candle_time,
        "candle_history": candle_history,
        "atr_5m": atr_5m, "adx_5m": adx_5m, "adx_15m": adx_15m, "bb_width_pct": bb_width_pct,
        "ema200_crosses_3h": ema200_crosses,
        "ema9": ema9, "ema20": ema20, "ema21": ema21, "ema50": ema50, "ema99": ema99, "ema200": ema200,
        "ema20_15m": ema20_15m, "ema50_15m": ema50_15m, "ema99_15m": ema99_15m, "ema200_15m": ema200_15m,
        "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower,
        "smi": smi_5m, "smi_signal": smi_sig_5m, "smi_prev": smi_5m_prev,
        "smi_15m": smi_15m, "smi_sig_15m": smi_sig_15m, "smi_15m_prev": smi_15m_prev,
        "struct_5m": struct_5m, "struct_5m_label": struct_5m_label, "sh_5m": sh_5m, "sl_5m": sl_5m,
        "struct_15m": struct_15m, "struct_15m_label": struct_15m_label, "sh_15m": sh_15m, "sl_15m": sl_15m,
        "struct_1h": struct_1h, "struct_1h_label": struct_1h_label, "sh_1h": sh_1h, "sl_1h": sl_1h,
        "day_map": day_map,
        "cvd_5m": cvd_5m, "cvd_15m": cvd_15m, "cvd_1h": cvd_1h,
        "prev2_candle": prev2_candle_anatomy,
        "prev_candle": prev_candle_anatomy,
        "curr_candle": curr_candle_anatomy
    }
    
    summary = (
        f"Asset: SOL/USDT | Current Price: ${current_price}\n"
        f"Regime Diagnostics -> ADX(14) 5m: {adx_5m} | ADX(14) 15m: {adx_15m} | EMA200 Chop Crosses (3h): {ema200_crosses}x | 5M ATR: {atr_5m}\n"
        f"24-Hour Wide Chart Map (288 Candles 5m):\n"
        f"  - 24H High: ${day_map['day_high']} | 24H Mid: ${day_map['day_mid']} | 24H Low: ${day_map['day_low']}\n"
        f"  - Major 24H Resistance Zones (price, touches): {day_map['major_res_zones']}\n"
        f"  - Major 24H Support Zones (price, touches): {day_map['major_sup_zones']}\n"
        f"Multi-Timeframe Structure:\n"
        f"  - 5M Structure: {struct_5m_label} (Swing High: ${sh_5m}, Swing Low: ${sl_5m})\n"
        f"  - 15M Structure: {struct_15m_label} (Swing High: ${sh_15m}, Swing Low: ${sl_15m})\n"
        f"  - 1H Structure: {struct_1h_label}\n"
        f"Key EMAs -> 5M EMA99: ${ema99} | 15M EMA99: ${ema99_15m} | 5M EMA20: ${ema20} | 5M EMA50: ${ema50} | 5M EMA200: ${ema200}\n"
        f"Bollinger Bands (5M) -> Upper: ${bb_upper} | Mid: ${bb_mid} | Lower: ${bb_lower}\n"
        f"Stochastic Momentum Index (SMI) -> 5M: {smi_5m} (prev {smi_5m_prev}, sig {smi_sig_5m}) | 15M: {smi_15m} (prev {smi_15m_prev}, sig {smi_sig_15m})\n"
        f"Spot Order Flow (CVD) -> 5m: ${cvd_5m:+,.0f} | 15m: ${cvd_15m:+,.0f} | 1h: ${cvd_1h:+,.0f}\n"
        f"Candles -> Prev2: {json.dumps(prev2_candle_anatomy)} | PrevClosed: {json.dumps(prev_candle_anatomy)} | Current: {json.dumps(curr_candle_anatomy)}\n"
        f"Last 8 Candles (5m): {json.dumps(last_candles)}"
    )
    return current_price, summary, metrics

def evaluate_professional_setup(m, cfg):
    """
    Menentukan Rezim Pasar secara pasti (TRENDING vs SIDEWAYS),
    melarang entry melawan candle yang masih jatuh/naik tanpa konfirmasi,
    dan hanya mengizinkan setup berprobabilitas tinggi (EMA 99 bounce di trend / S&R 24J + SMI di sideways).
    """
    price = m["price"]
    tp_dist = float(cfg["tp"])
    sl_dist = float(cfg["sl"])
    atr_5m = m["atr_5m"]
    adx_5m = m["adx_5m"]
    adx_15m = m["adx_15m"]
    crosses = m["ema200_crosses_3h"]
    
    c_prev2 = m["prev2_candle"]
    c_prev = m["prev_candle"]
    c_curr = m["curr_candle"]

    # 1. DETEKSI REZIM PASAR YANG PASTI (TRENDING vs SIDEWAYS)
    # Jika harga bolak-balik melewati EMA 200 (>= 3 kali dalam 3 jam) atau ADX lemah (< 21), maka pasar SIDEWAYS!
    is_choppy_ema200 = crosses >= 3
    if is_choppy_ema200 or (adx_5m < 21.0 and adx_15m < 22.0) or (m["struct_5m"] == 0.0 and m["struct_15m"] == 0.0):
        regime = "SIDEWAYS"
        regime_reason = f"SIDEWAYS (ADX 5m={adx_5m}, 15m={adx_15m}, potong EMA200 {crosses}x/3jam) -> Nonaktifkan EMA sebagai pemicu utama, gunakan S/R 24J + SMI + Candle Konfirmasi."
    else:
        regime = "TRENDING"
        regime_reason = f"TRENDING (ADX 5m={adx_5m}, 15m={adx_15m}, 5M: {m['struct_5m_label']}, 15M: {m['struct_15m_label']}) -> Gunakan Struktur LH/LL atau HH/HL + Pantulan EMA 99 / Klaster EMA."

    # 2. CEK VOLATILITAS WAJAR
    if atr_5m > 0.36 or max(c_curr["range"], c_prev["range"]) > 0.45:
        return {
            "regime": "CHOPPY_EXTREME",
            "regime_reason": f"Volatilitas terlalu ekstrem (ATR={atr_5m}), SL {sl_dist} rawan tersapu.",
            "strategy_mode": "HOLD",
            "setup_note": "Menunggu volatilitas mereda.",
            "allow_long": False,
            "allow_short": False,
            "prefer_limit": True,
            "suggested_limit_long": price,
            "suggested_limit_short": price
        }

    # 3. ANTI-PISAU JATUH & WAJIB KONFIRMASI CANDLE BERBALIK
    # Jangan LONG kalau candle sebelumnya merah & candle sekarang masih merah/turun
    bullish_confirmed = (
        (c_prev["dir"] == "BULLISH" and c_prev["body_pct"] >= 35 and c_curr["close"] >= c_prev["open"]) or
        (c_prev["lower_wick_pct"] >= 42 and c_curr["dir"] == "BULLISH") or
        (c_curr["dir"] == "BULLISH" and c_curr["body_pct"] >= 50 and c_curr["close"] > c_prev["high"])
    )
    # Jangan SHORT kalau candle sebelumnya hijau & candle sekarang masih hijau/naik
    bearish_confirmed = (
        (c_prev["dir"] == "BEARISH" and c_prev["body_pct"] >= 35 and c_curr["close"] <= c_prev["open"]) or
        (c_prev["upper_wick_pct"] >= 42 and c_curr["dir"] == "BEARISH") or
        (c_curr["dir"] == "BEARISH" and c_curr["body_pct"] >= 50 and c_curr["close"] < c_prev["low"])
    )

    allow_long = False
    allow_short = False
    setup_notes = []
    strategy_mode = ""

    day_map = m["day_map"]
    res_levels = [day_map["day_high"], m["sh_15m"], m["sh_5m"]] + [z[0] for z in day_map["major_res_zones"]]
    sup_levels = [day_map["day_low"], m["sl_15m"], m["sl_5m"]] + [z[0] for z in day_map["major_sup_zones"]]

    # Jarak toleransi sentuhan level penting
    zone_tol = max(0.18, round(atr_5m * 1.25, 3))

    if regime == "SIDEWAYS":
        strategy_mode = "SIDEWAYS_SR_24H_SMI"
        # Di pasar SIDEWAYS: JANGAN gunakan EMA sebagai indikator utama!
        # Cari harga di area Support/Resistance kuat 24 jam atau Upper/Lower BB + SMI jenuh + candle konfirmasi
        near_major_sup = any(abs(min(price, c_prev["low"], c_curr["low"]) - sup) <= zone_tol for sup in sup_levels) or (c_prev["low"] <= m["bb_lower"] * 1.001)
        near_major_res = any(abs(max(price, c_prev["high"], c_curr["high"]) - res) <= zone_tol for res in res_levels) or (c_prev["high"] >= m["bb_upper"] * 0.999)
        
        smi_bull_turn = (m["smi"] <= -25 or m["smi_15m"] <= -25) and (m["smi"] > m["smi_prev"] or m["smi"] > m["smi_signal"])
        smi_bear_turn = (m["smi"] >= 25 or m["smi_15m"] >= 25) and (m["smi"] < m["smi_prev"] or m["smi"] < m["smi_signal"])

        if near_major_sup and smi_bull_turn and bullish_confirmed:
            allow_long = True
            setup_notes.append(f"SIDEWAYS LONG: Harga memantul dari area Support kuat 24J/BB Lower + SMI jenuh jual ({m['smi']}) berbalik naik + Candle konfirmasi bullish.")
        else:
            setup_notes.append(f"SIDEWAYS LONG belum siap (Sup24J={near_major_sup}, SMI_bull={smi_bull_turn}, CandleBull={bullish_confirmed}).")

        if near_major_res and smi_bear_turn and bearish_confirmed:
            allow_short = True
            setup_notes.append(f"SIDEWAYS SHORT: Harga tertolak di Resistance kuat 24J/BB Upper + SMI jenuh beli ({m['smi']}) berbalik turun + Candle konfirmasi bearish.")
        else:
            setup_notes.append(f"SIDEWAYS SHORT belum siap (Res24J={near_major_res}, SMI_bear={smi_bear_turn}, CandleBear={bearish_confirmed}).")

    else:
        strategy_mode = "TREND_STRUCTURE_EMA99"
        # Di pasar TRENDING: Wajib ikuti struktur (HH/HL atau LH/LL) + Pantulan EMA 99 (5m/15m) atau EMA 20/21/50 + Candle Konfirmasi
        ema99_levels = [m["ema99"], m["ema99_15m"]]
        trend_emas = [m["ema99"], m["ema99_15m"], m["ema20"], m["ema21"], m["ema50"]]
        
        touched_ema99 = any(
            min(abs(price - e99), abs(c_prev["low"] - e99), abs(c_prev["high"] - e99), abs(c_curr["low"] - e99), abs(c_curr["high"] - e99)) <= zone_tol
            for e99 in ema99_levels
        )
        touched_trend_ema = any(
            min(abs(price - e), abs(c_prev["low"] - e), abs(c_prev["high"] - e), abs(c_curr["low"] - e), abs(c_curr["high"] - e)) <= zone_tol
            for e in trend_emas
        )

        # Struktur Naik (HH/HL atau HL) -> Hanya cari LONG setelah pullback ke EMA 99 / trend EMA + candle bullish
        if (m["struct_5m"] > 0 or m["struct_15m"] > 0) and m["struct_5m"] >= 0 and m["struct_15m"] >= 0:
            if (touched_ema99 or touched_trend_ema) and price >= m["ema99"] * 0.9985 and bullish_confirmed:
                allow_long = True
                tag_ema = "EMA 99 (5m/15m)" if touched_ema99 else "EMA Tren (20/21/50)"
                setup_notes.append(f"TREND LONG: Struktur naik ({m['struct_5m_label']}) + pullback menyentuh {tag_ema} + candle konfirmasi bullish.")
            else:
                setup_notes.append(f"TREND LONG menunggu pantulan EMA 99/20/50 & candle bullish (TouchedEMA={touched_trend_ema}, CandleBull={bullish_confirmed}).")

        # Struktur Turun (LH/LL atau LH) -> Hanya cari SHORT setelah pullback naik ke EMA 99 / trend EMA + candle bearish
        if (m["struct_5m"] < 0 or m["struct_15m"] < 0) and m["struct_5m"] <= 0 and m["struct_15m"] <= 0:
            if (touched_ema99 or touched_trend_ema) and price <= m["ema99"] * 1.0015 and bearish_confirmed:
                allow_short = True
                tag_ema = "EMA 99 (5m/15m)" if touched_ema99 else "EMA Tren (20/21/50)"
                setup_notes.append(f"TREND SHORT: Struktur turun ({m['struct_5m_label']}) + pullback naik menyentuh {tag_ema} + candle konfirmasi bearish.")
            else:
                setup_notes.append(f"TREND SHORT menunggu penolakan EMA 99/20/50 & candle bearish (TouchedEMA={touched_trend_ema}, CandleBear={bearish_confirmed}).")

    # 4. PASTIKAN JALUR TP 0.60 POIN MASUK AKAL (TIDAK MENABRAK DINDING UTAMA 24J)
    min_room = round(tp_dist * 0.65, 3)
    if allow_long:
        blocking_res = [r for r in res_levels if 0.12 < (r - price) < min_room]
        if blocking_res:
            allow_long = False
            setup_notes.append(f"LONG dibatalkan: terhalang Resistance kuat di ${blocking_res[0]} sebelum TP +{tp_dist}.")
    if allow_short:
        blocking_sup = [s for s in sup_levels if 0.12 < (price - s) < min_room]
        if blocking_sup:
            allow_short = False
            setup_notes.append(f"SHORT dibatalkan: terhalang Support kuat di ${blocking_sup[0]} sebelum TP -{tp_dist}.")

    prefer_limit = max(c_curr["range"], c_prev["range"]) > 0.25
    suggested_limit_long = round(min(price - 0.04, max(c_curr["mid"], m["ema99"], m["ema21"])), 3)
    suggested_limit_short = round(max(price + 0.04, min(c_curr["mid"], m["ema99"], m["ema21"])), 3)

    return {
        "regime": regime,
        "regime_reason": regime_reason,
        "strategy_mode": strategy_mode,
        "setup_note": " | ".join(setup_notes) if setup_notes else "Belum ada area probabilitas tinggi.",
        "allow_long": allow_long,
        "allow_short": allow_short,
        "prefer_limit": prefer_limit,
        "suggested_limit_long": suggested_limit_long,
        "suggested_limit_short": suggested_limit_short
    }

def monitor_pending_limit_order(cfg, metrics):
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

    relevant_candles = [c for c in metrics.get("candle_history", []) if c["t"] >= created_time]
    if not relevant_candles:
        relevant_candles = [{"t": created_time, "h": curr_price, "l": curr_price, "c": curr_price}]

    for c in relevant_candles:
        bar_high = curr_price if c["t"] == created_time else c["h"]
        bar_low = curr_price if c["t"] == created_time else c["l"]

        if direction == "LONG":
            if (bar_high - limit_p) >= 0.21 and bar_low > limit_p:
                cfg["pending_order"] = None
                cfg["stats"]["cancelled_limits"] += 1
                return cfg, "CANCELLED_MISSED", (
                    f"🚫 *LIMIT ORDER DIBATALKAN (HARGA TERLEWAT)*\n\n"
                    f"• Rencana: `LONG LIMIT` @ `${limit_p}`\n"
                    f"• Harga sudah lari ke `${bar_high}` (`+{round(bar_high - limit_p, 3)} pts`) tanpa menjemput."
                )

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
                return cfg, "FILLED", (
                    f"✅ *LIMIT ORDER TEREKSEKUSI (FILLED): LONG*\n\n"
                    f"• Entry: `${limit_p}` | TP: `${tp_p}` | SL: `${sl_p}`\n"
                    f"• Target 1:1 Pindah SL: `${bep_trigger}`"
                )

        elif direction == "SHORT":
            if (limit_p - bar_low) >= 0.21 and bar_high < limit_p:
                cfg["pending_order"] = None
                cfg["stats"]["cancelled_limits"] += 1
                return cfg, "CANCELLED_MISSED", (
                    f"🚫 *LIMIT ORDER DIBATALKAN (HARGA TERLEWAT)*\n\n"
                    f"• Rencana: `SHORT LIMIT` @ `${limit_p}`\n"
                    f"• Harga sudah jatuh ke `${bar_low}` (`-{round(limit_p - bar_low, 3)} pts`) tanpa menjemput."
                )

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
                return cfg, "FILLED", (
                    f"✅ *LIMIT ORDER TEREKSEKUSI (FILLED): SHORT*\n\n"
                    f"• Entry: `${limit_p}` | TP: `${tp_p}` | SL: `${sl_p}`\n"
                    f"• Target 1:1 Pindah SL: `${bep_trigger}`"
                )

    if len(relevant_candles) > 4:
        cfg["pending_order"] = None
        cfg["stats"]["cancelled_limits"] += 1
        return cfg, "CANCELLED_EXPIRED", (
            f"⌛ *LIMIT ORDER KEDALUWARSA (> 15 MENIT)*\n\n"
            f"• Rencana: `{direction} LIMIT` @ `${limit_p}` dibatalkan otomatis."
        )

    dist_now = round(abs(curr_price - limit_p), 3)
    return cfg, "WAITING_FILL", (
        f"⏳ *LIMIT ORDER MENUNGGU JEMPUTAN*\n\n"
        f"• Rencana: `{direction} LIMIT` @ `${limit_p}` (Jarak: `{dist_now} pts`)\n"
        f"• TP: `${tp_p}` | SL: `${sl_p}`"
    )

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

    relevant_candles = [c for c in metrics.get("candle_history", []) if c["t"] >= entry_open_time]
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
                    alerts.append(f"🛡️ *POSISI DITUTUP: SL DI AREA ENTRY (1:1 BEP)*\n• `LONG` @ `${entry}` | Hasil: `0.00 poin`\n\n{format_stats_text(cfg)}")
                    return cfg, "CLOSED_BEP", "\n\n---\n\n".join(alerts)
                else:
                    stats["sl_hit"] += 1
                    stats["net_points"] = round(stats["net_points"] - sl_dist, 3)
                    alerts.append(f"❌ *PERINGATAN: TERKENA STOP LOSS*\n• `LONG` @ `${entry}` | Hasil: `-{sl_dist} poin`\n\n{format_stats_text(cfg)}")
                    return cfg, "CLOSED_SL", "\n\n---\n\n".join(alerts)

            if bar_high >= tp_price:
                cfg["active_trade"] = None
                stats["total_closed"] += 1
                stats["tp_hit"] += 1
                stats["net_points"] = round(stats["net_points"] + tp_dist, 3)
                alerts.append(f"✅ *SELAMAT: TARGET TAKE PROFIT TERCAPAI!*\n• `LONG` @ `${entry}` | Profit: `+{tp_dist} poin`\n\n{format_stats_text(cfg)}")
                return cfg, "CLOSED_TP", "\n\n---\n\n".join(alerts)

            if not bep_moved and bar_high >= bep_trigger:
                bep_moved = True
                sl_price = entry
                trade["bep_moved"] = True
                trade["sl_price"] = entry
                cfg["active_trade"] = trade
                alerts.append(f"🔔 *1:1 RISK:REWARD TERCAPAI — PINDAH SL KE ENTRY (`${entry}`)*\n• Posisi `LONG` sekarang **BEBAS RISIKO (BEP)** | Target TP: `${tp_price}`")

        elif direction == "SHORT":
            if bar_high >= sl_price:
                cfg["active_trade"] = None
                stats["total_closed"] += 1
                if bep_moved:
                    stats["bep_hit"] += 1
                    alerts.append(f"🛡️ *POSISI DITUTUP: SL DI AREA ENTRY (1:1 BEP)*\n• `SHORT` @ `${entry}` | Hasil: `0.00 poin`\n\n{format_stats_text(cfg)}")
                    return cfg, "CLOSED_BEP", "\n\n---\n\n".join(alerts)
                else:
                    stats["sl_hit"] += 1
                    stats["net_points"] = round(stats["net_points"] - sl_dist, 3)
                    alerts.append(f"❌ *PERINGATAN: TERKENA STOP LOSS*\n• `SHORT` @ `${entry}` | Hasil: `-{sl_dist} poin`\n\n{format_stats_text(cfg)}")
                    return cfg, "CLOSED_SL", "\n\n---\n\n".join(alerts)

            if bar_low <= tp_price:
                cfg["active_trade"] = None
                stats["total_closed"] += 1
                stats["tp_hit"] += 1
                stats["net_points"] = round(stats["net_points"] + tp_dist, 3)
                alerts.append(f"✅ *SELAMAT: TARGET TAKE PROFIT TERCAPAI!*\n• `SHORT` @ `${entry}` | Profit: `+{tp_dist} poin`\n\n{format_stats_text(cfg)}")
                return cfg, "CLOSED_TP", "\n\n---\n\n".join(alerts)

            if not bep_moved and bar_low <= bep_trigger:
                bep_moved = True
                sl_price = entry
                trade["bep_moved"] = True
                trade["sl_price"] = entry
                cfg["active_trade"] = trade
                alerts.append(f"🔔 *1:1 RISK:REWARD TERCAPAI — PINDAH SL KE ENTRY (`${entry}`)*\n• Posisi `SHORT` sekarang **BEBAS RISIKO (BEP)** | Target TP: `${tp_price}`")

    if alerts:
        return cfg, "MOVED_BEP", "\n\n---\n\n".join(alerts)

    floating = round((curr_price - entry) if direction == "LONG" else (entry - curr_price), 3)
    sl_note = f"🛡️ Sudah di Entry (`${entry}`)" if bep_moved else f"`${sl_price}`"
    status_msg = (
        f"⏳ *POSISI AKTIF BERJALAN*\n\n"
        f"• Posisi: `{direction}` ({trade.get('order_type', 'MARKET')}) @ `${entry}`\n"
        f"• Harga Sekarang: `${curr_price}` (`{floating:+} pts`)\n"
        f"• TP: `${tp_price}` | SL: {sl_note}\n"
        f"• Alasan: _{trade.get('reason', '-')}_"
    )
    return cfg, "STILL_RUNNING", status_msg

def build_prompt(current_price, market_summary, eval_data, cfg):
    tp_val = cfg['tp']
    sl_val = cfg['sl']
    return f"""
    You are a disciplined, sniper-grade institutional crypto futures trader for SOL/USDT (5m & 15m).
    You NEVER jump into the market blindly. You inspect the 24-hour wide chart map (288 candles 5m) to locate major Support/Resistance zones and EMA 99 levels, and you strictly enforce market regime separation.

    LIVE DATA (24H WIDE CHART + MTF):
    {market_summary}

    REGIME & QUANT DIAGNOSTICS:
    - Confirmed Regime: {eval_data['regime']} ({eval_data['regime_reason']})
    - Strategy Mode: {eval_data['strategy_mode']}
    - Quantitative Gate Evaluation: {eval_data['setup_note']}
    - Permissions: allow_long={eval_data['allow_long']}, allow_short={eval_data['allow_short']}
    - Suggested Limit Levels: LONG=${eval_data['suggested_limit_long']} | SHORT=${eval_data['suggested_limit_short']}

    USER STRATEGY: {cfg['strategy']}

    STRICT PROFESSIONAL RULES:
    1. NEVER output LONG if allow_long=false; NEVER output SHORT if allow_short=false.
    2. NEVER enter LONG while price/candles are still falling without a confirmed bullish reversal/bounce candle; NEVER enter SHORT while price/candles are rising without a confirmed bearish rejection candle.
    3. If Confirmed Regime is SIDEWAYS (or price is chopping across EMA 200), DO NOT use EMA as primary trigger—use 24H Support/Resistance zones + Stochastic Momentum Index (SMI) oversold/overbought turn + candle confirmation.
    4. If Confirmed Regime is TRENDING, strictly follow trend structure (HH/HL or LH/LL) and look for high-probability bounces off EMA 99 (5m/15m) or EMA 20/21/50 with clear room for TP +{tp_val} and SL {sl_val}.

    Output strictly valid compact JSON (no markdown fences, max 16 words per field):
    {{
      "signal": "WAIT" | "LONG" | "SHORT",
      "order_type": "MARKET" | "LIMIT",
      "entry_price": <number>,
      "market_regime": "{eval_data['regime']}",
      "active_strategy": "{eval_data['strategy_mode']}",
      "key_zone_24h": "<Area kunci 24 jam / EMA 99 yang diuji>",
      "candle_confirmation": "<Konfirmasi candle pembalikan/pantulan>",
      "anticipation": "<Rencana antisipasi jika level tembus / +1R BEP>",
      "reasoning": "<Penjelasan profesional singkat Bahasa Indonesia>"
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
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 900}
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
    payload = {"model": BACKUP_AI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
    response = requests.post(BACKUP_AI_URL, headers=headers, json=payload, timeout=45)
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"[Backup AI] HTTP {response.status_code}: {data}")
    return data['choices'][0]['message']['content']

def local_quant_fallback(m, eval_data, cfg):
    price = m["price"]
    signal = "WAIT"
    order_type = "LIMIT" if eval_data["prefer_limit"] else "MARKET"
    entry_p = price
    
    if eval_data["allow_long"]:
        signal = "LONG"
        entry_p = eval_data["suggested_limit_long"] if order_type == "LIMIT" else price
    elif eval_data["allow_short"]:
        signal = "SHORT"
        entry_p = eval_data["suggested_limit_short"] if order_type == "LIMIT" else price

    res = {
        "signal": signal,
        "order_type": order_type,
        "entry_price": entry_p,
        "market_regime": eval_data["regime"],
        "active_strategy": eval_data["strategy_mode"],
        "key_zone_24h": f"24H H:${m['day_map']['day_high']} L:${m['day_map']['day_low']} | EMA99 5m:${m['ema99']} 15m:${m['ema99_15m']}",
        "candle_confirmation": f"Prev: {m['prev_candle']['pattern']} | Curr: {m['curr_candle']['pattern']}",
        "anticipation": f"Jika menembus balik level kunci, biarkan SL -{cfg['sl']} bekerja; jika tercapai +{cfg['sl']}, geser SL ke entry.",
        "reasoning": eval_data["setup_note"]
    }
    return res, "Argon-Sniper-Engine"

def analyze_market_with_fallback(current_price, market_summary, metrics, eval_data, cfg):
    prompt = build_prompt(current_price, market_summary, eval_data, cfg)
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
        ai_result, used_engine = local_quant_fallback(metrics, eval_data, cfg)

    # Kunci keras: AI tidak pernah boleh meloloskan sinyal jika saringan kuantitatif menolaknya
    sig = str(ai_result.get("signal", "WAIT")).upper()
    if sig == "LONG" and not eval_data["allow_long"]:
        ai_result["signal"] = "WAIT"
        ai_result["reasoning"] = f"[Ditolak Saringan Sniper] {eval_data['setup_note']}"
    elif sig == "SHORT" and not eval_data["allow_short"]:
        ai_result["signal"] = "WAIT"
        ai_result["reasoning"] = f"[Ditolak Saringan Sniper] {eval_data['setup_note']}"

    return ai_result, used_engine

if __name__ == "__main__":
    config = load_config()
    config, is_manual_scan = process_telegram_commands(config)
    
    try:
        price, market_summary, metrics = fetch_market_data()
        
        # 1. Tetap pantau Pending Limit Order atau Posisi Aktif yang sudah terlanjur berjalan meskipun bot di-pause
        if config.get("pending_order"):
            config, limit_status, limit_msg = monitor_pending_limit_order(config, metrics)
            if limit_status in ["CANCELLED_MISSED", "CANCELLED_EXPIRED", "FILLED"]:
                send_telegram(limit_msg)
            elif limit_status == "WAITING_FILL" and is_manual_scan:
                send_telegram(limit_msg)

        elif config.get("active_trade"):
            config, trade_status, trade_msg = monitor_active_trade(config, metrics)
            if trade_status in ["CLOSED_TP", "CLOSED_SL", "CLOSED_BEP", "MOVED_BEP"]:
                send_telegram(trade_msg)
            elif trade_status == "STILL_RUNNING" and is_manual_scan:
                send_telegram(trade_msg)

        # 2. Jika bot sedang PAUSED, jangan cari sinyal baru (kecuali user menekan /cek manual)
        elif config.get("bot_paused", False) and not is_manual_scan:
            print("Bot sedang dalam status PAUSED. Tidak mencari sinyal baru.")
                
        else:
            eval_data = evaluate_professional_setup(metrics, config)
            
            # Hemat Kuota AI: Panggil AI hanya jika setup lolos saringan probabilitas tinggi ATAU user minta /cek manual
            if not eval_data["allow_long"] and not eval_data["allow_short"] and not is_manual_scan:
                print(f"Hemat Kuota AI (Mode Sniper): {eval_data['regime']} | {eval_data['setup_note']}")
            else:
                ai_data, used_model = analyze_market_with_fallback(price, market_summary, metrics, eval_data, config)
                sig = str(ai_data.get("signal", "WAIT")).upper()
                order_type = str(ai_data.get("order_type", "MARKET")).upper()
                if order_type not in ["MARKET", "LIMIT"]:
                    order_type = "LIMIT" if eval_data["prefer_limit"] else "MARKET"
                    
                reason = ai_data.get("reasoning", eval_data["setup_note"])
                anticipation = ai_data.get("anticipation", "Jika level kunci ditembus balik, biarkan SL bekerja; saat +1R pindah SL ke entry.")
                key_zone = ai_data.get("key_zone_24h", f"24H H:${metrics['day_map']['day_high']} L:${metrics['day_map']['day_low']}")
                candle_conf = ai_data.get("candle_confirmation", f"{metrics['prev_candle']['pattern']}")
                
                if sig in ["LONG", "SHORT"]:
                    tp_dist = float(config["tp"])
                    sl_dist = float(config["sl"])
                    
                    if order_type == "LIMIT":
                        raw_entry = float(ai_data.get("entry_price", 0))
                        if sig == "LONG":
                            entry_p = raw_entry if (price - 0.19) <= raw_entry < price else eval_data["suggested_limit_long"]
                        else:
                            entry_p = raw_entry if price < raw_entry <= (price + 0.19) else eval_data["suggested_limit_short"]
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
                            f"🎯 *SINYAL SNIPER LIMIT: {sig} LIMIT*\n"
                            f"🤖 Engine: `{used_model}` | Rezim: `{eval_data['regime']}`\n"
                            f"🧭 Strategi Aktif: `{eval_data['strategy_mode']}`\n"
                            f"⚙️ Eksekusi: `{status_trade}`\n\n"
                            f"• *Harga Market:* `${price}` | *Pasang Limit:* `${entry_p}`\n"
                            f"• *Take Profit:* `${tp_price}` (`+{tp_dist} pts`) | *Stop Loss:* `${sl_price}` (`-{sl_dist} pts`)\n"
                            f"• *Area Kunci 24J / EMA99:* {key_zone}\n"
                            f"• *Konfirmasi Candle:* {candle_conf}\n\n"
                            f"🛡️ *Antisipasi:* {anticipation}\n"
                            f"💡 *Analisis:* {reason}"
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
                            f"🚨 *SINYAL SNIPER TERKONFIRMASI: {sig}*\n"
                            f"🤖 Engine: `{used_model}` | Rezim: `{eval_data['regime']}`\n"
                            f"🧭 Strategi Aktif: `{eval_data['strategy_mode']}`\n"
                            f"⚙️ Eksekusi: `{status_trade}`\n\n"
                            f"• *Entry:* `${entry_p}` | *TP:* `${tp_price}` (`+{tp_dist} pts`) | *SL:* `${sl_price}` (`-{sl_dist} pts`)\n"
                            f"• *Target 1:1 Pindah SL:* `${bep_trigger}`\n"
                            f"• *Area Kunci 24J / EMA99:* {key_zone}\n"
                            f"• *Konfirmasi Candle:* {candle_conf}\n\n"
                            f"🛡️ *Antisipasi:* {anticipation}\n"
                            f"💡 *Analisis:* {reason}"
                        )
                        send_telegram(msg)
                    
                elif is_manual_scan:
                    pause_note = " *(Status Bot: PAUSED)*" if config.get("bot_paused", False) else ""
                    msg = (
                        f"⏸️ *STATUS: WAIT (MENUNGGU AREA KUNCI & KONFIRMASI)*{pause_note}\n"
                        f"🤖 Engine: `{used_model}` | Rezim: `{eval_data['regime']}`\n"
                        f"💲 Harga SOL: `${price}` | ADX 5m: `{metrics['adx_5m']}` | Chop EMA200: `{metrics['ema200_crosses_3h']}x`\n"
                        f"🗺️ Peta 24J: High `${metrics['day_map']['day_high']}` | Mid `${metrics['day_map']['day_mid']}` | Low `${metrics['day_map']['day_low']}`\n"
                        f"📏 EMA 99: 5m `${metrics['ema99']}` | 15m `${metrics['ema99_15m']}` | SMI 5m: `{metrics['smi']}`\n\n"
                        f"🔍 *Evaluasi Sniper:* {eval_data['setup_note']}\n"
                        f"💡 *Kesimpulan:* {reason}"
                    )
                    send_telegram(msg)

    except Exception as e:
        print(f"Error siklus: {e}")
        if is_manual_scan:
            send_telegram(f"⚠️ *Argon System Warning*\n\n`{str(e)}`")

    save_config(config)
