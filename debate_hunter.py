import feedparser
import requests
import re
import time
import random
import base64
import os
import html
import json
from datetime import datetime, timedelta

# ==========================================
# ★設定エリア
# ==========================================
WP_URL = os.environ.get("WP_URL", "https://docchiyo.com")
WP_USER = os.environ.get("WP_USER", "bear")
WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") # 必須：GitHub Secretsに設定してください

# Discord Webhook
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF"

# モデル設定
MODEL_NAME = "gemma-3-27b-it"

# ★カテゴリーID設定
CATEGORY_IDS = {
    "social": 194,
    "food": 11,
    "tech": 24,
    "anime": 155,
    "entame": 95,
    "game": 13
}

# RSSリスト (社会・エンタメ・トレンド)
RSS_URLS = [
    "https://news.yahoo.co.jp/rss/topics/dom.xml",
    "https://news.yahoo.co.jp/rss/topics/ent.xml",
    "https://news.livedoor.com/topics/rss/dom.xml",
    "https://www.4gamer.net/rss/index.xml",
    "https://rocketnews24.com/feed/",
    "https://feeds.cinematoday.jp/cinematoday/rss",
    "https://mantan-web.jp/rss/rss.xml"
]

NG_WORDS = ["セール", "決算", "インタビュー", "レポート", "舞台", "オーディション", "求人", "人事", "放送", "プレゼント", "まとめ", "訃報", "死去", "ご冥福", "亡く", "逝去"]
TARGET_WORDS = ["発売", "リリース", "決定", "発表", "開始", "新商品", "新メニュー", "公開", "実写化", "映画化", "アニメ化", "検討", "方針", "批判", "物議", "炎上", "逮捕", "容疑", "可決", "辞任", "疑惑", "増税", "義務化", "中止", "話題"]

# ==========================================
# 関数定義
# ==========================================

def get_auth_header():
    if not WP_USER or not WP_APP_PASS: return None
    creds = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(creds.encode()).decode()
    return {'Authorization': f'Basic {token}'}

