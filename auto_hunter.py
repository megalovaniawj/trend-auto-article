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

# 情報源リスト (ゲーム専用)
RSS_URLS = [
    "https://www.4gamer.net/rss/index.xml",
    "https://news.denfaminicogamer.jp/feed"
]

# 除外ワード
NG_WORDS = ["セール", "決算", "インタビュー", "レポート", "舞台", "オーディション", "求人", "人事", "放送", "プレゼント", "まとめ", "漫画", "アニメ"]

# ターゲットワード
TARGET_WORDS = ["事前登録", "配信開始", "サービス開始", "発売", "リリース", "決定"]

# ==========================================
# 関数定義
# ==========================================

def get_auth_header():
    if not WP_USER or not WP_APP_PASS: return None
    creds = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(creds.encode()).decode()
    return {'Authorization': f'Basic {token}'}

def check_exists(title):
    headers = get_auth_header()
    if not headers: return False
    clean_search = re.sub(r'【.*?】', '', title).strip()[:15]
    endpoint = f"{WP_URL}/wp-json/wp/v2/posts?search={clean_search}&status=any"
    try:
        res = requests.get(endpoint, headers=headers, timeout=10)
        if res.status_code == 200:
            for post in res.json():
                if clean_search in post['title']['rendered']: return True
    except: pass
    return False

def extract_release_str(text):
    patterns = [
        r'\d{4}年\d{1,2}月\d{1,2}日', r'\d{1,2}月\d{1,2}日',
        r'\d{4}年\d{1,2}月', r'\d{4}年(春|夏|秋|冬|配信予定|リリース予定)', r'今冬', r'今春', r'今夏', r'今秋'
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match: return match.group(0)
    return "未定（公式発表待ち）"

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
        weights = [50, 30, 15, 5]
    else:
        options = ["即買い(予約済)", "様子見(レビュー待ち)", "セール待ち", "興味なし"]
        comments = [
            {"author": "名無し", "text": "ボリューム次第かな"},
            {"author": "FPS勢", "text": "PV見た感じ面白そう"},
            {"author": "匿名", "text": "バグなければ神ゲー"},
            {"author": "積みゲーマー", "text": "クリア時間どれくらい？"}
        ]
        weights = [45, 35, 15, 5]
    return options, comments, weights

def create_post(entry):
    title = entry.title
    link = entry.link
    description = entry.description
    
    clean_title = re.sub(r'【.*?】', '', title).split("」")[0].replace("「", "")
    clean_title = re.sub(r'\[.*?\]', '', clean_title).strip() 
    if len(clean_title) > 30: clean_title = clean_title[:30] + "..."
    wp_title = f"【投票】{clean_title}は面白い？プレイ前の期待度アンケート"
    
    game_type = determine_game_type(title + description)
    options, sakura_comments, vote_weights = generate_vote_options(game_type)
    release_str = extract_release_str(title + description)
    
    # 投票データ生成
    initial_votes = [0] * 4
    total_sakura = random.randint(8, 15)
    for _ in range(total_sakura):
        idx = random.choices([0, 1, 2, 3], weights=vote_weights)[0]
        initial_votes[idx] += 1
    
    items_str = ",".join([f"{opt}|" for opt in options])
    billing_text = "基本プレイ無料（アイテム課金制）" if game_type == "f2p" else "パッケージ・ダウンロード販売"
    
    # ★記事本文（フォームと導入のみ）
    content = f"""
[vote_bar items="{items_str}"]
[vote_summary items="{items_str}"]
<p>新作ゲーム『{clean_title}』の情報が公開されました。<br>皆さんの期待度やプレイ予定を教えてください！</p>
"""

    # ★詳細情報はメタデータに入れる（これでフォーム下に表示される）
    meta = {
        'wiki_h2_title': f"{clean_title} の基本情報",
        'wiki_h2_text': description[:150] + "...",
        
        'wiki_info1_h3': "配信日・リリース日はいつ？",
        'wiki_info_1': f"本作のリリース予定日は {release_str} です。\n詳細な日時が判明し次第、本記事でもお知らせします。",
        
        'wiki_info2_h3': "課金要素とビジネスモデル",
        'wiki_info_2': f"本作のゲームシステムは {billing_text} となっています。",
        
        'wiki_info3_h3': "みんなの評判・期待度",
        'wiki_info_3': "発表直後から多くのゲーマーの注目を集めています。\n下のコメント欄では、皆さんの推しキャラや、プレイ予定のハードなど、自由な書き込みをお待ちしています！",
        
        'wiki_fact_h3': "公式情報",
        'wiki_info_fact': f"詳細情報は以下のニュースソースをご確認ください。\n{link}",
        
        'post_views_count': '0'
    }
    
    for i, opt in enumerate(options, 1):
        meta[f'wiki_item_name_{i}'] = opt
        meta[f'wiki_item_img_{i}'] = ""
        meta[f'vote_multi_idx_{i-1}'] = str(initial_votes[i-1])

    current_time = datetime.now()
    status = 'draft'
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
            print(f"✅ 記事作成成功: {clean_title}")
            return pid, sakura_comments, clean_title, status
    except Exception as e:
        print(f"❌ エラー: {e}")
    
    return None, None, None, None

def post_sakura_comment(post_id, comments):
    if not comments: return
    count_limit = min(len(comments), random.randint(1, 3))
    selected = random.sample(comments, k=count_limit)
    url = f"{WP_URL}/wp-json/wp/v2/comments"
    headers = get_auth_header()
    if not headers: return
    for c in selected:
        c_dt = datetime.now() - timedelta(minutes=random.randint(5, 120))
        data = {'post': post_id, 'author_name': '匿名', 'content': c['text'], 'status': 'approve', 'date': c_dt.isoformat()}
        try: requests.post(url, headers=headers, json=data, timeout=10)
        except: pass

def send_discord(title, cat, status):
    if not DISCORD_WEBHOOK_URL or "ここに" in DISCORD_WEBHOOK_URL: return
    status_ja = {'publish': '🚀 即時公開', 'future': '📅 予約投稿', 'draft': '📝 下書き'}.get(status, status)
    msg = f"🎮 **GAME記事を作成**\n**題名:** {title}\n**状態:** {status_ja}\n{WP_URL}/wp-admin/"
    try: requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=5)
    except: pass

def main():
    print("🤖 ゲームハンター(通常版) 起動")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'}
    total = 0
    for rss in RSS_URLS:
        try:
            r = requests.get(rss, headers=headers, timeout=15)
            if r.status_code != 200: continue
            feed = feedparser.parse(r.content)
            for entry in feed.entries:
                if total >= 3: break
                title = entry.title
                if not any(w in title for w in TARGET_WORDS): continue
                if any(w in title for w in NG_WORDS): continue
                if check_exists(title): continue
                
                print(f"\n✨ ヒット: {title}")
                pid, comments, clean_title, status = create_post(entry)
                if pid:
                    post_sakura_comment(pid, comments)
                    send_discord(clean_title, "game", status)
                    total += 1
        except: pass
        if total >= 3: break
    print(f"🏁 完了: {total}件作成")

if __name__ == "__main__":
    main()
