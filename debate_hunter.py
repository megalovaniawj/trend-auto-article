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
    "https://www.4gamer.net/rss/index.xml",           # ゲーム
    "https://www.gizmodo.jp/index.xml",               # ガジェット
    "https://rocketnews24.com/feed/",                 # グルメ・ネタ
    "https://news.denfaminicogamer.jp/feed"           # ゲーム予備
]

# 除外ワード
NG_WORDS = ["セール", "決算", "インタビュー", "レポート", "舞台", "オーディション", "求人", "人事", "放送", "プレゼント", "まとめ", "漫画", "アニメ"]

# ターゲットワード
TARGET_WORDS = ["事前登録", "発売", "リリース", "決定", "発表", "登場", "開始", "新商品", "新メニュー", "販売"]

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
                existing_title = post['title']['rendered']
                if clean_search in existing_title:
                    return True
    except: pass
    return False

def extract_release_str(text):
    patterns = [
        r'\d{4}年\d{1,2}月\d{1,2}日', r'\d{1,2}月\d{1,2}日',
        r'\d{4}年\d{1,2}月下旬', r'\d{4}年\d{1,2}月上旬', r'\d{4}年\d{1,2}月中旬',
        r'\d{4}年\d{1,2}月', r'今冬', r'今春', r'今夏', r'今秋'
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match: return match.group(0)
    return "近日中（公式発表待ち）"

def determine_category(text):
    text = text.lower()
    if any(w in text for w in ["バーガー", "丼", "定食", "飲み放題", "食べ放題", "スタバ", "マック", "マクド", "カフェ", "ランチ", "味", "美味しい", "不味い", "試食", "グルメ", "スイーツ", "コンビニ", "ローソン", "セブン", "ファミマ", "ピザ", "カレー"]):
        return "food"
    if any(w in text for w in ["apple", "iphone", "android", "pixel", "galaxy", "pc", "スペック", "イヤホン", "ヘッドホン", "カメラ", "スマホ", "watch", "windows", "mac", "cpu", "gpu", "キーボード", "モニタ"]):
        return "tech"
    return "game"

def generate_content_data(category, title):
    clean_title = re.sub(r'【.*?】', '', title).split("」")[0].replace("「", "")
    clean_title = re.sub(r'\[.*?\]', '', clean_title).strip()
    if len(clean_title) > 35: clean_title = clean_title[:35] + "..."

    if category == "food":
        wp_title = f"【評価】『{clean_title}』はウマい？写真詐欺？食べた感想まとめ"
        options = ["神ウマ（リピ確）", "普通に美味しい", "期待外れ（微妙）", "金返せ（マズい）"]
        weights = [50, 30, 10, 10]
        comments = [
            "写真詐欺かと思ったけど普通に美味かった", "値段の割に量が少ない気がする", "これはリピ確だわ", 
            "期待しすぎたかも", "コンビニで買えるのはありがたい", "カロリーヤバそうｗ", 
            "味はいいけど高いな", "見た目のインパクトはすごい", "売り切れで買えなかった…", 
            "想像通りの味だった", "コスパは微妙かな", "温かいうちに食べるのがおすすめ"
        ]
        spec_h2 = "カロリー・価格情報"
        spec_text = "気になるカロリーや最新の価格情報は、公式サイトまたは店頭の表示をご確認ください。<br>期間限定メニューの場合、早期終了の可能性もあるためご注意ください。"

    elif category == "tech":
        wp_title = f"【評価】『{clean_title}』は買いか？コスパと性能を議論するスレ"
        options = ["即買い（神機）", "様子見（レビュー待ち）", "高すぎ（見送り）", "ゴミ（解散）"]
        weights = [45, 35, 15, 5]
        comments = [
            "スペックの割に高いな", "デザインは好き", "バッテリー持ちが気になる", 
            "前モデルから乗り換える価値ある？", "円安の影響がモロに出てるな", "予約したわ、届くの楽しみ", 
            "YouTuberのレビュー待ちかな", "この機能はいらないから安くして欲しかった", "実機触ってから決める", 
            "競合製品の方がコスパいいかも", "信者アイテム乙", "色が微妙なんだよなぁ"
        ]
        spec_h2 = "スペック・発売価格"
        spec_text = "詳細な技術仕様（スペック）や国内販売価格については、メーカー公式発表をご確認ください。<br>予約開始日や発売日についても随時更新予定です。"

    else:
        wp_title = f"【評価】『{clean_title}』は神ゲー？クソゲー？本音評価まとめ"
        options = ["神ゲー（覇権）", "良ゲー（普通）", "様子見（地雷臭）", "クソゲー（返金）"]
        weights = [40, 30, 20, 10]
        comments = [
            "PV詐欺じゃなければ神ゲー", "リセマラめんどくさそう", "課金圧が心配だな", 
            "キャラデザは最高", "システム周りが古臭い", "バグさえなければ覇権", 
            "運営の対応次第だな", "無課金でも遊べる？", "容量デカすぎｗ", 
            "マルチプレイあるのかな", "とりあえずDLしてみるわ", "声優が豪華すぎる"
        ]
        spec_h2 = "対応ハード・システム"
        spec_text = "対応プラットフォームや課金形態（基本無料/買い切り）については、公式サイトの最新情報をご確認ください。"

    return clean_title, wp_title, options, comments, weights, spec_h2, spec_text

def create_post(entry, category):
    title = entry.title
    link = entry.link
    description = entry.description
    
    clean_title, wp_title, options, comments_pool, weights, spec_h2, spec_text = generate_content_data(category, title)
    
    initial_votes = [0] * 4
    total_sakura = random.randint(40, 60)
    for _ in range(total_sakura):
        idx = random.choices([0, 1, 2, 3], weights=weights)[0]
        initial_votes[idx] += 1
    
    items_str = ",".join([f"{opt}|" for opt in options])
    release_str = extract_release_str(title + description)
    
    content = f"""
[vote_bar items="{items_str}"]
[vote_summary items="{items_str}"]
<p>話題の新作『{clean_title}』について、皆さんの本音を聞かせてください。<br><strong>「期待通り？」それとも「ガッカリ？」</strong><br>忖度なしの評価を投票で決定します！</p>
<h2>{clean_title} とは？</h2>
<p>{description}</p>
<h2>発売日・リリース時期</h2>
<p>リリース予定: <strong>{release_str}</strong></p>
<h2>{spec_h2}</h2>
<p>{spec_text}</p>
<h2>みんなの口コミ・評判（議論・レスバ歓迎）</h2>
<p>SNSや掲示板では既に様々な意見が飛び交っています。<br>
下のコメント欄で、あなたの率直な意見やリーク情報、感想を書き込んでください。<br>
匿名で投稿可能です。</p>
<p><a href="{link}" target="_blank" rel="noopener">情報元で全文を読む</a></p>
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
    if not headers: return None, None

    try:
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", headers=headers, json=post_data, timeout=30)
        if res.status_code == 201:
            pid = res.json()['id']
            print(f"✅ 作成成功({category}): {clean_title} (投票数: {sum(initial_votes)})")
            return pid, comments_pool
    except Exception as e:
        print(f"❌ エラー: {e}")
    
    return None, None

def post_sakura_comment(post_id, comments_pool):
    if not comments_pool: return
    count = random.randint(5, 10)
    selected = random.sample(comments_pool, k=min(len(comments_pool), count))
    url = f"{WP_URL}/wp-json/wp/v2/comments"
    headers = get_auth_header()
    if not headers: return

    for text in selected:
        c_dt = datetime.now() - timedelta(minutes=random.randint(5, 300))
        data = {'post': post_id, 'author_name': '匿名', 'content': text, 'status': 'approve', 'date': c_dt.isoformat()}
        try: requests.post(url, headers=headers, json=data, timeout=5)
        except: pass
    print(f"   💬 コメントを{len(selected)}件投稿しました")

def send_discord(title, cat, status):
    if not DISCORD_WEBHOOK_URL or "ここに" in DISCORD_WEBHOOK_URL: return
    status_ja = {'publish': '🚀 即時公開', 'future': '📅 予約投稿', 'draft': '📝 下書き'}.get(status, status)
    msg = f"🆕 **{cat.upper()}記事を作成**\n**題名:** {title}\n**状態:** {status_ja}\n{WP_URL}/wp-admin/"
    try: requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=5)
    except: pass

def main():
    print("🤖 議論ハンター(debate_hunter) 起動")
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
                
                cat = determine_category(title + entry.description)
                print(f"\n✨ ヒット({cat}): {title}")
                pid, comments_pool = create_post(entry, cat)
                if pid:
                    post_sakura_comment(pid, comments_pool)
                    clean_title = re.sub(r'【.*?】', '', title).split("」")[0]
                    send_discord(clean_title, cat, "draft")
                    total += 1
        except: pass
        if total >= 3: break
    print(f"🏁 完了: {total}件作成")

if __name__ == "__main__":
    main()
