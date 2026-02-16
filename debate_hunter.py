import feedparser
import requests
import re
import time
import random
import base64
import os
import json
from datetime import datetime, timedelta

# ==========================================
# ★設定エリア
# ==========================================
WP_URL = os.environ.get("WP_URL", "https://docchiyo.com")
WP_USER = os.environ.get("WP_USER", "bear")
WP_APP_PASS = os.environ.get("WP_APP_PASS")

# Discord Webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF"

# ★カテゴリーID設定 (画像に基づき設定)
CATEGORY_IDS = {
    "social": 194,  # 社会 (Social)
    "food": 11,     # food
    "tech": 24,     # tech (ガジェット含む)
    "anime": 155,   # anime
    "entame": 95,   # contents (エンタメ全般)
    "game": 13      # game
}

# 情報源リスト
RSS_URLS = [
    "https://news.yahoo.co.jp/rss/topics/dom.xml",    # 社会
    "https://news.yahoo.co.jp/rss/topics/ent.xml",    # エンタメ
    "https://news.livedoor.com/topics/rss/dom.xml",   # 国内
    "https://www.4gamer.net/rss/index.xml",           # ゲーム
    "https://rocketnews24.com/feed/",                 # グルメ
    "https://feeds.cinematoday.jp/cinematoday/rss",   # 映画
    "https://mantan-web.jp/rss/rss.xml"               # アニメ
]

# 除外ワード
NG_WORDS = ["セール", "決算", "インタビュー", "レポート", "舞台", "オーディション", "求人", "人事", "放送", "プレゼント", "まとめ", "訃報", "死去", "ご冥福"]

# ターゲットワード
TARGET_WORDS = ["発売", "リリース", "決定", "発表", "開始", "新商品", "新メニュー", "公開", "実写化", "映画化", "アニメ化", "検討", "方針", "批判", "物議", "炎上", "逮捕", "容疑", "可決", "辞任", "疑惑", "増税", "義務化", "中止"]

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

# --- テキスト処理系 ---

def clean_html(raw_html):
    """HTMLタグを除去してプレーンテキストにする"""
    cleaner = re.compile('<.*?>')
    cleantext = re.sub(cleaner, '', raw_html)
    return cleantext.strip()

def extract_release_str(text):
    patterns = [r'\d{4}年\d{1,2}月\d{1,2}日', r'\d{1,2}月\d{1,2}日', r'\d{4}年\d{1,2}月', r'今冬', r'今春', r'今夏', r'今秋']
    for pattern in patterns:
        match = re.search(pattern, text)
        if match: return match.group(0)
    return "近日中"

def extract_price_str(text):
    match = re.search(r'(\d{1,3}(,\d{3})*|\d+)円', text)
    if match: return match.group(0)
    return None

def determine_category(text):
    text = text.lower()
    if any(w in text for w in ["バーガー", "丼", "定食", "飲み放題", "食べ放題", "スタバ", "マック", "マクド", "ランチ", "味", "美味しい", "不味い", "試食", "グルメ", "スイーツ", "コンビニ", "ローソン", "セブン", "ファミマ", "ピザ", "カレー"]):
        return "food"
    if any(w in text for w in ["apple", "iphone", "android", "pixel", "galaxy", "pc", "スペック", "イヤホン", "ヘッドホン", "カメラ", "スマホ", "watch", "windows", "mac", "cpu", "gpu", "キーボード", "モニタ"]):
        return "tech"
    if any(w in text for w in ["アニメ", "声優", "マンガ", "漫画", "連載", "ジャンプ"]):
        return "anime" # アニメ専用IDへ
    if any(w in text for w in ["映画", "実写", "ドラマ", "興行収入", "視聴率", "ディズニー", "usj", "ジブリ"]):
        return "entame"
    if any(w in text for w in ["首相", "内閣", "政府", "議員", "選挙", "増税", "減税", "給付金", "逮捕", "容疑", "判決", "事故", "事件", "物議", "炎上", "批判", "迷惑", "異次元", "少子化", "不倫", "パパ活", "詐欺"]):
        return "social"
    return "game"

def get_wikipedia_summary(keyword):
    try:
        url = "https://ja.wikipedia.org/w/api.php"
        params = { "action": "query", "format": "json", "prop": "extracts", "exintro": True, "explaintext": True, "redirects": 1, "titles": keyword }
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid == "-1": continue
            summary = page.get("extract", "")
            if summary: return summary
    except: pass
    return None

# --- コンテンツ生成ロジック ---

