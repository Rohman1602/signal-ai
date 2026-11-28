import os
import json
import copy
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

DEFAULT_RULES = {
    "adx_sideways_5m_max": 21.0,
    "adx_sideways_15m_max": 22.0,
    "ema200_chop_crosses_min": 3,
    "smi_trend_long_max": -10.0,
    "smi_trend_short_min": 10.0,
    "smi_sideways_long_max": -25.0,
    "smi_sideways_short_min": 25.0,
    "sideways_require_15m_bb": True,
    "sideways_require_24h_sr": True,
    "require_candle_close_5m_15m": True,
    "max_atr_5m": 0.36,
    "max_candle_range_5m": 0.45,
    "min_bb_width_pct": 0.0,
    "custom_extra_rules": []
}


def now_wib_str():
    return datetime.now(WIB).strftime("%d/%m %H:%M WIB")


def load_config():
    default_cfg = {
        "bot_paused": False,
        "live_trading": False,
        "tp": 0.60,
        "sl": 0.23,
        "rules": copy.deepcopy(DEFAULT_RULES),
        "strategy": (
            "1. Deteksi Rezim Pasti (ADX 14 + Chop EMA 200): TRENDING atau SIDEWAYS. "
            "2. Mode TRENDING: Struktur HH/HL atau LH/LL + pantulan EMA 99 (5m/15m) atau EMA 20/21/50 + SMI 5m jenuh/koreksi wajar berbalik arah. "
            "3. Mode SIDEWAYS: Acuan 15m (BB 15m + SMI 15m jenuh berbalik arah + S/R 24J), eksekusi di 5m. "
            "4. Validasi Tutup Candle 5m & 15m: Candle tutup terakhir 5m dan 15m tidak boleh berlawanan dengan arah entry."
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
                merged_rules = copy.deepcopy(DEFAULT_RULES)
                if isinstance(loaded.get("rules"), dict):
                    merged_rules.update(loaded["rules"])
                if not isinstance(merged_rules.get("custom_extra_rules"), list):
                    merged_rules["custom_extra_rules"] = []
                default_cfg["rules"] = merged_rules
                if not isinstance(default_cfg.get("stats"), dict):
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
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
    commands = [
        {"command": "menu", "description": "Buka panel kendali utama"},
        {"command": "rules", "description": "Lihat semua angka indikator & aturan aktif"},
        {"command": "cek", "description": "Audit pasar 24 jam & cek posisi"},
        {"command": "tanya", "description": "Tanya AI kondisi & rencana bot saat ini"},
        {"command": "pause", "description": "Jeda pencarian sinyal sementara"},
        {"command": "resume", "description": "Aktifkan kembali pencarian sinyal"},
        {"command": "stats", "description": "Lihat evaluasi TP, SL, dan 1:1 BEP"},
        {"command": "reset_rules", "description": "Kembalikan parameter aturan ke default"},
        {"command": "reset_trade", "description": "Hapus posisi aktif / pending limit"},
        {"command": "reset_stats", "description": "Reset statistik evaluasi ke 0"}
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=10)
    except Exception:
        pass


def send_telegram(text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Gagal kirim Telegram: {e}")


def format_rules_text(cfg):
    r = cfg.get("rules", DEFAULT_RULES)
    extra = r.get("custom_extra_rules", [])
    extra_txt = "\n".join([f"  {i+1}. {item}" for i, item in enumerate(extra)]) if extra else "  _Belum ada aturan tambahan khusus_"
    return (
        f"⚙️ *PARAMETER & ATURAN AKTIF BOT*\n\n"
        f"• *Target TP / SL:* `+{cfg['tp']}` / `-{cfg['sl']} poin`\n"
        f"• *Batas Rezim Sideways:* ADX 5m `< {r['adx_sideways_5m_max']}`, 15m `< {r['adx_sideways_15m_max']}`, Chop EMA200 `>= {r['ema200_chop_crosses_min']}x`\n"
        f"• *SMI Mode Trending (5m):* LONG `<= {r['smi_trend_long_max']}` | SHORT `>= {r['smi_trend_short_min']}`\n"
        f"• *SMI Mode Sideways (15m):* LONG `<= {r['smi_sideways_long_max']}` | SHORT `>= {r['smi_sideways_short_min']}`\n"
        f"• *Filter Sideways 15m BB:* `{'AKTIF' if r['sideways_require_15m_bb'] else 'NONAKTIF'}` | *S/R 24J:* `{'AKTIF' if r['sideways_require_24h_sr'] else 'NONAKTIF'}`\n"
        f"• *Validasi Tutup Candle 5m & 15m:* `{'AKTIF' if r['require_candle_close_5m_15m'] else 'NONAKTIF'}`\n"
        f"• *Batas Volatilitas:* Max ATR 5m `{r['max_atr_5m']}` | Max Range `{r['max_candle_range_5m']}` | Min BB Width `{r['min_bb_width_pct']}%`\n"
        f"• *Aturan Tambahan dari Chat:*\n{extra_txt}\n\n"
        f"💬 _Ketik kalimat biasa di chat ini untuk mengubah angka atau menambah aturan baru._"
    )


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
        f"• ✅ Kena TP: `{tp_hit}` | 🛡️ 1:1 BEP: `{bep_hit}` | ❌ SL Awal: `{sl_hit}` | 🚫 Limit Batal: `{cancelled}`\n"
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
        sl_status = "🛡️ Sudah di Entry (BEP)" if active.get("bep_moved") else f"SL Awal (`${active['sl_price']}`)"
        pos_info = f"📌 *POSISI AKTIF:* `{active['direction']}` @ `${active['entry_price']}` | TP: `${active['tp_price']}` | {sl_status}"
    elif pending:
        pos_info = f"⏳ *LIMIT MENUNGGU:* `{pending['direction']}` @ `${pending['limit_price']}` | TP: `${pending['tp_price']}` | SL: `${pending['sl_price']}`"
    else:
        pos_info = "📌 *STATUS POSISI:* `Kosong (Kendali Penuh via Chat Telegram)`"

    text = (
        f"{header}\n\n"
        f"• *Status Scanner:* `{status_bot}`\n"
        f"• *Mode Eksekusi:* `{status_trade}` | *TP/SL:* `+{cfg['tp']}` / `-{cfg['sl']} poin`\n"
        f"{pos_info}\n\n"
        f"{format_stats_text(cfg)}"
    )
    keyboard = {
        "inline_keyboard": [
            [{"text": pause_btn, "callback_data": "toggle_pause"}],
            [{"text": toggle_label, "callback_data": "toggle_trading"}],
            [{"text": "📊 Cek Pasar 24J", "callback_data": "scan_now"}, {"text": "⚙️ Aturan & Angka", "callback_data": "show_rules"}],
            [{"text": "📈 Evaluasi", "callback_data": "show_stats"}, {"text": "🔄 Refresh", "callback_data": "show_menu"}]
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
        return cfg, False, None

    if not res.get("ok"):
        return cfg, False, None

    menu_requested = False
    manual_scan_requested = False
    user_messages = []

    for update in res.get("result", []):
        cfg["last_update_id"] = update["update_id"]

        if "callback_query" in update:
            cb = update["callback_query"]
            if str(cb["from"]["id"]) != TELEGRAM_CHAT_ID:
                continue
            try:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": cb["id"]}, timeout=10)
            except Exception:
                pass

            action = cb.get("data", "")
            if action == "toggle_pause":
                cfg["bot_paused"] = not bool(cfg.get("bot_paused", False))
                send_control_menu(cfg, header="⏸️ *Bot Dijeda (PAUSED)*" if cfg["bot_paused"] else "▶️ *Bot Diaktifkan Kembali (RESUMED)*")
            elif action == "toggle_trading":
                cfg["live_trading"] = not cfg["live_trading"]
                send_control_menu(cfg, header="✅ *Status Auto-Trading Diperbarui!*")
            elif action == "show_menu":
                send_control_menu(cfg)
            elif action == "show_stats":
                send_telegram(format_stats_text(cfg))
            elif action == "show_rules":
                send_telegram(format_rules_text(cfg))
            elif action == "scan_now":
                manual_scan_requested = True

        elif "message" in update and "text" in update["message"]:
            msg = update["message"]
            if str(msg["chat"]["id"]) != TELEGRAM_CHAT_ID:
                continue

            text = msg["text"].strip()
            low = text.lower()

            if low in ["/start", "/menu", "menu"]:
                register_bot_commands()
                menu_requested = True
            elif low in ["/rules", "/aturan", "aturan", "rules"]:
                send_telegram(format_rules_text(cfg))
            elif low in ["/pause", "pause"]:
                cfg["bot_paused"] = True
                send_control_menu(cfg, header="⏸️ *Pencarian Sinyal Dijeda (PAUSED)*")
            elif low in ["/resume", "resume"]:
                cfg["bot_paused"] = False
                send_control_menu(cfg, header="▶️ *Pencarian Sinyal Diaktifkan (RESUMED)*")
            elif low in ["/cek", "cek", "/scan"]:
                manual_scan_requested = True
            elif low in ["/stats", "stats"]:
                send_telegram(format_stats_text(cfg))
            elif low == "/reset_rules":
                cfg["rules"] = copy.deepcopy(DEFAULT_RULES)
                cfg["tp"] = 0.60
                cfg["sl"] = 0.23
                send_telegram("🔄 Semua parameter aturan & angka indikator dikembalikan ke default.")
            elif low == "/reset_trade":
                cfg["active_trade"] = None
                cfg["pending_order"] = None
                send_telegram("🗑️ Posisi aktif & pending limit order dihapus dari memori.")
            elif low == "/reset_stats":
                cfg["stats"] = {"total_closed": 0, "tp_hit": 0, "sl_hit": 0, "bep_hit": 0, "cancelled_limits": 0, "net_points": 0.0}
                send_telegram("🔄 Statistik evaluasi berhasil direset ke 0.")
            elif low.startswith("/tp "):
                try:
                    cfg["tp"] = float(text.split(" ", 1)[1].replace(",", "."))
                    send_telegram(f"✅ Take Profit diubah menjadi *+{cfg['tp']} poin*.")
                except ValueError:
                    send_telegram("⚠️ Contoh format: `/tp 0.60`")
            elif low.startswith("/sl "):
                try:
                    cfg["sl"] = float(text.split(" ", 1)[1].replace(",", "."))
                    send_telegram(f"✅ Stop Loss diubah menjadi *-{cfg['sl']} poin*.")
                except ValueError:
                    send_telegram("⚠️ Contoh format: `/sl 0.23`")
            elif low.startswith("/strategi "):
                new_strat = text.split(" ", 1)[1].strip()
                if new_strat:
                    user_messages.append(f"Ubah strategi/aturan menjadi: {new_strat}")
            elif low.startswith("/tanya"):
                q_body = text[6:].strip()
                user_messages.append(q_body if q_body else "Jelaskan strategi yang sedang dijalankan bot saat ini dan rencana eksekusi berikutnya.")
            elif not text.startswith("/"):
                user_messages.append(text)

    if menu_requested:
        send_control_menu(cfg)

    combined = "\n".join(user_messages).strip() if user_messages else None
    return cfg, manual_scan_requested, combined


def calc_ema_series(values, period):
    k = 2 / (period + 1)
    ema_list = [values[0]]
    for v in values[1:]:
        ema_list.append(v * k + ema_list[-1] * (1 - k))
    return ema_list


def calc_bb(closes, period=20, mult=2.0):
    win = closes[-period:]
    mid_val = sum(win) / float(period)
    std_dev = (sum((x - mid_val) ** 2 for x in win) / float(period)) ** 0.5
    return round(mid_val + mult * std_dev, 3), round(mid_val, 3), round(mid_val - mult * std_dev, 3)


def calc_atr(highs, lows, closes, period=14):
    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return round(calc_ema_series(trs, period)[-1], 4)


def calc_adx(highs, lows, closes, period=14):
    if len(closes) < period + 2:
        return 20.0
    plus_dm, minus_dm, tr_list = [0.0], [0.0], [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
        tr_list.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    tr_s = calc_ema_series(tr_list, period)
    pdm_s = calc_ema_series(plus_dm, period)
    mdm_s = calc_ema_series(minus_dm, period)
    dx_list = []
    for tr_v, p_v, m_v in zip(tr_s, pdm_s, mdm_s):
        if tr_v == 0:
            dx_list.append(0.0)
            continue
        p_di, m_di = (p_v / tr_v) * 100.0, (m_v / tr_v) * 100.0
        denom = p_di + m_di
        dx_list.append((abs(p_di - m_di) / denom) * 100.0 if denom > 0 else 0.0)
    return round(calc_ema_series(dx_list, period)[-1], 1)


def calc_smi_series(highs, lows, closes, length=10, smooth1=3, smooth2=3):
    rel_diff, hl_range = [], []
    for i in range(len(closes)):
        start = max(0, i - length + 1)
        hh = max(highs[start:i + 1])
        ll = min(lows[start:i + 1])
        rel_diff.append(closes[i] - (hh + ll) / 2.0)
        hl_range.append(hh - ll)

    d2 = calc_ema_series(calc_ema_series(rel_diff, smooth1), smooth2)
    r2 = calc_ema_series(calc_ema_series(hl_range, smooth1), smooth2)
    smi_vals = [(num / (den / 2.0)) * 100.0 if den != 0 else 0.0 for num, den in zip(d2, r2)]
    smi_sig = calc_ema_series(smi_vals, smooth2)
    return round(smi_vals[-1], 2), round(smi_sig[-1], 2), round(smi_vals[-2], 2)


def detect_swing_levels(highs, lows, closes, lookback=36):
    sub_h, sub_l = highs[-lookback:], lows[-lookback:]
    t = len(sub_h) // 3
    h1, h2, h3 = max(sub_h[:t]), max(sub_h[t:2 * t]), max(sub_h[2 * t:])
    l1, l2, l3 = min(sub_l[:t]), min(sub_l[t:2 * t]), min(sub_l[2 * t:])

    if h3 > h2 and l3 > l2 and closes[-1] > l3:
        return 1.0, "UPTREND (HH/HL)", round(h3, 3), round(l3, 3)
    if h3 < h2 and l3 < l2 and closes[-1] < h3:
        return -1.0, "DOWNTREND (LH/LL)", round(h3, 3), round(l3, 3)
    if h3 < h2 and closes[-1] < h3:
        return -0.5, "BEARISH LOWER HIGH (LH)", round(h3, 3), round(l3, 3)
    if l3 > l2 and closes[-1] > l3:
        return 0.5, "BULLISH HIGHER LOW (HL)", round(h3, 3), round(l3, 3)
    return 0.0, "RANGE / SIDEWAYS", round(max(h2, h3), 3), round(min(l2, l3), 3)


def map_24h_key_zones(highs_5m, lows_5m):
    day_high, day_low = round(max(highs_5m), 3), round(min(lows_5m), 3)
    piv_h, piv_l = [], []
    for i in range(4, len(highs_5m) - 4):
        if highs_5m[i] == max(highs_5m[i - 4:i + 5]):
            piv_h.append(highs_5m[i])
        if lows_5m[i] == min(lows_5m[i - 4:i + 5]):
            piv_l.append(lows_5m[i])

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
        ranked = sorted(clusters, key=len, reverse=True)
        return [(round(sum(c) / len(c), 3), len(c)) for c in ranked[:4]]

    return {
        "day_high": day_high,
        "day_low": day_low,
        "day_mid": round((day_high + day_low) / 2.0, 3),
        "major_res_zones": cluster_zones(piv_h),
        "major_sup_zones": cluster_zones(piv_l)
    }


def analyze_candle_anatomy(o, h, l, c, v, avg_v):
    rng = max(h - l, 0.001)
    body = abs(c - o)
    body_pct = round((body / rng) * 100, 1)
    up_wick_pct = round(((h - max(o, c)) / rng) * 100, 1)
    lo_wick_pct = round(((min(o, c) - l) / rng) * 100, 1)
    direction = "BULLISH" if c > o else ("BEARISH" if c < o else "DOJI")
    return {
        "dir": direction,
        "open": round(o, 3),
        "close": round(c, 3),
        "high": round(h, 3),
        "low": round(l, 3),
        "mid": round((h + l) / 2.0, 3),
        "range": round(rng, 3),
        "body_pct": body_pct,
        "upper_wick_pct": up_wick_pct,
        "lower_wick_pct": lo_wick_pct,
        "vol_ratio": round(v / avg_v, 2) if avg_v > 0 else 1.0
    }


def fetch_market_data():
    headers = {"Accept": "application/json", "User-Agent": "Argon-Pro/6.1"}
    res_5m = requests.get("https://data-api.binance.vision/api/v3/klines?symbol=SOLUSDT&interval=5m&limit=288", headers=headers, timeout=15)
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
    taker_buy = [float(k[10]) for k in k5]

    price = closes[-1]
    ema9 = round(calc_ema_series(closes, 9)[-1], 3)
    ema20 = round(calc_ema_series(closes, 20)[-1], 3)
    ema21 = round(calc_ema_series(closes, 21)[-1], 3)
    ema50 = round(calc_ema_series(closes, 50)[-1], 3)
    ema99 = round(calc_ema_series(closes, 99)[-1], 3)
    ema200_s = calc_ema_series(closes, 200)
    ema200 = round(ema200_s[-1], 3)

    crosses = sum(1 for i in range(-36, -1) if (closes[i] > ema200_s[i]) != (closes[i + 1] > ema200_s[i + 1]))
    atr_5m = calc_atr(highs, lows, closes, 14)
    adx_5m = calc_adx(highs, lows, closes, 14)
    bb_up, bb_mid, bb_lo = calc_bb(closes, 20, 2.0)
    bb_width_pct = round(((bb_up - bb_lo) / price) * 100, 3)
    smi_5m, smi_sig_5m, smi_5m_prev = calc_smi_series(highs, lows, closes, 10, 3, 3)
    struct_5m, struct_5m_lbl, sh_5m, sl_5m = detect_swing_levels(highs, lows, closes, 36)
    day_map = map_24h_key_zones(highs, lows)

    deltas = [2 * tb - qv for tb, qv in zip(taker_buy, quote_vols)]
    avg_v20 = sum(vols[-21:-1]) / 20.0
    prev_c = analyze_candle_anatomy(opens[-2], highs[-2], lows[-2], closes[-2], vols[-2], avg_v20)
    curr_c = analyze_candle_anatomy(opens[-1], highs[-1], lows[-1], closes[-1], vols[-1], avg_v20)

    struct_15m, struct_15m_lbl, sh_15m, sl_15m = 0.0, "N/A", sh_5m, sl_5m
    ema99_15m = ema99
    bb_up_15m, bb_mid_15m, bb_lo_15m = bb_up, bb_mid, bb_lo
    hi_15m, lo_15m = highs[-1], lows[-1]
    smi_15m, smi_sig_15m, smi_15m_prev = smi_5m, smi_sig_5m, smi_5m_prev
    adx_15m = adx_5m
    prev_c15 = prev_c

    try:
        res_15m = requests.get("https://data-api.binance.vision/api/v3/klines?symbol=SOLUSDT&interval=15m&limit=150", headers=headers, timeout=10)
        if res_15m.status_code == 200:
            k15 = res_15m.json()
            o15, h15, l15, c15, v15 = [float(k[1]) for k in k15], [float(k[2]) for k in k15], [float(k[3]) for k in k15], [float(k[4]) for k in k15], [float(k[5]) for k in k15]
            prev_c15 = analyze_candle_anatomy(o15[-2], h15[-2], l15[-2], c15[-2], v15[-2], sum(v15[-21:-1]) / 20.0)
            struct_15m, struct_15m_lbl, sh_15m, sl_15m = detect_swing_levels(h15, l15, c15, 24)
            ema99_15m = round(calc_ema_series(c15, 99)[-1], 3)
            bb_up_15m, bb_mid_15m, bb_lo_15m = calc_bb(c15, 20, 2.0)
            hi_15m, lo_15m = round(max(h15[-2], h15[-1]), 3), round(min(l15[-2], l15[-1]), 3)
            smi_15m, smi_sig_15m, smi_15m_prev = calc_smi_series(h15, l15, c15, 10, 3, 3)
            adx_15m = calc_adx(h15, l15, c15, 14)
    except Exception:
        pass

    metrics = {
        "price": price,
        "latest_candle_time": open_times[-1],
        "candle_history": [{"t": open_times[i], "h": highs[i], "l": lows[i], "c": closes[i]} for i in range(-40, 0)],
        "atr_5m": atr_5m, "adx_5m": adx_5m, "adx_15m": adx_15m, "bb_width_pct": bb_width_pct,
        "ema200_crosses_3h": crosses,
        "ema9": ema9, "ema20": ema20, "ema21": ema21, "ema50": ema50, "ema99": ema99, "ema200": ema200, "ema99_15m": ema99_15m,
        "bb_upper": bb_up, "bb_mid": bb_mid, "bb_lower": bb_lo,
        "bb_upper_15m": bb_up_15m, "bb_mid_15m": bb_mid_15m, "bb_lower_15m": bb_lo_15m,
        "high_15m_recent": hi_15m, "low_15m_recent": lo_15m,
        "smi": smi_5m, "smi_signal": smi_sig_5m, "smi_prev": smi_5m_prev,
        "smi_15m": smi_15m, "smi_sig_15m": smi_sig_15m, "smi_15m_prev": smi_15m_prev,
        "struct_5m": struct_5m, "struct_5m_label": struct_5m_lbl, "sh_5m": sh_5m, "sl_5m": sl_5m,
        "struct_15m": struct_15m, "struct_15m_label": struct_15m_lbl, "sh_15m": sh_15m, "sl_15m": sl_15m,
        "day_map": day_map,
        "cvd_15m": round(sum(deltas[-3:]), 0),
        "prev_candle": prev_c,
        "curr_candle": curr_c,
        "prev_candle_15m": prev_c15
    }

    summary = (
        f"SOL/USDT: ${price} | ADX 5m/15m: {adx_5m}/{adx_15m} | EMA200 Cross(3h): {crosses}x | ATR5m: {atr_5m} | BBWidth: {bb_width_pct}%\n"
        f"24H Range: High ${day_map['day_high']} | Mid ${day_map['day_mid']} | Low ${day_map['day_low']} | Res: {day_map['major_res_zones']} | Sup: {day_map['major_sup_zones']}\n"
        f"Structure -> 5M: {struct_5m_lbl} | 15M: {struct_15m_lbl}\n"
        f"EMAs -> 5M EMA99:${ema99}, EMA20:${ema20}, EMA50:${ema50}, EMA200:${ema200} | 15M EMA99:${ema99_15m}\n"
        f"BB 15M -> Upper:${bb_up_15m}, Mid:${bb_mid_15m}, Lower:${bb_lo_15m} | BB 5M -> Upper:${bb_up}, Lower:${bb_lo}\n"
        f"SMI -> 5M: {smi_5m} (prev {smi_5m_prev}, sig {smi_sig_5m}) | 15M: {smi_15m} (prev {smi_15m_prev}, sig {smi_sig_15m})\n"
        f"Closed Candles -> Prev5M: {prev_c['dir']} (body {prev_c['body_pct']}%) | Prev15M: {prev_c15['dir']} (body {prev_c15['body_pct']}%) | Curr5M: {curr_c['dir']}"
    )
    return price, summary, metrics


def evaluate_professional_setup(m, cfg):
    r = cfg.get("rules", DEFAULT_RULES)
    price = m["price"]
    tp_dist, sl_dist = float(cfg["tp"]), float(cfg["sl"])
    atr_5m, adx_5m, adx_15m, crosses = m["atr_5m"], m["adx_5m"], m["adx_15m"], m["ema200_crosses_3h"]
    c_prev, c_curr, c15_prev = m["prev_candle"], m["curr_candle"], m["prev_candle_15m"]

    adx5_max = float(r.get("adx_sideways_5m_max", 21.0))
    adx15_max = float(r.get("adx_sideways_15m_max", 22.0))
    is_chop = crosses >= int(r.get("ema200_chop_crosses_min", 3))

    if is_chop or (adx_5m < adx5_max and adx_15m < adx15_max) or (m["struct_5m"] == 0.0 and m["struct_15m"] == 0.0):
        regime = "SIDEWAYS"
        regime_reason = f"SIDEWAYS (ADX 5m={adx_5m}, 15m={adx_15m}, potong EMA200 {crosses}x) -> Acuan 15m BB+SMI, eksekusi 5m."
    else:
        regime = "TRENDING"
        regime_reason = f"TRENDING (ADX 5m={adx_5m}, 15m={adx_15m}, {m['struct_5m_label']}) -> EMA 99/20/50 + SMI 5m jenuh/koreksi wajar."

    if atr_5m > float(r.get("max_atr_5m", 0.36)) or max(c_curr["range"], c_prev["range"]) > float(r.get("max_candle_range_5m", 0.45)):
        return {"regime": "CHOPPY_EXTREME", "regime_reason": "Volatilitas ekstrem.", "strategy_mode": "HOLD", "setup_note": "ATR/Range terlalu besar.", "allow_long": False, "allow_short": False, "prefer_limit": True, "suggested_limit_long": price, "suggested_limit_short": price}

    min_bb_w = float(r.get("min_bb_width_pct", 0.0))
    if min_bb_w > 0 and m["bb_width_pct"] < min_bb_w:
        return {"regime": regime, "regime_reason": regime_reason, "strategy_mode": "HOLD_LOW_VOL", "setup_note": f"BB Width {m['bb_width_pct']}% < {min_bb_w}%.", "allow_long": False, "allow_short": False, "prefer_limit": True, "suggested_limit_long": price, "suggested_limit_short": price}

    if bool(r.get("require_candle_close_5m_15m", True)):
        no_bear_close = c_prev["dir"] != "BEARISH" and c15_prev["dir"] != "BEARISH" and c_curr["dir"] != "BEARISH"
        no_bull_close = c_prev["dir"] != "BULLISH" and c15_prev["dir"] != "BULLISH" and c_curr["dir"] != "BULLISH"
    else:
        no_bear_close = c_prev["dir"] != "BEARISH" and c_curr["dir"] != "BEARISH"
        no_bull_close = c_prev["dir"] != "BULLISH" and c_curr["dir"] != "BULLISH"

    bull_ok = no_bear_close and (
        (c_prev["dir"] == "BULLISH" and c_prev["body_pct"] >= 35 and c_curr["close"] >= c_prev["open"]) or
        (c_prev["lower_wick_pct"] >= 42 and c_curr["dir"] == "BULLISH") or
        (c_curr["dir"] == "BULLISH" and c_curr["body_pct"] >= 50 and c_curr["close"] > c_prev["high"])
    )
    bear_ok = no_bull_close and (
        (c_prev["dir"] == "BEARISH" and c_prev["body_pct"] >= 35 and c_curr["close"] <= c_prev["open"]) or
        (c_prev["upper_wick_pct"] >= 42 and c_curr["dir"] == "BEARISH") or
        (c_curr["dir"] == "BEARISH" and c_curr["body_pct"] >= 50 and c_curr["close"] < c_prev["low"])
    )

    allow_long, allow_short, notes = False, False, []
    day_map = m["day_map"]
    res_levels = [day_map["day_high"], m["sh_15m"], m["sh_5m"]] + [z[0] for z in day_map["major_res_zones"]]
    sup_levels = [day_map["day_low"], m["sl_15m"], m["sl_5m"]] + [z[0] for z in day_map["major_sup_zones"]]
    zone_tol = max(0.18, round(atr_5m * 1.25, 3))

    if regime == "SIDEWAYS":
        mode = "SIDEWAYS_15M_BB_SMI_5M_EXEC"
        bb_tol = min(0.18, max(0.08, round(((m["bb_upper_15m"] - m["bb_lower_15m"]) / 2.0) * 0.14, 3)))
        lo_touch = min(price, m["low_15m_recent"], c_prev["low"], c_curr["low"])
        hi_touch = max(price, m["high_15m_recent"], c_prev["high"], c_curr["high"])

        near_bb_lo = (lo_touch <= m["bb_lower_15m"] + bb_tol) if r.get("sideways_require_15m_bb", True) else True
        near_bb_hi = (hi_touch >= m["bb_upper_15m"] - bb_tol) if r.get("sideways_require_15m_bb", True) else True
        smi_sw_lo = float(r.get("smi_sideways_long_max", -25.0))
        smi_sw_hi = float(r.get("smi_sideways_short_min", 25.0))

        smi15_buy = (m["smi_15m"] <= smi_sw_lo) and (m["smi_15m"] > m["smi_15m_prev"] or m["smi_15m"] > m["smi_sig_15m"])
        smi15_sell = (m["smi_15m"] >= smi_sw_hi) and (m["smi_15m"] < m["smi_15m_prev"] or m["smi_15m"] < m["smi_sig_15m"])
        near_sup = any(abs(lo_touch - s) <= zone_tol for s in sup_levels) if r.get("sideways_require_24h_sr", True) else True
        near_res = any(abs(hi_touch - rv) <= zone_tol for rv in res_levels) if r.get("sideways_require_24h_sr", True) else True

        if near_bb_lo and smi15_buy and near_sup and bull_ok:
            allow_long = True
            notes.append(f"SIDEWAYS LONG siap: 15m BB Low (${m['bb_lower_15m']}) + SMI15 ({m['smi_15m']}) + Sup 24J + C5m({c_prev['dir']}) & C15m({c15_prev['dir']}) searah.")
        else:
            notes.append(f"SIDEWAYS LONG tunggu [BB15_Low={near_bb_lo}, SMI15={m['smi_15m']}/{smi_sw_lo}, Sup24J={near_sup}, C5m={c_prev['dir']}, C15m={c15_prev['dir']}].")

        if near_bb_hi and smi15_sell and near_res and bear_ok:
            allow_short = True
            notes.append(f"SIDEWAYS SHORT siap: 15m BB Up (${m['bb_upper_15m']}) + SMI15 ({m['smi_15m']}) + Res 24J + C5m({c_prev['dir']}) & C15m({c15_prev['dir']}) searah.")
        else:
            notes.append(f"SIDEWAYS SHORT tunggu [BB15_Up={near_bb_hi}, SMI15={m['smi_15m']}/{smi_sw_hi}, Res24J={near_res}, C5m={c_prev['dir']}, C15m={c15_prev['dir']}].")
    else:
        mode = "TREND_STRUCTURE_EMA99_SMI5M"
        emas = [m["ema99"], m["ema99_15m"], m["ema20"], m["ema21"], m["ema50"]]
        touched_ema = any(min(abs(price - e), abs(c_prev["low"] - e), abs(c_prev["high"] - e), abs(c_curr["low"] - e), abs(c_curr["high"] - e)) <= zone_tol for e in emas)
        smi_tr_lo = float(r.get("smi_trend_long_max", -10.0))
        smi_tr_hi = float(r.get("smi_trend_short_min", 10.0))

        smi5_buy = (m["smi"] <= smi_tr_lo) and (m["smi"] > m["smi_prev"] or m["smi"] > m["smi_signal"])
        smi5_sell = (m["smi"] >= smi_tr_hi) and (m["smi"] < m["smi_prev"] or m["smi"] < m["smi_signal"])

        if (m["struct_5m"] > 0 or m["struct_15m"] > 0) and m["struct_5m"] >= 0 and m["struct_15m"] >= 0:
            if touched_ema and price >= m["ema99"] * 0.9985 and smi5_buy and bull_ok:
                allow_long = True
                notes.append(f"TREND LONG siap: Struktur naik + pullback EMA + SMI5m ({m['smi']}<={smi_tr_lo}) + C5m({c_prev['dir']}) & C15m({c15_prev['dir']}) searah.")
            else:
                notes.append(f"TREND LONG tunggu [EMA={touched_ema}, SMI5m={m['smi']}/{smi_tr_lo}, C5m={c_prev['dir']}, C15m={c15_prev['dir']}].")

        if (m["struct_5m"] < 0 or m["struct_15m"] < 0) and m["struct_5m"] <= 0 and m["struct_15m"] <= 0:
            if touched_ema and price <= m["ema99"] * 1.0015 and smi5_sell and bear_ok:
                allow_short = True
                notes.append(f"TREND SHORT siap: Struktur turun + pullback EMA + SMI5m ({m['smi']}>={smi_tr_hi}) + C5m({c_prev['dir']}) & C15m({c15_prev['dir']}) searah.")
            else:
                notes.append(f"TREND SHORT tunggu [EMA={touched_ema}, SMI5m={m['smi']}/{smi_tr_hi}, C5m={c_prev['dir']}, C15m={c15_prev['dir']}].")

    min_room = round(tp_dist * 0.65, 3)
    if allow_long and any(0.12 < (rv - price) < min_room for rv in res_levels):
        allow_long = False
        notes.append("LONG ditahan: terhalang Resistance dekat sebelum TP.")
    if allow_short and any(0.12 < (price - sv) < min_room for sv in sup_levels):
        allow_short = False
        notes.append("SHORT ditahan: terhalang Support dekat sebelum TP.")

    prefer_limit = max(c_curr["range"], c_prev["range"]) > 0.25
    lim_long = round(min(price - 0.04, max(c_curr["mid"], m["bb_lower_15m"] if regime == "SIDEWAYS" else m["ema99"])), 3)
    lim_short = round(max(price + 0.04, min(c_curr["mid"], m["bb_upper_15m"] if regime == "SIDEWAYS" else m["ema99"])), 3)

    return {
        "regime": regime,
        "regime_reason": regime_reason,
        "strategy_mode": mode,
        "setup_note": " | ".join(notes) if notes else "Menunggu setup valid.",
        "allow_long": allow_long,
        "allow_short": allow_short,
        "prefer_limit": prefer_limit,
        "suggested_limit_long": lim_long,
        "suggested_limit_short": lim_short
    }


def monitor_pending_limit_order(cfg, metrics):
    pending = cfg.get("pending_order")
    if not pending:
        return cfg, "NO_PENDING", None

    direction = pending["direction"]
    limit_p, tp_p, sl_p = float(pending["limit_price"]), float(pending["tp_price"]), float(pending["sl_price"])
    sl_dist, created_t, curr_p = float(pending["initial_sl_dist"]), int(pending["created_open_time"]), metrics["price"]

    candles = [c for c in metrics.get("candle_history", []) if c["t"] >= created_t] or [{"t": created_t, "h": curr_p, "l": curr_p, "c": curr_p}]
    for c in candles:
        bh = curr_p if c["t"] == created_t else c["h"]
        bl = curr_p if c["t"] == created_t else c["l"]

        if direction == "LONG":
            if (bh - limit_p) >= 0.21 and bl > limit_p:
                cfg["pending_order"] = None
                cfg["stats"]["cancelled_limits"] += 1
                return cfg, "CANCELLED_MISSED", f"🚫 *LIMIT DIBATALKAN:* `LONG` @ `${limit_p}` terlewat (harga lari ke `${bh}`)."
            if c["t"] > created_t and bl <= limit_p:
                cfg["pending_order"] = None
                bep = round(limit_p + sl_dist, 3)
                cfg["active_trade"] = {"direction": "LONG", "order_type": "LIMIT", "entry_price": limit_p, "tp_price": tp_p, "sl_price": sl_p, "initial_sl_dist": sl_dist, "bep_trigger_price": bep, "bep_moved": False, "entry_open_time": c["t"], "entry_time": now_wib_str(), "reason": pending.get("reason", "-")}
                return cfg, "FILLED", f"✅ *LIMIT TERISI (FILLED): LONG* @ `${limit_p}` | TP: `${tp_p}` | SL: `${sl_p}` | 1:1 BEP: `${bep}`"

        elif direction == "SHORT":
            if (limit_p - bl) >= 0.21 and bh < limit_p:
                cfg["pending_order"] = None
                cfg["stats"]["cancelled_limits"] += 1
                return cfg, "CANCELLED_MISSED", f"🚫 *LIMIT DIBATALKAN:* `SHORT` @ `${limit_p}` terlewat (harga jatuh ke `${bl}`)."
            if c["t"] > created_t and bh >= limit_p:
                cfg["pending_order"] = None
                bep = round(limit_p - sl_dist, 3)
                cfg["active_trade"] = {"direction": "SHORT", "order_type": "LIMIT", "entry_price": limit_p, "tp_price": tp_p, "sl_price": sl_p, "initial_sl_dist": sl_dist, "bep_trigger_price": bep, "bep_moved": False, "entry_open_time": c["t"], "entry_time": now_wib_str(), "reason": pending.get("reason", "-")}
                return cfg, "FILLED", f"✅ *LIMIT TERISI (FILLED): SHORT* @ `${limit_p}` | TP: `${tp_p}` | SL: `${sl_p}` | 1:1 BEP: `${bep}`"

    if len(candles) > 4:
        cfg["pending_order"] = None
        cfg["stats"]["cancelled_limits"] += 1
        return cfg, "CANCELLED_EXPIRED", f"⌛ *LIMIT KEDALUWARSA (> 15 MENIT):* `{direction}` @ `${limit_p}` dibatalkan."

    return cfg, "WAITING_FILL", f"⏳ *MENUNGGU LIMIT:* `{direction}` @ `${limit_p}` (Sekarang `${curr_p}`)"


def monitor_active_trade(cfg, metrics):
    trade = cfg.get("active_trade")
    if not trade:
        return cfg, "NO_TRADE", None

    direction = trade["direction"]
    entry, tp_p, sl_p = float(trade["entry_price"]), float(trade["tp_price"]), float(trade["sl_price"])
    bep_trig, bep_moved = float(trade["bep_trigger_price"]), bool(trade.get("bep_moved", False))
    entry_t, curr_p = int(trade.get("entry_open_time", 0)), metrics["price"]
    tp_dist, sl_dist = round(abs(tp_p - entry), 3), round(float(trade.get("initial_sl_dist", cfg["sl"])), 3)
    stats, alerts = cfg["stats"], []

    candles = [c for c in metrics.get("candle_history", []) if c["t"] >= entry_t] or [{"t": entry_t + 1, "h": curr_p, "l": curr_p, "c": curr_p}]
    for c in candles:
        bh = curr_p if (c["t"] == entry_t and trade.get("order_type", "MARKET") == "MARKET") else c["h"]
        bl = curr_p if (c["t"] == entry_t and trade.get("order_type", "MARKET") == "MARKET") else c["l"]

        if direction == "LONG":
            if bl <= sl_p:
                cfg["active_trade"] = None
                stats["total_closed"] += 1
                if bep_moved:
                    stats["bep_hit"] += 1
                    alerts.append(f"🛡️ *DITUTUP DI ENTRY (1:1 BEP):* `LONG` @ `${entry}` (`0.00 poin`)\n\n{format_stats_text(cfg)}")
                    return cfg, "CLOSED_BEP", "\n\n---\n\n".join(alerts)
                stats["sl_hit"] += 1
                stats["net_points"] = round(stats["net_points"] - sl_dist, 3)
                alerts.append(f"❌ *KENA STOP LOSS:* `LONG` @ `${entry}` (`-{sl_dist} poin`)\n\n{format_stats_text(cfg)}")
                return cfg, "CLOSED_SL", "\n\n---\n\n".join(alerts)
            if bh >= tp_p:
                cfg["active_trade"] = None
                stats["total_closed"] += 1
                stats["tp_hit"] += 1
                stats["net_points"] = round(stats["net_points"] + tp_dist, 3)
                alerts.append(f"✅ *TARGET TP TERCAPAI:* `LONG` @ `${entry}` (`+{tp_dist} poin`)\n\n{format_stats_text(cfg)}")
                return cfg, "CLOSED_TP", "\n\n---\n\n".join(alerts)
            if not bep_moved and bh >= bep_trig:
                bep_moved = True
                sl_p = entry
                trade["bep_moved"], trade["sl_price"] = True, entry
                cfg["active_trade"] = trade
                alerts.append(f"🔔 *1:1 TERCAPAI — PINDAH SL KE ENTRY (`${entry}`)* | Posisi `LONG` bebas risiko menuju TP `${tp_p}`")

        elif direction == "SHORT":
            if bh >= sl_p:
                cfg["active_trade"] = None
                stats["total_closed"] += 1
                if bep_moved:
                    stats["bep_hit"] += 1
                    alerts.append(f"🛡️ *DITUTUP DI ENTRY (1:1 BEP):* `SHORT` @ `${entry}` (`0.00 poin`)\n\n{format_stats_text(cfg)}")
                    return cfg, "CLOSED_BEP", "\n\n---\n\n".join(alerts)
                stats["sl_hit"] += 1
                stats["net_points"] = round(stats["net_points"] - sl_dist, 3)
                alerts.append(f"❌ *KENA STOP LOSS:* `SHORT` @ `${entry}` (`-{sl_dist} poin`)\n\n{format_stats_text(cfg)}")
                return cfg, "CLOSED_SL", "\n\n---\n\n".join(alerts)
            if bl <= tp_p:
                cfg["active_trade"] = None
                stats["total_closed"] += 1
                stats["tp_hit"] += 1
                stats["net_points"] = round(stats["net_points"] + tp_dist, 3)
                alerts.append(f"✅ *TARGET TP TERCAPAI:* `SHORT` @ `${entry}` (`+{tp_dist} poin`)\n\n{format_stats_text(cfg)}")
                return cfg, "CLOSED_TP", "\n\n---\n\n".join(alerts)
            if not bep_moved and bl <= bep_trig:
                bep_moved = True
                sl_p = entry
                trade["bep_moved"], trade["sl_price"] = True, entry
                cfg["active_trade"] = trade
                alerts.append(f"🔔 *1:1 TERCAPAI — PINDAH SL KE ENTRY (`${entry}`)* | Posisi `SHORT` bebas risiko menuju TP `${tp_p}`")

    if alerts:
        return cfg, "MOVED_BEP", "\n\n---\n\n".join(alerts)

    flt = round((curr_p - entry) if direction == "LONG" else (entry - curr_p), 3)
    return cfg, "STILL_RUNNING", f"⏳ *POSISI AKTIF:* `{direction}` @ `${entry}` | Sekarang: `${curr_p}` (`{flt:+} pts`) | TP: `${tp_p}` | SL: `${sl_p}`"


def extract_json_safely(raw_text):
    clean = raw_text.replace("```json", "").replace("```", "").strip()
    s, e = clean.find("{"), clean.rfind("}")
    if s != -1 and e > s:
        clean = clean[s:e + 1]
    return json.loads(clean)


def call_gemini(model_name, prompt, api_key, temp=0.1, max_tokens=2048):
    clean = model_name.replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean}:generateContent?key={api_key}"
    gen_cfg = {"temperature": temp, "maxOutputTokens": max_tokens}
    if "gemini" in clean.lower():
        gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
    res = requests.post(url, headers={"Content-Type": "application/json"}, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_cfg}, timeout=45)
    data = res.json()
    if res.status_code != 200:
        raise Exception(f"[{clean}] HTTP {res.status_code}: {data.get('error', {}).get('message', '')}")
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    txt = "\n".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought", False)).strip()
    if not txt:
        raise Exception(f"[{clean}] Respons kosong.")
    return txt


def call_backup_ai(prompt, temp=0.1):
    if not BACKUP_AI_API_KEY:
        raise Exception("BACKUP_AI_API_KEY kosong.")
    res = requests.post(BACKUP_AI_URL, headers={"Content-Type": "application/json", "Authorization": f"Bearer {BACKUP_AI_API_KEY}"}, json={"model": BACKUP_AI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": temp}, timeout=45)
    data = res.json()
    if res.status_code != 200:
        raise Exception(f"[Backup] HTTP {res.status_code}")
    return data["choices"][0]["message"]["content"]


def call_any_ai_text(prompt, temp=0.25, max_tokens=2048):
    models = ["gemma-4-31b-it", "gemini-3.1-flash-lite-preview", "gemini-2.5-flash", "gemma-4-26b-a4b-it"]
    for idx, key in enumerate(GEMINI_API_KEYS, start=1):
        for m_name in models:
            try:
                rep = call_gemini(m_name, prompt, key, temp=temp, max_tokens=max_tokens)
                if rep and len(rep) >= 10:
                    return rep, f"{m_name} #Akun{idx}"
            except Exception as e:
                print(f"Lewati Akun#{idx} {m_name}: {e}")
    if BACKUP_AI_API_KEY:
        try:
            rep = call_backup_ai(prompt, temp=temp)
            if rep and len(rep) >= 10:
                return rep, BACKUP_AI_MODEL
        except Exception as e:
            print(f"Lewati Backup AI: {e}")
    return None, None


def handle_natural_telegram_message(user_msg, market_summary, eval_data, metrics, cfg):
    prompt = f"""
    Kamu asisten kendali bot trading SOL/USDT. Tentukan apakah pesan pengguna meminta UBAH PENGATURAN/ATURAN ("UPDATE_CONFIG"), BERTANYA KONDISI PASAR ("QUESTION"), atau keduanya ("BOTH").
    PESAN: "{user_msg}"
    CONFIG SAAT INI: tp={cfg['tp']}, sl={cfg['sl']}, bot_paused={cfg['bot_paused']}, live_trading={cfg['live_trading']}, rules={json.dumps(cfg['rules'])}, strategy="{cfg['strategy']}"
    PASAR LIVE: {market_summary} | Rezim: {eval_data['regime']} | Evaluasi: {eval_data['setup_note']}
    KUNCI RULES YANG BISA DIUBAH: adx_sideways_5m_max, adx_sideways_15m_max, ema200_chop_crosses_min, smi_trend_long_max, smi_trend_short_min, smi_sideways_long_max, smi_sideways_short_min, sideways_require_15m_bb, sideways_require_24h_sr, require_candle_close_5m_15m, max_atr_5m, max_candle_range_5m, min_bb_width_pct.
    Balas HANYA JSON murni tanpa markdown:
    {{"intent":"UPDATE_CONFIG"|"QUESTION"|"BOTH","updates":{{"tp":null,"sl":null,"bot_paused":null,"live_trading":null,"rules":{{}},"add_custom_rule":null,"clear_custom_rules":false,"new_strategy_text":null}},"reply_indonesian":"<Jawaban Bahasa Indonesia rapi tanpa bintang ganda **>"}}
    """
    raw, engine = call_any_ai_text(prompt, temp=0.25)
    if raw:
        try:
            parsed = extract_json_safely(raw)
            intent = str(parsed.get("intent", "QUESTION")).upper()
            upd = parsed.get("updates", {}) if isinstance(parsed.get("updates"), dict) else {}
            changes = []

            if intent in ["UPDATE_CONFIG", "BOTH"]:
                if upd.get("tp") is not None:
                    cfg["tp"] = round(float(upd["tp"]), 3)
                    changes.append(f"TP -> `+{cfg['tp']} poin`")
                if upd.get("sl") is not None:
                    cfg["sl"] = round(float(upd["sl"]), 3)
                    changes.append(f"SL -> `-{cfg['sl']} poin`")
                if isinstance(upd.get("bot_paused"), bool):
                    cfg["bot_paused"] = upd["bot_paused"]
                    changes.append(f"Scanner -> `{'PAUSED' if cfg['bot_paused'] else 'AKTIF'}`")
                if isinstance(upd.get("live_trading"), bool):
                    cfg["live_trading"] = upd["live_trading"]
                    changes.append(f"Auto-Trading -> `{'ON' if cfg['live_trading'] else 'OFF'}`")
                if isinstance(upd.get("rules"), dict):
                    for k, v in upd["rules"].items():
                        if k in DEFAULT_RULES and v is not None and k != "custom_extra_rules":
                            cfg["rules"][k] = bool(v) if isinstance(DEFAULT_RULES[k], bool) else (int(v) if isinstance(DEFAULT_RULES[k], int) else float(v))
                            changes.append(f"`{k}` -> `{cfg['rules'][k]}`")
                if upd.get("clear_custom_rules") is True:
                    cfg["rules"]["custom_extra_rules"] = []
                    changes.append("Aturan tambahan khusus dihapus")
                if upd.get("add_custom_rule"):
                    nr = str(upd["add_custom_rule"]).strip()
                    if nr and nr not in cfg["rules"]["custom_extra_rules"]:
                        cfg["rules"]["custom_extra_rules"].append(nr)
                        changes.append(f"Aturan baru: _{nr}_")
                if upd.get("new_strategy_text"):
                    cfg["strategy"] = str(upd["new_strategy_text"]).strip()
                    changes.append("Deskripsi strategi utama diperbarui")

            reply_txt = str(parsed.get("reply_indonesian", "")).replace("**", "*").strip()
            if changes:
                return cfg, f"✅ *PENGATURAN BOT DIPERBARUI* (`{engine}`)\n\n" + "\n".join(f"• {c}" for c in changes) + f"\n\n{reply_txt}"
            if reply_txt:
                return cfg, f"🤖 *ASISTEN ARGON* (`{engine}`)\n\n{reply_txt}"
        except Exception as e:
            print(f"Parse error QA: {e}")
            return cfg, f"🤖 *ASISTEN ARGON* (`{engine}`)\n\n{raw.replace('**', '*')}"

    return cfg, f"🤖 *STATUS BOT:* Rezim `{eval_data['regime']}` | SOL `${metrics['price']}` | SMI 5m `{metrics['smi']}` | C5m `{metrics['prev_candle']['dir']}` | C15m `{metrics['prev_candle_15m']['dir']}`\n• {eval_data['setup_note']}"


def analyze_market_with_fallback(price, market_summary, metrics, eval_data, cfg):
    r = cfg.get("rules", DEFAULT_RULES)
    extra = "; ".join(r.get("custom_extra_rules", [])) or "None"
    prompt = (
        f"Sniper SOL/USDT trader. LIVE: {market_summary}\n"
        f"Regime: {eval_data['regime']} | Gate: {eval_data['setup_note']} | allow_long={eval_data['allow_long']}, allow_short={eval_data['allow_short']}\n"
        f"LimitLong=${eval_data['suggested_limit_long']} | LimitShort=${eval_data['suggested_limit_short']} | ExtraRules: {extra}\n"
        f"Rules: Never output LONG if allow_long=false; never SHORT if allow_short=false. Enforce ExtraRules strictly.\n"
        f'Output JSON only: {{"signal":"WAIT"|"LONG"|"SHORT","order_type":"MARKET"|"LIMIT","entry_price":0,"key_zone_24h":"","candle_confirmation":"","anticipation":"","reasoning":""}}'
    )
    raw, engine = call_any_ai_text(prompt, temp=0.1, max_tokens=1024)
    ai_res = None
    if raw:
        try:
            ai_res = extract_json_safely(raw)
        except Exception:
            ai_res = None

    if ai_res is None:
        sig = "LONG" if eval_data["allow_long"] else ("SHORT" if eval_data["allow_short"] else "WAIT")
        otype = "LIMIT" if eval_data["prefer_limit"] else "MARKET"
        ep = (eval_data["suggested_limit_long"] if sig == "LONG" else eval_data["suggested_limit_short"]) if otype == "LIMIT" else price
        ai_res = {
            "signal": sig,
            "order_type": otype,
            "entry_price": ep,
            "key_zone_24h": f"EMA99:${metrics['ema99']} | 15mBB:${metrics['bb_lower_15m']}-${metrics['bb_upper_15m']}",
            "candle_confirmation": f"C5m:{metrics['prev_candle']['dir']} | C15m:{metrics['prev_candle_15m']['dir']} | SMI5m:{metrics['smi']}",
            "anticipation": f"SL -{cfg['sl']} pts; geser SL ke entry saat +{cfg['sl']} pts.",
            "reasoning": eval_data["setup_note"]
        }
        engine = "Argon-Sniper-Engine"

    sig = str(ai_res.get("signal", "WAIT")).upper()
    if (sig == "LONG" and not eval_data["allow_long"]) or (sig == "SHORT" and not eval_data["allow_short"]):
        ai_res["signal"] = "WAIT"
        ai_res["reasoning"] = f"[Ditolak Saringan] {eval_data['setup_note']}"
    return ai_res, engine


if __name__ == "__main__":
    config = load_config()
    config, is_manual_scan, user_natural_msg = process_telegram_commands(config)

    try:
        price, market_summary, metrics = fetch_market_data()
        eval_data = evaluate_professional_setup(metrics, config)

        if user_natural_msg:
            config, chat_reply = handle_natural_telegram_message(user_natural_msg, market_summary, eval_data, metrics, config)
            eval_data = evaluate_professional_setup(metrics, config)
            send_telegram(chat_reply)

        if config.get("pending_order"):
            config, l_stat, l_msg = monitor_pending_limit_order(config, metrics)
            if l_stat in ["CANCELLED_MISSED", "CANCELLED_EXPIRED", "FILLED"] or (l_stat == "WAITING_FILL" and is_manual_scan):
                send_telegram(l_msg)

        elif config.get("active_trade"):
            config, t_stat, t_msg = monitor_active_trade(config, metrics)
            if t_stat in ["CLOSED_TP", "CLOSED_SL", "CLOSED_BEP", "MOVED_BEP"] or (t_stat == "STILL_RUNNING" and is_manual_scan):
                send_telegram(t_msg)

        elif config.get("bot_paused", False) and not is_manual_scan:
            print("Bot status PAUSED.")

        else:
            if not eval_data["allow_long"] and not eval_data["allow_short"] and not is_manual_scan:
                print(f"WAIT: {eval_data['regime']} | {eval_data['setup_note']}")
            else:
                ai_data, used_model = analyze_market_with_fallback(price, market_summary, metrics, eval_data, config)
                sig = str(ai_data.get("signal", "WAIT")).upper()
                otype = str(ai_data.get("order_type", "MARKET")).upper()
                if otype not in ["MARKET", "LIMIT"]:
                    otype = "LIMIT" if eval_data["prefer_limit"] else "MARKET"

                reason = ai_data.get("reasoning", eval_data["setup_note"])
                anticipation = ai_data.get("anticipation", "SL bekerja otomatis; pindah ke entry saat +1R.")
                key_zone = ai_data.get("key_zone_24h", f"EMA99:${metrics['ema99']} | BB15m:${metrics['bb_lower_15m']}-${metrics['bb_upper_15m']}")
                c_conf = ai_data.get("candle_confirmation", f"C5m:{metrics['prev_candle']['dir']} | C15m:{metrics['prev_candle_15m']['dir']}")

                if sig in ["LONG", "SHORT"]:
                    tp_d, sl_d = float(config["tp"]), float(config["sl"])
                    if otype == "LIMIT":
                        raw_e = float(ai_data.get("entry_price", 0))
                        entry_p = (raw_e if (price - 0.19) <= raw_e < price else eval_data["suggested_limit_long"]) if sig == "LONG" else (raw_e if price < raw_e <= (price + 0.19) else eval_data["suggested_limit_short"])
                    else:
                        entry_p = price

                    tp_p = round(entry_p + tp_d, 3) if sig == "LONG" else round(entry_p - tp_d, 3)
                    sl_p = round(entry_p - sl_d, 3) if sig == "LONG" else round(entry_p + sl_d, 3)
                    bep_p = round(entry_p + sl_d, 3) if sig == "LONG" else round(entry_p - sl_d, 3)
                    st_trade = "🟢 ON (LIVE)" if config["live_trading"] else "🔴 OFF (Dry Run)"

                    if otype == "LIMIT":
                        config["pending_order"] = {"direction": sig, "limit_price": entry_p, "tp_price": tp_p, "sl_price": sl_p, "initial_sl_dist": sl_d, "created_open_time": metrics["latest_candle_time"], "created_time": now_wib_str(), "reason": reason}
                        send_telegram(
                            f"🎯 *SINYAL SNIPER LIMIT: {sig} LIMIT* (`{used_model}`)\n"
                            f"• Rezim: `{eval_data['regime']}` | Eksekusi: `{st_trade}`\n"
                            f"• Market: `${price}` | Limit 5m: `${entry_p}` | TP: `${tp_p}` | SL: `${sl_p}`\n"
                            f"• SMI 5m/15m: `{metrics['smi']}` / `{metrics['smi_15m']}` | Candle: {c_conf}\n"
                            f"• Area: {key_zone}\n"
                            f"🛡️ *Antisipasi:* {anticipation}\n💡 *Analisis:* {reason}"
                        )
                    else:
                        config["active_trade"] = {"direction": sig, "order_type": "MARKET", "entry_price": entry_p, "tp_price": tp_p, "sl_price": sl_p, "initial_sl_dist": sl_d, "bep_trigger_price": bep_p, "bep_moved": False, "entry_open_time": metrics["latest_candle_time"], "entry_time": now_wib_str(), "reason": reason}
                        send_telegram(
                            f"🚨 *SINYAL SNIPER: {sig}* (`{used_model}`)\n"
                            f"• Rezim: `{eval_data['regime']}` | Eksekusi: `{st_trade}`\n"
                            f"• Entry 5m: `${entry_p}` | TP: `${tp_p}` | SL: `${sl_p}` | 1:1 BEP: `${bep_p}`\n"
                            f"• SMI 5m/15m: `{metrics['smi']}` / `{metrics['smi_15m']}` | Candle: {c_conf}\n"
                            f"• Area: {key_zone}\n"
                            f"🛡️ *Antisipasi:* {anticipation}\n💡 *Analisis:* {reason}"
                        )
                elif is_manual_scan:
                    send_telegram(
                        f"⏸️ *STATUS: WAIT* (`{used_model}` | Rezim: `{eval_data['regime']}`)\n"
                        f"• SOL: `${price}` | ADX 5m/15m: `{metrics['adx_5m']}`/`{metrics['adx_15m']}`\n"
                        f"• SMI 5m/15m: `{metrics['smi']}` / `{metrics['smi_15m']}` | Candle Tutup: 5m `{metrics['prev_candle']['dir']}` | 15m `{metrics['prev_candle_15m']['dir']}`\n"
                        f"• 15m BB: `${metrics['bb_lower_15m']}-${metrics['bb_upper_15m']}` | EMA99 5m/15m: `${metrics['ema99']}`/`${metrics['ema99_15m']}`\n"
                        f"🔍 *Evaluasi:* {eval_data['setup_note']}"
                    )
    except Exception as e:
        print(f"Error siklus: {e}")
        if is_manual_scan or user_natural_msg:
            send_telegram(f"⚠️ *Argon System Warning*\n`{str(e)}`")

    save_config(config)
