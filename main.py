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
            "1. Anti-Menebak & Ikuti Tren: Selaraskan arah 5m dengan tren 1h. Dilarang melawan tren kuat kecuali ada lonjakan CVD berlawanan arah + konfirmasi struktur baru (HH/HL atau LH/LL) + divergensi SMI. "
            "2. Pasar Trending: Fokus pada struktur HH/HL/LH/LL, susunan EMA (9, 10, 20, 30, 50, 200), dan dorongan CVD. "
            "3. Pasar Sideways: Fokus pada pantulan Bollinger Bands (Upper/Mid/Lower), Swing High/Low, dan persilangan SMI. "
            "4. Jika harga di zona tanggung/tanpa konfirmasi jelas, pilih WAIT."
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
        sl_status = "🛡️ Sudah pindah ke Entry (BEP)" if active.get("bep_moved") else f"SL Awal (`{active['sl_price']}`)"
        pos_info = (
            f"📌 *POSISI AKTIF:* `{active['direction']}` @ `${active['entry_price']}`\n"
            f"   Target TP: `${active['tp_price']}` | {sl_status}"
        )
    else:
        pos_info = "📌 *POSISI AKTIF:* `Tidak ada (Memantau setup baru)`"

    text = (
        f"{header}\n\n"
        f"• *Mode Eksekusi:* `{status_trade}`\n"
        f"• *Target TP / SL:* `+{cfg['tp']}` / `-{cfg['sl']} poin`\n"
        f"{pos_info}\n\n"
        f"{format_stats_text(cfg)}\n\n"
        f"_(Mode Hening Aktif: Bot hanya mengirim alert otomatis saat ada Entry baru, 1:1 BEP, atau kena TP/SL)_"
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
                    "• `/cek` — Mengecek analisa market / posisi aktif sekarang\n"
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

def detect_structure(highs, lows, lookback=30):
    sub_h = highs[-lookback:]
    sub_l = lows[-lookback:]
    mid = len(sub_h) // 2
    
    prev_swing_high = max(sub_h[:mid])
    last_swing_high = max(sub_h[mid:])
    prev_swing_low = min(sub_l[:mid])
    last_swing_low = min(sub_l[mid:])
    
    if last_swing_high > prev_swing_high and last_swing_low > prev_swing_low:
        trend_code = 1.0
        label = "UPTREND (HH/HL)"
    elif last_swing_high < prev_swing_high and last_swing_low < prev_swing_low:
        trend_code = -1.0
        label = "DOWNTREND (LH/LL)"
    else:
        trend_code = 0.0
        label = "SIDEWAYS / TRANSISI"
        
    return trend_code, label, round(last_swing_high, 3), round(last_swing_low, 3)

def fetch_market_data():
    headers = {'Accept': 'application/json', 'User-Agent': 'Argon-Bot/2.0'}
    
    # 1. Tarik 220 candle 5m agar EMA 200 presisi
    url_5m = "https://data-api.binance.vision/api/v3/klines?symbol=SOLUSDT&interval=5m&limit=220"
    res_5m = requests.get(url_5m, headers=headers, timeout=15)
    if res_5m.status_code != 200:
        raise Exception(f"Gagal tarik data 5m Binance: HTTP {res_5m.status_code}")
    klines = res_5m.json()
    
    opens = [float(k[1]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    vols = [float(k[5]) for k in klines]
    quote_vols = [float(k[7]) for k in klines]
    taker_buy_quotes = [float(k[10]) for k in klines]
    
    current_price = closes[-1]
    
    # Hitung seluruh EMA sesuai skill (9, 10, 20, 30, 50, 200)
    ema9 = round(calc_ema_series(closes, 9)[-1], 3)
    ema10 = round(calc_ema_series(closes, 10)[-1], 3)
    ema20 = round(calc_ema_series(closes, 20)[-1], 3)
    ema30 = round(calc_ema_series(closes, 30)[-1], 3)
    ema50 = round(calc_ema_series(closes, 50)[-1], 3)
    ema200 = round(calc_ema_series(closes, 200)[-1], 3)
    
    # Bollinger Bands (20, 2)
    win20 = closes[-20:]
    bb_mid_val = sum(win20) / 20.0
    std_dev = (sum((x - bb_mid_val) ** 2 for x in win20) / 20.0) ** 0.5
    bb_upper = round(bb_mid_val + 2 * std_dev, 3)
    bb_lower = round(bb_mid_val - 2 * std_dev, 3)
    bb_mid = round(bb_mid_val, 3)
    
    # Stochastic Momentum Index (SMI & Signal)
    smi, smi_signal = calc_smi_series(highs, lows, closes, 10, 3, 3)
    
    # Struktur Pasar 5m
    struct_code, struct_label, swing_high, swing_low = detect_structure(highs, lows, 36)
    
    # Spot CVD (Cumulative Volume Delta dalam USDT) 5m terakhir & 15m (3 bar terakhir)
    deltas_usdt = [2 * tbq - qv for tbq, qv in zip(taker_buy_quotes, quote_vols)]
    cvd_5m = round(deltas_usdt[-1], 0)
    cvd_15m = round(sum(deltas_usdt[-3:]), 0)
    cvd_1h = round(sum(deltas_usdt[-12:]), 0)
    
    # 2. Konteks Timeframe Besar (1H) agar sesuai prinsip Trend-Following Skill
    htf_context = "Tidak tersedia"
    try:
        url_1h = "https://data-api.binance.vision/api/v3/klines?symbol=SOLUSDT&interval=1h&limit=60"
        res_1h = requests.get(url_1h, headers=headers, timeout=10)
        if res_1h.status_code == 200:
            k1h = res_1h.json()
            c1h = [float(k[4]) for k in k1h]
            h1h = [float(k[2]) for k in k1h]
            l1h = [float(k[3]) for k in k1h]
            ema20_1h = round(calc_ema_series(c1h, 20)[-1], 3)
            ema50_1h = round(calc_ema_series(c1h, 50)[-1], 3)
            _, struct_1h_label, _, _ = detect_structure(h1h, l1h, 24)
            htf_context = f"1H Trend: {struct_1h_label} | EMA20(1H): ${ema20_1h} | EMA50(1H): ${ema50_1h}"
    except Exception:
        pass

    last_candles = [
        {"o": round(opens[i], 2), "h": round(highs[i], 2), "l": round(lows[i], 2), "c": round(closes[i], 2), "cvd_usd": round(deltas_usdt[i], 0)}
        for i in range(-6, 0)
    ]
    
    # Ambil range High/Low dari 2 candle terakhir untuk mengecek sentuhan TP/SL/BEP antar jeda cron
    recent_2bar_high = max(highs[-2:])
    recent_2bar_low = min(lows[-2:])

    metrics = {
        "price": current_price,
        "recent_high": recent_2bar_high,
        "recent_low": recent_2bar_low,
        "ema9": ema9, "ema10": ema10, "ema20": ema20, "ema30": ema30, "ema50": ema50, "ema200": ema200,
        "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower,
        "smi": smi, "smi_signal": smi_signal,
        "structure_trend": struct_code, "structure_label": struct_label,
        "last_swing_high": swing_high, "last_swing_low": swing_low,
        "cvd_5m": cvd_5m, "cvd_15m": cvd_15m, "cvd_1h": cvd_1h,
        "htf_context": htf_context,
        "last_open": opens[-1], "last_high": highs[-1], "last_low": lows[-1]
    }
    
    summary = (
        f"Asset: SOL/USDT Perp/Spot | Current Price: ${current_price}\n"
        f"Higher Timeframe Context -> {htf_context}\n"
        f"5M Market Structure -> {struct_label} (code={struct_code}) | Swing High: ${swing_high} | Swing Low: ${swing_low}\n"
        f"5M EMAs -> EMA9: ${ema9} | EMA10: ${ema10} | EMA20: ${ema20} | EMA30: ${ema30} | EMA50: ${ema50} | EMA200: ${ema200}\n"
        f"5M Volatility & Momentum -> BB Upper: ${bb_upper} | BB Mid: ${bb_mid} | BB Lower: ${bb_lower} | SMI: {smi} (Signal: {smi_signal})\n"
        f"Spot Order Flow (CVD USDT) -> 5m: ${cvd_5m:+,.0f} | 15m: ${cvd_15m:+,.0f} | 1h: ${cvd_1h:+,.0f}\n"
        f"Last 6 Candles (5m): {json.dumps(last_candles)}"
    )
    return current_price, summary, metrics

def monitor_active_trade(cfg, metrics):
    """
    Memantau posisi yang sedang aktif.
    Mengembalikan (cfg, status_code, message_to_send_or_None)
    status_code: 'CLOSED_TP', 'CLOSED_SL', 'CLOSED_BEP', 'MOVED_BEP', 'STILL_RUNNING'
    """
    trade = cfg.get("active_trade")
    if not trade:
        return cfg, "NO_TRADE", None

    direction = trade["direction"]
    entry = float(trade["entry_price"])
    tp_price = float(trade["tp_price"])
    sl_price = float(trade["sl_price"])
    bep_trigger = float(trade["bep_trigger_price"])
    bep_moved = bool(trade.get("bep_moved", False))
    
    curr_price = metrics["price"]
    check_high = max(curr_price, metrics["recent_high"])
    check_low = min(curr_price, metrics["recent_low"])
    
    tp_dist = round(abs(tp_price - entry), 3)
    sl_dist = round(float(trade.get("initial_sl_dist", cfg["sl"])), 3)
    stats = cfg["stats"]

    if direction == "LONG":
        # 1. Cek jika terkena SL (atau BEP jika SL sudah dipindah ke entry)
        if check_low <= sl_price:
            cfg["active_trade"] = None
            stats["total_closed"] += 1
            if bep_moved:
                stats["bep_hit"] += 1
                msg = (
                    f"🛡️ *POSISI DITUTUP: SL DI AREA ENTRY (1:1 BEP)*\n\n"
                    f"• Arah: `LONG` @ `${entry}`\n"
                    f"• Harga Tersentuh: `${check_low}`\n"
                    f"• Hasil: `0.00 poin (Aman / Tanpa Risiko)`\n\n"
                    f"{format_stats_text(cfg)}"
                )
                return cfg, "CLOSED_BEP", msg
            else:
                stats["sl_hit"] += 1
                stats["net_points"] = round(stats["net_points"] - sl_dist, 3)
                msg = (
                    f"❌ *PERINGATAN: TERKENA STOP LOSS*\n\n"
                    f"• Arah: `LONG` @ `${entry}`\n"
                    f"• Batas SL: `${sl_price}` (Tersentuh: `${check_low}`)\n"
                    f"• Hasil: `-{sl_dist} poin`\n\n"
                    f"{format_stats_text(cfg)}"
                )
                return cfg, "CLOSED_SL", msg

        # 2. Cek jika terkena Take Profit
        if check_high >= tp_price:
            cfg["active_trade"] = None
            stats["total_closed"] += 1
            stats["tp_hit"] += 1
            stats["net_points"] = round(stats["net_points"] + tp_dist, 3)
            msg = (
                f"✅ *SELAMAT: TARGET TAKE PROFIT TERCAPAI!*\n\n"
                f"• Arah: `LONG` @ `${entry}`\n"
                f"• Target TP: `${tp_price}` (Tersentuh: `${check_high}`)\n"
                f"• Profit: `+{tp_dist} poin`\n\n"
                f"{format_stats_text(cfg)}"
            )
            return cfg, "CLOSED_TP", msg

        # 3. Cek jika baru saja mencapai rasio 1:1 (saatnya pindah SL ke area Entry!)
        if not bep_moved and check_high >= bep_trigger:
            trade["bep_moved"] = True
            trade["sl_price"] = entry
            cfg["active_trade"] = trade
            msg = (
                f"🔔 *PENGINGAT 1:1 RISK:REWARD — PINDAH SL KE ENTRY!*\n\n"
                f"• Posisi Aktif: `LONG` @ `${entry}`\n"
                f"• Harga Saat Ini: `${curr_price}` (Sudah mencapai +1R di `${bep_trigger}`)\n"
                f"• 👉 *Tindakan:* Geser Stop Loss Anda ke area Entry (`${entry}`) agar posisi ini **BEBAS RISIKO (BEP)**!\n"
                f"• Target TP Akhir Tetap: `${tp_price}` (`+{tp_dist} poin`)"
            )
            return cfg, "MOVED_BEP", msg

    elif direction == "SHORT":
        # 1. Cek jika terkena SL (atau BEP)
        if check_high >= sl_price:
            cfg["active_trade"] = None
            stats["total_closed"] += 1
            if bep_moved:
                stats["bep_hit"] += 1
                msg = (
                    f"🛡️ *POSISI DITUTUP: SL DI AREA ENTRY (1:1 BEP)*\n\n"
                    f"• Arah: `SHORT` @ `${entry}`\n"
                    f"• Harga Tersentuh: `${check_high}`\n"
                    f"• Hasil: `0.00 poin (Aman / Tanpa Risiko)`\n\n"
                    f"{format_stats_text(cfg)}"
                )
                return cfg, "CLOSED_BEP", msg
            else:
                stats["sl_hit"] += 1
                stats["net_points"] = round(stats["net_points"] - sl_dist, 3)
                msg = (
                    f"❌ *PERINGATAN: TERKENA STOP LOSS*\n\n"
                    f"• Arah: `SHORT` @ `${entry}`\n"
                    f"• Batas SL: `${sl_price}` (Tersentuh: `${check_high}`)\n"
                    f"• Hasil: `-{sl_dist} poin`\n\n"
                    f"{format_stats_text(cfg)}"
                )
                return cfg, "CLOSED_SL", msg

        # 2. Cek jika terkena Take Profit
        if check_low <= tp_price:
            cfg["active_trade"] = None
            stats["total_closed"] += 1
            stats["tp_hit"] += 1
            stats["net_points"] = round(stats["net_points"] + tp_dist, 3)
            msg = (
                f"✅ *SELAMAT: TARGET TAKE PROFIT TERCAPAI!*\n\n"
                f"• Arah: `SHORT` @ `${entry}`\n"
                f"• Target TP: `${tp_price}` (Tersentuh: `${check_low}`)\n"
                f"• Profit: `+{tp_dist} poin`\n\n"
                f"{format_stats_text(cfg)}"
            )
            return cfg, "CLOSED_TP", msg

        # 3. Cek jika mencapai rasio 1:1
        if not bep_moved and check_low <= bep_trigger:
            trade["bep_moved"] = True
            trade["sl_price"] = entry
            cfg["active_trade"] = trade
            msg = (
                f"🔔 *PENGINGAT 1:1 RISK:REWARD — PINDAH SL KE ENTRY!*\n\n"
                f"• Posisi Aktif: `SHORT` @ `${entry}`\n"
                f"• Harga Saat Ini: `${curr_price}` (Sudah mencapai +1R di `${bep_trigger}`)\n"
                f"• 👉 *Tindakan:* Geser Stop Loss Anda ke area Entry (`${entry}`) agar posisi ini **BEBAS RISIKO (BEP)**!\n"
                f"• Target TP Akhir Tetap: `${tp_price}` (`+{tp_dist} poin`)"
            )
            return cfg, "MOVED_BEP", msg

    # Posisi masih berjalan normal
    floating = round((curr_price - entry) if direction == "LONG" else (entry - curr_price), 3)
    sl_note = f"🛡️ Sudah di Entry (`${entry}`)" if bep_moved else f"`${sl_price}`"
    status_msg = (
        f"⏳ *POSISI MASIH BERJALAN (MEMORI AKTIF)*\n\n"
        f"• Posisi: `{direction}` sejak `{trade.get('entry_time', '-')}`\n"
        f"• Harga Entry: `${entry}` | Harga Sekarang: `${curr_price}` (`{floating:+} poin`)\n"
        f"• Target TP: `${tp_price}`\n"
        f"• Stop Loss: {sl_note}\n"
        f"• Trigger 1:1 BEP: `${bep_trigger}` ({'Tercapai ✅' if bep_moved else 'Menunggu'})\n"
        f"• Alasan Awal: _{trade.get('reason', '-')}_"
    )
    return cfg, "STILL_RUNNING", status_msg

def build_prompt(current_price, market_summary, cfg):
    tp_val = cfg['tp']
    sl_val = cfg['sl']
    return f"""
    You are an autonomous 5-minute timeframe quantitative crypto futures analyst following the user's strict trading skill.
    
    LIVE MARKET & INDICATOR DATA:
    {market_summary}

    USER'S STRATEGY RULES:
    {cfg['strategy']}

    MANDATORY STEP-BY-STEP VERIFICATION BEFORE DECIDING:
    You MUST test the strategy rules one by one in order before outputting a signal:
    - Step 1 (Trend & Structure): Compare 1H trend with 5M structure (HH/HL vs LH/LL). Never fight a strong trend unless Spot CVD strongly surges against it AND a new structure break is confirmed.
    - Step 2 (Adaptive Indicator Check):
      * If TRENDING: Check EMA alignment (9, 10, 20, 30, 50, 200) and pullback/breakout confirmation.
      * If SIDEWAYS: Check Bollinger Bands (Upper/Mid/Lower) bounce and Swing High/Low boundaries.
    - Step 3 (Momentum & Order Flow Confirmation): Verify SMI vs SMI Signal crossover and Spot CVD (5m & 15m).
    - Step 4 (Final Trigger): If ANY required confirmation is missing or price is in a neutral "no man's land", you MUST output "WAIT". Only output "LONG" or "SHORT" when all rules pass right now.

    RISK MANAGEMENT:
    - If LONG: take_profit = {round(current_price + tp_val, 3)}, stop_loss = {round(current_price - sl_val, 3)}
    - If SHORT: take_profit = {round(current_price - tp_val, 3)}, stop_loss = {round(current_price + sl_val, 3)}

    Output strictly valid JSON without markdown fences:
    {{
      "signal": "WAIT" | "LONG" | "SHORT",
      "market_regime": "TRENDING" | "SIDEWAYS",
      "step_by_step_check": {{
        "step1_trend_structure": "<Lulus/Gagal + penjelasan singkat>",
        "step2_adaptive_indicator": "<Lulus/Gagal + penjelasan singkat>",
        "step3_momentum_cvd": "<Lulus/Gagal + penjelasan singkat>"
      }},
      "entry_price": {current_price},
      "take_profit": <number>,
      "stop_loss": <number>,
      "reasoning": "<Kesimpulan Bahasa Indonesia kenapa ENTRY sekarang atau kenapa masih WAIT>"
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
    blocked = ["2.5", "2.0", "1.5", "1.0", "embedding", "imagen", "veo", "tts", "aqa", "robotics", "computer-use", "deep-research", "vision"]
    
    # Utamakan gemini-3.1-flash-lite-preview yang sudah terbukti berjalan lancar di akun Anda
    candidates = ["gemini-3.1-flash-lite-preview", "gemini-3.1-pro-preview"]
    
    try:
        res = requests.get(url, timeout=15).json()
        available = []
        for m in res.get("models", []):
            name = m.get("name", "").replace("models/", "")
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods and not any(b in name.lower() for b in blocked):
                available.append(name)
        
        for prefix in ["gemini-3.1", "gemini-3", "gemma-3", "gemini"]:
            for name in available:
                if name.startswith(prefix) and name not in candidates:
                    candidates.append(name)
    except Exception:
        for fallback in ["gemini-3-flash-preview", "gemma-3-27b-it", "gemma-3-12b-it"]:
            if fallback not in candidates:
                candidates.append(fallback)
                
    return candidates[:8]

def call_backup_ai(prompt):
    if not BACKUP_AI_API_KEY:
        raise Exception("BACKUP_AI_API_KEY belum diisi.")
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {BACKUP_AI_API_KEY}'}
    payload = {"model": BACKUP_AI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
    response = requests.post(BACKUP_AI_URL, headers=headers, json=payload, timeout=60)
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"[Backup AI] HTTP {response.status_code}: {data}")
    return data['choices'][0]['message']['content']

def local_quant_fallback(m, cfg):
    price = m["price"]
    tp_val, sl_val = cfg["tp"], cfg["sl"]
    ema9, ema21, ema50 = m["ema9"], m["ema20"], m["ema50"]
    bb_up, bb_low = m["bb_upper"], m["bb_lower"]
    smi, smi_sig = m["smi"], m["smi_signal"]
    cvd15 = m["cvd_15m"]
    
    is_uptrend = m["structure_trend"] == 1.0 and ema9 > ema21 > ema50
    is_downtrend = m["structure_trend"] == -1.0 and ema9 < ema21 < ema50
    
    signal = "WAIT"
    regime = "TRENDING" if (is_uptrend or is_downtrend) else "SIDEWAYS"
    tp_p = round(price + tp_val, 3)
    sl_p = round(price - sl_val, 3)
    reason = f"Menunggu konfirmasi penuh. Harga ${price}, Struktur: {m['structure_label']}, SMI: {smi}/{smi_sig}, CVD 15m: ${cvd15:+,.0f}."

    if is_uptrend and m["last_low"] <= ema9 and price > ema9 and smi > smi_sig and cvd15 > 0:
        signal = "LONG"
        reason = f"Lulus 3 tahap: Uptrend selaras (EMA9>20>50), pullback rejection di EMA 9 (${ema9}), SMI bullish ({smi}), CVD 15m positif (${cvd15:+,.0f})."
    elif is_downtrend and m["last_high"] >= ema9 and price < ema9 and smi < smi_sig and cvd15 < 0:
        signal = "SHORT"
        tp_p = round(price - tp_val, 3)
        sl_p = round(price + sl_val, 3)
        reason = f"Lulus 3 tahap: Downtrend selaras (EMA9<20<50), rejection di EMA 9 (${ema9}), SMI bearish ({smi}), CVD 15m negatif (${cvd15:+,.0f})."
    elif not is_uptrend and not is_downtrend:
        if price <= bb_low * 1.001 and smi <= -55 and smi > smi_sig:
            signal = "LONG"
            reason = f"Pasar Sideways: Pantulan Lower BB (${bb_low}) terkonfirmasi persilangan naik SMI ({smi} > {smi_sig})."
        elif price >= bb_up * 0.999 and smi >= 55 and smi < smi_sig:
            signal = "SHORT"
            tp_p = round(price - tp_val, 3)
            sl_p = round(price + sl_val, 3)
            reason = f"Pasar Sideways: Penolakan Upper BB (${bb_up}) terkonfirmasi persilangan turun SMI ({smi} < {smi_sig})."

    res = {
        "signal": signal,
        "market_regime": regime,
        "step_by_step_check": {
            "step1_trend_structure": m["structure_label"],
            "step2_adaptive_indicator": f"EMA9 ${ema9} / BB ${bb_low}-${bb_up}",
            "step3_momentum_cvd": f"SMI {smi} vs {smi_sig}, CVD 15m ${cvd15:+,.0f}"
        },
        "entry_price": price,
        "take_profit": tp_p,
        "stop_loss": sl_p,
        "reasoning": reason
    }
    return res, "Argon-Quant-Engine"

def analyze_market_with_fallback(current_price, market_summary, metrics, cfg):
    prompt = build_prompt(current_price, market_summary, cfg)
    candidates = discover_active_google_models()

    for model_name in candidates:
        try:
            raw = call_gemini(model_name, prompt)
            clean = raw.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
            return parsed, model_name
        except Exception as e:
            print(f"Lewati {model_name}: {e}")
            if "503" in str(e):
                time.sleep(2)

    if BACKUP_AI_API_KEY:
        try:
            raw = call_backup_ai(prompt)
            clean = raw.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
            return parsed, f"Backup ({BACKUP_AI_MODEL})"
        except Exception as e:
            print(f"Lewati Backup AI: {e}")

    return local_quant_fallback(metrics, cfg)

if __name__ == "__main__":
    config = load_config()
    config, is_manual_scan = process_telegram_commands(config)
    
    try:
        price, market_summary, metrics = fetch_market_data()
        
        # 1. Cek terlebih dahulu apakah ada posisi aktif dari siklus sebelumnya
        if config.get("active_trade"):
            config, trade_status, trade_msg = monitor_active_trade(config, metrics)
            
            # Kirim pesan jika posisi baru saja menyentuh TP, SL, 1:1 BEP, atau user mengecek manual
            if trade_status in ["CLOSED_TP", "CLOSED_SL", "CLOSED_BEP", "MOVED_BEP"]:
                send_telegram(trade_msg)
            elif trade_status == "STILL_RUNNING" and is_manual_scan:
                send_telegram(trade_msg)
            else:
                print("Mode Hening: Posisi aktif masih berjalan normal, tidak mengirim spam.")
                
        # 2. Jika TIDAK ada posisi aktif, evaluasi setup strategi baru secara bertahap
        else:
            ai_data, used_model = analyze_market_with_fallback(price, market_summary, metrics, config)
            sig = str(ai_data.get("signal", "WAIT")).upper()
            steps = ai_data.get("step_by_step_check", {})
            reason = ai_data.get("reasoning", "-")
            regime = ai_data.get("market_regime", "-")
            
            if sig in ["LONG", "SHORT"]:
                tp_dist = float(config["tp"])
                sl_dist = float(config["sl"])
                tp_price = round(price + tp_dist, 3) if sig == "LONG" else round(price - tp_dist, 3)
                sl_price = round(price - sl_dist, 3) if sig == "LONG" else round(price + sl_dist, 3)
                bep_trigger = round(price + sl_dist, 3) if sig == "LONG" else round(price - sl_dist, 3)
                
                # Simpan posisi baru ke dalam memori config.json
                config["active_trade"] = {
                    "direction": sig,
                    "entry_price": price,
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                    "initial_sl_dist": sl_dist,
                    "bep_trigger_price": bep_trigger,
                    "bep_moved": False,
                    "entry_time": now_wib_str(),
                    "reason": reason
                }
                
                status_trade = "🟢 ON (LIVE)" if config["live_trading"] else "🔴 OFF (Dry Run)"
                msg = (
                    f"🚨 *SINYAL ENTRY TERKONFIRMASI: {sig}*\n"
                    f"🤖 Engine: `{used_model}` | Rezim: `{regime}`\n"
                    f"⚙️ Eksekusi: `{status_trade}`\n\n"
                    f"• *Entry:* `${price}`\n"
                    f"• *Take Profit:* `${tp_price}` (`+{tp_dist} poin`)\n"
                    f"• *Stop Loss:* `${sl_price}` (`-{sl_dist} poin`)\n"
                    f"• *Target 1:1 Pindah SL:* `${bep_trigger}`\n\n"
                    f"🔍 *Audit Strategi Bertahap:*\n"
                    f"1️⃣ Tren & Struktur: {steps.get('step1_trend_structure', '-')}\n"
                    f"2️⃣ Indikator Adaptif: {steps.get('step2_adaptive_indicator', '-')}\n"
                    f"3️⃣ Momentum & CVD: {steps.get('step3_momentum_cvd', '-')}\n\n"
                    f"💡 *Kesimpulan:* {reason}\n\n"
                    f"_(Bot akan terus memantau posisi ini di latar belakang dan memberi tahu saat mencapai 1:1 BEP, TP, atau SL)_"
                )
                send_telegram(msg)
                
            else:
                # Setup masih WAIT: Hanya kirim pesan jika user menekan tombol Cek Sinyal secara manual
                if is_manual_scan:
                    msg = (
                        f"⏸️ *STATUS: WAIT (MENUNGGU KONFIRMASI)*\n"
                        f"🤖 Engine: `{used_model}` | Rezim: `{regime}`\n"
                        f"💲 Harga SOL Saat Ini: `${price}`\n\n"
                        f"🔍 *Hasil Uji Strategi Bertahap:*\n"
                        f"1️⃣ Tren & Struktur: {steps.get('step1_trend_structure', '-')}\n"
                        f"2️⃣ Indikator Adaptif: {steps.get('step2_adaptive_indicator', '-')}\n"
                        f"3️⃣ Momentum & CVD: {steps.get('step3_momentum_cvd', '-')}\n\n"
                        f"💡 *Alasan Belum Entry:* {reason}\n\n"
                        f"_(Mode Hening aktif: Bot tidak akan mengirim notif setiap 5 menit selama status masih WAIT)_"
                    )
                    send_telegram(msg)
                else:
                    print("Mode Hening: Setup masih WAIT, tidak mengirim spam ke Telegram.")

    except Exception as e:
        print(f"Error siklus: {e}")
        if is_manual_scan:
            send_telegram(f"⚠️ *Argon System Warning*\n\n`{str(e)}`")

    # Simpan seluruh perubahan memori posisi, statistik, dan ID chat Telegram ke config.json
    save_config(config)
