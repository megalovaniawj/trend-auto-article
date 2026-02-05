# -*- coding: utf-8 -*-
"""
【トレンド自動記事作成 V93】カスタムフィールド完全対応・最終版
修正点:
1. コンテンツ出力先の変更: HTML直書きをやめ、WordPressのカスタムフィールド（meta）へデータを渡す方式に変更。
   これにより、テーマ側のテンプレート機能で「フォームの下」に正しく表示されるようになる。
2. ウソ防止安全策: Wikiデータ取得失敗時は、多選択（推し投票）から2択（好き嫌い）へ自動変更。
3. 重複制御の最適化: 過去記事による候補除外を撤廃（次回実行時は同テーマも可）。今回の実行内での重複のみ禁止。
4. その他: アフィリエイト削除、Wiki4000文字、タイトル作品名必須。
"""

import os
import sys
import warnings
import logging
import requests
import base64
import time
import random
import json
import feedparser
import re
from urllib.parse import quote
from datetime import datetime, timedelta

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

warnings.filterwarnings("ignore")

# ==========================================
# ★設定エリア
# ==========================================
WP_URL = "https://docchiyo.com"
WP_USER = "bear"
WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not WP_APP_PASS or not GEMINI_API_KEY:
    print("❌ エラー: 環境変数（シークレット）が設定されていません。")
    sys.exit(1)

MODEL_NAME = "gemma-3-27b-it"
ARTICLES_TO_CREATE = 3

# ユーザーエージェント
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
HEADERS = {'User-Agent': USER_AGENT}

# NGワード
NG_KEYWORDS = [
    "リウマチ", "癌", "がん", "腫瘍", "うつ", "鬱", "障害", "症候群", "病気", "疾患",
    "病院", "治療", "手術", "薬", "ワクチン", "感染", "ウイルス", "菌", "陽性", "陰性",
    "痛み", "激痛", "苦しい", "吐き気", "下痢", "発熱", "高熱", "脳梗塞", "心筋梗塞", "死亡", "死去", "遺体",
    "殺人", "殺害", "刺さ", "死刑", "逮捕", "容疑者", "書類送検", "捜査", "警察", "犯人",
    "事故", "火災", "火事", "爆発", "地震", "津波", "災害", "襲撃", "強盗", "不審者",
    "被害", "告発", "辞任", "解雇", "契約解除", "裁判", "訴訟", "判決", "賠償", "横領", "脱税",
    "遅延", "運転見合わせ", "人身事故", "停電", "天気", "気象", "雨", "訃報", "お別れ",
    "揶揄", "失言", "処分", "厳罰", "炎上", "謝罪", "不倫", "浮気", "供述",
    "ほのぼの", "癒やし", "かわいい", "猫", "犬", "動物園", "水族館", "住吉大社", "ローカル", "地域"
]

def get_auth_header():
    creds = f"{WP_USER.strip()}:{WP_APP_PASS.strip()}"
    token = base64.b64encode(creds.encode()).decode()
    return {'Authorization': f'Basic {token}'}

def get_all_existing_titles():
    # 記事作成直前の「完全一致重複」を防ぐためだけに取得
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
    print(f" -> 合計 {len(titles)} 件取得完了")
    return titles

def get_google_realtime_trends():
    print("    👉 Google Realtime API: ", end="")
    items = [] 
    try:
        url = "https://trends.google.co.jp/trends/api/realtimetrends?hl=ja&tz=-540&cat=all&fi=0&fs=0&geo=JP&ri=300&rs=20&sort=0"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            content = resp.text.replace(")]}',", "").strip()
            data = json.loads(content)
            stories = data.get('storySummaries', {}).get('trendingStories', [])
            for story in stories:
                title = story.get('title', '')
                articles = story.get('articles', [])
                headline = articles[0]['articleTitle'] if articles else title
                if not title and story.get('entityNames'): title = story['entityNames'][0]
                if title: items.append((title, headline))
            print(f"OK ({len(items)}件)")
            return items
    except:
        print("失敗")
    return []

