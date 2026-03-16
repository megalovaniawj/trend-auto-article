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
# あなたの環境変数から取得。なければエラー終了。
WP_URL = "https://docchiyo.com"
WP_USER = "bear"
WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not WP_APP_PASS or not GEMINI_API_KEY:
    print("❌ エラー: 環境変数が設定されていません。")
    sys.exit(1)

# ★ 使用モデル: Gemma 3 27B
MODEL_NAME = "gemma-3-27b-it"

# 安全設定: コンプラによる生成拒否を最小限にする
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

# 優先的に拾いたいトレンドワード
MEGA_TRENDS = ["WBC", "ワールドカップ", "五輪", "オリンピック", "M-1", "大谷翔平"]

# 収集元RSSリスト
RSS_FEEDS = [
    "https://news.yahoo.co.jp/rss/topics/it.xml",
    "https://news.yahoo.co.jp/rss/topics/entertainment.xml",
    "https://www.4gamer.net/rss/index.xml",
    "https://automaton-media.com/feed/",
    "https://dengekionline.com/feed/",
    "https://animeanime.jp/feed/"
]

# ==========================================
# ★ 2. ヘルパー関数（V74流の丁寧な実装）
# ==========================================

def get_auth_header():
    """WordPress API用の認証ヘッダー。Content-Typeを忘れず付与。"""
    creds = f"{WP_USER.strip()}:{WP_APP_PASS.strip()}"
    token = base64.b64encode(creds.encode()).decode()
    return {
        'Authorization': f'Basic {token}',
        'Content-Type': 'application/json'
    }

def get_all_existing_titles():
    """過去記事のタイトルを全件取得して重複を防ぐ。ページネーション対応。"""
    print("📚 過去記事を全件チェック中...", end="")
    titles = []
    page = 1
    while True:
        try:
            url = f"{WP_URL}/wp-json/wp/v2/posts?per_page=100&page={page}&fields=title"
            res = requests.get(url, headers=get_auth_header(), timeout=20)
            if res.status_code != 200: break
            posts = res.json()
            if not posts: break
            for p in posts:
                titles.append(p['title']['rendered'])
            if len(posts) < 100: break
            page += 1
        except Exception as e:
            print(f"\n⚠️ 過去記事取得中にエラー: {e}")
            break
    print(f" -> 合計 {len(titles)} 件取得")
    return titles

def get_term_id(slug):
    """カテゴリーIDを取得。なければ新規作成する。"""
    headers = get_auth_header()
    try:
        res = requests.get(f"{WP_URL}/wp-json/wp/v2/categories?slug={slug}", headers=headers, timeout=10)
        if res.status_code == 200 and res.json():
            return res.json()[0]['id']
        # カテゴリーが存在しない場合は作成
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/categories", headers=headers, json={'name':slug, 'slug':slug}, timeout=10)
        if res.status_code in [200, 201]:
            return res.json()['id']
    except Exception as e:
        print(f"⚠️ カテゴリー取得エラー: {e}")
    return 1 # デフォルトのカテゴリーID

# ==========================================
# ★ 3. ニュース収集＆鮮度フィルタ
# ==========================================

def get_mega_trends_and_entertainment_news():
    """RSSから最新ニュースを取得し、鮮度（時間）でティア分けする。"""
    print("📡 ニュースの収集を開始します...")
    now_utc = datetime.utcnow()
    news_list = []

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:12]:
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

    # ティア分け（新鮮なもの、トレンドワードを含むものを優先）
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
# ★ 4. API 通信（Gemma 3 27B対応パース）
# ==========================================

