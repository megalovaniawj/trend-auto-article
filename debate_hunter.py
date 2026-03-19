# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import requests
import feedparser
import re
from datetime import datetime, timedelta
import pytz
import random
import base64

# ==========================================
# ★ 1. 設定エリア
# ==========================================
WP_URL = "https://docchiyo.com"
WP_USER = "bear"
WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF"

if not WP_APP_PASS or not GEMINI_API_KEY:
    print("❌ エラー: 環境変数が設定されていません。")
    sys.exit(1)

# 使用モデル
MODEL_NAME = "gemma-3-27b-it"

# コンプラ制限を最大限解除
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

# 優先トレンド
MEGA_TRENDS = ["WBC", "ワールドカップ", "五輪", "オリンピック", "M-1", "大谷翔平", "Fate", "ポケモン", "PS5", "Switch"]

# RSSフィード
RSS_FEEDS = [
    "https://news.yahoo.co.jp/rss/topics/it.xml",
    "https://news.yahoo.co.jp/rss/topics/entertainment.xml",
    "https://www.4gamer.net/rss/index.xml",
    "https://automaton-media.com/feed/",
    "https://dengekionline.com/feed/",
    "https://animeanime.jp/feed/"
]

# ==========================================
# ★ 2. ヘルパー関数
# ==========================================

def get_auth_header():
    """WordPress API認証。Content-Typeを付与して415エラーを防止。"""
    creds = f"{WP_USER.strip()}:{WP_APP_PASS.strip()}"
    token = base64.b64encode(creds.encode()).decode()
    return {
        'Authorization': f'Basic {token}',
        'Content-Type': 'application/json'
    }

def clean_title(text):
    """記号や空白を除去して純粋な文字列にする（重複チェック用）"""
    if not text: return ""
    return re.sub(r'[^\w\s]', '', text).replace(' ', '').replace('　', '')

def get_existing_data():
    """★修正: 重複投稿防止のための完全タイトル一覧と、3日以内の生タイトル一覧を取得"""
    print("📚 過去記事を全件チェック中...", end="")
    titles = []
    recent_titles = []
    page = 1
    three_days_ago = datetime.now() - timedelta(days=3)

    while True:
        try:
            url = f"{WP_URL}/wp-json/wp/v2/posts?per_page=100&page={page}&fields=title,date"
            res = requests.get(url, headers=get_auth_header(), timeout=25)
            if res.status_code != 200: break
            posts = res.json()
            if not posts: break
            for p in posts:
                title_text = p['title']['rendered']
                # 完全重複チェック用にクリーンアップして保存
                titles.append(clean_title(title_text))
                
                # 3日以内の記事か判定し、生タイトルを保存（テーマ重複チェック用）
                post_date_str = p['date']
                post_date = datetime.strptime(post_date_str, "%Y-%m-%dT%H:%M:%S")
                if post_date > three_days_ago:
                    recent_titles.append(title_text)

            if len(posts) < 100: break
            page += 1
        except Exception as e:
            print(f"\n⚠️ 過去記事取得エラー: {e}")
            break
    print(f" -> 合計 {len(titles)} 件取得 (うち直近3日: {len(recent_titles)}件)")
    return titles, recent_titles

def get_term_id(slug):
    """カテゴリーID取得。存在しなければ作成。"""
    headers = get_auth_header()
    try:
        res = requests.get(f"{WP_URL}/wp-json/wp/v2/categories?slug={slug}", headers=headers, timeout=15)
        if res.status_code == 200 and res.json():
            return res.json()[0]['id']
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/categories", headers=headers, json={'name':slug, 'slug':slug}, timeout=15)
        if res.status_code in [200, 201]:
            return res.json()['id']
    except Exception as e:
        print(f"⚠️ カテゴリー処理エラー: {e}")
    return 1

# ==========================================
# ★ 3. ニュース収集
# ==========================================

def get_mega_trends_and_entertainment_news():
    """RSSからニュースを収集し、ティア分け。"""
    print("📡 ニュースの収集を開始します...")
    now_utc = datetime.utcnow()
    news_list = []

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
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
            print(f"⚠️ RSS取得失敗 ({url}): {e}")

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
# ★ 4. API通信（Gemma 3 27Bパース強化版）
# ==========================================