def get_raw_trends():
    print("\n📈 トレンド候補を収集中...")
    raw_data = [] 
    raw_data.extend(get_google_realtime_trends())

    rss_sources = [
        ("Googleアニメ", "https://news.google.com/rss/search?q=アニメ&hl=ja&gl=JP&ceid=JP:ja"),
        ("Googleゲーム", "https://news.google.com/rss/search?q=ゲーム&hl=ja&gl=JP&ceid=JP:ja"),
        ("Google漫画", "https://news.google.com/rss/search?q=漫画&hl=ja&gl=JP&ceid=JP:ja"),
        ("4Gamer", "https://www.4gamer.net/rss/index.xml"),
        ("Yahooエンタメ", "https://news.yahoo.co.jp/rss/topics/entertainment.xml"),
    ]

    for name, url in rss_sources:
        print(f"    👉 {name}: ", end="")
        entries = []
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.content)
                entries = feed.entries
        except: pass
        
        if not entries:
            try:
                feed = feedparser.parse(url)
                entries = feed.entries
            except: pass

        if entries:
            count = 0
            for entry in entries:
                full_title = entry.title
                simple_title = re.sub(r'【.*?】', '', full_title).strip()
                simple_title = re.sub(r'^PR:', '', simple_title).strip()
                simple_title = re.sub(r' - .*', '', simple_title).strip()
                if len(simple_title) > 5:
                    raw_data.append((simple_title, full_title))
                    count += 1
                if count >= 8: break
            print(f"OK ({count}件)")
        else:
            print("取得失敗")

    cleaned_data = []
    seen = set()
    for kw, headline in raw_data:
        kw = kw.strip()
        if not kw: continue
        if kw in seen: continue
        is_ng = False
        for ng in NG_KEYWORDS:
            if ng in kw or ng in headline:
                is_ng = True; break
        if not is_ng:
            cleaned_data.append({'keyword': kw, 'headline': headline})
            seen.add(kw)

    print(f" -> 有効候補: {len(cleaned_data)}件")
    return cleaned_data

def select_best_topics(candidates):
    if not candidates: return []
    print("🤔 AI編集長が厳選中...", end="")
    
    # ★重要: ここで過去記事チェックを行わない。
    # これにより、次回実行時には同じテーマでも（トレンドなら）候補に挙がる。
    
    candidates_str = "\n".join([f"- {c['keyword']}: {c['headline']}" for c in candidates[:80]])
    
    prompt = f"""
    Webメディア編集長として、以下のニュースリストを**「読者が熱狂的に投票したくなる順」にランキング化**し、上位10個を選んでください。

    【ニュースリスト (キーワード: 見出し)】
    {candidates_str}

    【★絶対的な優先順位】
    1. **アニメ・漫画・ゲームの「具体的な新作・キャラ」**
    2. **VTuber・YouTuberの話題**
    3. **チェーン店グルメ・商品**
    4. **アイドル・芸能**（※ゴシップは除外）

    ※事件、事故、政治、暗いニュースは絶対に選ばないこと。

    【出力形式】
    上位10個の「キーワード」のみをカンマ区切りで出力してください。
    """
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = { "contents": [{"parts": [{"text": prompt}]}] }
    
    final_selection = []
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30)
        if res.status_code == 200:
            text = res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            selected_keywords = [x.strip() for x in re.split(r'[,\n、]', text) if x.strip()]
            
            # 部分一致で柔軟に採用
            for kw in selected_keywords:
                for item in candidates:
                    if (item['keyword'] in kw) or (kw in item['keyword']):
                        if item not in final_selection:
                            final_selection.append(item)
                        break 
    except: pass
    
    # 候補不足時の補充
    if len(final_selection) < ARTICLES_TO_CREATE:
        print(f"    ⚠️ AI選出不足({len(final_selection)}件)。不足分を自動補充します。")
        current_kws = [x['keyword'] for x in final_selection]
        for c in candidates:
            if c['keyword'] not in current_kws:
                final_selection.append(c)
                if len(final_selection) >= 10: break
    
    print(f" -> 👑 選抜: {[item['keyword'] for item in final_selection[:5]]}...")
    return final_selection

