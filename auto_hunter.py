import feedparser
import requests
import re
import time
import random
import base64
import os
from datetime import datetime, timedelta

# ==========================================
# ★設定エリア
# ==========================================
WP_URL = os.environ.get("WP_URL", "https://docchiyo.com")
WP_USER = os.environ.get("WP_USER", "bear")
WP_APP_PASS = os.environ.get("WP_APP_PASS")

# Discord Webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF"

# PR TIMES RSS (ゲーム・おもちゃカテゴリ)
RSS_URL = "https://prtimes.jp/companyrss.php?c_id=24"

# 除外ワード
NG_WORDS = ["グッズ", "コラボ", "キャンペーン", "イベント", "ポップアップ", "フェア", "記念", "主題歌", "サントラ", "レポート", "舞台", "オーディション"]
# ターゲットワード
TARGET_WORDS = ["事前登録", "配信", "サービス開始", "発売", "リリース", "決定"]

# ==========================================
# 関数定義
# ==========================================

def get_auth_header():
    if not WP_USER or not WP_APP_PASS:
        print("❌ 【エラー】WordPressの認証情報（URL, ユーザー, パスワード）が設定されていません。Secretsを確認してください。")
        return None
    creds = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(creds.encode()).decode()
    return {'Authorization': f'Basic {token}'}

def check_exists(title):
    headers = get_auth_header()
    if not headers: return False
    
    search_term = title[:15] 
    endpoint = f"{WP_URL}/wp-json/wp/v2/posts?search={search_term}&status=any"
    try:
        res = requests.get(endpoint, headers=headers, timeout=10)
        if res.status_code == 200:
            for post in res.json():
                if post['title']['rendered'] == title:
                    return True
    except Exception as e:
        print(f"⚠️ 記事重複チェック中にエラー: {e}")
    return False

def extract_release_date(text):
    now = datetime.now()
    match_long = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if match_long:
        try:
            return datetime(int(match_long.group(1)), int(match_long.group(2)), int(match_long.group(3)), 7, 0, 0)
        except: pass

    match_short = re.search(r'(\d{1,2})月(\d{1,2})日', text)
    if match_short:
        try:
            month = int(match_short.group(1))
            day = int(match_short.group(2))
            year = now.year
            return datetime(year, month, day, 7, 0, 0)
        except: pass
    return None

