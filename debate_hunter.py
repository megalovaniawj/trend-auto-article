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
WP_USER = os.environ.get("WP_USER", "bear") # ユーザー名
WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# エラーチェック
if not WP_APP_PASS or not GEMINI_API_KEY:
    print("❌ エラー: GitHub Secrets (WP_APP_PASS, GEMINI_API_KEY) が読み込めません。YAMLを確認してください。")
    # テスト用に直書きする場合のみコメントアウトを外す
    # GEMINI_API_KEY = "AIzaSyD..." 
    # sys.exit(1) # 本番では停止させる

# Discord Webhook
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF"

# モデル設定 (安定版を使用)
MODEL_NAME = "gemini-2.0-flash" 

# ★カテゴリーID設定 (あなたのサイト用)
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

# ==========================================
# 関数定義
# ==========================================

def get_auth_header():
    creds = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(creds.encode()).decode()
    return {'Authorization': f'Basic {token}'}

def clean_text(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- 1. トレンド収集 (Googleトレンド & RSS) ---

def get_google_trends():
    print("📈 トレンド収集中 (Google Trends)...", end="")
    trends = []
    try:
        # 日本の急上昇ワード (JSON API)
        url = "https://trends.google.co.jp/trends/api/realtimetrends?hl=ja&tz=-540&cat=all&fi=0&fs=0&geo=JP&ri=300&rs=20&sort=0"
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = json.loads(res.text.replace(")]}',", "").strip())
            stories = data.get('storySummaries', {}).get('trendingStories', [])
            for story in stories[:5]: # 上位5つ
                title = story.get('title')
                articles = story.get('articles', [])
                desc = articles[0].get('snippet', '') if articles else ""
                link = articles[0].get('url', '') if articles else ""
                if title:
                    trends.append({"title": title, "desc": desc, "link": link, "source": "Googleトレンド"})
            print(f" OK ({len(trends)}件)")
    except Exception as e:
        print(f" 失敗: {e}")
    
    return trends

def get_rss_trends():
    print("📡 RSS収集中...", end="")
    rss_urls = [
        "https://news.yahoo.co.jp/rss/topics/dom.xml",    # 社会
        "https://news.yahoo.co.jp/rss/topics/ent.xml",    # エンタメ
        "https://www.4gamer.net/rss/index.xml",           # ゲーム
        "https://rocketnews24.com/feed/",                 # グルメ
        "https://mantan-web.jp/rss/rss.xml"               # アニメ
    ]
    items = []
    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]: # 各2件
                if len(entry.title) > 10:
                    items.append({"title": clean_text(entry.title), "desc": clean_text(entry.description), "link": entry.link, "source": "RSS"})
        except: pass
    print(f" OK ({len(items)}件)")
    return items

# --- 2. 情報調査 (Wiki & News Scraping) ---

def fetch_web_info(url):
    """ニュース記事の本文要約を取得 (OGタグ)"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        if r.status_code == 200:
            match = re.search(r'<meta (property|name)="og:description" content="(.*?)"', r.text)
            if match: return clean_text(match.group(2))
    except: pass
    return ""

def get_wikipedia_data(keyword):
    """Wikipediaから情報を取得"""
    try:
        # キーワードをきれいにする
        clean_kw = re.sub(r'【.*?】', '', keyword).strip()
        url = "https://ja.wikipedia.org/w/api.php"
        params = { "action": "query", "format": "json", "prop": "extracts", "exintro": True, "explaintext": True, "redirects": 1, "titles": clean_kw }
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid == "-1": continue
            return page.get("extract", "")[:1000] # 長すぎないように
    except: pass
    return None

# --- 3. AI編集長による企画・記事作成 ---

def generate_article_plan(item):
    """Geminiに記事構成を考えさせる"""
    print(f"🧠 AI編集長が企画中: {item['title']}...")
    
    # 追加調査
    web_desc = fetch_web_info(item['link'])
    wiki_data = get_wikipedia_data(item['title'])
    
    context_text = f"ニュース: {item['title']}\n概要: {item['desc']}\n詳細: {web_desc}\nWiki: {wiki_data}"

    # PHP版のコメント人格定義
    persona_prompt = """
    【コメント生成指示】
    この記事に対する「読者の反応」を5〜8件生成せよ。以下の人格を使い分けること。
    - 普通/丁寧: 「〜だね」「〜ですね」
    - 辛口/雑: 「〜だろ」「微妙」
    - 感情的/オタク: 「神！」「尊い」「覇権」
    - ネットスラング: 「草」「それな」
    - ギャル/関西弁: 「〜やな」「ビジュ良すぎ」
    """

    prompt = f"""
    あなたはWebメディアの凄腕編集長です。以下のトレンド情報を元に、PVが爆発する「投票記事」を作成してください。

    【入力情報】
    {context_text}

    【企画ルール】
    1. **ジャンル判定**: 内容から最適なカテゴリ(social, food, tech, anime, entame, game)を選べ。
       - 事件・政治・炎上 → social
       - アニメ・漫画 → anime
       - 芸能・映画 → entame
    2. **記事タイプ**: 
       - 「A vs B」や「賛否両論」なら → 対決型
       - 「推しキャラ」「名曲」なら → 多選択型(Wiki等の固有名詞を使用)
       - 「新商品」「新作」なら → 期待度評価(買う/買わない)
    3. **内容**: 
       - タイトルは煽りを含めてクリックしたくなるように。
       - 導入文はニュース背景を詳しく。
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

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    data = { "contents": [{"parts": [{"text": prompt}]}], "safetySettings": SAFETY_SETTINGS }
    
    try:
        res = requests.post(url, headers=headers, json=data, timeout=60)
        if res.status_code == 200:
            text = res.json()['candidates'][0]['content']['parts'][0]['text']
            text = text.replace('```json', '').replace('```', '').strip()
            # JSON部分抽出
            start = text.find('{')
            end = text.rfind('}') + 1
            return json.loads(text[start:end])
        else:
            print(f"API Error: {res.text}")
    except Exception as e:
        print(f"Generat Error: {e}")
    return None

