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
WP_URL_DEFAULT = "https://docchiyo.com"
WP_USER_DEFAULT = "bear"

WP_URL = os.environ.get("WP_URL")
if not WP_URL: WP_URL = WP_URL_DEFAULT

WP_USER = os.environ.get("WP_USER")
if not WP_USER: WP_USER = WP_USER_DEFAULT

WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not WP_APP_PASS or not GEMINI_API_KEY:
    print("❌ エラー: 環境変数 (WP_APP_PASS, GEMINI_API_KEY) が読み込めません。")
    sys.exit(1)

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF"

# ★モデル設定
MODEL_NAME = "gemma-3-27b-it" 

CATEGORY_IDS = {
    "social": 194, "food": 11, "tech": 24,
    "anime": 155, "entame": 95, "game": 13
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'}

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

# ★RSSリスト
RSS_URLS = [
    "https://news.yahoo.co.jp/rss/topics/dom.xml",   # 社会
    "https://news.yahoo.co.jp/rss/topics/it.xml",    # IT
    "https://news.yahoo.co.jp/rss/topics/ent.xml",   # エンタメ
    "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml", # IT/ビジネス
    "https://entabe.jp/news.rss",                    # グルメ
    "https://rocketnews24.com/feed/",                # 雑多・グルメ
    "https://www.businessinsider.jp/feed/index.xml", # ビジネス・社会
    "https://www.4gamer.net/rss/index.xml"           # ゲーム
]

NG_WORDS = ["セール", "決算", "インタビュー", "レポート", "舞台", "オーディション", "求人", "人事", "放送", "プレゼント", "まとめ", "訃報", "死去", "ご冥福", "亡く", "逝去"]
TARGET_WORDS = ["発売", "リリース", "決定", "発表", "開始", "新商品", "新メニュー", "公開", "実写化", "映画化", "アニメ化", "検討", "方針", "批判", "物議", "炎上", "逮捕", "容疑", "可決", "辞任", "疑惑", "増税", "義務化", "中止", "話題"]

# ==========================================
# 関数定義
# ==========================================

def get_auth_header():
    creds = f"{WP_USER.strip()}:{WP_APP_PASS.strip()}"
    token = base64.b64encode(creds.encode()).decode()
    # 415エラー対策: Content-Type と User-Agent を追加してWAFを回避
    return {
        'Authorization': f'Basic {token}',
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

def clean_text(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# 重複チェック機能
def check_exists(title):
    headers = get_auth_header()
    if not headers: return False
    
    clean_title = clean_text(title)
    keywords = re.findall(r'[a-zA-Z0-9]+|[ァ-ンー]{3,}', clean_title)
    if keywords:
        search_query = max(keywords, key=len)
    else:
        search_query = clean_title[:15]

    endpoint = f"{WP_URL}/wp-json/wp/v2/posts?search={search_query}&status=any&per_page=5"
    
    print(f"   🔍 重複チェック: '{search_query}' で検索...", end="")
    
    try:
        res = requests.get(endpoint, headers=headers, timeout=10)
        if res.status_code == 200:
            posts = res.json()
            if posts:
                for post in posts:
                    try:
                        post_date = datetime.fromisoformat(post['date'])
                        diff = datetime.now() - post_date
                        if diff.days < 30: 
                            print(f" -> 🛑 あり ({diff.days}日前): {post['title']['rendered'][:10]}...")
                            return True
                    except: pass
                
                print(f" -> 🟢 古いのでOK")
                return False
            else:
                print(" -> 🟢 なし")
                return False
    except Exception as e:
        print(f" -> ⚠️ エラー: {e}")
        pass
    return False

# --- 1. トレンド収集 ---

def get_trends():
    print("📈 トレンド収集中...", end="")
    items = []
    
    # Google Trends
    try:
        url = "https://trends.google.co.jp/trends/api/realtimetrends?hl=ja&tz=-540&cat=all&fi=0&fs=0&geo=JP&ri=300&rs=20&sort=0"
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = json.loads(res.text.replace(")]}',", "").strip())
            stories = data.get('storySummaries', {}).get('trendingStories', [])
            for story in stories[:10]:
                title = story.get('title')
                articles = story.get('articles', [])
                desc = articles[0].get('snippet', '') if articles else ""
                link = articles[0].get('url', '') if articles else ""
                if title:
                    items.append({"title": title, "desc": desc, "link": link})
    except: pass

    # RSS (ランダム順)
    shuffled_rss = RSS_URLS.copy()
    random.shuffle(shuffled_rss) 

    for url in shuffled_rss:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]: 
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
        # キーワード抽出の強化（タイトルから漢字2文字以上、カタカナ英数字3文字以上を抜き出す）
        kw_match = re.findall(r'[a-zA-Z0-9]{3,}|[ァ-ンー]{3,}|[一-龠]{2,}', keyword)
        search_kw = max(kw_match, key=len) if kw_match else keyword[:15]
        
        clean_kw = re.sub(r'【.*?】', '', search_kw).strip()
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

# --- 3. AI編集長による企画・記事作成 (論点整理モード) ---

def generate_article_plan(item):
    print(f"   🧠 AI編集長が企画中 (論点整理モード): {item['title'][:20]}...")
    
    web_desc = fetch_web_info(item['link'])
    wiki_data = get_wikipedia_data(item['title'])
    
    context_text = f"ニュース: {item['title']}\n概要: {item['desc']}\n詳細: {web_desc}\nWiki: {wiki_data}"

    persona_prompt = """
    【コメント生成指示】
    この記事に対する「読者のリアルな書き込み」を5件生成し、JSONの `comments` 配列に格納せよ。
    以下の5人のキャラクターになりきり、口調やテンションを完全に演じ分けること。名前は不要（システム側で処理するため）。

    1. **熱狂的な賛成派**: 「うおおお！神！」「絶対買う」「これは英断」 (短文、勢い重視)
    2. **冷笑的な反対派**: 「はいはい解散」「今更感w」「改悪でしかない」 (スラング、批判的)
    3. **慎重な分析家**: 「スペック的には...」「コスパ次第かな」「論点はそこじゃない」 (冷静、長文可)
    4. **無知な初心者**: 「これ何？」「どういうこと？」「誰か教えて」 (質問、弱気)
    5. **通りすがりの一般人**: 「話題だね」「へー」「みんな熱いな」 (無関心、相槌)
    """

    prompt = f"""
    あなたは投票サイト「どっちよ.com」の凄腕編集長です。
    トレンドニュースを元に、読者が「思わず議論に参加したくなる」究極の投票記事を作成してください。

    【入力情報】
    {context_text}

    【★企画ルール：厳守】
    
    1. **タイトル (title)**: 
       - 「対立構造（AかBか、賛成か反対か）」が明確に伝わるキャッチーなタイトル ＋ 「アリ？ナシ？」「どっち？」等の短い問いかけ。

    2. **記事本文 (h2_text)**:
       - **この記事の最大の価値は「論点の整理」です。単なるニュース解説ではなく、「なぜ今ネットで議論・賛否が巻き起こっているのか」を徹底的に整理して記述してください。**
       - ニュースの基本情報（背景・スペック等）を簡潔に書いた後、必ず【賛成派（肯定派）の主張】と【反対派（否定派）の主張】を分かりやすく対比させて、**600〜800文字**で詳しく解説してください。
       - 読者がこの本文を読むだけで「なるほど、そういう論争があるのか。自分はこっち派だな」と判断できるようにすること。

    3. **選択肢 (items)**: 
       - `name`: 選択肢の名前のみ。2つ〜4つの選択肢。
       - 単純な「賛成/反対」や「買う/買わない」などの明確な対立構造にすること。
       - **解説文 (text) は不要です。絶対に作成しないでください。**

    4. **豆知識 (fact_text)**:
       - Wiki資料がある場合はそれを活用し、ない場合でもあなたの知識を活用して、ニュースに関連する情報を**200文字前後**で詳しく書いてください。
       - **もしどうしても書くことがない場合のみ、空文字 "" にしてください。その場合、見出し(fact_h3)も空文字にしてください。**

    5. **コメント (comments)**:
       - 上記の「コメント生成指示」に従い、5つの異なる視点のコメントを生成してください。

    【出力形式(JSONのみ)】
    {{
      "category": "social/food/tech/anime/entame/game のいずれか",
      "title": "対立構造がわかるニュース事実＋問いかけ",
      "h2_title": "議論を促す導入見出し",
      "h2_text": "ニュース詳細と【賛成派・反対派の論点整理】を含む充実した本文(600文字以上)",
      "fact_h3": "内容に即した具体的な見出し(空にする場合はここも空文字)",
      "fact_text": "ニュースの背景や雑学(200文字前後。書けない場合は空文字)",
      "items": [
        {{ "name": "選択肢1" }}, 
        {{ "name": "選択肢2" }},
        {{ "name": "選択肢3(必要なら)" }}
      ],
      "comments": [
          {{ "name": "匿名", "content": "コメント本文1" }},
          {{ "name": "匿名", "content": "コメント本文2" }},
          {{ "name": "匿名", "content": "コメント本文3" }},
          {{ "name": "匿名", "content": "コメント本文4" }},
          {{ "name": "匿名", "content": "コメント本文5" }}
      ]
    }}
    {persona_prompt}
    """

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = { "contents": [{"parts": [{"text": prompt}]}], "safetySettings": SAFETY_SETTINGS }
    
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
            elif res.status_code == 429:
                if attempt < max_retries - 1:
                    print(f"   ⚠️ API制限。20秒待機...")
                    time.sleep(20) 
                else:
                    return None
            else:
                return None
        except Exception as e:
            print(f"   ❌ 通信エラー: {e}")
            return None
    return None

# --- 4. コメント投稿関数 ---
def post_comment_to_wp(pid, name, content):
    url = f"{WP_URL}/wp-json/wp/v2/comments"
    headers = get_auth_header()
    c_dt = datetime.now() - timedelta(minutes=random.randint(5, 120))
    data = {
        'post': pid,
        'author_name': name,
        'content': content,
        'status': 'approve', 
        'date': c_dt.isoformat()
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=10)
        if res.status_code == 201:
            return True, ""
        else:
            return False, f"{res.status_code} {res.text}"
    except Exception as e:
        return False, str(e)

# --- 5. WordPress投稿 ---

def post_to_wordpress(ai_data):
    if not ai_data: return False
    
    cat_slug = ai_data.get('category', 'social')
    cat_id = CATEGORY_IDS.get(cat_slug, 194)
    
    wp_title = ai_data.get('title')
    items = ai_data.get('items', [])
    
    if len(items) < 2: return False

    items_str = ",".join([f"{item['name']}|" for item in items])
    
    content = f"""
[vote_bar items="{items_str}"]
[vote_summary items="{items_str}"]
"""

    # ★修正箇所: 本文(fact_text)が空なら、見出し(fact_h3)も空にして枠を非表示にする
    f_text = ai_data.get('fact_text', '').strip()
    f_h3 = ai_data.get('fact_h3', '関連情報')
    if not f_text:
        f_h3 = ""

    meta = {
        'wiki_h2_title': ai_data.get('h2_title', 'ニュースの背景'),
        'wiki_h2_text': ai_data.get('h2_text', ''),
        'wiki_fact_h3': f_h3,
        'wiki_info_fact': f_text,
        'post_views_count': '0'
    }

    initial_votes = [0] * 10
    total_sakura = random.randint(40, 60)
    
    for i, item in enumerate(items):
        idx = i + 1
        meta[f'wiki_item_name_{idx}'] = item['name']
        meta[f'wiki_item_img_{idx}'] = ""
        meta[f'wiki_info{idx}_h3'] = "" 
        meta[f'wiki_info_{idx}'] = "" 
        
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
        'status': 'publish', 
        'date': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'categories': [cat_id],
        'meta': meta
    }

    try:
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", headers=get_auth_header(), json=post_data, timeout=30)
        if res.status_code == 201:
            pid = res.json()['id']
            print(f"   ✅ 投稿成功 (公開): {wp_title[:20]}... (ID:{pid})")
            
            print("   💬 コメント投稿中...", end="")
            
            comments_list = ai_data.get('comments', [])
            if not comments_list:
                comments_list = [
                    {"name": "匿名", "content": "これは気になる！"},
                    {"name": "匿名", "content": "様子見かなあ。"},
                    {"name": "匿名", "content": "期待してる！"},
                    {"name": "匿名", "content": "どっちも捨てがたい..."},
                    {"name": "匿名", "content": "盛り上がってきたね"}
                ]

            success_c = 0
            for c in comments_list:
                if isinstance(c, str):
                    c_content = c
                else:
                    c_content = c.get('content', c.get('text', ''))
                
                # ★修正: 名前を強制的に「匿名」にする
                c_name = "匿名" 
                
                if c_content:
                    success, msg = post_comment_to_wp(pid, c_name, c_content)
                    if success:
                        success_c += 1
                        print(f" [OK]", end="")
                    else:
                        print(f" [NG:{msg}]", end="")
                    time.sleep(1) 
            
            print(f" -> 完了 ({success_c}件)")
            return True
        else:
            print(f"   ❌ WP投稿失敗: {res.status_code} {res.text}")
    except Exception as e:
        print(f"   ❌ エラー: {e}")
    return False

# ==========================================
# メイン処理
# ==========================================
def main():
    print(f"🤖 トレンド・ハンター v67 (Model: {MODEL_NAME} / 論点整理モード) 起動")
    
    candidates = get_trends()
    random.shuffle(candidates)
    
    count = 0
    for item in candidates:
        # ★記事作成数: ここで調整 (現在は1件でストップするようになっています)
        if count >= 1: break
        
        if check_exists(item['title']):
            continue
            
        ai_data = generate_article_plan(item)
        if ai_data:
            if post_to_wordpress(ai_data):
                count += 1
                try: 
                    msg = f"🆕 記事作成: {ai_data['title']}\n{WP_URL}/wp-admin/"
                    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
                except: pass
                
        print("   ☕ 休憩中(15s)...")
        time.sleep(15)

    print(f"\n🏁 完了: {count}件作成")

if __name__ == "__main__":
    main()