def extract_pure_keyword(headline, raw_keyword):
    print(f"    🧹 見出しから「核KW」を純粋抽出中...", end="")
    prompt = f"""
    以下のニュース見出しから、Wikipediaで検索可能な【1つの固有名詞（作品名・人名・サービス名）】を抽出せよ。
    前置きは不要。単語1つのみを出力せよ。

    見出し: {headline}
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = { "contents": [{"parts": [{"text": prompt}]}] }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=20)
        if res.status_code == 200:
            pure_kw = res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            pure_kw = re.sub(r'[\r\n].*', '', pure_kw)
            pure_kw = re.sub(r'[「」『』【】"\'\.\s]', '', pure_kw)
            print(f" -> [{pure_kw}]")
            return pure_kw
    except: pass
    print(" -> 失敗（元のキーワードを使用）")
    return "EXTRACT_FAILED"

def perform_fact_check(pure_keyword):
    print(f"    🕵️‍♂️ ファクトチェック（Wikipedia公式から「{pure_keyword}」のデータを直接取得）...", end="")
    api_url = "https://ja.wikipedia.org/w/api.php"
    params = {"action": "query", "format": "json", "prop": "extracts", "explaintext": True, "titles": pure_keyword, "redirects": 1}
    try:
        r = requests.get(api_url, params=params, headers={'User-Agent': USER_AGENT}, timeout=15)
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))
        if "missing" in page:
            search_params = {"action": "query", "list": "search", "srsearch": pure_keyword, "format": "json"}
            s_res = requests.get(api_url, params=search_params, headers={'User-Agent': USER_AGENT}, timeout=5)
            s_data = s_res.json()
            if s_data.get('query', {}).get('search'):
                correct_title = s_data['query']['search'][0]['title']
                params['titles'] = correct_title
                r = requests.get(api_url, params=params, headers={'User-Agent': USER_AGENT}, timeout=15)
                page = next(iter(r.json().get("query", {}).get("pages", {}).values()))
            else:
                print(" [ページなし]")
                return "SEARCH_FAILED"
        extract = page.get("extract", "")
        if not extract:
            print(" [テキストなし]")
            return "SEARCH_FAILED"
        
        # 4000文字
        fact_text = f"【「{pure_keyword}」に関するWikipediaの事実データ】\n{extract[:4000]}"
        print(" [取得完了]")
        return fact_text
    except:
        print(" [APIエラー]")
        return "SEARCH_FAILED"

def perform_news_research(pure_keyword):
    print(f"    📰 背景調査（Googleニュースで「{pure_keyword}」の最新動向を検索）...", end="")
    url = f"https://news.google.com/rss/search?q={quote(pure_keyword)}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        res = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=10)
        if res.status_code == 200:
            feed = feedparser.parse(res.content)
            if feed.entries:
                news_text = f"【「{pure_keyword}」の最新ニュース（トレンド背景）】\n"
                print(" [調査完了]")
                for i, entry in enumerate(feed.entries[:3]):
                    title = re.sub(r' [-|–|:|：].*', '', entry.title).strip()
                    news_text += f"・{title}\n"
                    print(f"      👉 記事{i+1}: {title}")
                return news_text
    except: pass
    print(" [ニュースなし]")
    return "（直近のニュースは見つかりませんでした）"

def analyze_and_extract_core(pure_keyword, headline, fact_check_data, news_data):
    print(f"    🧠 AIが100の成功事例を元に企画をメガ思考中...", end="")
    ai_fact_input = fact_check_data if fact_check_data != "SEARCH_FAILED" else "情報なし"
    
    prompt = f"""
    あなたは凄腕のWeb編集者です。
    一番盛り上がる「好き・嫌い・好み」の投票企画を【自分で考えて】ください。

    【★鉄の掟（守れない場合は『SKIP』）】
    
    1. **【タイトル生成テンプレート（絶対に守れ！）】**
       - **WHICH_BESTの場合**: 「【{pure_keyword}】（具体的なテーマ）は？推しは？」
       - **LIKE_DISLIKEの場合**: 
         - **キャラ・人物名なら**: 「【作品名】{pure_keyword}、好き？普通？嫌い？」という形式にする。単独の「入間くん」はNG。「【魔入りました！入間くん】入間くん」とする。
       
    2. **【企画パターンの固定】**
       - **「キャラクター・人物」** 👉 **「LIKE_DISLIKE（好感度投票）」**
       - **「作品全体・グループ」** 👉 **「WHICH_BEST（推し投票）」**

    3. **【捏造の完全禁止】**
       - 選択肢はWikiに実在する名称（固有名詞）のみ。セリフや文章は禁止。

    【入力情報】
    純粋キーワード: {pure_keyword}
    元の見出し: {headline}
    ★最新ニュース（トレンドの背景）: 
    {news_data}
    ★事実データ（Wikipedia）: 
    {ai_fact_input}

    【分類する記事タイプ】
    - **LIKE_DISLIKE (2択)**: 「好き？嫌い？」「買う？買わない？」など。
    - **WHICH_BEST (多選択)**: 「推しは？」（※Wikiにデータがない場合は選ばないこと！）
    - **SKIP (作成不可)**

    【出力形式(JSON)】
    {{
        "core_keyword": "{pure_keyword}",
        "article_type": "LIKE_DISLIKE" or "WHICH_BEST" or "SKIP",
        "proposed_title": "一番盛り上がるタイトル（※作品名を含めること）",
        "reason": "なぜ今トレンドなのかの背景",
        "suggested_category": "contents" または "people"
    }}
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = { "contents": [{"parts": [{"text": prompt}]}] }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30)
        if res.status_code == 200:
            text = res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            text = text.replace('```json', '').replace('```', '').strip()
            start = text.find('{'); end = text.rfind('}') + 1
            analysis = json.loads(text[start:end])
            print(f" -> [{analysis['article_type']}] {analysis['proposed_title']}")
            print(f"      👀 理由: {analysis['reason']}")
            return analysis
    except: pass
    print(" -> 分析失敗")
    return {"core_keyword": pure_keyword, "article_type": "SKIP", "proposed_title": "", "reason": "", "suggested_category": "contents"}

