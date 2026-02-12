# -*- coding: utf-8 -*-
import os
import sys
import json
import requests
import time
from datetime import datetime, timedelta

try:
    import tweepy
except ImportError:
    print("⚠️ エラー: 'tweepy' がインストールされていません。")
    sys.exit(1)

WP_URL = "https://docchiyo.com"
HISTORY_FILE = "x_post_history.json"

# GitHub ActionsのSecretsから読み込む
    api_key = os.environ.get("5aBdDm28LUSxuxe2puyMjYXZZ")
    api_secret = os.environ.get("XxsuMbrNliAKALzvSDPDWKOnwgJdvStHBbwzRydIrHOZG3w7jP")
    access_token = os.environ.get("2020047210755547136-NFzfRgJ1Z1HYupt3qsxLHyudWuTL4A")
    access_secret = os.environ.get("4Lbwjegb2ZEAL4d6aOqGfg39k140yBlgfARuoZ27UuLCX")

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=4, ensure_ascii=False)

def clean_old_history(history):
    new_history = {}
    limit_date = datetime.now() - timedelta(days=30)
    for title, date_str in history.items():
        try:
            post_date = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
            if post_date > limit_date:
                new_history[title] = date_str
        except: pass
    return new_history

def get_latest_posts(count=3):
    print(f"📡 サイトから最新{count}件の記事を取得中...", end="")
    try:
        url = f"{WP_URL}/wp-json/wp/v2/posts?per_page={count}&_fields=title,link"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            posts = res.json()
            print(f" OK ({len(posts)}件)")
            return posts
        else:
            return []
    except:
        return []

def extract_hashtags(title):
    tags = ["投票", "アンケート"]
    import re
    match = re.search(r'【(.*?)】', title)
    if match:
        tags.insert(0, match.group(1))
    return " ".join([f"#{t}" for t in tags[:3]])

def post_to_x(title, url):
    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET]):
        print("⚠️ APIキー不足")
        return False

    client = tweepy.Client(
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_SECRET
    )

    tags = extract_hashtags(title)
    text = f"{title}\n\nみんなの意見を聞かせてください！👇\n{url}\n\n{tags}"

    try:
        client.create_tweet(text=text)
        print(f"🐦 投稿成功: {title}")
        return True
    except Exception as e:
        print(f"❌ 投稿失敗: {e}")
        return False

if __name__ == "__main__":
    print("--- X自動投稿チェック開始 ---")
    history = load_history()
    history = clean_old_history(history)
    latest_posts = get_latest_posts(3)
    
    posted = False
    # 最新の記事からチェック
    for post in latest_posts:
        title = post['title']['rendered']
        link = post['link']
        
        if title in history:
            continue
            
        if post_to_x(title, link):
            history[title] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            posted = True
            break # 1回につき1記事だけ投稿して終了
    
    save_history(history)
    if not posted:
        print("新規投稿なし")
