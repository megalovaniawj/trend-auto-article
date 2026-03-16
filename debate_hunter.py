# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import requests
import feedparser
from datetime import datetime, timedelta
import pytz
import re
import google.generativeai as genai

# ==========================================
# ★ 1. 設定エリア
# ==========================================
# WordPress設定
WP_URL = os.environ.get("WP_URL")  # 例: "https://docchiyo.com"
WP_USER = os.environ.get("WP_USER")
WP_APP_PASS = os.environ.get("WP_APP_PASS")

# Gemini API設定
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # 安定して高速・安価な2.5-flashを推奨
    model = genai.GenerativeModel('gemini-2.5-flash')
else:
    print("⚠️ エラー: GEMINI_API_KEY が設定されていません。")
    sys.exit(1)

# Discord設定
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# メガトレンド（例外的に拾う特大キーワード）
MEGA_TRENDS = ["WBC", "ワールドカップ", "五輪", "オリンピック", "M-1", "大谷翔平"]

# 情報源（エンタメ特化 + Google Trends エンタメ）
RSS_FEEDS = [
    "https://news.yahoo.co.jp/rss/topics/it.xml",
    "https://news.yahoo.co.jp/rss/topics/entertainment.xml",
    "https://www.4gamer.net/rss/index.xml",
    "https://automaton-media.com/feed/",
    "https://dengekionline.com/feed/",
    "https://animeanime.jp/feed/"
]

# ==========================================
# ★ 2. ニュース収集＆鮮度フィルター機能
# ==========================================
def get_mega_trends_and_entertainment_news():
    """RSSとトレンドからニュースを取得し、鮮度ごとにTier分けする"""
    print("📡 ニュースの収集を開始します...")
    now_utc = datetime.utcnow()
    news_list = []

    # 1. RSSの取得
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]: # 各サイト上位10件をチェック
                # 発行日時の解析
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_time = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                else:
                    pub_time = now_utc # 時間不明は最新扱い

                hours_ago = (now_utc - pub_time).total_seconds() / 3600
                
                news_list.append({
                    "title": entry.title,
                    "link": entry.link,
                    "hours_ago": hours_ago,
                    "source": feed.feed.title if hasattr(feed.feed, 'title') else "RSS"
                })
        except Exception as e:
            print(f"⚠️ RSS取得エラー ({url}): {e}")

    # 2. Google Trends (cat=e エンタメ特化) の取得
    try:
        gt_url = "https://trends.google.co.jp/trends/api/realtimetrends?hl=ja&tz=-540&cat=e&fi=0&fs=0&geo=JP&ri=300&rs=20&sort=0"
        gt_res = requests.get(gt_url, timeout=10)
        if gt_res.status_code == 200:
            gt_text = gt_res.text
            # 先頭の不要な文字列を取り除く
            if gt_text.startswith(")]}',"):
                gt_text = gt_text[5:]
            gt_data = json.loads(gt_text)
            
            for story in gt_data.get('storySummaries', {}).get('trendingStories', [])[:5]:
                title = story.get('title', '')
                articles = story.get('articles', [])
                link = articles[0].get('url') if articles else ""
                
                if title and link:
                    news_list.append({
                        "title": title,
                        "link": link,
                        "hours_ago": 1, # トレンドは超新鮮(1時間)として扱う
                        "source": "Google Trends"
                    })
    except Exception as e:
        print(f"⚠️ Google Trends取得エラー: {e}")

    # 3. カスケード（多段）鮮度フィルターによる振り分け
    tier1 = [] # 12時間以内
    tier2 = [] # 24時間以内
    tier3 = [] # 48時間以内
    
    for news in news_list:
        title_text = news['title']
        h_ago = news['hours_ago']
        
        # メガトレンドキーワードが含まれていれば無条件でTier1
        is_mega = any(mega in title_text for mega in MEGA_TRENDS)
        
        if is_mega or h_ago <= 12:
            tier1.append(news)
        elif h_ago <= 24:
            tier2.append(news)
        elif h_ago <= 48:
            tier3.append(news)
        # 48時間より古いものは捨てる
        
    print(f"✅ 取得完了: [超新鮮] {len(tier1)}件, [新鮮] {len(tier2)}件, [妥協] {len(tier3)}件")
    return tier1, tier2, tier3

