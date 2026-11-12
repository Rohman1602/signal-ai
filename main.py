import os
import requests
import pandas as pd
import numpy as np
import google.generativeai as genai

# Mengambil kunci rahasia dari sistem GitHub (Lebih Aman)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")

ENABLE_LIVE_TRADING = False

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def fetch_binance_data():
    url = "https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval=5m&limit=50"
    response = requests.get(url)
    data = response.json()
    df = pd.DataFrame(data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'qav', 'not', 'tbba', 'tbqa', 'ignore'
    ])
    current_price = float(df['close'].iloc[-1])
    return current_price, df

def analyze_market_with_ai(current_price):
    prompt = f"""
    You are a 5-minute timeframe trading AI agent for SOL/USDT.
    Current price is {current_price}. Apply your adaptive strategy (EMA 9/Volume for trend, Bollinger/SMI for sideways).
    Take Profit: +0.60 points. Stop Loss: -0.23 points.
    
    Output format strictly JSON:
    {{"signal": "WAIT" or "LONG" or "SHORT", "entry_price": {current_price}, "take_profit": <number>, "stop_loss": <number>, "reasoning": "<short text>"}}
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f'{{"signal": "ERROR", "reasoning": "{str(e)}"}}'

if __name__ == "__main__":
    print("Mengeksekusi analisa 5 menit...")
    price, df = fetch_binance_data()
    ai_result = analyze_market_with_ai(price)
    
    msg = f"🚨 *Argon Signal*\n\n```json\n{ai_result}\n```\nLive Trading: `OFF`"
    send_telegram_message(msg)
