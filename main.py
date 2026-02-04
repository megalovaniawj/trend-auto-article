# -*- coding: utf-8 -*-
import os
import sys
import warnings
import logging
import requests
import base64
import io
import time
import random
import shutil
import glob
import json
import feedparser
import re
from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from urllib.parse import quote
from datetime import datetime, timedelta
from icrawler.builtin import BingImageCrawler
try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

warnings.filterwarnings("ignore")
logging.getLogger("duckduckgo_search").setLevel(logging.WARNING)

# ==========================================
# ★設定エリア（GitHubのシークレットから読み込み）
# ==========================================
WP_URL = "https://docchiyo.com"
WP_USER = "bear"
WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not WP_APP_PASS or not GEMINI_API_KEY:
    print("❌ エラー: 環境変数（シークレット）が設定されていません。")
    sys.exit(1)

MODEL_NAME = "gemma-3-27b-it"
ARTICLES_TO_CREATE = 3  # 1回の起動で作成する記事数
DEFAULT_IMAGE_ID = 0
AFFILIATE_SHORTCODE = '<div class="aff-btn">[btn url="https://www.amazon.co.jp/s?k={word}" text="Amazonで「{word}」を見る" target="_blank"]</div>'

TARGET_SIZE = (1000, 1000)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
    'Referer': 'https://www.google.com/'
}

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
            print(".", end="") 
            time.sleep(0.5) 
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
        ("Yahooエンタメ", "https://news.yahoo.co.jp/rss/topics/entertainment.xml"),
        ("はてなエンタメ", "https://b.hatena.ne.jp/hotentry/entertainment.rss"),
        ("はてなゲーム", "https://b.hatena.ne.jp/hotentry/game.rss"),
        ("まんたんウェブ", "https://mantan-web.jp/rss/rss2.0/anime"),
        ("ファミ通", "https://www.famitsu.com/rss/fcom_all.xml"),
        ("オリコン", "https://www.oricon.co.jp/rss/news/entertainment.xml"),
        ("映画.com", "https://eiga.com/news/rss/"),
        ("Googleエンタメ", "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=ja&gl=JP&ceid=JP:ja"),
        ("はてな社会", "https://b.hatena.ne.jp/hotentry/social.rss"), 
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
                simple_title = re.sub(r' [-|–|:|：].*', '', full_title).strip()
                simple_title = re.sub(r'【.*?】', '', simple_title).strip()
                if len(simple_title) > 2:
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

def select_best_topics(candidates, existing_titles):
    if not candidates: return []
    print("🤔 AI編集長が厳選中...", end="")
    
    safe_candidates = []
    for c in candidates:
        is_duplicate = False
        for exist in existing_titles[-50:]: 
            if c['keyword'] in exist: is_duplicate = True; break
        if not is_duplicate: safe_candidates.append(c)
    
    if len(safe_candidates) < 3:
        safe_candidates = candidates

    candidates_str = "\n".join([f"- {c['keyword']}: {c['headline']}" for c in safe_candidates[:80]])
    
    prompt = f"""
    Webメディア編集長として、以下のニュースリストを**「読者が熱狂的に投票したくなる順」にランキング化**し、上位10個を選んでください。

    【ニュースリスト (キーワード: 見出し)】
    {candidates_str}

    【★評価基準】
    1位〜5位: アニメ、漫画、ゲーム、アイドル、映画など。
    6位〜8位: 日常の議論、マナー、食品、サービスなど。
    低評価（選ばない）: 政治、事件、ほのぼのニュース。

    【出力形式】
    上位10個の「キーワード」のみをカンマ区切りで出力してください。絶対に10個出力すること。
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
            
            for kw in selected_keywords:
                for item in candidates:
                    if item['keyword'] == kw:
                        final_selection.append(item)
                        break
    except: pass
    
    if not final_selection:
        print("    ⚠️ AI選出エラー。上位候補を自動採用します。")
        final_selection = safe_candidates[:10]
    
    print(f" -> 👑 選抜: {[item['keyword'] for item in final_selection]}")
    return final_selection

def extract_pure_keyword(headline, raw_keyword):
    print(f"    🧹 見出しから「核KW」を純粋抽出中...", end="")
    prompt = f"""
    以下のニュース見出しから、Wikipediaで検索可能な【1つの固有名詞（人名・作品名・企業名など）】だけを抽出せよ。
    「キーワードは」などの前置き、句読点、記号、出来事の描写は一切不要。単語1つのみを出力せよ。

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
    return raw_keyword

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
            
        fact_text = f"【「{pure_keyword}」に関するWikipediaの事実データ】\n{extract[:2000]}"
        print(" [取得完了]")
        return fact_text

    except Exception as e:
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
                for i, entry in enumerate(feed.entries[:3]):
                    title = re.sub(r' [-|–|:|：].*', '', entry.title).strip()
                    news_text += f"・{title}\n"
                print(" [調査完了]")
                return news_text
    except: pass
    print(" [ニュースなし]")
    return "（直近のニュースは見つかりませんでした）"