def get_dynamic_spec_content(category, description):
    """本文から情報を抜き出し、それっぽい見出しと内容を動的に生成する"""
    clean_desc = clean_html(description)
    price = extract_price_str(clean_desc)
    date_str = extract_release_str(clean_desc)
    
    # 本文を適度な長さにカットして引用風にする
    desc_quote = clean_desc[:200] + ("..." if len(clean_desc) > 200 else "")

    headers_db = {
        "social": ["ニュースの概要", "議論の背景", "争点", "世間の関心事"],
        "food": ["価格・販売情報", "商品詳細", "メニュー情報", "スペック"],
        "tech": ["スペック・価格", "技術仕様", "発売日情報", "詳細データ"],
        "entame": ["作品概要", "公開情報", "放送・公開日", "スタッフ・キャスト"],
        "game": ["ゲーム仕様", "プラットフォーム", "対応機種", "製品情報"],
        "anime": ["放送情報", "作品データ", "キャスト・スタッフ", "あらすじ"]
    }
    
    h3_title = random.choice(headers_db.get(category, headers_db["game"]))
    body_text = ""

    # 定型文ではなく、取得した本文(desc_quote)をベースに組み立てる
    if category == "food":
        body_text = f"{desc_quote}\n\n"
        if price: body_text += f"価格は **{price}** と発表されています。"
            
    elif category == "social":
        body_text = f"{desc_quote}\n\n本件についてはSNS上でも賛否両論の意見が飛び交っており、大きな議論を呼んでいます。"
        
    elif category == "tech" or category == "game":
        body_text = f"{desc_quote}\n\n"
        if date_str != "近日中": body_text += f"リリース予定時期は **{date_str}** です。"
        if price: body_text += f"価格は **{price}** となっています。"
        
    else: # entame, anime
        body_text = f"{desc_quote}\n\n公開・放送予定: **{date_str}**"

    return h3_title, body_text

def get_dynamic_review_text(category):
    """口コミセクションもランダム化"""
    templates = [
        "SNSや掲示板では既に様々な意見が飛び交っています。\n「期待通り」「いや、それは違う」など、賛否両論の状態です。",
        "発表直後から大きな反響を呼んでおり、トレンド入りするほどの話題となっています。\n特に以下の点が議論の的になっているようです。",
        "ネット上では「待ってました！」という歓迎の声と、「少し不安」という慎重な意見が入り混じっています。",
        "賛成派と反対派で意見が真っ二つに割れているようです。\nあなたの率直な意見もぜひ投票・コメントで教えてください。"
    ]
    return random.choice(templates) + "\n\n下のコメント欄で、あなたの意見やリーク情報、感想を書き込んでください。\n匿名で投稿可能です。"

def generate_persona_comments(category, title, options):
    comments = []
    templates = {
        "social": {
            "positive": ["これは評価できる。まともな判断。", "{title}に関しては支持する。", "批判もあるだろうけど英断。", "日本のスタンダードになるべき。", "遅すぎたけどマシ。"],
            "negative": ["日本終わったな。", "国民を舐めてる。", "税金使うなよ...呆れた。", "理解できない。誰得？", "即刻撤回すべき。"],
            "neutral": ["どっちもどっち。", "事実確認が先。", "今後の展開次第。", "マスコミの切り取りじゃね？"]
        },
        "food": {
            "positive": ["{title}はリピ確。", "見た目詐欺かと思ったけど味はガチ。", "カロリー爆弾だけど食う価値あるｗ", "飛ぶぞ。", "値段以上の満足感。"],
            "negative": ["写真と実物が違いすぎて草。", "期待してたのに微妙。", "味が薄い。", "これでこの値段は高い。", "話題だけど美味しくない。"],
            "neutral": ["売り切れてたわ...", "カロリー見てそっと閉じたｗ", "一度は食べてみたい。", "みんなの感想待ち。"]
        },
        "tech": {
            "positive": ["{title}のスペックえぐい。", "デザイン最高。", "求めてた機能が来た！", "コスパ最強。", "レビュー見る限り良さげ。"],
            "negative": ["高すぎワロタ。", "期待外れ。", "バッテリー持ち悪そう。", "この値段は舐めてる。", "信者乙。"],
            "neutral": ["実機触ってから決める。", "レビュー待ち。", "金がない...", "色が微妙。"]
        },
        "entame": {
            "positive": ["涙止まらん。神作。", "キャストがハマり役。", "作画クオリティ高い。", "脚本が天才。", "社会現象になる。"],
            "negative": ["原作改変が酷い。", "時間の無駄だった。", "ポリコレ配慮しすぎ。", "声優が合ってない。", "予告詐欺。"],
            "neutral": ["嫌いじゃない。", "来週次第。", "原作知らないけど楽しめる？", "とりあえず見る。"]
        },
        "anime": {
            "positive": ["神回確定。", "作画班の気合がすごい。", "声優の演技に鳥肌。", "今期の覇権はこれ。", "OP/EDも最高。"],
            "negative": ["展開が遅い。", "原作カットしすぎ。", "作画崩壊してない？", "期待はずれ。", "キャラデザが微妙。"],
            "neutral": ["とりあえず3話まで見る。", "原作未読だけど分かるかな？", "考察が捗る。", "2期あるかな？"]
        },
        "game": {
            "positive": ["神ゲー確定！", "PVで鳥肌立った。", "声優豪華すぎｗ", "システム良かった。", "覇権の予感。"],
            "negative": ["どうせ集金ゲー。", "システムが古臭い。", "リセマラ地獄。", "運営が信用できない。", "即サ終しそう。"],
            "neutral": ["無課金でも遊べる？", "容量デカすぎｗ", "とりあえずDL。", "評判待ち。"]
        }
    }

    def apply_persona(text, persona):
        if persona == "rough": return text.replace("です", "だろ").replace("ます", "る").replace("すごい", "ヤバい") + " 草"
        elif persona == "otaku": return text + " というか、結論これ一択。"
        elif persona == "gal": return text.replace("。", "！").replace("すごい", "神").replace("美味い", "優勝") + " 尊い..."
        return text 

    # カテゴリ辞書にない場合はgameを使う
    target_temps = templates.get(category, templates["game"])
    num_comments = random.randint(5, 8)
    
    for _ in range(num_comments):
        rand_val = random.randint(1, 100)
        if category == "social":
            if rand_val <= 40: base_text = random.choice(target_temps["positive"])
            elif rand_val <= 80: base_text = random.choice(target_temps["negative"])
            else: base_text = random.choice(target_temps["neutral"])
        else:
            if rand_val <= 70: base_text = random.choice(target_temps["positive"])
            elif rand_val <= 90: base_text = random.choice(target_temps["negative"])
            else: base_text = random.choice(target_temps["neutral"])
            
        short_title = title[:15]
        text = base_text.replace("{title}", short_title)
        persona = random.choice(["standard", "standard", "rough", "otaku", "gal"])
        comments.append(apply_persona(text, persona))
        
    return comments

