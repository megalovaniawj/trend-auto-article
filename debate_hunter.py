# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import requests
import feedparser
from datetime import datetime, timedelta
import pytz
import random
import base64

# ==========================================
# ★ 1. 設定エリア
# ==========================================
WP_URL = os.environ.get("WP_URL")
WP_USER = os.environ.get("WP_USER")
WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not WP_APP_PASS or not GEMINI_API_KEY:
    print("❌ エラー: 環境変数が設定されていません。")
    sys.exit(1)

# モデルは賢くて速い2.5-flashを使用
MODEL_NAME = "gemini-2.5-flash"

# コンプラ制限を解除（ゲーム用語等での弾きを防止）
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
    return {'Authorization': f'Basic {token}'}

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
# ★ 2. ニュース収集＆鮮度フィルター
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

    try:
        gt_url = "https://trends.google.co.jp/trends/api/realtimetrends?hl=ja&tz=-540&cat=e&fi=0&fs=0&geo=JP&ri=300&rs=20&sort=0"
        gt_res = requests.get(gt_url, timeout=10)
        if gt_res.status_code == 200:
            gt_text = gt_res.text.replace(")]}',", "").strip()
            gt_data = json.loads(gt_text)
            for story in gt_data.get('storySummaries', {}).get('trendingStories', [])[:5]:
                title = story.get('title', '')
                articles = story.get('articles', [])
                link = articles[0].get('url') if articles else ""
                if title and link:
                    news_list.append({"title": title, "link": link, "hours_ago": 1, "source": "Google Trends"})
    except Exception as e:
        print(f"⚠️ Google Trends取得エラー: {e}")

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
# ★ 3. Gemini API 通信処理（警告回避のREST方式）
# ==========================================
def call_gemini_api(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "safetySettings": SAFETY_SETTINGS,
        "generationConfig": {"response_mime_type": "application/json"}
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=45)
        if res.status_code == 200:
            text = res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            text = text.replace('```json', '').replace('```', '').strip()
            start = text.find('{')
            end = text.rfind('}') + 1
            if start != -1 and end != 0:
                return json.loads(text[start:end])
        else:
            print(f"   ❌ APIエラー ({res.status_code}): {res.text[:200]}")
    except Exception as e:
        print(f"   ❌ 通信エラー: {e}")
    return None

# ==========================================
# ★ 4. AI編集長（ボツ判定）
# ==========================================
def ask_ai_editor(news_item):
    print(f"🤖 AI編集長が査定中: {news_item['title']}")
    prompt = f"""
    あなたはエンタメ・ゲーム特化の論争メディアの編集長です。
    以下のニュースが、読者が熱狂して投票やコメントをしたくなる「炎上・賛否両論・熱い議論」のテーマになるか、100点満点で採点してください。

    【ニュースタイトル】
    {news_item['title']}

    【採点基準】
    1. 感情の衝突(40点): 「怒り」「悲しみ」「熱狂」がぶつかり合うか。単なる事実報告は低評価。
    2. 選択肢構造(40点): 読者が選べる明確な選択肢が作れるか。
    3. ターゲット層(20点): ゲーマー・オタク層が好む話題か。

    【出力形式のルール(JSON)】
    {{
      "score": 点数,
      "reason": "採点の理由（100文字程度）",
      "vote_type": "binary_plus", // 対立+中立(様子見)の場合はこれ、複数人気投票は "multiple"
      "candidates": ["選択肢1", "選択肢2", "選択肢3(中立/様子見など)"]
    }}
    """
    result = call_gemini_api(prompt)
    if result:
        print(f"   👉 判定: {result.get('score', 0)}点 ({result.get('vote_type')})")
        print(f"   👉 理由: {result.get('reason')}")
        return result
    return {"score": 0}

# ==========================================
# ★ 5. 記事＆初期コメント生成
# ==========================================
def get_comment_personas(count=5):
    definitions = {
        'normal': "普通。「〜だね」。",
        'polite': "丁寧。「ですね」。",
        'rough': "乱暴。「〜だろ」。",
        'excited': "感情的。「〜すぎ！」。",
        'slang': "ネット民。「草」。",
        'otaku': "オタク。「尊い」。",
        'simple': "一言。「これ。」。"
    }
    keys = list(definitions.keys())
    selected = random.choices(keys, k=count)
    return "\n".join([f"- {k}: {definitions[k]}" for k in selected])

