# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import requests
import feedparser
from datetime import datetime, timedelta
import random
import base64

# ==========================================
# ★ 1. 設定エリア
# ==========================================
WP_URL = "https://docchiyo.com"
WP_USER = "bear"
WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not WP_APP_PASS or not GEMINI_API_KEY:
    print("❌ エラー: 環境変数が設定されていません。")
    sys.exit(1)

# ★ 修正: モデルを Gemma 3 27B に指定
MODEL_NAME = "gemma-3-27b-it"

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

MEGA_TRENDS = ["WBC", "ワールドカップ", "五輪", "オリンピック", "M-1", "大谷翔平"]

RSS_FEEDS = [
    "https://news.yahoo.co.jp/rss/topics/it.xml",
    "https://news.yahoo.co.jp/rss/topics/entertainment.xml",
    "https://www.4gamer.net/rss/index.xml",
    "https://automaton-media.com/feed/",
    "https://dengekionline.com/feed/",
    "https://animeanime.jp/feed/"
]

def get_auth_header():
    creds = f"{WP_USER.strip()}:{WP_APP_PASS.strip()}"
    token = base64.b64encode(creds.encode()).decode()
    return {
        'Authorization': f'Basic {token}',
        'Content-Type': 'application/json'
    }

def get_all_existing_titles():
    print("📚 過去記事を全件チェック中...", end="")
    titles = []
    page = 1
    while True:
        try:
            url = f"{WP_URL}/wp-json/wp/v2/posts?per_page=100&page={page}&fields=title"
            res = requests.get(url, headers=get_auth_header(), timeout=10)
            if res.status_code != 200: break
            posts = res.json()
            if not posts: break
            for p in posts:
                titles.append(p['title']['rendered'])
            if len(posts) < 100: break
            page += 1
        except: break
    print(f" -> 合計 {len(titles)} 件取得")
    return titles

def get_term_id(slug):
    headers = get_auth_header()
    try:
        res = requests.get(f"{WP_URL}/wp-json/wp/v2/categories?slug={slug}", headers=headers)
        if res.json(): return res.json()[0]['id']
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/categories", headers=headers, json={'name':slug, 'slug':slug})
        return res.json()['id']
    except: return 1

# ==========================================
# ★ 2. ニュース収集
# ==========================================
def get_mega_trends_and_entertainment_news():
    print("📡 ニュースの収集を開始します...")
    now_utc = datetime.utcnow()
    news_list = []

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_time = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                else:
                    pub_time = now_utc

                hours_ago = (now_utc - pub_time).total_seconds() / 3600
                news_list.append({
                    "title": entry.title,
                    "link": entry.link,
                    "hours_ago": hours_ago,
                    "source": feed.feed.title if hasattr(feed.feed, 'title') else "RSS"
                })
        except Exception as e:
            print(f"⚠️ RSS取得エラー ({url}): {e}")

    tier1, tier2, tier3 = [], [], []
    for news in news_list:
        h_ago = news['hours_ago']
        is_mega = any(mega in news['title'] for mega in MEGA_TRENDS)
        if is_mega or h_ago <= 12: tier1.append(news)
        elif h_ago <= 24: tier2.append(news)
        elif h_ago <= 48: tier3.append(news)
        
    print(f"✅ 取得完了: [超新鮮] {len(tier1)}件, [新鮮] {len(tier2)}件, [妥協] {len(tier3)}件")
    return tier1, tier2, tier3

# ==========================================
# ★ 3. API 通信処理 (429リトライ機能)
# ==========================================
def call_gemini_api(prompt, retries=3):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "safetySettings": SAFETY_SETTINGS,
        "generationConfig": {"response_mime_type": "application/json"}
    }
    
    for attempt in range(retries):
        try:
            time.sleep(3) # Gemma用。Geminiよりは少し早めでOK
            res = requests.post(url, headers=headers, json=data, timeout=45)
            
            if res.status_code == 200:
                text = res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
                text = text.replace('```json', '').replace('```', '').strip()
                start = text.find('{')
                end = text.rfind('}') + 1
                if start != -1 and end != 0:
                    return json.loads(text[start:end])
            elif res.status_code == 429:
                print(f"   ⚠️ API制限 (429) - 30秒待機中... ({attempt + 1}/{retries})")
                time.sleep(30)
            else:
                print(f"   ❌ APIエラー ({res.status_code}): {res.text[:100]}...")
                return None
        except Exception as e:
            print(f"   ❌ 通信エラー: {e}")
            time.sleep(5)
    return None