def call_gemini_api(prompt):
    """GemmaはJSONモードがないため、出力からJSONを強引に抽出する丁寧なロジック。"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "safetySettings": SAFETY_SETTINGS
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=60)
        if res.status_code == 200:
            res_json = res.json()
            if 'candidates' in res_json:
                text = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
                # Markdownのコードブロックを掃除
                text = text.replace('```json', '').replace('```', '').strip()
                # 最初の '{' から 最後の '}' までを切り出す
                start_idx = text.find('{')
                end_idx = text.rfind('}') + 1
                if start_idx != -1 and end_idx != 0:
                    json_str = text[start_idx:end_idx]
                    return json.loads(json_str)
        print(f"   ❌ APIエラー ({res.status_code}): {res.text[:200]}")
    except Exception as e:
        print(f"   ❌ 通信/パースエラー: {e}")
    return None

# ==========================================
# ★ 5. AI編集長（査定）
# ==========================================

def ask_ai_editor(news_item):
    """ニュースを査定し、対立軸（選択肢）を考案する。"""
    print(f"🤖 AI編集長が査定中: {news_item['title']}")
    prompt = f"""
    あなたは論争メディアの敏腕編集長です。以下のニュースを読み、読者が「どっち？」と熱狂的に議論したくなるか採点してください。
    必ずJSON形式のみで回答してください。

    ニュース: {news_item['title']}

    【出力JSONフォーマット】
    {{
      "score": 0から100の点数,
      "reason": "100文字以内の採点理由",
      "vote_type": "binary_plus",
      "candidates": ["選択肢1", "選択肢2", "様子見/その他"]
    }}
    """
    result = call_gemini_api(prompt)
    if result:
        print(f"   👉 判定: {result.get('score', 0)}点")
        print(f"   👉 理由: {result.get('reason')}")
        return result
    return {"score": 0}

# ==========================================
# ★ 6. 記事＆コメント生成
# ==========================================

def get_comment_personas(count=6):
    """V74流のペルソナ指定。多様なコメントを生成させる。"""
    definitions = {
        'normal': "一般的で落ち着いた意見。「〜だと思います」。",
        'polite': "非常に丁寧で論理的な意見。「〜ですね」。",
        'rough': "ぶっきらぼうで攻撃的な意見。「〜だろ」「意味不明」。",
        'excited': "テンションが高く、感情的な意見。「〜すぎ！」「最高！」。",
        'slang': "ネットスラングを多用する意見。「草」「w」「情弱」。",
        'otaku': "知識をひけらかすオタク的な意見。「〜は基本ですよね」。",
        'simple': "非常に短く、直感的な意見。「これ一択」。「なし」。"
    }
    selected_keys = random.choices(list(definitions.keys()), k=count)
    return "\n".join([f"- {k}: {definitions[k]}" for k in selected_keys])

def generate_article_content(news_item, editor_data):
    """本編記事、豆知識、サクラコメントを統合生成する。"""
    print(f"✍️ AIライターが記事とコメントを執筆中...")
    title = news_item['title']
    cands = json.dumps(editor_data.get('candidates', []), ensure_ascii=False)
    personas = get_comment_personas(6)
    
    prompt = f"""
    論争サイト「どっちよ.com」の記事を作成してください。JSON形式のみで出力せよ。

    【ニュース】 {title}
    【選択肢】 {cands}

    【タイトル作成の鉄則】
    - 30文字以内。
    - 「どっち？」「どれ？」と心の中で補って意味が通る疑問形にすること。
    - 読者がどちらかの陣営に立ちたくなるような「煽り」を含めること。
    - 悪い例：「WBCの議論について」 
    - 良い例：「【激論】NetflixのWBC批判は正論？それとも単なる暴論？」

    【コメント作成の鉄則】
    - 以下のペルソナになりきり、計6つの対立するコメントを作成せよ。
    {personas}

    【出力JSONフォーマット】
    {{
      "post_title": "作成したタイトル",
      "slug": "english-slug-name",
      "category_slug": "contents",
      "h2_title": "議論の核心を突く見出し",
      "intro": "ニュースの概要と、なぜ議論になっているかの背景(約300文字)",
      "items": [
        {{ "name": "選択肢名", "desc": "この陣営の意見を代弁する解説(約200文字)", "votes": 100から500のランダム値 }}
      ],
      "trivia_title": "関連する豆知識の見出し",
      "trivia_text": "ニュースを深掘りする背景知識(約300文字)",
      "comments": [
        {{ "name": "匿名ユーザー", "text": "コメント本文" }}
      ]
    }}
    """
    return call_gemini_api(prompt)

# ==========================================
# ★ 7. WordPress投稿（V74/V70流の重厚な実装）
# ==========================================

def post_to_wordpress(article_data):
    """記事投稿、メタデータ保存、コメント投稿を一つの流れで行う。"""
    print("🚀 WordPressへ送信中...")
    
    # ショートコード組み立て
    items = article_data.get('items', [])
    items_str_list = [f"{item['name']}|" for item in items]
    items_str = ", ".join(items_str_list)
    content = f'[vote_bar items="{items_str}"]\n\n[vote_summary items="{items_str}"]'

    wp_api_url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth_header = get_auth_header()
    
    # 投稿時間は少しランダムに過去へずらし、即時公開を確実にする
    post_time = datetime.now() - timedelta(minutes=random.randint(5, 20))
    
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
            
            # --- カスタムフィールド（メタデータ）の網羅的な保存 ---
            # V74/V70の「wiki_item_img」初期化ロジック等も完全に網羅
            meta_payload = {
                "meta": {
                    "post_views_count": "0",
                    "wiki_h2_title": article_data.get("h2_title", ""),
                    "wiki_h2_text": article_data.get("intro", ""),
                    "wiki_fact_h3": article_data.get("trivia_title", ""),
                    "wiki_info_fact": article_data.get("trivia_text", "")
                }
            }
            
            for i, item in enumerate(items[:10]):
                idx = i + 1
                meta_payload["meta"][f"wiki_item_name_{idx}"] = item["name"]
                meta_payload["meta"][f"wiki_item_img_{idx}"] = "" # 空文字で初期化
                meta_payload["meta"][f"wiki_info{idx}_h3"] = f"{item['name']}の意見"
                meta_payload["meta"][f"wiki_info_{idx}"] = item["desc"]
                
                # 投票データのセット
                votes = item.get('votes', random.randint(30, 150))
                meta_payload["meta"][f'vote_multi_idx_{i}'] = str(votes)
                
                # 2択の場合の特殊フィールド
                if len(items) == 2:
                    k = 'vote_count_a' if i == 0 else 'vote_count_b'
                    meta_payload["meta"][k] = str(votes)

            # メタデータ更新実行
            requests.post(f"{wp_api_url}/{post_id}", headers=auth_header, json=meta_payload, timeout=20)
            
            # --- 初期コメント（サクラコメント）の投稿 ---
            comments = article_data.get('comments', [])
            if comments:
                print(f"💬 コメント投稿中({len(comments)}件)...", end="")
                for com in comments:
                    # コメントの投稿時間も記事公開後の時間に散らす
                    c_time = post_time + timedelta(minutes=random.randint(1, 9))
                    try:
                        requests.post(f"{WP_URL}/wp-json/wp/v2/comments", headers=auth_header, 
                                      json={
                                          'post': post_id, 
                                          'author_name': com['name'], 
                                          'content': com['text'], 
                                          'status': 'approve', 
                                          'date': c_time.strftime('%Y-%m-%dT%H:%M:%S')
                                      }, timeout=15)
                        time.sleep(0.5) # 連続投稿エラー防止
                    except:
                        continue
                print(" 完了")
                
            return {"link": post_link, "id": post_id, "title": article_data.get('post_title')}
        else:
            print(f"❌ WP投稿エラー ({res.status_code}): {res.text[:200]}")
    except Exception as e:
        print(f"❌ WordPress通信エラー: {e}")
    return None

# ==========================================
# ★ 8. メインループ
# ==========================================

if __name__ == "__main__":
    print("=== どっちよ.com AI自動投稿システム V81 (完全復旧版) ===")
    
    # 既存タイトルの取得
    existing_titles = get_all_existing_titles()
    
    # ニュースの取得
    tier1, tier2, tier3 = get_mega_trends_and_entertainment_news()
    search_queue = tier1 + tier2 + tier3
    
    if not search_queue:
        print("💤 ニュースがありませんでした。")
        sys.exit(0)
        
    posted_count = 0
    for news in search_queue:
        # 1回の実行につき1記事投稿の制限（必要に応じて変更）
        if posted_count >= 1: break
            
        # 査定
        editor_verdict = ask_ai_editor(news)
        
        # API制限回避のためのしっかりとした待機（15秒）
        print("   ⏳ 次のAPI処理まで15秒待機します...")
        time.sleep(15)
        
        if editor_verdict and editor_verdict.get("score", 0) >= 70:
            print(f"🎉 70点突破！記事生成フェーズへ。")
            
            # 記事生成
            article = generate_article_content(news, editor_verdict)
            
            if article:
                # タイトル重複チェック
                if article.get('post_title') in existing_titles:
                    print(f"   🚫 重複記事（{article.get('post_title')}）のためスキップ")
                    continue
                    
                # 投稿実行
                post_result = post_to_wordpress(article)
                
                if post_result:
                    posted_count += 1
                    # Discord通知（丁寧なエラー処理付き）
                    if DISCORD_WEBHOOK_URL:
                        edit_url = f"{WP_URL.rstrip('/')}/wp-admin/post.php?post={post_result['id']}&action=edit"
                        discord_data = {
                            "content": f"🔥 **議論の火種を投下しました！**\n\n**【タイトル】**\n{post_result['title']}\n\n**【URL】**\n{post_result['link']}\n\n**【編集】**\n{edit_url}"
                        }
                        try:
                            d_res = requests.post(DISCORD_WEBHOOK_URL, json=discord_data, timeout=15)
                            d_res.raise_for_status()
                            print("🔔 Discord通知を送信しました")
                        except Exception as e:
                            print(f"⚠️ Discord通知失敗: {e}")
        else:
            print(f"🗑️ スコア不足（{editor_verdict.get('score', 0)}点）。次のネタを探します...\n")

    print("=== 処理終了 ===")