def generate_content_data(category, title):
    clean_title = re.sub(r'【.*?】', '', title).split("」")[0].replace("「", "").strip()
    if len(clean_title) > 35: clean_title = clean_title[:35] + "..."

    # カテゴリ別のタイトルと選択肢
    if category == "social":
        wp_title = f"【議論】『{clean_title}』はあり？なし？世間の反応まとめ"
        options = ["支持する（あり）", "理解できない（なし）", "どちらとも言えない", "もっと議論が必要"]
        weights = [30, 40, 20, 10]
    elif category == "food":
        wp_title = f"【評価】『{clean_title}』はウマい？写真詐欺？食べた感想まとめ"
        options = ["神ウマ（リピ確）", "普通に美味しい", "期待外れ（微妙）", "金返せ（マズい）"]
        weights = [50, 30, 10, 10]
    elif category == "tech":
        wp_title = f"【評価】『{clean_title}』は買いか？コスパと性能を議論するスレ"
        options = ["即買い（神機）", "様子見（レビュー待ち）", "高すぎ（見送り）", "ゴミ（解散）"]
        weights = [45, 35, 15, 5]
    elif category == "entame" or category == "anime":
        wp_title = f"【評価】『{clean_title}』は面白い？つまらない？感想・評判まとめ"
        options = ["最高（神作品）", "普通に楽しめる", "期待外れ（微妙）", "時間の無駄（駄作）"]
        weights = [40, 30, 20, 10]
    else: # Game
        wp_title = f"【評価】『{clean_title}』は神ゲー？クソゲー？本音評価まとめ"
        options = ["神ゲー（覇権）", "良ゲー（普通）", "様子見（地雷臭）", "クソゲー（返金）"]
        weights = [40, 30, 20, 10]

    return clean_title, wp_title, options, weights