# ==========================================
# ★ 4. AI編集長
# ==========================================
def ask_ai_editor(news_item):
    print(f"🤖 AI編集長が査定中: {news_item['title']}")
    prompt = f"""
    あなたはエンタメ・ゲーム特化の論争メディアの編集長です。
    以下のニュースが、読者が熱狂して投票やコメントをしたくなる「炎上・賛否両論・熱い議論」のテーマになるか、100点満点で採点してください。

    【ニュースタイトル】
    {news_item['title']}

    【出力形式(JSON)】
    {{
      "score": 点数,
      "reason": "採点の理由",
      "vote_type": "binary_plus",
      "candidates": ["選択肢1", "選択肢2", "選択肢3"]
    }}
    """
    result = call_gemini_api(prompt)
    if result:
        print(f"   👉 判定: {result.get('score', 0)}点")
        return result
    return {"score": 0}

# ==========================================
# ★ 5. 記事＆初期コメント生成
# ==========================================
def get_comment_personas(count=5):
    definitions = {
        'normal': "普通。「〜だね」。", 'polite': "丁寧。「ですね」。",
        'rough': "乱暴。「〜だろ」。", 'excited': "感情的。「〜すぎ！」。",
        'slang': "ネット民。「草」。", 'otaku': "オタク。「尊い」。",
        'simple': "一言。「これ。」。"
    }
    keys = list(definitions.keys())
    selected = random.choices(keys, k=count)
    return "\n".join([f"- {k}: {definitions[k]}" for k in selected])

def generate_article_content(news_item, editor_data):
    print(f"✍️ AIライターが記事とコメントを執筆中...")
    title = news_item['title']
    cands = json.dumps(editor_data.get('candidates', []), ensure_ascii=False)
    personas = get_comment_personas(6)
    
    prompt = f"""
    論争サイト「どっちよ.com」の敏腕編集長として記事を作成してください。

    【ニュース】 {title}
    【選択肢】 {cands}

    【タイトル作成ルール】
    - 必ず「どっち？」「どれ？」と心の中で補って意味が通る、30文字以内の疑問形にしてください。
    - 単なる報告ではなく、読者に選択を迫る煽りを含めてください。

    【サクラコメント指定】
    以下のペルソナになりきって、熱いコメントを6つ生成してください。
    {personas}

    【出力形式(JSON)】
    {{
      "post_title": "作成したタイトル",
      "slug": "short-english-slug",
      "category_slug": "contents",
      "h2_title": "核心を突く煽り見出し",
      "intro": "炎上の経緯(約300文字)",
      "items": [
        {{ "name": "選択肢1", "desc": "代弁(約200文字)", "votes": 123 }}
      ],
      "trivia_title": "豆知識見出し",
      "trivia_text": "背景解説(約300文字)",
      "comments": [
        {{ "name": "匿名", "text": "コメント本文" }}
      ]
    }}
    """
    return call_gemini_api(prompt)