def call_gemini_api(prompt, retries=2):
    """Gemma特有の不規則な出力を確実にJSONとしてパースする重厚なロジック。"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "safetySettings": SAFETY_SETTINGS
    }
    
    for attempt in range(retries + 1):
        try:
            res = requests.post(url, headers=headers, json=data, timeout=60)
            if res.status_code == 200:
                res_json = res.json()
                if 'candidates' in res_json:
                    text = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
                    text = text.replace('```json', '').replace('```', '').strip()
                    start = text.find('{')
                    end = text.rfind('}') + 1
                    if start != -1 and end != 0:
                        return json.loads(text[start:end])
            elif res.status_code == 429:
                print(f"   ⚠️ 429制限。30秒待機（試行 {attempt+1}）")
                time.sleep(30)
                continue
            print(f"   ❌ APIエラー ({res.status_code}): {res.text[:200]}")
        except Exception as e:
            print(f"   ❌ 通信/パースエラー: {e}")
            time.sleep(5)
    return None

# ==========================================
# ★ 5. AI編集長（査定：エンタメ特化＆選択肢洗練）
# ==========================================

def ask_ai_editor(news_item):
    """エンタメ特化を厳格にし、選択肢から冗長なタイトル繰り返しを排除。"""
    print(f"🤖 AI編集長が査定中: {news_item['title']}")
    prompt = f"""
    あなたはエンタメ・ゲーム・オタク文化に特化した討論サイトの編集長です。JSON形式でのみ答えてください。
    
    【査定基準】
    1. エンタメ、ゲーム、アニメ、オタク趣味に関連しない一般ニュース（政治、経済、一般企業の戦略など）は、一律で「30点以下」にせよ。
    2. 読者が「自分はこっち派だ！」と感情的に選びたくなる二項対立があるか。

    【選択肢（candidates）の作成ルール】
    - ニュースタイトルの内容を繰り返さない。
    - 主語を省き、単刀直入にせよ。
    - 悪い例：「ドコモのAI戦略は成功する」「ドコモのAI戦略は失敗する」
    - 良い例：「期待できる」「不安の方が大きい」「どちらでもない」

    ニュース: {news_item['title']}

    出力JSON:
    {{
      "score": 点数(0-100),
      "core_topic": "ニュースのメインテーマとなる固有名詞（例：呪術廻戦、サイボーグ009、嵐 など。3日以内の重複判定に使用します）",
      "reason": "採点理由(100字程度)",
      "vote_type": "binary_plus",
      "candidates": ["選択肢1", "選択肢2", "中立/その他"]
    }}
    """
    result = call_gemini_api(prompt)
    if result:
        print(f"   👉 判定: {result.get('score', 0)}点")
        print(f"   👉 理由: {result.get('reason')}")
        return result
    return {"score": 0, "core_topic": ""}

# ==========================================
# ★ 6. 記事生成（事実ベース徹底・コメント自然化）
# ==========================================

def get_natural_personas(count):
    """★修正: コメントの件数を動的にし、掲示板風の自然な指示文に変更"""
    return f"""
    以下のネットユーザーになりきって、掲示板のような自然なコメントを【必ず {count} 個】生成してください。
    
    【★コメントの鉄則（絶対遵守）】
    1. 「【選択肢名】」のような機械的な前置きは**絶対に書かない**こと。
    2. 「〇〇に一票」「私は△△を選びます」のような説明口調は避ける。
    3. 「やっぱこれだわ」「いや、普通に考えてそれはないだろ」「設定的にこっちが正解なんだよな」といった、感情的で生の声を意識すること。
    4. 会話のライブ感を出すため、数件は「>>3 わかる」「それな」「異論は認める」のような、前のコメントへの反応（アンカーや同調）を含めること。
    """

def generate_article_content(news_item, editor_data):
    """記事本編、豆知識、自然なコメントを統合生成。"""
    print(f"✍️ AIライターが記事とコメントを執筆中...")
    title = news_item['title']
    cands = json.dumps(editor_data.get('candidates', []), ensure_ascii=False)
    
    # ★修正: コメント数を10〜20の間でランダムに決定
    comment_count = random.randint(10, 20)
    persona_instruction = get_natural_personas(comment_count)
    
    prompt = f"""
    論争サイト「どっちよ.com」の編集長として、記事をJSONで作成せよ。

    【ニュース】 {title}
    【選択肢】 {cands}

    【★タイトル作成の厳格ルール】
    - 30文字以内。
    - 必ず「どっち？」「どれ？」と心の中で補って意味が通る疑問形にする。
    - 「【炎上】」「【悲報】」「【激論】」のような、わざとらしい煽りワードは一切使用しないこと。
    - 【重要】抽象的・淡白なタイトルは禁止。ニュースの具体的な固有名詞（商品名、作品名、人物名など）を必ず含め、何について議論しているか一目でわかるようにすること。
    - 悪い例：「新SNSは普及する？」「あのコラボは成功？」
    - 良い例：「Fateリメイク販売中止。バンナムの判断は妥当？それとも？」

    【コメント生成指示】
    {persona_instruction}

    出力JSON:
    {{
      "post_title": "固有名詞を含んだ事実ベースの疑問形タイトル",
      "slug": "english-slug",
      "category_slug": "contents",
      "h2_title": "議論の核心を突く見出し",
      "intro": "背景解説(約300字)",
      "items": [
        {{ "name": "選択肢1", "desc": "代弁(約200字)" }}
      ],
      "trivia_title": "豆知識見出し",
      "trivia_text": "解説(300字)",
      "comments": [
        {{ "name": "匿名", "text": "やっぱこれ一択だろ" }},
        {{ "name": "名無し", "text": ">>1 いや、普通に考えてこっちだわ" }}
        // ... 指定された {comment_count} 件生成すること
      ]
    }}
    """
    return call_gemini_api(prompt)

# ==========================================
# ★ 7. 投稿処理（演出強化版・画像生成なし）
# ==========================================

def post_to_wordpress(article_data):
    """記事投稿、メタデータ保存、コメント個別投稿を省略なしで行う。"""
    print("🚀 WordPressへ送信中...")
    
    # --- 投票数の演出的ランダム化ロジック ---
    items = article_data.get('items', [])
    mode = random.choice(['接戦', '圧倒的', '中程度', '僅差'])
    
    for i, item in enumerate(items):
        if mode == '接戦':
            item['votes'] = random.randint(180, 230)
        elif mode == '圧倒的':
            item['votes'] = random.randint(450, 700) if i == 0 else random.randint(10, 40)
        elif mode == '僅差':
            item['votes'] = random.randint(300, 350) if i == 0 else random.randint(250, 290)
        else: # 中程度
            item['votes'] = random.randint(350, 500) if i == 0 else random.randint(100, 200)

        # 端数を少し散らす
        if item['votes'] % 10 == 0: item['votes'] += random.randint(1, 9)

    items_str_list = [f"{item['name']}|" for item in items]
    items_str = ", ".join(items_str_list)
    content = f'[vote_bar items="{items_str}"]\n\n[vote_summary items="{items_str}"]'

    wp_api_url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth_header = get_auth_header()
    
    # 公開時間を過去にずらして即時反映
    post_time = datetime.now() - timedelta(minutes=random.randint(10, 25))
    
    post_payload = {
        "title": article_data.get('post_title', 'タイトル未定'),
        "content": content,
        "status": "publish",
        "date": post_time.strftime('%Y-%m-%dT%H:%M:%S'),
        "categories": [get_term_id(article_data.get('category_slug', 'contents'))],
        "slug": article_data.get('slug', 'post')
    }
    
    try:
        res = requests.post(wp_api_url, headers=auth_header, json=post_payload, timeout=40)
        if res.status_code == 201:
            res_data = res.json()
            post_id = res_data.get("id")
            post_link = res_data.get("link")
            print(f"✅ 記事投稿成功! (ID: {post_id})")
            
            # --- カスタムフィールド（メタデータ）保存 ---
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
                meta_payload["meta"][f"wiki_item_img_{idx}"] = ""
                meta_payload["meta"][f"wiki_info{idx}_h3"] = f"{item['name']}の意見"
                meta_payload["meta"][f"wiki_info_{idx}"] = item["desc"]
                
                # 演出済みの投票数をセット
                meta_payload["meta"][f'vote_multi_idx_{i}'] = str(item['votes'])
                
                if len(items) == 2:
                    k = 'vote_count_a' if i == 0 else 'vote_count_b'
                    meta_payload["meta"][k] = str(item['votes'])

            requests.post(f"{wp_api_url}/{post_id}", headers=auth_header, json=meta_payload, timeout=25)
            
            # --- 初期コメントの個別投稿 ---
            comments = article_data.get('comments', [])
            if comments:
                print(f"💬 コメント投稿中({len(comments)}件)...", end="")
                for com in comments:
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
                        time.sleep(0.3)
                    except: continue
                print(" 完了")
                
            return {"link": post_link, "id": post_id, "title": article_data.get('post_title')}
        else:
            print(f"❌ WP投稿エラー ({res.status_code}): {res.text[:300]}")
    except Exception as e:
        print(f"❌ WordPress通信エラー: {e}")
    return None

# ==========================================
# ★ 8. メインループ
# ==========================================

if __name__ == "__main__":
    print("=== どっちよ.com AI自動投稿システム V92改 (具体化・3日間制限・自然コメント版) ===")
    
    # 既存タイトル取得（比較用にクリーンアップ済みのリストと、3日以内の生タイトルリストを取得）
    existing_titles, recent_titles = get_existing_data()
    recent_texts_combined = " ".join(recent_titles) # 検索しやすいように結合しておく
    
    # ニュース収集
    tier1, tier2, tier3 = get_mega_trends_and_entertainment_news()
    search_queue = tier1 + tier2 + tier3
    
    if not search_queue:
        print("💤 ニュースなし。終了。")
        sys.exit(0)
        
    posted_count = 0
    for news in search_queue:
        if posted_count >= 1: break
            
        verdict = ask_ai_editor(news)
        print("   ⏳ 待機中(15s)...")
        time.sleep(15)
        
        if verdict and verdict.get("score", 0) >= 70:
            print(f"🎉 70点突破！合格。")
            
            # ★ 追加: 3日以内のテーマ重複制限
            core_topic = verdict.get("core_topic", "")
            if core_topic and len(core_topic) > 1 and core_topic in recent_texts_combined:
                print(f"   🚫 3日以内の重複テーマ検知（{core_topic}）のためスキップ")
                continue

            article = generate_article_content(news, verdict)
            
            if article:
                # ★ 重複チェック：記号等を無視したクリーンアップ比較
                if clean_title(article.get('post_title')) in existing_titles:
                    print(f"   🚫 重複スキップ（類似タイトル検知）: {article.get('post_title')}")
                    continue
                    
                res = post_to_wordpress(article)
                
                if res:
                    posted_count += 1
                    if DISCORD_WEBHOOK_URL:
                        edit_url = f"{WP_URL.rstrip('/')}/wp-admin/post.php?post={res['id']}&action=edit"
                        discord_payload = {
                            "content": f"🔥 **新しい議論を投下しました！**\n\n**【タイトル】**\n{res['title']}\n\n**【URL】**\n{res['link']}\n\n**【編集】**\n{edit_url}"
                        }
                        try:
                            d_res = requests.post(DISCORD_WEBHOOK_URL, json=discord_payload, timeout=15)
                            d_res.raise_for_status() 
                            print("🔔 Discord通知送信完了")
                        except Exception as e:
                            print(f"⚠️ Discord通知失敗: {e}")
                    else:
                        print("⚠️ DISCORD_WEBHOOK_URL が設定されていません。")
        else:
            print(f"🗑️ ボツ（{verdict.get('score', 0) if verdict else 'Error'}点）。次へ...\n")

    print("=== 処理終了 ===")