def get_comment_personas(count=10):
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
    selected_keys = random.choices(keys, k=count)
    persona_prompt = "以下の10人のキャラになりきって、各1つ（計10個）コメントを書いて。\n"
    for i, key in enumerate(selected_keys):
        persona_prompt += f"{i+1}. {key}: {definitions[key]}\n"
    return persona_prompt

def generate_article_content(analysis_data, original_headline, fact_check_data, news_data):
    theme = analysis_data['core_keyword']
    a_type = analysis_data['article_type']
    title_idea = analysis_data['proposed_title']
    reason = analysis_data['reason']
    cat = analysis_data.get('suggested_category', 'contents')

    print(f"🤖 記事執筆中 ({theme})...", end="")
    persona_instruction = get_comment_personas(10)
    
    # ★ウソ防止の安全策
    fact_instruction = ""
    if fact_check_data != "SEARCH_FAILED" and fact_check_data != "NO_SEARCH_MODULE":
        fact_instruction = f"""
    【ファクトチェック情報】
    以下のWiki情報を参考に、必ず事実のみに基づいて作成すること。嘘は厳禁。
    {fact_check_data}
        """

    type_instruction = ""
    if a_type == "LIKE_DISLIKE":
        type_instruction = f"""
        **【対決型（2択）】**
        - タイトル: 「{title_idea}」
        - 選択肢: 2〜3個（例: 好き/嫌い/普通、見る/見ない）
        - **解説文(text)**: 各選択肢を選ぶ理由を**200〜300文字程度**で熱く語ること。
        """
    elif a_type == "WHICH_BEST":
        type_instruction = f"""
        **【多選択型（推し）】**
        - タイトル: 「{title_idea}」
        - **【重要：選択肢（items）のルール】**
          1. **絶対に「作品名」「キャラ名」「役者名」などの固有名詞（20文字以内）のみにすること。**
          2. **「セリフ」や「あらすじ」は禁止。**
          3. 5〜10個列挙。「その他」も必須。
        - **解説文(text)**: その選択肢の魅力や背景を**200〜300文字程度**で深掘り解説すること。
        """
    elif a_type == "RATE":
        type_instruction = f"""
        **【頻度・実態型】**
        - タイトル: 「{title_idea}」
        - 選択肢: 段階的な数（毎日 / 週1回 / 行かない 等）。
        - **解説文(text)**: その頻度の人の心理を**200文字程度**で描写すること。
        """

    prompt = f"""
    トレンドテーマ「{theme}」について、読者参加型の「投票記事」を作成してください。
    
    【前提情報】
    ニュース: {original_headline}
    背景: {news_data}
    {fact_instruction}
    
    【★構成ルール】
    {type_instruction}

    【コメント】
    {persona_instruction}
    
    【投票数】
    * ランダムな数値（例: 487, 123）

    【★JSON形式（slugは英語小文字とハイフンのみ。数字禁止）】
    {{
        "title": "タイトル",
        "slug": "short-english-slug",
        "is_product": false,
        "tags": ["タグ"],
        "category_slug": "{cat}", 
        "h2_title": "導入H2見出し（例：『〇〇』がついに話題に！）",
        "h2_text": "記事冒頭の導入文（★400〜500文字程度）。ニュースの背景を詳しく説明し、『そこで今回は、みんなの推しを聞いてみたいと思います！』と投票につなげる。",
        "comparison_table": "| A | B |\\n|---|---|", 
        "fact_h3": "豆知識の見出し",
        "info_fact": "豆知識の本文（★300〜400文字程度）。Wikiのトリビアを詳しく紹介する。",
        "items": [ 
            {{ "name": "選択肢1(短く固有名詞)", "text": "濃厚な解説(200文字以上)", "votes": 234 }}, 
            {{ "name": "選択肢2(短く固有名詞)", "text": "濃厚な解説(200文字以上)", "votes": 87 }}
        ],
        "comments": [ {{ "name": "匿名", "text": "コメント" }} ]
    }}
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = { "contents": [{"parts": [{"text": prompt}]}] }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=120)
        if res.status_code != 200: return None
        text = res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        text = text.replace('```json', '').replace('```', '').strip()
        start = text.find('{'); end = text.rfind('}') + 1
        data_json = json.loads(text[start:end])
        print(" -> 完了")
        return data_json
    except:
        print(" -> 生成エラー")
        return None

def get_term_id(slug):
    headers = get_auth_header()
    try:
        res = requests.get(f"{WP_URL}/wp-json/wp/v2/categories?slug={slug}", headers=headers)
        if res.json(): return res.json()[0]['id']
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/categories", headers=headers, json={'name':slug, 'slug':slug})
        return res.json()['id']
    except: return 1

def post_comment(pid, name, text, date_str):
    try:
        requests.post(f"{WP_URL}/wp-json/wp/v2/comments", headers=get_auth_header(), 
                      json={'post': pid, 'author_name': name, 'content': text, 'status': 'approve', 'date': date_str})
    except: pass

# ==========================================
# メイン処理
# ==========================================
print("\n🔥 完全自動トレンド記事作成 (V93: カスタムフィールド対応完全版) 開始...")

success_count = 0
processed_core_keywords = set() # 今回の実行における重複防止用

existing_titles = get_all_existing_titles()
selected_items = select_best_topics(get_raw_trends()) # 過去記事フィルタリング廃止

if not selected_items:
    print("❌ ネタ切れ")
else:
    for item in selected_items:
        if success_count >= ARTICLES_TO_CREATE:
            print(f"🎉 目標記事数（{ARTICLES_TO_CREATE}記事）に達したため、処理を終了します。")
            break
            
        print(f"\n🚀 候補: {item['headline']}")
        
        # STEP1
        core_kw = extract_pure_keyword(item['headline'], item['keyword'])
        
        if core_kw == "EXTRACT_FAILED":
             print(" -> ⚠️ キーワード抽出失敗のためスキップ")
             continue
        
        # ★今回の実行内で既に扱ったテーマならスキップ
        if core_kw in processed_core_keywords:
            print(f" -> 🚫 重複テーマ（{core_kw}）のためスキップ")
            continue
        processed_core_keywords.add(core_kw)
        
        # STEP2 (Wiki)
        fact_check_data = perform_fact_check(core_kw)
        # STEP3 (News)
        news_data = perform_news_research(core_kw)
        # STEP4 (Analysis)
        analysis_data = analyze_and_extract_core(core_kw, item['headline'], fact_check_data, news_data)
        
        if analysis_data['article_type'] == "SKIP":
            print(" -> ⚠️ 投票化が難しいためスキップします。")
            continue

        # ★重要: 安全策（Wiki検索失敗時は、嘘を防ぐため「好き嫌い」に変更）
        if analysis_data['article_type'] == "WHICH_BEST" and fact_check_data == "SEARCH_FAILED":
            print(f" -> ⚠️検索失敗: 嘘を防ぐため「{analysis_data['core_keyword']}」の好感度調査（好き/嫌い）に変更します。")
            analysis_data['article_type'] = "LIKE_DISLIKE"
            analysis_data['proposed_title'] = f"【{analysis_data['core_keyword']}】好き？普通？苦手？"
            analysis_data['suggested_category'] = "people"

        # TPM対策
        print("☕ 制限回避のため10秒休憩中...", end="")
        time.sleep(10)
        print(" 再開")

        data = generate_article_content(analysis_data, item['headline'], fact_check_data, news_data)
        if not data: continue
        
        if data['title'] in existing_titles:
            print(" -> タイトル重複のためSKIP")
            continue

        print(f"📝 作成決定: {data['title']}")
        
        items_str = []
        
        # ★ここが最重要修正ポイント！
        # コンテンツをHTML直書きではなく、カスタムフィールド(meta)に渡す
        meta = {
            'post_views_count': '0',
            # 導入部分
            'wiki_h2_title': data.get('h2_title', ''),
            'wiki_h2_text': data.get('h2_text', ''),
            # 豆知識（共通部分）
            'wiki_fact_h3': data.get('fact_h3', ''),
            'wiki_info_fact': data.get('info_fact', '')
        }
        
        if data.get('comparison_table'): meta['wiki_comparison_table'] = data['comparison_table']

        # 選択肢ごとの解説をMetaに登録（これでグリッド表示される）
        for i, item_choice in enumerate(data['items']):
            idx = i + 1
            if idx > 10: break
            name = item_choice['name']
            
            # 各選択肢のタイトルと解説文
            meta[f'wiki_info{idx}_h3'] = name
            meta[f'wiki_info_{idx}'] = item_choice.get('text', '')
            
            meta[f'wiki_item_name_{idx}'] = name
            meta[f'wiki_item_img_{idx}'] = "" # 画像は空
            
            votes = item_choice.get('votes', 0)
            if votes % 10 == 0: votes += random.randint(1, 9)
            meta[f'vote_multi_idx_{i}'] = str(votes)
            
            if len(data['items']) == 2:
                k = 'vote_count_a' if i == 0 else 'vote_count_b'
                meta[k] = str(votes)
            
            items_str.append(name)

        cat_id = get_term_id(data.get('category_slug', 'contents'))
        
        # 本文には投票システムだけ入れる（余計なHTMLは書かない）
        content = ""
        if len(items_str) == 2:
            sc = f'[vote_bar name_a="{items_str[0]}" name_b="{items_str[1]}"]\n\n[vote_summary name_a="{items_str[0]}" name_b="{items_str[1]}"]'
        else:
            sc = f'[vote_bar items="{", ".join(items_str)}"]\n\n[vote_summary items="{", ".join(items_str)}"]'
        content = sc

        now = datetime.now()
        post_time = now - timedelta(hours=1)
        clean_slug = data.get('slug', 'post')
        
        post_data = {
            'title': data['title'],
            'content': content,
            'status': 'publish',
            'date': post_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'categories': [cat_id],
            'slug': clean_slug, 
            'meta': meta
        }
        
        try:
            res = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", headers=get_auth_header(), json=post_data, timeout=60)
            if res.status_code == 201:
                pid = res.json()['id']
                print(f"✅ 投稿完了 (ID:{pid})")
                print("💬 コメント投稿中...", end="")
                for com in data.get('comments', []):
                    c_time = post_time + timedelta(minutes=random.randint(5, 55))
                    if c_time > now: c_time = now
                    post_comment(pid, com['name'], com['text'], c_time.strftime('%Y-%m-%dT%H:%M:%S'))
                    time.sleep(0.2)
                print(" 完了")
                success_count += 1
                existing_titles.append(data['title'])
        except: print("❌ 投稿エラー")
        
        print("☕ 制限回避のため65秒休憩中...")
        time.sleep(65)

print(f"\n🎉 完了 ({success_count}記事)")