def generate_article_content(news_item, editor_data):
    print(f"✍️ AIライターが記事とコメントを執筆中...")
    title = news_item['title']
    cands = json.dumps(editor_data.get('candidates', []), ensure_ascii=False)
    personas = get_comment_personas(6) # 6件のコメントを生成
    
    prompt = f"""
    以下のニュースと選択肢を元に、読者を煽り投票したくなる論説記事を作成してください。

    【ニュース】 {title}
    【選択肢】 {cands}

    【サクラコメントのペルソナ指定】
    以下のキャラクターになりきって、各選択肢に対する熱いコメントを合計6つ生成してください。
    {personas}

    【出力形式(JSON) ※slugは英語小文字とハイフンのみ】
    {{
      "post_title": "【〇〇】〇〇は？ (※WP用タイトル。30文字以内)",
      "slug": "short-english-slug",
      "category_slug": "contents",
      "h2_title": "議論の核心を突く煽り見出し",
      "intro": "なぜ今これが燃えているのか。(約300文字)",
      "items": [
        {{ "name": "選択肢1", "desc": "代弁(約200文字)", "votes": ランダムな数値(例:123) }}
      ],
      "trivia_title": "関連する豆知識の見出し",
      "trivia_text": "ニュースに関する背景解説。(約300文字)",
      "comments": [
        {{ "name": "匿名", "text": "ペルソナに合わせたコメント" }}
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
    
    cat_id = get_term_id(article_data.get('category_slug', 'contents'))
    clean_slug = article_data.get('slug', 'post')
    
    post_payload = {
        "title": article_data.get('post_title', 'タイトル未定'),
        "content": content,
        "status": "publish",
        "date": post_time.strftime('%Y-%m-%dT%H:%M:%S'),
        "categories": [cat_id],
        "slug": clean_slug
    }
    
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
            meta_payload["meta"][f"wiki_item_img_{idx}"] = ""
            meta_payload["meta"][f"wiki_info{idx}_h3"] = f"{item['name']}の意見"
            meta_payload["meta"][f"wiki_info_{idx}"] = item["desc"]
            # 投票数
            votes = item.get('votes', random.randint(10, 200))
            meta_payload["meta"][f'vote_multi_idx_{i}'] = str(votes)
            if len(article_data.get("items", [])) == 2:
                k = 'vote_count_a' if i == 0 else 'vote_count_b'
                meta_payload["meta"][k] = str(votes)

        requests.post(f"{wp_api_url}/{post_id}", headers=auth_header, json=meta_payload)
        
        # 初期コメント投稿
        print("💬 コメント投稿中...", end="")
        for com in article_data.get('comments', []):
            c_time = post_time + timedelta(minutes=random.randint(1, 9))
            requests.post(f"{WP_URL}/wp-json/wp/v2/comments", headers=auth_header, 
                          json={'post': post_id, 'author_name': com['name'], 'content': com['text'], 'status': 'approve', 'date': c_time.strftime('%Y-%m-%dT%H:%M:%S')})
            time.sleep(0.5) # コメント連続投稿時のエラー防止
        print(" 完了")
            
        return {"link": post_link, "id": post_id, "title": article_data.get('post_title')}
    else:
        print(f"❌ WP投稿エラー: {res.text}")
        return None

# ==========================================
# ★ メイン処理
# ==========================================
if __name__ == "__main__":
    print("=== どっちよ.com AI自動投稿システム V73 スタート ===")
    
    existing_titles = get_all_existing_titles()
    
    tier1, tier2, tier3 = get_mega_trends_and_entertainment_news()
    search_queue = tier1 + tier2 + tier3
    
    if not search_queue:
        print("💤 ニュースがありません。終了します。")
        sys.exit(0)
        
    posted_count = 0
    
    for news in search_queue:
        if posted_count >= 1: break
            
        editor_verdict = ask_ai_editor(news)
        
        # ★最重要: 1分間に5回の制限を回避するための待機（エラー429対策）
        print("   ⏳ API制限回避のため15秒待機します...")
        time.sleep(15)
        
        if editor_verdict.get("score", 0) >= 70:
            print(f"🎉 70点突破！記事生成に進みます。")
            
            article = generate_article_content(news, editor_verdict)
            
            if article:
                if article.get('post_title') in existing_titles:
                    print(f"   🚫 タイトル重複のためスキップ: {article.get('post_title')}")
                    continue
                    
                post_result = post_to_wordpress(article)
                if post_result:
                    posted_count += 1
                    post_link = post_result["link"]
                    post_id = post_result["id"]
                    edit_url = f"{WP_URL.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
                    
                    if DISCORD_WEBHOOK_URL:
                        discord_data = {
                            "content": f"🎉 **新しい論争記事が投稿されました！**\n\n**【タイトル】**\n{post_result['title']}\n\n**【公開URL】**\n{post_link}\n\n**【編集画面】**\n{edit_url}"
                        }
                        try:
                            requests.post(DISCORD_WEBHOOK_URL, json=discord_data)
                            print("🔔 Discordに通知を送信しました")
                        except: pass
        else:
            print(f"🗑️ ボツ。次のニュースを探します...\n")

    if posted_count == 0:
        print("💤 今回は合格を出すネタがありませんでした。")
        
    print("=== 処理終了 ===")