def create_post(entry, category):
    title = entry.title
    link = entry.link
    description = clean_html(entry.description) # ★ここでHTML除去
    
    clean_title, wp_title, options, weights = generate_content_data(category, title)
    comments_pool = generate_persona_comments(category, clean_title, options)
    
    initial_votes = [0] * 4
    total_sakura = random.randint(40, 60)
    for _ in range(total_sakura):
        idx = random.choices([0, 1, 2, 3], weights=weights)[0]
        initial_votes[idx] += 1
    
    items_str = ",".join([f"{opt}|" for opt in options])
    
    # 動的コンテンツ生成
    release_str = extract_release_str(description)
    spec_h3, spec_text = get_dynamic_spec_content(category, description) # 本文から要約作成
    wiki_full_text = get_wikipedia_summary(clean_title)
    
    # 導入文作成（RSS本文を使用）
    intro_text = description[:200] + "..."
    wiki_trivia = "詳細情報は公式発表をご確認ください。"
    
    if wiki_full_text:
        intro_text += "\n\n<h3>💡 概要（Wikipedia）</h3>\n<p>" + wiki_full_text[:200] + "...</p>"
        wiki_trivia = wiki_full_text[:400] + "..."

    content = f"""
[vote_bar items="{items_str}"]
[vote_summary items="{items_str}"]
<p>話題の『{clean_title}』について、皆さんの本音を聞かせてください。<br><strong>「支持する？」それとも「反対？」</strong><br>忖度なしの評価を投票で決定します！</p>
"""

    # メタデータ（動的コンテンツをセット）
    meta = {
        'wiki_h2_title': f"{clean_title} について",
        'wiki_h2_text': intro_text,
        
        'wiki_info1_h3': "日時・期間",
        'wiki_info_1': f"関連日時: {release_str}",
        
        'wiki_info2_h3': spec_h3,
        'wiki_info_2': spec_text,
        
        'wiki_info3_h3': "みんなの口コミ・評判",
        'wiki_info_3': get_dynamic_review_text(category), # 口コミ導入文もランダム化
        
        'wiki_fact_h3': "豆知識・補足",
        'wiki_info_fact': wiki_trivia,

        'post_views_count': '0'
    }

    for i, opt in enumerate(options, 1):
        meta[f'wiki_item_name_{i}'] = opt
        meta[f'wiki_item_img_{i}'] = ""
        meta[f'vote_multi_idx_{i-1}'] = str(initial_votes[i-1])

    current_time = datetime.now()
    status = 'draft' 
    post_date = current_time.strftime('%Y-%m-%dT%H:%M:%S')
    
    # カテゴリID設定
    cat_id = CATEGORY_IDS.get(category, 1)
    
    post_data = {'title': wp_title, 'content': content, 'status': status, 'date': post_date, 'categories': [cat_id], 'meta': meta}

    headers = get_auth_header()
    if not headers: return None, None

    try:
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", headers=headers, json=post_data, timeout=30)
        if res.status_code == 201:
            pid = res.json()['id']
            print(f"✅ 作成成功({category}): {clean_title}")
            return pid, comments_pool
    except Exception as e: print(f"❌ エラー: {e}")
    return None, None

def post_sakura_comment(post_id, comments_pool):
    if not comments_pool: return
    url = f"{WP_URL}/wp-json/wp/v2/comments"
    headers = get_auth_header()
    if not headers: return
    
    print(f"   💬 コメント投稿開始（全{len(comments_pool)}件）...")
    
    for i, text in enumerate(comments_pool):
        c_dt = datetime.now() - timedelta(minutes=random.randint(5, 300))
        data = {
            'post': post_id,
            'author_name': '匿名', 
            'content': text,
            'status': 'approve',
            'date': c_dt.isoformat()
        }
        try:
            r = requests.post(url, headers=headers, json=data, timeout=10)
            if r.status_code == 201:
                print(f"      - コメント{i+1} OK")
            else:
                print(f"      - コメント{i+1} 失敗: {r.status_code}")
        except: pass
        time.sleep(1.5) # 連投規制回避

def send_discord(title, cat, status):
    if not DISCORD_WEBHOOK_URL or "ここに" in DISCORD_WEBHOOK_URL: return
    status_ja = {'publish': '🚀 即時公開', 'future': '📅 予約投稿', 'draft': '📝 下書き'}.get(status, status)
    msg = f"📰 **{cat.upper()}記事を作成**\n**題名:** {title}\n**状態:** {status_ja}\n{WP_URL}/wp-admin/"
    try: requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=5)
    except: pass

def main():
    print("🤖 議論ハンター(debate_hunter) v21 起動")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'}
    total = 0
    for rss in RSS_URLS:
        print(f"\n📡 取得中: {rss} ...")
        try:
            r = requests.get(rss, headers=headers, timeout=15)
            if r.status_code != 200: continue
            feed = feedparser.parse(r.content)
            
            rss_count = 0
            for entry in feed.entries:
                if total >= 3 or rss_count >= 1: break
                
                title = entry.title
                if not any(w in title for w in TARGET_WORDS): continue
                if any(w in title for w in NG_WORDS):
                    print(f"✖️ NG: {title[:20]}...")
                    continue
                if check_exists(title):
                    print(f"🔷 済: {title[:20]}...")
                    continue
                
                cat = determine_category(title + entry.description)
                print(f"\n✨ ヒット({cat}): {title}")
                pid, comments_pool = create_post(entry, cat)
                if pid:
                    post_sakura_comment(pid, comments_pool)
                    clean_title = re.sub(r'【.*?】', '', title).split("」")[0]
                    send_discord(clean_title, cat, "draft")
                    total += 1
                    rss_count += 1
        except Exception as e: print(f"エラー: {e}")
        if total >= 3: break
    print(f"🏁 完了: {total}件作成")

if __name__ == "__main__":
    main()