def analyze_and_extract_core(pure_keyword, headline, fact_check_data, news_data):
    print(f"    🧠 AIが100の成功事例を元に企画をメガ思考中...", end="")
    ai_fact_input = fact_check_data if fact_check_data != "SEARCH_FAILED" else "情報なし"
    prompt = f"""
    あなたは凄腕のWeb編集者です。提供された「元の見出し」「最新ニュース」「事実データ」を読み込み、
    【なぜ今このキーワードがトレンドなのか】の文脈を理解した上で、
    一番盛り上がる「好き・嫌い・好み」の投票企画を【自分で考えて】ください。

    【重要ルール】
    1. 最新ニュースの内容にフォーカスし、今読者が一番語りたい切り口を見つけること。
    2. タイトルや選択肢には「具体的な名前（キャラ名、商品名、曲名など）」を必ず入れること。
    3. **【タレントの救済措置（最終手段）】ニュースが特定のタレントに関するものであれば、安易に「好き？嫌い？」に逃げず、まずはその人物の「代表曲」「出演ドラマ・映画」「YouTube企画」などをリストアップし、「〇〇で一番好きな作品は？」といった推し投票（WHICH_BEST）を第一に考えること。**
    4. どうしても代表作等で投票化が難しい場合【のみ】、最終手段として「〇〇は好き？嫌い？」というシンプルな好感度調査（LIKE_DISLIKE）に着地させること。「SKIP」にはしない。その際、category_slugは必ず「people」にすること。
    5. ニュースの内容が上記いずれにも当てはまらず、どうしても投票に落とし込めない場合のみ「SKIP」と判断すること。

    【入力情報】
    純粋キーワード: {pure_keyword}
    元の見出し: {headline}
    ★最新ニュース（トレンドの背景）: 
    {news_data}
    ★事実データ（Wikipedia）: 
    {ai_fact_input}

    【分類する記事タイプ】
    - **LIKE_DISLIKE (2択)**: 「好き？嫌い？」「見る？見ない？」「買う？買わない？」
    - **WHICH_BEST (多選択)**: 「推しは？」「どれを買う？」 (※タイトルに『〇〇の曲で』『〇〇のキャラで』『〇〇の商品で』と具体的に入れること)
    - **RATE (生活)**: 「利用頻度は？」(※段階的な選択肢を想定)
    - **SKIP (作成不可)**

    【出力形式(JSON)】
    {{
        "core_keyword": "企画の主役となる単語",
        "article_type": "LIKE_DISLIKE" or "WHICH_BEST" or "RATE" or "SKIP",
        "proposed_title": "あなたが考えた、一番盛り上がるタイトル（※キャラ名・曲名・商品名を必ず入れること）",
        "reason": "なぜ今トレンドなのかの背景",
        "suggested_category": "contents" または "people" (タレントやYouTuberならpeopleにする)
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
            return analysis
    except: pass
    print(" -> 分析失敗")
    return {"core_keyword": pure_keyword, "article_type": "SKIP", "proposed_title": "", "reason": "", "suggested_category": "contents"}

def get_comment_personas(count=10):
    definitions = {
        'normal': "普通のユーザー。「〜だね」「〜かも」。論理的すぎずスマホ短文。",
        'polite': "丁寧。「ですね」「と思います」。掲示板の敬語。",
        'rough': "乱暴。「〜だろ」「〜じゃね？」。言い切り。",
        'excited': "感情的。「マジで〜」「〜すぎ！」。勢い重視。",
        'question': "自信なさげ。「〜かな？」。迷っている感じ。",
        'slang': "ネットスラング。「草」「それな」。ノリ重視。",
        'kansai': "関西弁。「〜やな」「せやね」。",
        'otaku': "早口オタク。「〜なんだよなぁ」「結局〇〇一択」。",
        'gal': "ギャル。「尊い...」「ビジュ良すぎ」。",
        'simple': "一言。「これ。」「間違いない。」。"
    }
    keys = ['normal', 'polite', 'rough', 'excited', 'question', 'slang', 'kansai', 'otaku', 'gal', 'simple']
    weights = [16, 16, 16, 16, 16, 4, 4, 4, 4, 4]
    selected_keys = random.choices(keys, weights=weights, k=count)
    persona_prompt = "以下の10人のキャラクターになりきって、それぞれ1つずつ（計10個）コメントを書いてください。\n"
    for i, key in enumerate(selected_keys):
        persona_prompt += f"{i+1}. キャラ[{key}]: {definitions[key]}\n"
    return persona_prompt

def generate_article_content(analysis_data, original_headline, fact_check_data, news_data):
    theme = analysis_data['core_keyword']
    a_type = analysis_data['article_type']
    title_idea = analysis_data['proposed_title']
    reason = analysis_data['reason']
    cat = analysis_data.get('suggested_category', 'contents')

    print(f"🤖 記事執筆中 ({theme})...", end="")
    persona_instruction = get_comment_personas(10)
    fact_instruction = ""
    if fact_check_data != "SEARCH_FAILED" and fact_check_data != "NO_SEARCH_MODULE":
        fact_instruction = f"""
    【ファクトチェック情報（裏取りデータ）】
    以下のWikipediaの検索結果を参考に、必ず事実のみに基づいて記事・選択肢を作成してください。嘘（ハルシネーション）は厳禁です。
    {fact_check_data}
        """

    type_instruction = ""
    if a_type == "LIKE_DISLIKE":
        type_instruction = f"""
        **【対決型（2択）】**
        - タイトル: 「{title_idea}」を採用せよ。
        - 選択肢: 2〜3個（例: 大好き/普通/苦手、見る/見ない、買う/見送る）
        - **解説文(text)のルール**: **生成した「全ての選択肢」に対して、互いの正義（選ぶ理由）を100〜150文字程度で簡潔に熱く語ること。**
        """
    elif a_type == "WHICH_BEST":
        type_instruction = f"""
        **【多選択型（推し）】**
        - タイトル: 「{title_idea}」を採用せよ。（※「〇〇の曲で」「〇〇のキャラで」「〇〇の用途で」のように具体的にすること）
        - 選択肢: 具体的な名前（曲名、キャラ名、商品名、用途など）を5〜10個列挙。「その他」も必須。
        - **【超重要：ハルシネーション（嘘）の完全禁止】選択肢（items）は、必ず提供された「Wikipediaの事実データ」のテキスト内に、一言一句違わず記載されている確実な作品名・楽曲名のみを使用すること。AIの記憶や連想で勝手に作品名を作り出すことは絶対に許されない。**
        - **【全選択肢への言及】生成した「全ての選択肢（items）」に対して、必ず100文字程度で解説文（text）を書き下ろすこと。「同上」「省略」や空欄（""）は絶対に許されない。1つでも解説文が欠落している場合、記事として失敗とみなす。**
        """
    elif a_type == "RATE":
        type_instruction = f"""
        **【頻度・実態型】**
        - タイトル: 「{title_idea}」を採用せよ。
        - 選択肢: **具体的な数を段階的にいれてください**（例: 毎日 / 週2〜3回 / 週1回 / 月1回 / 行かない）。
        - **解説文(text)のルール**: **生成した「全ての選択肢」に対して、「その選択肢を選ぶ人の心理・生活スタイル」を100文字程度で書くこと。**
        """

    prompt = f"""
    トレンドテーマ「{theme}」について、読者参加型の「投票記事」を作成してください。
    
    【前提情報】
    元のニュース: {original_headline}
    ★トレンドの背景（最新ニュース）: {news_data}
    （※記事の導入では、この最新ニュースの内容に触れて「いま〇〇が話題ですが〜」とつなげてください）

    {fact_instruction}
    
    【★構成・解説文ルール（絶対遵守）】
    {type_instruction}

    【コメント作成ルール】
    {persona_instruction}
    
    【投票数】
    * ランダムな数値（例: 487, 123）にすること。

    【★JSON形式（絶対ルール）】
    ※ comments内の "name" フィールドは、AIのペルソナ（キャラ名など）に関わらず、全て "匿名" に統一すること。
    {{
        "title": "タイトル",
        "slug": "slug",
        "is_product": false,
        "tags": ["タグ"],
        "category_slug": "{cat}", 
        "h2_title": "導入H2",
        "h2_text": "導入文(300〜400字程度。要点だけを短くまとめること。)",
        "comparison_table": "| A | B |\\n|---|---|", 
        "fact_h3": "豆知識H3",
        "info_fact": "豆知識",
        "items": [ 
            {{ "name": "選択肢1", "text": "解説", "votes": 234 }}, 
            {{ "name": "選択肢2", "text": "解説", "votes": 87 }}
        ],
        "comments": [ 
            {{ "name": "匿名", "text": "コメント" }}
        ],
        "infos": [ {{ "h3": "補足H3", "text": "補足" }} ]
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

def search_wiki_correct_title(name):
    api_url = "https://ja.wikipedia.org/w/api.php"
    params = {"action": "query", "list": "search", "srsearch": name, "format": "json"}
    try:
        r = requests.get(api_url, params=params, timeout=5)
        data = r.json()
        if data.get('query', {}).get('search'): return data['query']['search'][0]['title']
    except: pass
    return None

def scrape_wiki_image(name, retry=True):
    target_name = name
    url = f"https://ja.wikipedia.org/wiki/{quote(target_name)}"
    headers = {'User-Agent': USER_AGENT}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 404 and retry:
            corrected = search_wiki_correct_title(name)
            if corrected and corrected != name: return scrape_wiki_image(corrected, retry=False)
        if res.status_code != 200: return None
        soup = BeautifulSoup(res.content, "html.parser")
        images = soup.select("table.infobox img")
        if not images: images = soup.select(".thumbimage")
        valid_src = None
        if images:
            for img in images:
                src = img.get("src")
                if not src: continue
                check_src = src.lower()
                if any(x in check_src for x in ["flag_of", ".svg", "logo", "icon", "padlock"]): continue 
                valid_src = src
                break 
        if not valid_src and retry:
            corrected = search_wiki_correct_title(name)
            if corrected and corrected != name: return scrape_wiki_image(corrected, retry=False)
        if not valid_src: return None
        if valid_src.startswith("//"): valid_src = "https:" + valid_src
        elif valid_src.startswith("/"): valid_src = "https://ja.wikipedia.org" + valid_src
        if "/thumb/" in valid_src:
            try:
                parts = valid_src.split("/thumb/")
                base = parts[0]
                filename = parts[1].rsplit('/', 1)[0]
                original = f"{base}/{filename}"
                if any(original.lower().endswith(x) for x in ['.jpg','.jpeg','.png','.webp']): valid_src = original
            except: pass
        return valid_src
    except: return None

def search_web_image(query):
    keyword = f"{query}"
    temp_dir = 'temp_img_dl'
    if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    try:
        crawler = BingImageCrawler(storage={'root_dir': temp_dir}, log_level='ERROR')
        crawler.crawl(keyword=keyword, max_num=1, overwrite=True)
        files_in_dir = glob.glob(os.path.join(temp_dir, '*'))
        if files_in_dir:
            with open(files_in_dir[0], 'rb') as f: return f.read()
    except: pass
    return None

def fetch_image_data(name):
    wiki_url = scrape_wiki_image(name)
    if wiki_url:
        try:
            r = requests.get(wiki_url, headers={'User-Agent': USER_AGENT}, timeout=10)
            if r.status_code == 200: return r.content
        except: pass
    return None

def process_image_binary(img_data):
    if not img_data: return None
    try:
        img = Image.open(io.BytesIO(img_data)).convert('RGB')
        img.thumbnail(TARGET_SIZE, Image.Resampling.LANCZOS)
        bg = Image.new('RGB', TARGET_SIZE, (255, 255, 255))
        bg.paste(img, ((TARGET_SIZE[0]-img.width)//2, (TARGET_SIZE[1]-img.height)//2))
        output = io.BytesIO()
        bg.save(output, format='JPEG', quality=95)
        return output.getvalue()
    except: return None

def upload_image_to_wp(img_binary, filename):
    url = f"{WP_URL}/wp-json/wp/v2/media"
    headers = get_auth_header()
    headers['Content-Disposition'] = f'attachment; filename="{filename}.jpg"'
    headers['Content-Type'] = 'image/jpeg'
    try:
        res = requests.post(url, headers=headers, data=img_binary, timeout=30)
        if res.status_code == 201: return res.json().get('source_url'), res.json().get('id')
    except: pass
    return "", None

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
print("\n🔥 完全自動トレンド記事作成 (V69: AI思考・メガ進化版) 開始...")

success_count = 0
existing_titles = get_all_existing_titles()
selected_items = select_best_topics(get_raw_trends(), existing_titles)

if not selected_items:
    print("❌ ネタ切れ")
else:
    for item in selected_items:
        if success_count >= ARTICLES_TO_CREATE:
            print(f"🎉 目標記事数（{ARTICLES_TO_CREATE}記事）に達したため、処理を終了します。")
            break
            
        print(f"\n🚀 候補: {item['headline']}")
        
        # STEP1 - 純粋な「核KW」だけを抽出する
        core_kw = extract_pure_keyword(item['headline'], item['keyword'])
            
        # STEP2 - Wiki APIで「普遍的な事実」をチェック（IPブロック回避）
        fact_check_data = perform_fact_check(core_kw)

        # STEP3 - Google News RSSで「今のトレンド背景」を調査
        news_data = perform_news_research(core_kw)

        # STEP4 - 全ての情報を統合してメガ思考
        analysis_data = analyze_and_extract_core(core_kw, item['headline'], fact_check_data, news_data)
        
        if analysis_data['article_type'] == "SKIP":
            print(" -> ⚠️ 投票化が難しいためスキップします。")
            continue

        # 【究極の自動変換】嘘の作品名が出るのを防ぐため「好き・嫌い」へ変換
        if analysis_data['article_type'] == "WHICH_BEST" and fact_check_data == "SEARCH_FAILED":
            print(f" -> ⚠️検索失敗: 嘘を防ぐため「{analysis_data['core_keyword']}」の好感度調査（好き/嫌い）に変更します。")
            analysis_data['article_type'] = "LIKE_DISLIKE"
            analysis_data['proposed_title'] = f"{analysis_data['core_keyword']}、好き？普通？苦手？"
            analysis_data['suggested_category'] = "people"

        data = generate_article_content(analysis_data, item['headline'], fact_check_data, news_data)
        if not data: continue
        
        if data['title'] in existing_titles:
            print(" -> タイトル重複のためSKIP")
            continue

        print(f"📝 作成決定: {data['title']}")
        
        featured_media_id = DEFAULT_IMAGE_ID
        is_people_2choices = (data.get('category_slug') == 'people' and len(data['items']) == 2)
        if is_people_2choices:
            print(f"    📸 People/2択記事: アイキャッチ用に「{analysis_data['core_keyword']}」の画像を探索中...", end="")
            person_img_data = fetch_image_data(analysis_data['core_keyword'])
            if not person_img_data:
                person_img_data = search_web_image(f"{analysis_data['core_keyword']} wiki")
            if person_img_data:
                bin_data = process_image_binary(person_img_data)
                if bin_data:
                    _, featured_media_id = upload_image_to_wp(bin_data, f"featured_{int(time.time())}")
                    print(" [取得・設定完了]")
            if not person_img_data:
                print(" [画像なし]")

        item_images = {}
        for item_choice in data['items']:
            name = item_choice['name']
            if name in ["好き", "嫌い", "その他", "行かない", "週1回", "毎日", "仕事", "遊び", "アリ", "ナシ", "普通", "興味ない", "見る", "見ない", "苦手"]: continue
            img_data = fetch_image_data(name)
            if img_data: item_images[name] = img_data
        
        items_str = []
        meta = {
            'wiki_h2_title': data.get('h2_title',''),
            'wiki_h2_text': data.get('h2_text',''),
            'wiki_fact_h3': data.get('fact_h3',''),
            'wiki_info_fact': data.get('info_fact',''),
            'post_views_count': '0'
        }
        if data.get('comparison_table'): meta['wiki_comparison_table'] = data['comparison_table']

        for i, item_choice in enumerate(data['items']):
            idx = i + 1
            if idx > 10: break
            name = item_choice['name']
            meta[f'wiki_info{idx}_h3'] = name
            meta[f'wiki_info_{idx}'] = item_choice.get('text', '')
            
            img_url = ""
            if name in item_images:
                bin_data = process_image_binary(item_images[name])
                if bin_data:
                    img_url, _ = upload_image_to_wp(bin_data, f"img_{int(time.time())}_{idx}")
                    time.sleep(1)
            
            meta[f'wiki_item_name_{idx}'] = name
            meta[f'wiki_item_img_{idx}'] = img_url
            
            votes = item_choice.get('votes', 0)
            if votes % 10 == 0: votes += random.randint(1, 9)
            meta[f'vote_multi_idx_{i}'] = str(votes)
            
            if len(data['items']) == 2:
                k = 'vote_count_a' if i == 0 else 'vote_count_b'
                meta[k] = str(votes)
            
            items_str.append(f"{name}|{img_url}" if img_url else name)

        cat_id = get_term_id(data.get('category_slug', 'contents'))
        
        if len(items_str) == 2:
            sc = f'[vote_bar name_a="{items_str[0]}" name_b="{items_str[1]}"]\n\n[vote_summary name_a="{items_str[0]}" name_b="{items_str[1]}"]'
        else:
            sc = f'[vote_bar items="{", ".join(items_str)}"]\n\n[vote_summary items="{", ".join(items_str)}"]'
        
        content = sc
        if data.get('is_product'):
            content += f"\n\n{AFFILIATE_SHORTCODE.format(word=analysis_data['core_keyword'])}"

        now = datetime.now()
        post_time = now - timedelta(hours=1)
        
        post_data = {
            'title': data['title'],
            'content': content,
            'status': 'publish',
            'date': post_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'categories': [cat_id],
            'slug': data.get('slug') + '-' + str(int(time.time())),
            'meta': meta
        }
        
        if featured_media_id and featured_media_id > 0:
            post_data['featured_media'] = featured_media_id

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
        
        time.sleep(5)

print(f"\n🎉 完了 ({success_count}記事)")
