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

# 情報源リスト
RSS_URLS = [
    "https://www.4gamer.net/rss/index.xml",
    "https://news.denfaminicogamer.jp/feed"
]

# 除外ワード
NG_WORDS = ["グッズ", "コラボ", "キャンペーン", "イベント", "ポップアップ", "フェア", "記念", "主題歌", "サントラ", "レポート", "舞台", "オーディション", "セール", "ゲーミングPC", "キーボード", "マウス", "ヘッドセット", "チェア", "インタビュー", "決算"]

# ターゲットワード
TARGET_WORDS = ["事前登録", "配信開始", "サービス開始", "発売", "リリース", "決定"]

# ==========================================
# 関数定義
# ==========================================

def get_auth_header():
    if not WP_USER or not WP_APP_PASS:
        print("❌ 【エラー】WordPressの認証情報が設定されていません。")
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
    return "未定（公式発表待ち）"

def extract_platforms(text):
    """本文からプラットフォームを抽出する"""
    platforms = []
    text_lower = text.lower()
    
    if "switch" in text_lower: platforms.append("Nintendo Switch")
    if "ps5" in text_lower: platforms.append("PlayStation 5")
    if "ps4" in text_lower: platforms.append("PlayStation 4")
    if "steam" in text_lower or "pc" in text_lower: platforms.append("PC (Steam等)")
    if "ios" in text_lower or "app store" in text_lower: platforms.append("iOS")
    if "android" in text_lower or "google play" in text_lower: platforms.append("Android")
    
    if not platforms: return "未定 / 公式サイトをご確認ください"
    return "、".join(list(set(platforms)))

def send_discord_notification(title, release_str, status_type):
    if not DISCORD_WEBHOOK_URL or "ここに" in DISCORD_WEBHOOK_URL:
        return
        
    status_ja = {
        'publish': '🚀 即時公開',
        'future': '📅 予約投稿',
        'draft': '📝 下書き保存'
    }.get(status_type, status_type)

    login_url = f"{WP_URL}/wp-admin/"
    message = f"✅ **記事を作成しました（＋サクラ投票完了）**\n\n" \
              f"**タイトル:** {title}\n" \
              f"**時期:** {release_str}\n" \
              f"**状態:** {status_ja}\n" \
              f"**確認:** {login_url}"
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        print("💬 Discordに通知を送りました")
    except: pass

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
    platforms = extract_platforms(title + description)
    
    # サクラ投票データの生成
    initial_votes = [0] * 4
    total_sakura = random.randint(8, 15)
    
    for _ in range(total_sakura):
        idx = random.choices([0, 1, 2, 3], weights=vote_weights)[0]
        initial_votes[idx] += 1
    
    items_str = ",".join([f"{opt}|" for opt in options])
    
    billing_text = "基本プレイ無料（アイテム課金制）" if game_type == "f2p" else "パッケージ・ダウンロード販売"
    
    # ▼【修正】コンテンツの順番を「フォーム → テキスト」に完全変更
    content = f"""
[vote_bar items="{items_str}"]
[vote_summary items="{items_str}"]
<p>新作ゲーム『{clean_title}』の情報が公開されました。<br>皆さんの期待度やプレイ予定を教えてください！</p>
<h2>{clean_title} の基本情報</h2>
<p>{description}</p>
<h2>配信日・リリース日はいつ？</h2>
<p>本作のリリース予定日は <strong>{release_str}</strong> です。<br>詳細な日時が判明し次第、本記事でもお知らせします。</p>
<h2>課金要素とビジネスモデル</h2>
<p>本作のゲームシステムは <strong>{billing_text}</strong> となっています。</p>
<h2>対応ハード・プラットフォーム</h2>
<p>現在発表されている対応プラットフォームは以下の通りです。</p>
<p><strong>{platforms}</strong></p>
<h2>みんなの評判・期待度</h2>
<p>発表直後から多くのゲーマーの注目を集めています。<br>下のコメント欄では、皆さんの推しキャラや、プレイ予定のハードなど、自由な書き込みをお待ちしています！</p>
<p><a href="{link}" target="_blank" rel="noopener">ニュースソースで全文を読む（4Gamer/電ファミ）</a></p>
"""

    meta = {
        'wiki_h2_title': f"{clean_title} について",
        'wiki_h2_text': description[:100] + "...",
        'post_views_count': '0'
    }
    
    for i, opt in enumerate(options, 1):
        meta[f'wiki_item_name_{i}'] = opt
        meta[f'wiki_item_img_{i}'] = ""
        meta[f'vote_multi_idx_{i-1}'] = str(initial_votes[i-1])

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
            print(f"✅ 記事作成成功！ ID: {pid} (サクラ投票: {sum(initial_votes)}票)")
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
    print("🤖 ゲームハンター(自動投稿ロボ v9) 起動！")
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'}
    total_created = 0
    
    for rss_url in RSS_URLS:
        print(f"\n📡 RSS取得中: {rss_url} ...")
        try:
            resp = requests.get(rss_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"⚠️ 取得失敗 (Status: {resp.status_code})")
                continue
            
            feed = feedparser.parse(resp.content)
            if not feed.entries:
                print("⚠️ 記事がありませんでした")
                continue
                
            print(f"   ↪︎ {len(feed.entries)} 件の記事を取得")
            
            for entry in feed.entries:
                if total_created >= 3: break
                title = entry.title
                
                if not any(w in title for w in TARGET_WORDS): continue
                if any(w in title for w in NG_WORDS):
                    print(f"✖️ スキップ(NGワード): {title[:30]}...")
                    continue
                
                clean_title_check = re.sub(r'【.*?】', '', title).split("」")[0].replace("「", "")
                wp_check_title = f"【投票】{clean_title_check}は面白い？プレイ前の期待度アンケート"
                
                if check_exists(wp_check_title):
                    print(f"🔷 スキップ(作成済): {clean_title_check}")
                    continue

                print(f"\n✨ 【ヒット！】作成を開始します: {title}")
                pid, sakura, clean_title, status = create_post(entry)
                
                if pid:
                    post_sakura_comment(pid, sakura)
                    release_str = extract_release_str(title + entry.description)
                    send_discord_notification(clean_title, release_str, status)
                    total_created += 1

        except Exception as e:
            print(f"❌ エラー発生: {e}")
        
        if total_created >= 3:
            print("\n🛑 制限（3件）に達したため終了します")
            break

    print("--------------------------------------------------")
    print(f"🏁 全処理完了！ 作成記事数: {total_created}件")
    print("--------------------------------------------------")

if __name__ == "__main__":
    main()