def clean_text(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def check_exists(title):
    headers = get_auth_header()
    if not headers: return False
    clean_search = clean_text(title)[:15]
    endpoint = f"{WP_URL}/wp-json/wp/v2/posts?search={clean_search}&status=any"
    try:
        res = requests.get(endpoint, headers=headers, timeout=10)
        if res.status_code == 200:
            for post in res.json():
                if clean_search in post['title']['rendered']: return True
    except: pass
    return False

def determine_category(text):
    text = text.lower()
    if any(w in text for w in ["バーガー", "丼", "定食", "飲み放題", "食べ放題", "スタバ", "マック", "マクド", "ランチ", "味", "美味しい", "不味い", "試食", "グルメ", "スイーツ", "コンビニ", "ローソン", "セブン", "ファミマ", "ピザ", "カレー"]): return "food"
    if any(w in text for w in ["apple", "iphone", "android", "pixel", "galaxy", "pc", "スペック", "イヤホン", "ヘッドホン", "カメラ", "スマホ", "watch", "windows", "mac", "cpu", "gpu", "キーボード", "モニタ"]): return "tech"
    if any(w in text for w in ["アニメ", "声優", "マンガ", "漫画", "連載", "ジャンプ", "プリキュア", "ガンダム"]): return "anime"
    if any(w in text for w in ["映画", "実写", "ドラマ", "興行収入", "視聴率", "ディズニー", "usj", "ジブリ"]): return "entame"
    if any(w in text for w in ["首相", "内閣", "政府", "議員", "選挙", "増税", "減税", "給付金", "逮捕", "容疑", "判決", "事故", "事件", "物議", "炎上", "批判", "迷惑", "異次元", "少子化", "不倫", "パパ活", "詐欺"]): return "social"
    return "game"

# --- 情報収集 ---

def fetch_og_description(url):
    """ニュース記事の本文要約を取得"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            # description または og:description を探す
            match = re.search(r'<meta (property|name)="og:description" content="(.*?)"', r.text)
            if match: return clean_text(match.group(2))
            match2 = re.search(r'<meta name="description" content="(.*?)"', r.text)
            if match2: return clean_text(match2.group(1))
    except: pass
    return None

def get_wikipedia_summary(keyword):
    """Wikipediaから情報を取得"""
    try:
        clean_kw = re.sub(r'【.*?】', '', keyword).strip()
        url = "https://ja.wikipedia.org/w/api.php"
        params = { "action": "query", "format": "json", "prop": "extracts", "exintro": True, "explaintext": True, "redirects": 1, "titles": clean_kw }
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid == "-1": continue
            summary = page.get("extract", "")
            if summary: return summary
    except: pass
    return None

# --- AI生成ロジック (main.py方式) ---

def generate_article_with_ai(category, title, news_text, wiki_text):
    """
    Gemini APIを使って、記事構成・タイトル・コメントを一括生成する。
    PHPの人格ロジックをプロンプトに組み込む。
    """
    
    # PHP版の人格定義
    persona_prompt = """
    【コメント生成ルール】
    この記事に対する読者の反応コメントを5〜8件生成してください。
    以下の「人格」をランダムに割り当てて、口調を演じ分けてください。
    
    - 主要人格 (確率高):
      1. 普通: 「〜だね」「〜かも」
      2. 丁寧: 「〜ですね」「〜と思います」
      3. 雑・男言葉: 「〜だろ」「〜じゃね？」
      4. 感情的: 「〜すぎ！」「マジで〜」
      5. 弱気: 「〜かな？」「〜だっけ？」
    - レア人格 (確率低):
      1. ネットスラング: 「草」「それな」
      2. 関西弁: 「〜やな」「せやね」
      3. オタク: 「尊い」「〜なんだよなぁ」
      4. ギャル: 「神」「ビジュ良すぎ」
      5. 一言: 「これ。」「間違いない。」
    """

    prompt = f"""
    あなたはWebメディアの編集長です。以下のトレンドニュースを元に、読者参加型の「投票記事」を作成してください。
    テンプレートや固定文言は使わず、ニュースの内容に合わせて動的に文章を構成してください。

    【入力情報】
    カテゴリ: {category}
    ニュースタイトル: {title}
    ニュース概要: {news_text}
    Wikipedia情報: {wiki_text}

    【作成指示】
    1. **タイトル**: 読者が思わずクリックしたくなる、煽りや問いかけを含んだタイトル。
    2. **記事導入(H2)**: ニュースの背景を詳しく解説し、「そこで皆さんに聞きたいのですが...」と投票へ繋げる導入文（300文字程度）。
    3. **豆知識(H3)**: Wikipedia情報やニュース詳細を元にした、補足情報やトリビア（200文字程度）。
    4. **選択肢(Items)**: 
       - ニュースの内容が「対立構造（賛成vs反対、A vs B）」なら、それに応じた2〜4つの選択肢。
       - 「新商品」や「作品」なら、「期待する/しない」「買う/買わない」など。
       - 各選択肢には、なぜそれを選ぶのかの短い解説文をつけること。
    5. **コメント**: {persona_prompt}

    【出力形式(JSON)】
    Markdown記法は含めず、純粋なJSONのみを出力してください。
    {{
      "title": "記事タイトル",
      "h2_title": "導入の見出し（例：〇〇がついに発表！）",
      "h2_text": "導入の本文...",
      "fact_h3": "豆知識の見出し",
      "fact_text": "豆知識の本文...",
      "items": [
        {{ "name": "選択肢名（例：賛成）", "text": "選択肢の解説..." }},
        {{ "name": "選択肢名（例：反対）", "text": "選択肢の解説..." }}
      ],
      "comments": [
        "コメント1", "コメント2", "コメント3", "コメント4", "コメント5"
      ]
    }}
    """

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    data = { "contents": [{"parts": [{"text": prompt}]}] }
    
    try:
        res = requests.post(url, headers=headers, json=data, timeout=60)
        if res.status_code == 200:
            text = res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            # JSON部分だけ抽出
            text = text.replace('```json', '').replace('```', '').strip()
            start = text.find('{')
            end = text.rfind('}') + 1
            return json.loads(text[start:end])
    except Exception as e:
        print(f"Generate Error: {e}")
    return None

# --- 投稿処理 ---

def create_post(entry, category):
    title = clean_text(entry.title)
    link = entry.link
    
    # 情報収集
    news_text = fetch_og_description(link) or clean_text(entry.description)
    wiki_text = get_wikipedia_summary(title) or "詳細情報は公式発表をご確認ください。"
    
    clean_title = re.sub(r'【.*?】', '', title).split("」")[0].replace("「", "").strip()
    
    # ★AIによる記事生成
    print(f"   🧠 AIが記事を構成中... ({clean_title})")
    ai_data = generate_article_with_ai(category, title, news_text, wiki_text)
    
    if not ai_data:
        print("   ❌ AI生成失敗")
        return None, None, None

    # AIデータを元に構築
    wp_title = ai_data.get('title', f"【投票】{clean_title}")
    items = ai_data.get('items', [])
    comments = ai_data.get('comments', [])
    
    # 選択肢文字列作成
    items_str = ",".join([f"{item['name']}|" for item in items])
    
    # 本文（フォームのみ）
    content = f"""
[vote_bar items="{items_str}"]
[vote_summary items="{items_str}"]
<p>話題の『{clean_title}』について、皆さんの本音を聞かせてください。<br><strong>「支持する？」それとも「反対？」</strong><br>忖度なしの評価を投票で決定します！</p>
"""

    # メタデータセット
    meta = {
        'wiki_h2_title': ai_data.get('h2_title', f"{clean_title}について"),
        'wiki_h2_text': ai_data.get('h2_text', news_text),
        'wiki_fact_h3': ai_data.get('fact_h3', "関連情報"),
        'wiki_info_fact': ai_data.get('fact_text', wiki_text),
        'post_views_count': '0'
    }

    # 投票初期値 & 詳細説明セット
    initial_votes = [0] * 10
    total_sakura = random.randint(40, 60)
    
    # 選択肢データの登録
    for i, item in enumerate(items):
        idx = i + 1
        meta[f'wiki_item_name_{idx}'] = item['name']
        meta[f'wiki_item_img_{idx}'] = ""
        
        # アイテムごとの解説（AI生成）をセット
        meta[f'wiki_info{idx}_h3'] = item['name']
        meta[f'wiki_info_{idx}'] = item.get('text', '')
    
    # 投票数の割り振り
    weights = [60, 30, 10, 10, 5, 5, 5, 5, 5, 5] # 上位に偏らせる
    for _ in range(total_sakura):
        # 選択肢数に合わせて重みリストをスライス
        valid_weights = weights[:len(items)]
        chosen_idx = random.choices(range(len(items)), weights=valid_weights)[0]
        initial_votes[chosen_idx] += 1

    for i in range(len(items)):
        meta[f'vote_multi_idx_{i}'] = str(initial_votes[i])

    post_data = {
        'title': wp_title,
        'content': content,
        'status': 'draft', # 下書き
        'date': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'categories': [CATEGORY_IDS.get(category, 1)],
        'meta': meta
    }

    headers = get_auth_header()
    if not headers: return None, None, None

    try:
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", headers=headers, json=post_data, timeout=30)
        if res.status_code == 201:
            pid = res.json()['id']
            print(f"✅ 作成成功({category}): {wp_title}")
            return pid, comments, clean_title
        else:
            print(f"❌ 作成失敗: {res.status_code} {res.text}")
    except Exception as e: print(f"❌ エラー: {e}")
    return None, None, None

def post_sakura_comment(post_id, comments):
    if not post_id or not comments: return
    url = f"{WP_URL}/wp-json/wp/v2/comments"
    headers = get_auth_header()
    if not headers: return
    
    print(f"   💬 コメント投稿開始（{len(comments)}件）...")
    
    for i, text in enumerate(comments):
        # 投稿時間をずらす
        c_dt = datetime.now() - timedelta(minutes=random.randint(5, 300))
        data = {
            'post': post_id,
            'author_name': '匿名', 
            'content': text,
            'status': 'approve',
            'date': c_dt.isoformat()
        }
        try:
            requests.post(url, headers=headers, json=data, timeout=10)
        except: pass
        time.sleep(1.5) # 連投規制回避

def send_discord(title, cat):
    if not DISCORD_WEBHOOK_URL or "ここに" in DISCORD_WEBHOOK_URL: return
    msg = f"📰 **{cat.upper()}記事を作成**\n**題名:** {title}\n{WP_URL}/wp-admin/"
    try: requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=5)
    except: pass

def main():
    print("🤖 議論ハンター(debate_hunter) v25 - AI編集長モード 起動")
    
    if not GEMINI_API_KEY:
        print("❌ エラー: GEMINI_API_KEY が設定されていません。")
        return

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
                
                title = clean_text(entry.title)
                if not any(w in title for w in TARGET_WORDS): continue
                if any(w in title for w in NG_WORDS):
                    print(f"✖️ NG: {title[:20]}...")
                    continue
                if check_exists(title):
                    print(f"🔷 済: {title[:20]}...")
                    continue
                
                cat = determine_category(title + entry.description)
                print(f"\n✨ ヒット({cat}): {title}")
                
                pid, comments, clean_title = create_post(entry, cat)
                if pid:
                    post_sakura_comment(pid, comments)
                    send_discord(clean_title, cat)
                    total += 1
                    rss_count += 1
                    
                    # API制限回避のため休憩
                    print("☕ 休憩中(10s)...")
                    time.sleep(10)
                    
        except Exception as e: print(f"エラー: {e}")
        if total >= 3: break
    print(f"🏁 完了: {total}件作成")

if __name__ == "__main__":
    main()