# ==========================================
# ★ 6. WordPress投稿＆Discord通知
# ==========================================
def post_to_wordpress(article_data):
    print("🚀 WordPressへ送信中...")
    items_str_list = [f"{item['name']}|" for item in article_data.get('items', [])]
    items_str = ", ".join(items_str_list)
    content = f'[vote_bar items="{items_str}"]\n\n[vote_summary items="{items_str}"]'

    wp_api_url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth_header = get_auth_header()
    post_time = datetime.now() - timedelta(minutes=10)
    
    post_payload = {
        "title": article_data.get('post_title', 'タイトル未定'),
        "content": content,
        "status": "publish",
        "date": post_time.strftime('%Y-%m-%dT%H:%M:%S'),
        "categories": [get_term_id(article_data.get('category_slug', 'contents'))],
        "slug": article_data.get('slug', 'post')
    }
    
    try:
        res = requests.post(wp_api_url, headers=auth_header, json=post_payload, timeout=30)
        if res.status_code == 201:
            res_data = res.json()
            post_id = res_data.get("id")
            post_link = res_data.get("link")
            print(f"✅ 記事投稿成功! (ID: {post_id})")
            
            # カスタムフィールド保存
            meta_payload = {
                "meta": {
                    "post_views_count": "0",
                    "wiki_h2_title": article_data.get("h2_title", ""),
                    "wiki_h2_text": article_data.get("intro", ""),
                    "wiki_fact_h3": article_data.get("trivia_title", ""),
                    "wiki_info_fact": article_data.get("trivia_text", "")
                }
            }
            for i, item in enumerate(article_data.get("items", [])[:10]):
                idx = i + 1
                meta_payload["meta"][f"wiki_item_name_{idx}"] = item["name"]
                meta_payload["meta"][f"wiki_info{idx}_h3"] = f"{item['name']}の意見"
                meta_payload["meta"][f"wiki_info_{idx}"] = item["desc"]
                votes = item.get('votes', random.randint(10, 200))
                meta_payload["meta"][f'vote_multi_idx_{i}'] = str(votes)
                if len(article_data.get("items", [])) == 2:
                    k = 'vote_count_a' if i == 0 else 'vote_count_b'
                    meta_payload["meta"][k] = str(votes)

            requests.post(f"{wp_api_url}/{post_id}", headers=auth_header, json=meta_payload, timeout=15)
            
            # 初期コメント投稿 (復活)
            print("💬 コメント投稿中...", end="")
            for com in article_data.get('comments', []):
                c_time = post_time + timedelta(minutes=random.randint(1, 9))
                requests.post(f"{WP_URL}/wp-json/wp/v2/comments", headers=auth_header, 
                              json={'post': post_id, 'author_name': com['name'], 'content': com['text'], 'status': 'approve', 'date': c_time.strftime('%Y-%m-%dT%H:%M:%S')}, timeout=10)
                time.sleep(0.5)
            print(" 完了")
                
            return {"link": post_link, "id": post_id, "title": article_data.get('post_title')}
        else:
            print(f"❌ WP投稿エラー ({res.status_code}): {res.text[:200]}")
    except Exception as e:
        print(f"❌ 通信エラー: {e}")
    return None

# ==========================================
# ★ メイン処理
# ==========================================
if __name__ == "__main__":
    print("=== どっちよ.com AI自動投稿システム V77 スタート ===")
    
    existing_titles = get_all_existing_titles()
    tier1, tier2, tier3 = get_mega_trends_and_entertainment_news()
    search_queue = tier1 + tier2 + tier3
    
    posted_count = 0
    for news in search_queue:
        if posted_count >= 1: break
            
        editor_verdict = ask_ai_editor(news)
        if editor_verdict.get("score", 0) >= 70:
            print(f"🎉 70点突破！")
            article = generate_article_content(news, editor_verdict)
            
            if article:
                if article.get('post_title') in existing_titles:
                    print(f"   🚫 重複スキップ")
                    continue
                    
                post_result = post_to_wordpress(article)
                if post_result:
                    posted_count += 1
                    if DISCORD_WEBHOOK_URL:
                        discord_data = {"content": f"🎉 **投稿完了**\n{post_result['title']}\n{post_result['link']}"}
                        requests.post(DISCORD_WEBHOOK_URL, json=discord_data, timeout=10)
                        print("🔔 Discord通知完了")
        else:
            print(f"🗑️ ボツ。次へ...\n")
            time.sleep(5)

    print("=== 処理終了 ===")
