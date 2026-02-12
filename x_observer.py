# -*- coding: utf-8 -*-
import os
import sys
import json
import requests
import time
from datetime import datetime, timedelta

# Tweepyの読み込みチェック
try:
    import tweepy
except ImportError:
    print("⚠️ エラー: 'tweepy' がインストールされていません。")
    sys.exit(1)

# ==========================================
# ★設定エリア
# ==========================================
WP_URL = "https://docchiyo.com"
HISTORY_FILE = "x_post_history.json"

# GitHub ActionsのSecretsから読み込む
X_API_KEY = os.environ.get("X_API_KEY")
X_API_SECRET = os.environ.get("X_API_SECRET")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN")
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET")

# ==========================================
# 関数定義
# ==========================================

def check_env_vars():
    """環境変数が正しく渡されているか確認する（中身は見せずに有無だけ表示）"""
    print("\n🔑 認証情報のチェック:")
    print(f"  - API_KEY: {'OK' if X_API_KEY else '❌ 未設定'}")
    print(f"  - API_SECRET: {'OK' if X_API_SECRET else '❌ 未設定'}")
    print(f"  - ACCESS_TOKEN: {'OK' if X_ACCESS_TOKEN else '❌ 未設定'}")
    print(f"  - ACCESS_SECRET: {'OK' if X_ACCESS_SECRET else '❌ 未設定'}")
    
    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET]):
        print("\n⚠️ エラー: GitHub ActionsのYAMLファイルで 'env:' の設定が漏れている可能性があります。")
        return False
    return True

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
    """30日以上前の履歴を掃除する"""
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
    print(f"📡 最新記事をチェック中...", end="")
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
        tags.insert(0, match.group(1))
    return " ".join([f"#{t}" for t in tags[:3]])

def post_to_x(title, url):
    """Xへ投稿実行"""
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

# ==========================================
# メイン処理
# ==========================================
if __name__ == "__main__":
    print("--- X自動投稿チェック開始 ---")
    
    # 1. 鍵のチェック
    if not check_env_vars():
        sys.exit(1) # 鍵がないなら強制終了

    # 2. 履歴の準備
    history = load_history()
    history = clean_old_history(history)
    
    # 3. 記事の取得
    latest_posts = get_latest_posts(3)
    
    posted_count = 0
    
    # 4. 未投稿の記事を探して投稿
    for post in latest_posts:
        title = post['title']['rendered']
        link = post['link']
        
        # 履歴にあったらスキップ
        if title in history:
            print(f"⏭️ スキップ（済）: {title}")
            continue
            
        # 投稿実行
        print(f"🚀 投稿を試みます: {title}")
        if post_to_x(title, link):
            history[title] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            posted_count += 1
            break # 1回につき1記事だけ投稿して終了
    
    # 5. 履歴を保存
    save_history(history)
    
    if posted_count == 0:
        print("💤 新しい記事はありませんでした（または全て投稿済み）")
