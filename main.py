# -*- coding: utf-8 -*-
"""
【トレンド自動記事作成 V102】プロンプト誘導方式でgemma-4思考プロセス完全排除
"""

import os
import sys
import warnings
import requests
import base64
import time
import random
import json
import feedparser
import re
from urllib.parse import quote
from datetime import datetime, timedelta

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

warnings.filterwarnings("ignore")

# ==========================================
# ★設定エリア
# ==========================================
WP_URL = "https://docchiyo.com"
WP_USER = "bear"
WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF")

if not WP_APP_PASS or not GEMINI_API_KEY:
    print("❌ エラー: 環境変数（シークレット）が設定されていません。")
    sys.exit(1)

MODEL_NAME = "gemma-4-31b-it"
ARTICLES_TO_CREATE = 2

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
HEADERS = {'User-Agent': USER_AGENT}

NG_KEYWORDS = [
    "リウマチ", "癌", "がん", "腫瘍", "うつ", "鬱", "障害", "症候群", "病気", "疾患",
    "病院", "治療", "手術", "薬", "ワクチン", "感染", "ウイルス", "菌", "陽性", "陰性",
    "痛み", "激痛", "苦しい", "吐き気", "下痢", "発熱", "高熱", "脳梗塞", "心筋梗塞", "死亡", "死去", "遺体",
    "殺人", "殺害", "刺さ", "死刑", "逮捕", "容疑者", "書類送検", "捜査", "警察", "犯人",
    "事故", "火災", "火事", "爆発", "地震", "津波", "災害", "襲撃", "強盗", "不審者",
    "被害", "告発", "辞任", "解雇", "契約解除", "裁判", "訴訟", "判決", "賠償", "横領", "脱税",
    "遅延", "運転見合わせ", "人身事故", "停電", "天気", "気象", "雨", "訃報", "お別れ",
    "揶揄", "失言", "処分", "厳罰", "炎上", "謝罪", "不倫", "浮気", "供述",
    "ほのぼの", "癒やし", "かわいい", "猫", "犬", "動物園", "水族館", "住吉大社", "ローカル", "地域"
]

# ==========================================
# ★ ヘルパー関数
# ==========================================

def get_auth_header():
    creds = f"{WP_USER.strip()}:{WP_APP_PASS.strip()}"
    token = base64.b64encode(creds.encode()).decode()
    return {
        'Authorization': f'Basic {token}',
        'Content-Type': 'application/json'
    }

def get_auth_header_get():
    creds = f"{WP_USER.strip()}:{WP_APP_PASS.strip()}"
    token = base64.b64encode(creds.encode()).decode()
    return {'Authorization': f'Basic {token}'}

def clean_title(text):
    if not text: return ""
    return re.sub(r'[^\w\s]', '', text).replace(' ', '').replace('　', '')

def get_all_existing_titles():
    print("📚 過去記事を全件チェック中...", end="")
    titles = []
    page = 1
    while True:
        try:
            url = f"{WP_URL}/wp-json/wp/v2/posts?per_page=100&page={page}&fields=title"
            res = requests.get(url, headers=get_auth_header_get(), timeout=10)
            if res.status_code != 200: break
            posts = res.json()
            if not posts: break
            for p in posts:
                titles.append(clean_title(p['title']['rendered']))
            if len(posts) < 100: break
            page += 1
        except: break
    print(f" -> 合計 {len(titles)} 件取得完了")
    return titles

def send_discord_notification(post_id, title, post_url):
    if not DISCORD_WEBHOOK_URL:
        return
    edit_url = f"{WP_URL.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
    payload = {
        "content": f"🔥 **AI編集長が記事を投稿しました！**\n\n**【タイトル】**\n{title}\n\n**【公開URL】**\n{post_url}\n\n**【編集】**\n{edit_url}"
    }
    try:
        d_res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        d_res.raise_for_status()
        print(" 🔔 Discord通知送信完了")
    except Exception as e:
        print(f" ⚠️ Discord通知失敗: {e}")

def call_gemini(prompt, timeout=30):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}], "safetySettings": SAFETY_SETTINGS}
    try:
        res = requests.post(url, headers=headers, json=data, timeout=timeout)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except:
        pass
    return None

def parse_json_from_text(text):
    """テキストからJSONを抽出してパース"""
    try:
        text = text.replace('```json', '').replace('```', '').strip()
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end > 0:
            return json.loads(text[start:end])
    except:
        pass
    return None

# ==========================================
# ★ トレンド収集＆分析
# ==========================================

def get_google_realtime_trends():
    print("    👉 Google Realtime API: ", end="")
    items = []
    try:
        url = "https://trends.google.co.jp/trends/api/realtimetrends?hl=ja&tz=-540&cat=all&fi=0&fs=0&geo=JP&ri=300&rs=20&sort=0"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            content = resp.text.replace(")]}',", "").strip()
            data = json.loads(content)
            stories = data.get('storySummaries', {​​​​​​​​​​​​​​​​