def extract_release_str(text):
    patterns = [
        r'\d{4}年\d{1,2}月\d{1,2}日',
        r'\d{1,2}月\d{1,2}日',
        r'\d{4}年\d{1,2}月',
        r'\d{4}年(春|夏|秋|冬|配信予定|リリース予定)',
        r'今冬|今春|今夏|今秋'
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match: return match.group(0)
    return "リリース時期未定"

def send_discord_notification(title, release_str, status_type):
    if not DISCORD_WEBHOOK_URL or "ここに" in DISCORD_WEBHOOK_URL:
        print("⚠️ Discord Webhook URLが設定されていないため通知をスキップしました")
        return
        
    status_ja = {
        'publish': '🚀 即時公開（配信済み/当日）',
        'future': '📅 予約投稿（発売日の朝7時）',
        'draft': '📝 下書き保存（日付不明など）'
    }.get(status_type, status_type)

    login_url = f"{WP_URL}/wp-admin/"
    message = f"✅ **記事を作成しました**\n\n" \
              f"**タイトル:** {title}\n" \
              f"**時期:** {release_str}\n" \
              f"**状態:** {status_ja}\n" \
              f"**確認:** {login_url}"
    
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        if res.status_code in [200, 204]:
            print("💬 Discordに通知を送りました")
        else:
            print(f"❌ Discord通知エラー: {res.status_code}")
    except Exception as e:
        print(f"❌ Discord通信エラー: {e}")

def determine_game_type(text):
    text = text.lower()
    score_f2p = 0
    score_paid = 0
    if any(w in text for w in ["基本プレイ無料", "app store", "google play", "事前登録", "リセマラ", "ガチャ", "ios", "android"]):
        score_f2p += 1
    if any(w in text for w in ["パッケージ版", "ダウンロード版", "switch", "ps5", "ps4", "steam", "円", "税"]):
        score_paid += 1
        if "基本プレイ無料" in text: score_f2p += 5
    return "f2p" if score_f2p >= score_paid else "paid"

def generate_vote_options(game_type):
    if game_type == "f2p":
        options = ["絶対やる(事前登録済)", "様子見(評判待ち)", "リセマラだけやる", "興味なし"]
        comments = [
            {"author": "名無し", "text": "リセマラめんどくさそう"},
            {"author": "通りすがり", "text": "絵は好みだけどシステムがな"},
            {"author": "ガチャ爆死", "text": "配布石に期待"},
            {"author": "匿名", "text": "量産型じゃないことを祈る"}
        ]
    else:
        options = ["即買い(予約済)", "様子見(レビュー待ち)", "セール待ち", "興味なし"]
        comments = [
            {"author": "名無し", "text": "ボリューム次第かな"},
            {"author": "FPS勢", "text": "PV見た感じ面白そう"},
            {"author": "匿名", "text": "バグなければ神ゲー"},
            {"author": "積みゲーマー", "text": "クリア時間どれくらい？"}
        ]
    return options, comments

def create_post(entry):
    title = entry.title
    link = entry.link
    description = entry.description
    
    clean_title = re.sub(r'【.*?】', '', title).split("」")[0].replace("「", "")
    if len(clean_title) > 30: clean_title = clean_title[:30] + "..."
    wp_title = f"【投票】{clean_title}は面白い？プレイ前の期待度アンケート"
    
    game_type = determine_game_type(title + description)
    options, sakura_comments = generate_vote_options(game_type)
    items_str = ",".join([f"{opt}|" for opt in options])
    
    content = f"""
<p>新作ゲーム『{clean_title}』の情報が公開されました。<br>皆さんの期待度やプレイ予定を教えてください！</p>
[vote_bar items="{items_str}"]
[vote_summary items="{items_str}"]
<h2>{clean_title} の基本情報</h2>
<p>{description}</p>
<p><a href="{link}" target="_blank" rel="noopener">公式情報（PR TIMES）</a></p>
"""

    meta = {
        'wiki_h2_title': f"{clean_title} について",
        'wiki_h2_text': description[:100] + "...",
        'post_views_count': '0'
    }
    for i, opt in enumerate(options, 1):
        meta[f'wiki_item_name_{i}'] = opt
        meta[f'wiki_item_img_{i}'] = ""
        meta[f'vote_multi_idx_{i-1}'] = "0"

    release_date = extract_release_date(title + description)
    current_time = datetime.now()
    status = 'draft'
    post_date = current_time.strftime('%Y-%m-%dT%H:%M:%S')

    if release_date:
        if release_date > current_time:
            status = 'future'
            post_date = release_date.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            status = 'publish'
            post_date = current_time.strftime('%Y-%m-%dT%H:%M:%S')
    
    post_data = {
        'title': wp_title,
        'content': content,
        'status': status,
        'date': post_date,
        'categories': [1],
        'meta': meta
    }

    headers = get_auth_header()
    if not headers: return None, None, None, None

    try:
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", headers=headers, json=post_data, timeout=30)
        if res.status_code == 201:
            pid = res.json()['id']
            print(f"✅ 記事作成に成功しました！ ID: {pid} ステータス: {status}")
            return pid, sakura_comments, clean_title, status
        else:
            print(f"❌ 記事作成失敗: {res.status_code} {res.text}")
    except Exception as e:
        print(f"❌ 通信エラー: {e}")
    
    return None, None, None, None

def post_sakura_comment(post_id, comments):
    if not comments: return
    selected = random.sample(comments, k=random.randint(1, 2))
    url = f"{WP_URL}/wp-json/wp/v2/comments"
    headers = get_auth_header()
    if not headers: return

    for c in selected:
        c_dt = datetime.now() - timedelta(minutes=random.randint(5, 120))
        data = {'post': post_id, 'author_name': c['author'], 'content': c['text'], 'status': 'approve', 'date': c_dt.isoformat()}
        try:
            requests.post(url, headers=headers, json=data, timeout=10)
            print(f"   💬 サクラコメントを投稿: 「{c['text']}」")
        except: pass

def main():
    print("--------------------------------------------------")
    print("🤖 ゲームハンター(自動投稿ロボ) 起動！")
    print("📡 PR TIMESから最新ニュースを取得しています...")
    
    # ▼【修正】ブラウザのふりをしてアクセスする設定を追加
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # requestsを使ってデータを取得し、それをfeedparserに渡す
        response = requests.get(RSS_URL, headers=headers, timeout=10)
        print(f"   ↪︎ サーバー応答: {response.status_code}") # 200ならOK
        
        feed = feedparser.parse(response.content)
    except Exception as e:
        print(f"❌ RSSの取得に失敗しました: {e}")
        return

    if not feed.entries:
        print("⚠️ ニュースが1件も取得できませんでした。（RSSが空か、ブロックされています）")
        return

    print(f"   ↪︎ {len(feed.entries)} 件のニュースを取得しました。チェックを開始します。")
    print("--------------------------------------------------")

    count = 0
    checked_count = 0
    
    for entry in feed.entries:
        checked_count += 1
        title = entry.title
        
        # 理由付きログ出力
        if not any(w in title for w in TARGET_WORDS):
            print(f"⚪️ スキップ: {title[:30]}... (ターゲットワード無し)")
            continue
        
        if any(w in title for w in NG_WORDS):
            print(f"✖️ スキップ: {title[:30]}... (NGワード: '{next(w for w in NG_WORDS if w in title)}' を検出)")
            continue
        
        clean_title_check = re.sub(r'【.*?】', '', title).split("」")[0].replace("「", "")
        wp_check_title = f"【投票】{clean_title_check}は面白い？プレイ前の期待度アンケート"
        
        if check_exists(wp_check_title):
            print(f"🔷 スキップ: {clean_title_check} (すでに作成済み)")
            continue

        print(f"\n✨ 【ヒット！】作成を開始します: {title}")
        pid, sakura, clean_title, status = create_post(entry)
        
        if pid:
            post_sakura_comment(pid, sakura)
            release_str = extract_release_str(title + entry.description)
            send_discord_notification(clean_title, release_str, status)
            count += 1
            
        if count >= 3:
            print("\n🛑 一度の実行制限（3件）に達したので終了します。")
            break

    print("--------------------------------------------------")
    print(f"🏁 処理完了！ 全{len(feed.entries)}件中、{count}件の記事を作成しました。")
    print("--------------------------------------------------")

if __name__ == "__main__":
    main()