# --- 4. WordPress投稿 ---

def post_to_wordpress(ai_data):
    if not ai_data: return False
    
    cat_slug = ai_data.get('category', 'social')
    cat_id = CATEGORY_IDS.get(cat_slug, 194) # デフォルトはsocial
    
    wp_title = ai_data['title']
    items = ai_data.get('items', [])
    
    # 選択肢文字列
    items_str = ",".join([f"{item['name']}|" for item in items])
    
    # 本文
    content = f"""
[vote_bar items="{items_str}"]
[vote_summary items="{items_str}"]
<p>話題のニュースについて、皆さんの意見を聞かせてください。<br><strong>あなたの「一票」が世論を作ります！</strong></p>
"""

    # メタデータ
    meta = {
        'wiki_h2_title': ai_data.get('h2_title', 'ニュースの背景'),
        'wiki_h2_text': ai_data.get('h2_text', ''),
        'wiki_fact_h3': ai_data.get('fact_h3', '関連情報'),
        'wiki_info_fact': ai_data.get('fact_text', ''),
        'post_views_count': '0'
    }

    # 投票初期値＆解説
    initial_votes = [0] * 10
    total_sakura = random.randint(40, 60)
    
    for i, item in enumerate(items):
        idx = i + 1
        meta[f'wiki_item_name_{idx}'] = item['name']
        meta[f'wiki_item_img_{idx}'] = ""
        meta[f'wiki_info{idx}_h3'] = item['name']
        meta[f'wiki_info_{idx}'] = item.get('text', '')
        
    # 重み付け投票
    weights = [50, 30, 10, 5, 5] + [1] * 5
    for _ in range(total_sakura):
        valid_weights = weights[:len(items)]
        chosen_idx = random.choices(range(len(items)), weights=valid_weights)[0]
        initial_votes[chosen_idx] += 1

    for i in range(len(items)):
        meta[f'vote_multi_idx_{i}'] = str(initial_votes[i])
        if len(items) == 2: # VSモード用
            k = 'vote_count_a' if i == 0 else 'vote_count_b'
            meta[k] = str(initial_votes[i])

    post_data = {
        'title': wp_title,
        'content': content,
        'status': 'draft', # ★安全のため下書き
        'date': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'categories': [cat_id],
        'meta': meta
    }

    try:
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", headers=get_auth_header(), json=post_data, timeout=30)
        if res.status_code == 201:
            pid = res.json()['id']
            print(f"✅ 投稿成功: {wp_title} (ID:{pid})")
            
            # コメント投稿
            print("💬 コメント投入中...")
            for comment in ai_data.get('comments', []):
                c_data = {
                    'post': pid,
                    'author_name': '匿名',
                    'content': comment,
                    'status': 'approve',
                    'date': (datetime.now() - timedelta(minutes=random.randint(10, 300))).isoformat()
                }
                requests.post(f"{WP_URL}/wp-json/wp/v2/comments", headers=get_auth_header(), json=c_data, timeout=5)
                time.sleep(1) # 連投規制回避
            return True
        else:
            print(f"❌ 投稿失敗: {res.text}")
    except Exception as e:
        print(f"❌ エラー: {e}")
    return False

# ==========================================
# メイン処理
# ==========================================
def main():
    print("🤖 トレンド・ハンター v25 起動")
    
    # 1. ネタ探し (トレンド + RSS)
    candidates = get_google_trends() + get_rss_trends()
    
    # シャッフルしてランダム性を出す
    random.shuffle(candidates)
    
    count = 0
    # 2. 記事作成 (最大3件)
    for item in candidates:
        if count >= 3: break
        
        # 重複チェック (タイトル検索)
        if check_exists(item['title']):
            print(f"🔷 済: {item['title']}")
            continue
            
        # AIで記事生成
        ai_data = generate_article_plan(item)
        if ai_data:
            if post_to_wordpress(ai_data):
                count += 1
                # Discord通知
                try: requests.post(DISCORD_WEBHOOK_URL, json={"content": f"🆕 記事作成: {ai_data['title']}"})
                except: pass
                
        # API制限回避の休憩
        time.sleep(5)

    print(f"🏁 完了: {count}件作成")

if __name__ == "__main__":
    main()
