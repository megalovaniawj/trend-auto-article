# -*- coding: utf-8 -*-
import os
import sys
import json
import requests
import time
from datetime import datetime, timedelta

# Tweepyの読み込み
try:
    import tweepy
except ImportError:
    print("⚠️ エラー: 'tweepy' がインストールされていません。")
    print("pip install tweepy を実行してください。")
    sys.exit(1)

# ==========================================
# ★設定エリア
# ==========================================
WP_URL = "https://docchiyo.com"
HISTORY_FILE = "x_post_history.json"

# 投稿したい時間（24時間表記）
TARGET_TIMES = ["08:30", "12:00", "20:30"]

# X API Key
    api_key = os.environ.get("5aBdDm28LUSxuxe2puyMjYXZZ")
    api_secret = os.environ.get("XxsuMbrNliAKALzvSDPDWKOnwgJdvStHBbwzRydIrHOZG3w7jP")
    access_token = os.environ.get("2020047210755547136-NFzfRgJ1Z1HYupt3qsxLHyudWuTL4A")
    access_secret = os.environ.get("4Lbwjegb2ZEAL4d6aOqGfg39k140yBlgfARuoZ27UuLCX")

# ==========================================
# 関数定義
# ==========================================

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
            print(" 失敗")
            return []
    except Exception as e:
        print(f" エラー: {e}")
        return []

def extract_hashtags(title):
    tags = ["投票", "アンケート"]
    import re
    match = re.search(r'【(.*?)】', title)
    if match:
        core_kw = match.group(1)
        tags.insert(0, core_kw)
    tags_str = " ".join([f"#{t}" for t in tags[:3]])
    return tags_str

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

def check_and_post():
    """投稿処理の実行本体"""
    print(f"\n⏰ 時間になりました！投稿チェックを開始します ({datetime.now().strftime('%H:%M')})")
    
    history = load_history()
    history = clean_old_history(history)
    latest_posts = get_latest_posts(3)
    
    posted_count = 0
    
    # 3記事あるうち、まだ投稿していないものを1つだけ探して投稿する
    # （一気に3つ連投するとスパム判定される恐れがあるため、1回につき1記事が安全です）
    for post in latest_posts:
        title = post['title']['rendered']
        link = post['link']
        
        if title in history:
            print(f"⏭️ 履歴あり: {title}")
            continue
            
        if post_to_x(title, link):
            history[title] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            posted_count += 1
            break # 今回のターンは1記事投稿したら終了
            
    save_history(history)
    
    if posted_count == 0:
        print("💤 新しい記事がないか、すべて投稿済みです。")
    else:
        print("🎉 投稿完了。次の時間まで待機します。")

# ==========================================
# 常駐監視ループ
# ==========================================
if __name__ == "__main__":
    print("\n========================================")
    print(f"👀 X自動投稿ボットが起動しました。")
    print(f"⏰ ターゲット時間: {', '.join(TARGET_TIMES)}")
    print("   PCをつけたまま、この画面を閉じないでください。")
    print("========================================\n")

    while True:
        # 現在時刻を取得 (HH:MM形式)
        now_str = datetime.now().strftime('%H:%M')
        
        # 指定の時間になったら実行
        if now_str in TARGET_TIMES:
            check_and_post()
            
            # 同じ分（例：08:30:00〜08:30:59）の間に何度も実行されないよう、61秒待つ
            time.sleep(61)
            
            print(f"\n💤 次のスケジュールまで待機中...")
        
        # 30秒ごとに時計をチラ見する
        time.sleep(30)
