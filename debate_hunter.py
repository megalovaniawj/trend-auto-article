import os
import sys
import requests
import base64
import time
import random
import json
import feedparser
import re
import html
from datetime import datetime, timedelta

# ==========================================
# ★設定エリア
# ==========================================
WP_URL = os.environ.get("WP_URL", "https://docchiyo.com")
WP_USER = os.environ.get("WP_USER", "bear")
WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# エラーチェック
if not WP_APP_PASS or not GEMINI_API_KEY:
    print("❌ エラー: 環境変数 (WP_APP_PASS, GEMINI_API_KEY) が読み込めません。")
    sys.exit(1)

# Discord Webhook
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF"

# モデル設定
MODEL_NAME = "gemini-2.0-flash" 

# ★カテゴリーID設定 (確認済みID)
CATEGORY_IDS = {
    "social": 194, "food": 11, "tech": 24,
    "anime": 155, "entame": 95, "game": 13
}

# ユーザーエージェント
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'}

# コンプラ回避設定
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

# RSSリスト
RSS_URLS = [
    "https://news.yahoo.co.jp/rss/topics/dom.xml",
    "https://news.yahoo.co.jp/rss/topics/ent.xml",
    "https://news.livedoor.com/topics/rss/dom.xml",
    "https://www.4gamer.net/rss/index.xml",
    "https://rocketnews24.com/feed/",
    "https://feeds.cinematoday.jp/cinematoday/rss",
    "https://mantan-web.jp/rss/rss.xml"
]

# NGワード・ターゲットワード
NG_WORDS = ["セール", "決算", "インタビュー", "レポート", "舞台", "オーディション", "求人", "人事", "放送", "プレゼント", "まとめ", "訃報", "死去", "ご冥福", "亡く", "逝去"]
TARGET_WORDS = ["発売", "リリース", "決定", "発表", "開始", "新商品", "新メニュー", "公開", "実写化", "映画化", "アニメ化", "検討", "方針", "批判", "物議", "炎上", "逮捕", "容疑", "可決", "辞任", "疑惑", "増税", "義務化", "中止", "話題"]

# ==========================================
# 関数定義
# ==========================================

def get_auth_header():
    creds = f"{WP_USER.strip()}:{WP_APP_PASS.strip()}"
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
                if clean_search in post['title']['rendered']:
                    return True
    except: pass
    return False

# --- 1. トレンド収集 ---

def get_trends():
    print("📈 トレンド収集中 (Google & RSS)...", end="")
    items = []
    
    # Google Trends
    try:
        url = "https://trends.google.co.jp/trends/api/realtimetrends?hl=ja&tz=-540&cat=all&fi=0&fs=0&geo=JP&ri=300&rs=20&sort=0"
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = json.loads(res.text.replace(")]}',", "").strip())
            stories = data.get('storySummaries', {}).get('trendingStories', [])
            for story in stories[:3]:
                title = story.get('title')
                articles = story.get('articles', [])
                desc = articles[0].get('snippet', '') if articles else ""
                link = articles[0].get('url', '') if articles else ""
                if title:
                    items.append({"title": title, "desc": desc, "link": link})
    except: pass

    # RSS
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]: # 拾える数を少し増やす
                title = clean_text(entry.title)
                if any(w in title for w in TARGET_WORDS) and not any(w in title for w in NG_WORDS):
                    items.append({"title": title, "desc": clean_text(entry.description), "link": entry.link})
        except: pass
        
    print(f" OK ({len(items)}件)")
    return items

# --- 2. 情報調査 ---