# ==========================================
# ★ 3. AI編集長（ボツ判定＆記事型選択）
# ==========================================
def ask_ai_editor(news_item):
    """ニュースを評価し、70点以上なら型と選択肢を返す"""
    print(f"🤖 AI編集長が査定中: {news_item['title']}")
    
    prompt = f"""
    あなたはエンタメ・ゲーム特化の論争メディアの敏腕編集長です。
    以下のニュースが、読者が熱狂して投票やコメントをしたくなる「炎上・賛否両論・熱い議論」のテーマになるか、100点満点で採点してください。

    【ニュースタイトル】
    {news_item['title']}

    【採点基準（必ず守ること）】
    1. 感情の衝突 (40点): 「怒り」「悲しみ」「熱狂」がぶつかり合うか。単なる事実の報告は0点。
    2. 選択肢の構造 (40点): 読者が選べる明確な選択肢が作れるか。
    3. ターゲット層 (20点): ゲーマー・オタク層・ネット民が好む話題か。

    【出力形式のルール】
    以下のJSONフォーマットのみを絶対に出力してください。（Markdown記法や```jsonなどは一切含めないこと）

    {{
      "score": 点数(数値),
      "reason": "採点の理由（100文字程度）",
      "vote_type": "binary_plus", // 二項対立＋中立(様子見)が適している場合は "binary_plus", 単純な人気投票が適している場合は "multiple"
      "candidates": [
        "選択肢1（熱量高め）",
        "選択肢2（熱量高め）",
        "選択肢3（中立・様子見・その他）" // vote_typeがbinary_plusの場合は必ず3つ、multipleの場合は5〜10個
      ]
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(response_mime_type="application/json")
        )
        result = json.loads(response.text)
        print(f"   👉 判定: {result.get('score', 0)}点 ({result.get('vote_type')})")
        print(f"   👉 理由: {result.get('reason')}")
        return result
    except Exception as e:
        print(f"   ❌ AI編集長エラー: {e}")
        return {"score": 0}

# ==========================================
# ★ 4. 記事本文のAI執筆（1500文字高密度）
# ==========================================
def generate_article_content(news_item, editor_data):
    """合格したネタから、WordPressに投稿する完全な記事データを作る"""
    print(f"✍️ AIライターが記事を執筆中...")
    
    title = news_item['title']
    vote_type = editor_data.get('vote_type', 'binary_plus')
    candidates_json = json.dumps(editor_data.get('candidates', []), ensure_ascii=False)
    
    prompt = f"""
    以下のニュースと選択肢を元に、読者を煽り、投票したくなるような熱い論説記事を作成してください。
    文字数は無駄に長くせず、非常に高密度で具体的な内容にしてください。（合計約1500文字想定）

    【テーマとなるニュース】
    {title}
    
    【設定された選択肢】
    {candidates_json}

    【出力形式のルール】
    以下のJSONフォーマットのみを絶対に出力してください。（Markdown記法は禁止）

    {{
      "post_title": "【〇〇】〇〇は？ (※WordPressのタイトル用。20〜30文字程度)",
      "h2_title": "記事のH2見出し (※議論の核心を突く煽り文句)",
      "intro": "読者を惹きつける導入文。なぜ今これが燃えているのか。(約300文字)",
      "items": [
        {{
          "name": "選択肢1の名前",
          "desc": "この選択肢を選ぶ人の気持ちの代弁、具体的な主張。(約200〜300文字)"
        }},
        // ...設定された選択肢の数だけ繰り返す
      ],
      "trivia_title": "専門性を高める豆知識の見出し (例: 過去の似たような炎上事件)",
      "trivia_text": "検索エンジン(SEO)に評価されるような、背景知識や事実関係の解説。(約400文字)"
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(response_mime_type="application/json")
        )
        article_data = json.loads(response.text)
        return article_data
    except Exception as e:
        print(f"❌ AI執筆エラー: {e}")
        return None

# ==========================================
# ★ 5. WordPressへの自動投稿
# ==========================================
def post_to_wordpress(article_data):
    """生成された記事データをWordPressのREST APIで投稿・メタ保存する"""
    if not WP_URL or not WP_USER or not WP_APP_PASS:
        print("⚠️ WPの認証情報がないため投稿をスキップします。")
        return None

    print("🚀 WordPressへ記事を送信中...")
    
    # 1. 本文のショートコード生成
    items_str_list = []
    for item in article_data.get('items', []):
        # 画像URLは空でOKなので "|" をつける
        items_str_list.append(f"{item['name']}|")
    items_str = ", ".join(items_str_list)
    
    content = f'[vote_bar items="{items_str}"]\n\n[vote_summary items="{items_str}"]'

    # 2. 記事の基本データの送信
    wp_api_url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth = (WP_USER, WP_APP_PASS)
    
    # ※カテゴリIDは環境に合わせて変更してください（現在はデフォルト未指定）
    post_payload = {
        "title": article_data.get('post_title', 'タイトル未定'),
        "content": content,
        "status": "publish"
    }
    
    res = requests.post(wp_api_url, auth=auth, json=post_payload, timeout=30)
    
    if res.status_code == 201:
        res_data = res.json()
        post_id = res_data.get("id")
        post_link = res_data.get("link")
        print(f"✅ 記事投稿成功! (Post ID: {post_id})")
        
        # 3. カスタムメタデータ（カスタムフィールド）の保存
        meta_payload = {
            "meta": {
                "wiki_h2_title": article_data.get("h2_title", ""),
                "wiki_h2_text": article_data.get("intro", ""),
                "wiki_fact_h3": article_data.get("trivia_title", ""),
                "wiki_info_fact": article_data.get("trivia_text", "")
            }
        }
        
        # 選択肢のメタデータを追加
        for i, item in enumerate(article_data.get("items", [])[:10]):
            idx = i + 1
            meta_payload["meta"][f"wiki_item_name_{idx}"] = item["name"]
            meta_payload["meta"][f"wiki_item_img_{idx}"] = ""
            meta_payload["meta"][f"wiki_info{idx}_h3"] = f"{item['name']}派の意見"
            meta_payload["meta"][f"wiki_info_{idx}"] = item["desc"]

        # メタデータをPOSTで更新（WordPress側のREST API許可設定が必要）
        meta_res = requests.post(f"{wp_api_url}/{post_id}", auth=auth, json=meta_payload)
        if meta_res.status_code == 200:
            print("✅ カスタムフィールドの保存も完了しました！")
        else:
            print(f"⚠️ メタデータの保存に失敗しました: {meta_res.text}")
            
        return {"link": post_link, "id": post_id}
    else:
        print(f"❌ WP投稿エラー: {res.status_code} - {res.text}")
        return None

# ==========================================
# ★ メイン処理
# ==========================================
if __name__ == "__main__":
    print("=== どっちよ.com AI自動投稿システム v71 スタート ===")
    
    # 1. ニュースの取得と仕分け
    tier1, tier2, tier3 = get_mega_trends_and_entertainment_news()
    
    # 探索順序（Tier1 -> Tier2 -> Tier3）
    search_queue = tier1 + tier2 + tier3
    
    if not search_queue:
        print("💤 48時間以内のニュースが1件もありませんでした。処理を終了します。")
        sys.exit(0)
        
    posted_count = 0
    
    # 2. AI編集長による査定と執筆
    for news in search_queue:
        # すでに1件投稿したら、スパム化防止のため今回は終了する
        if posted_count >= 1:
            break
            
        editor_verdict = ask_ai_editor(news)
        
        if editor_verdict.get("score", 0) >= 70:
            print(f"🎉 70点突破！記事の生成に進みます。")
            article = generate_article_content(news, editor_verdict)
            
            if article:
                post_result = post_to_wordpress(article)
                if post_result:
                    posted_count += 1
                    post_link = post_result["link"]
                    post_id = post_result["id"]
                    
                    # 編集用のログインURLを生成
                    edit_url = f"{WP_URL.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
                    
                    # Discordへ通知
                    if DISCORD_WEBHOOK_URL:
                        discord_data = {
                            "content": f"🎉 **新しい論争記事が自動投稿されました！**\n\n**【タイトル】**\n{article.get('post_title')}\n\n**【公開URL】**\n{post_link}\n\n**【ログインURL（編集画面）】**\n{edit_url}"
                        }
                        try:
                            requests.post(DISCORD_WEBHOOK_URL, json=discord_data)
                            print("🔔 Discordに通知を送信しました")
                        except Exception as e:
                            print(f"⚠️ Discord通知エラー: {e}")
        else:
            print(f"🗑️ ボツ（点数不足）。次のニュースを探します...\n")

    if posted_count == 0:
        print("💤 今回はAI編集長が合格を出す熱いネタがありませんでした。")
        
    print("=== 処理終了 ===")