def fetch_web_info(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        if r.status_code == 200:
            match = re.search(r'<meta (property|name)="og:description" content="(.*?)"', r.text)
            if match: return clean_text(match.group(2))
    except: pass
    return ""

def get_wikipedia_data(keyword):
    try:
        clean_kw = re.sub(r'【.*?】', '', keyword).strip()
        url = "https://ja.wikipedia.org/w/api.php"
        params = { "action": "query", "format": "json", "prop": "extracts", "exintro": True, "explaintext": True, "redirects": 1, "titles": clean_kw }
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid == "-1": continue
            return page.get("extract", "")[:800]
    except: pass
    return None

# --- 3. AI編集長による企画・記事作成 ---

def generate_article_plan(item):
    print(f"   🧠 AI編集長が企画中: {item['title'][:20]}...")
    
    web_desc = fetch_web_info(item['link'])
    wiki_data = get_wikipedia_data(item['title'])
    
    context_text = f"ニュース: {item['title']}\n概要: {item['desc']}\n詳細: {web_desc}\nWiki: {wiki_data}"

    persona_prompt = """
    【コメント生成指示】
    この記事に対する「読者の反応」を5〜8件生成せよ。以下の人格確率に基づいて演じ分けること。
    - **主要人格 (計80%)**:
      1. 普通: 「〜だね」
      2. 丁寧: 「〜ですね」
      3. 雑・男言葉: 「〜だろ」
      4. 感情的: 「〜すぎ！」「マジで」
      5. 弱気: 「〜かな？」「〜だっけ？」
    - **レア人格 (計20%)**:
      1. ネットスラング: 「草」「それな」
      2. 関西弁: 「〜やな」「せやね」
      3. オタク: 「尊い」「〜なんだよなぁ」
      4. ギャル: 「神」「ビジュ良すぎ」
      5. 一言: 「これ。」
    """

    prompt = f"""
    あなたはWebメディアの凄腕編集長です。以下のトレンド情報を元に、PVが爆発する「投票記事」を作成してください。

    【入力情報】
    {context_text}

    【企画ルール】
    1. **ジャンル判定**: 内容から最適なカテゴリ(social, food, tech, anime, entame, game)を選べ。
    2. **記事タイプ**: 
       - 「A vs B」や「賛否両論」なら → 対決型
       - 「推しキャラ」「名曲」なら → 多選択型(Wiki等の固有名詞を使用)
       - 「新商品」「新作」なら → 期待度評価(買う/買わない)
    3. **内容**: 
       - タイトルは煽りを含めてクリックしたくなるように。
       - 導入文はニュース背景を詳しく解説。
       - 豆知識はWiki情報を活用。
       - **選択肢は必ず2つ以上作成すること。**

    【出力形式(JSONのみ)】
    {{
      "category": "social/food/tech/anime/entame/game のいずれか",
      "title": "記事タイトル",
      "h2_title": "導入見出し",
      "h2_text": "導入本文(300字程度)",
      "fact_h3": "豆知識見出し",
      "fact_text": "豆知識本文(Wiki活用)",
      "items": [
        {{ "name": "選択肢1", "text": "解説..." }},
        {{ "name": "選択肢2", "text": "解説..." }}
      ],
      "comments": ["コメント1", "コメント2", "コメント3", "コメント4", "コメント5"]
    }}
    {persona_prompt}
    """

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = { "contents": [{"parts": [{"text": prompt}]}], "safetySettings": SAFETY_SETTINGS }
    
    # ★追加：エラー発生時に自動リトライ（待機）するロジック
    max_retries = 2
    for attempt in range(max_retries):
        try:
            res = requests.post(url, headers=headers, json=data, timeout=60)
            if res.status_code == 200:
                text = res.json()['candidates'][0]['content']['parts'][0]['text']
                text = text.replace('```json', '').replace('```', '').strip()
                start = text.find('{')
                end = text.rfind('}') + 1
                return json.loads(text[start:end])
            elif res.status_code == 429: # 制限エラー
                if attempt < max_retries - 1:
                    print("   ⚠️ API制限(429)を検知。60秒待機してから再挑戦します...")
                    time.sleep(60)
                else:
                    print("   ❌ API制限が解除されないため、この記事はスキップします。")
                    return None
            else:
                try:
                    err_msg = res.json().get('error', {}).get('message', '不明なエラー')
                    print(f"   ❌ APIエラー ({res.status_code}): {err_msg}")
                except:
                    print(f"   ❌ APIエラー ({res.status_code})")
                return None
        except Exception as e:
            print(f"   ❌ 通信エラー: {e}")
            return None
            
    return None

# --- 4. WordPress投稿 ---

def post_to_wordpress(ai_data):
    if not ai_data: return False
    
    cat_slug = ai_data.get('category', 'social')
    cat_id = CATEGORY_IDS.get(cat_slug, 194)
    
    wp_title = ai_data.get('title')
    items = ai_data.get('items', [])
    
    # 選択肢がない場合はスキップ
    if len(items) < 2:
        print("   ⚠️ 選択肢不足のためスキップ")
        return False

    items_str = ",".join([f"{item['name']}|" for item in items])
    
    content = f"""
[vote_bar items="{items_str}"]
[vote_summary items="{items_str}"]
<p>話題のニュースについて、皆さんの意見を聞かせてください。<br><strong>あなたの「一票」が世論を作ります！</strong></p>
"""

    meta = {
        'wiki_h2_title': ai_data.get('h2_title', 'ニュースの背景'),
        'wiki_h2_text': ai_data.get('h2_text', ''),
        'wiki_fact_h3': ai_data.get('fact_h3', '関連情報'),
        'wiki_info_fact': ai_data.get('fact_text', ''),
        'post_views_count': '0'
    }

    initial_votes = [0] * 10
    total_sakura = random.randint(40, 60)
    
    for i, item in enumerate(items):
        idx = i + 1
        meta[f'wiki_item_name_{idx}'] = item['name']
        meta[f'wiki_item_img_{idx}'] = ""
        meta[f'wiki_info{idx}_h3'] = item['name']
        meta[f'wiki_info_{idx}'] = item.get('text', '')
        
    weights = [50, 30, 10, 5, 5] + [1] * 5
    for _ in range(total_sakura):
        valid_weights = weights[:len(items)]
        chosen_idx = random.choices(range(len(items)), weights=valid_weights)[0]
        initial_votes[chosen_idx] += 1

    for i in range(len(items)):
        meta[f'vote_multi_idx_{i}'] = str(initial_votes[i])
        if len(items) == 2:
            k = 'vote_count_a' if i == 0 else 'vote_count_b'
            meta[k] = str(initial_votes[i])

    post_data = {
        'title': wp_title,
        'content': content,
        'status': 'draft', # ★下書き保存
        'date': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'categories': [cat_id],
        'meta': meta
    }

    try:
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", headers=get_auth_header(), json=post_data, timeout=30)
        if res.status_code == 201:
            pid = res.json()['id']
            print(f"   ✅ 投稿成功: {wp_title[:15]}... (ID:{pid})")
            
            print("   💬 コメント投入中...", end="")
            for comment in ai_data.get('comments', []):
                c_data = {
                    'post': pid,
                    'author_name': '匿名',
                    'content': comment,
                    'status': 'approve',
                    'date': (datetime.now() - timedelta(minutes=random.randint(10, 300))).isoformat()
                }
                requests.post(f"{WP_URL}/wp-json/wp/v2/comments", headers=get_auth_header(), json=c_data, timeout=5)
                time.sleep(1) 
            print(" 完了")
            return True
        else:
            print(f"   ❌ WP投稿失敗: {res.status_code}")
    except Exception as e:
        print(f"   ❌ エラー: {e}")
    return False

# ==========================================
# メイン処理
# ==========================================
def main():
    print("🤖 トレンド・ハンター v31 (スマートログ版) 起動")
    
    candidates = get_trends()
    random.shuffle(candidates)
    
    count = 0
    for item in candidates:
        if count >= 3: break
        
        if check_exists(item['title']):
            print(f"🔷 済: {item['title'][:20]}...")
            continue
            
        ai_data = generate_article_plan(item)
        if ai_data:
            if post_to_wordpress(ai_data):
                count += 1
                try: requests.post(DISCORD_WEBHOOK_URL, json={"content": f"🆕 記事作成: {ai_data['title']}"})
                except: pass
                
        # 連続実行によるAPIエラーを防ぐため、1記事ごとに15秒休む
        time.sleep(15)

    print(f"\n🏁 完了: {count}件作成")

if __name__ == "__main__":
    main()
