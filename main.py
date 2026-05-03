# -*- coding: utf-8 -*-
"""
【トレンド自動記事作成 V97】415修正・スレッド返信・関連性強化版
修正点:
1. 415エラー修正: POSTリクエストにContent-Type: application/jsonを明示
2. スレッド返信実装: >>数字 を検出してparent IDを指定
3. 返信の関連性強化: プロンプト改善で返信元に関連した内容を生成
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
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF")

if not WP_APP_PASS or not GEMINI_API_KEY:
    print("❌ エラー: 環境変数（シークレット）が設定されていません。")
    sys.exit(1)

MODEL_NAME = "gemma-3-27b-it"
ARTICLES_TO_CREATE = 2

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
HEADERS = {'User-Agent': USER_AGENT}

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

# ==========================================
# ★ ヘルパー関数
# ==========================================

def get_auth_header():
    """★修正: Content-Typeを明示的に追加（415エラー対策）"""
    creds = f"{WP_USER.strip()}:{WP_APP_PASS.strip()}"
    token = base64.b64encode(creds.encode()).decode()
    return {
        'Authorization': f'Basic {token}',
        'Content-Type': 'application/json'
    }

def get_auth_header_get():
    """GETリクエスト用（Content-Typeなし）"""
    creds = f"{WP_USER.strip()}:{WP_APP_PASS.strip()}"
    token = base64.b64encode(creds.encode()).decode()
    return {'Authorization': f'Basic {token}'}

def clean_title(text):
    if not text: return ""
    return re.sub(r'[^\w\s]', '', text).replace(' ', '').replace('　', '')

def get_all_existing_titles():
    print("📚 過去記事を全件チェック中...", end="")
    titles = []
    page = 1
    while True:
        try:
            url = f"{WP_URL}/wp-json/wp/v2/posts?per_page=100&page={page}&fields=title"
            res = requests.get(url, headers=get_auth_header_get(), timeout=10)
            if res.status_code != 200: break
            posts = res.json()
            if not posts: break
            for p in posts:
                titles.append(clean_title(p['title']['rendered']))
            if len(posts) < 100: break
            page += 1
        except: break
    print(f" -> 合計 {len(titles)} 件取得完了")
    return titles

def send_discord_notification(post_id, title, post_url):
    if not DISCORD_WEBHOOK_URL:
        return
    edit_url = f"{WP_URL.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
    payload = {
        "content": f"🔥 **AI編集長が記事を投稿しました！**\n\n**【タイトル】**\n{title}\n\n**【公開URL】**\n{post_url}\n\n**【編集】**\n{edit_url}"
    }
    try:
        d_res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        d_res.raise_for_status()
        print(" 🔔 Discord通知送信完了")
    except Exception as e:
        print(f" ⚠️ Discord通知失敗: {e}")

# ==========================================
# ★ トレンド収集＆分析
# ==========================================

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
                if title: items.append((title, headline, "Googleトレンド"))
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

    for source_name, url in rss_sources:
        print(f"    👉 {source_name}: ", end="")
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
                    raw_data.append((simple_title, full_title, source_name))
                    count += 1
                if count >= 8: break
            print(f"OK ({count}件)")
        else:
            print("取得失敗")

    cleaned_data = []
    seen = set()
    for kw, headline, source in raw_data:
        kw = kw.strip()
        if not kw: continue
        if kw in seen: continue
        is_ng = False
        for ng in NG_KEYWORDS:
            if ng in kw or ng in headline:
                is_ng = True; break
        if not is_ng:
            cleaned_data.append({'keyword': kw, 'headline': headline, 'source': source})
            seen.add(kw)

    print(f" -> 有効候補: {len(cleaned_data)}件")
    return cleaned_data

def select_best_topics(candidates):
    if not candidates: return []
    print("🤔 AI編集長が厳選中...", end="")

    candidates_str = "\n".join([f"- {c['keyword']} ({c['source']}): {c['headline']}" for c in candidates[:80]])

    prompt = f"""
    Webメディア編集長として、以下のニュースリストを**「読者が熱狂的に投票したくなる順」にランキング化**し、上位10個を選んでください。

    【ニュースリスト】
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
    data = { "contents": [{"parts": [{"text": prompt}]}], "safetySettings": SAFETY_SETTINGS }

    final_selection = []
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30)
        if res.status_code == 200:
            text = res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            selected_keywords = [x.strip() for x in re.split(r'[,\n、]', text) if x.strip()]

            for kw in selected_keywords:
                for item in candidates:
                    if (item['keyword'] in kw) or (kw in item['keyword']):
                        if item not in final_selection:
                            final_selection.append(item)
                        break
    except: pass

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
    data = { "contents": [{"parts": [{"text": prompt}]}], "safetySettings": SAFETY_SETTINGS }
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
    print(f"    🕵️‍♂️ ファクトチェック中...", end="")
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
        fact_text = f"【「{pure_keyword}」に関するWikipediaの事実データ】\n{extract[:4000]}"
        print(" [取得完了]")
        return fact_text
    except:
        print(" [APIエラー]")
        return "SEARCH_FAILED"

def perform_news_research(pure_keyword):
    print(f"    📰 背景調査中...", end="")
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

def analyze_and_extract_core(pure_keyword, headline, fact_check_data, news_data, source_type):
    print(f"    🧠 AI編集長が企画を考案中...", end="")
    ai_fact_input = fact_check_data if fact_check_data != "SEARCH_FAILED" else "Wiki情報なし"

    prompt = f"""
    あなたは凄腕のWeb編集者です。
    トレンドの「文脈」と「事実（Wiki）」を読み解き、一番盛り上がる投票企画を立案してください。

    【★最重要：柔軟な企画レシピ（状況に応じて使い分けろ）】

    1. **🎮 ゲームが話題の場合 (ソース: {source_type})**
       - **WHICH_BEST**: 「好きなNPCは？」「最強の武器は？」「倒せないボスは？」
       - ※Wikiにリスト（登場人物・武器等）がある場合のみ選択。なければ『好き嫌い（2択）』へ。

    2. **🎤 歌手・アーティストが話題の場合**
       - **WHICH_BEST**: 「一番好きな曲は？」「最高傑作のアルバムは？」
       - ※Wikiにディスコグラフィがある場合のみ選択。

    3. **⚡ キャラクター・人物が話題の場合**
       - **パターンA**: ニュースで「必殺技」や「セリフ」が話題なら「かっこいい？微妙？（**LIKE_DISLIKE**）」
       - **パターンB**: 作品全体の人気投票へ広げる「推しキャラは誰？（**WHICH_BEST**）」
       - **パターンC**: 単純にそのキャラの好感度「好き？嫌い？（**LIKE_DISLIKE**）」

    4. **🎬 映画・イベントが話題の場合**
       - **WHICH_BEST**: 「どのシリーズが好き？」「注目選手は？」
       - **LIKE_DISLIKE**: 「面白かった？つまらなかった？」

    【★鉄の掟】
    - **捏造禁止**: WHICH_BESTの選択肢は、必ずWikiのデータ内にある固有名詞を使うこと。
    - **4PGP対策**: ソースがゲーム系（4Gamer等）なら、セキュリティソフトと混同せずゲームとして扱え。

    【入力情報】
    KW: {pure_keyword} (ソース: {source_type})
    見出し: {headline}
    ★トレンド背景: {news_data}
    ★Wikiデータ: {ai_fact_input}

    【出力形式(JSON)】
    {{
        "core_keyword": "{pure_keyword}",
        "article_type": "LIKE_DISLIKE" or "WHICH_BEST" or "SKIP",
        "proposed_title": "一番盛り上がるタイトル",
        "reason": "企画の意図",
        "suggested_category": "contents" または "people"
    }}
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = { "contents": [{"parts": [{"text": prompt}]}], "safetySettings": SAFETY_SETTINGS }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30)
        if res.status_code == 200:
            text = res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            text = text.replace('```json', '').replace('```', '').strip()
            start = text.find('{'); end = text.rfind('}') + 1
            analysis = json.loads(text[start:end])
            print(f" -> [{analysis['article_type']}] {analysis['proposed_title']}")
            print(f"      👀 意図: {analysis['reason']}")
            return analysis
    except: pass
    print(" -> 分析失敗")
    return {"core_keyword": pure_keyword, "article_type": "SKIP", "proposed_title": "", "reason": "", "suggested_category": "contents"}

def get_natural_personas(count):
    """★修正: 返信の関連性を強化したプロンプト"""
    return f"""
    以下のネットユーザーになりきって、掲示板のような自然なコメントを【必ず {count} 個】生成してください。

    【★コメントの鉄則（絶対遵守）】
    1. 「【選択肢名】」のような機械的な前置きは**絶対に書かない**こと。
    2. 「〇〇に一票」「私は△△を選びます」のような説明口調は避ける。
    3. 「やっぱこれだわ」「いや、普通に考えてそれはないだろ」「設定的にこっちが正解なんだよな」といった、感情的で生の声を意識すること。
    4. {count}件のうち2〜3件は >>数字 の形で特定のコメントへの返信を含めること。
    5. 返信する場合は**必ず返信元のコメント内容を踏まえた関連性のある内容**にすること。
       - 例: >>2 が「キャラAが最強」と言っていたら、>>3 は「いやキャラAはボス戦では弱いだろ」のように具体的に反応する。
       - 単なる「わかる」「それな」だけでなく、賛成・反論・補足を明確にすること。
    6. >>数字 の数字は必ず1から始まる連番（実際に存在するコメント番号）を使うこと。
    """

def generate_article_content(analysis_data, original_headline, fact_check_data, news_data):
    theme = analysis_data['core_keyword']
    a_type = analysis_data['article_type']
    title_idea = analysis_data['proposed_title']
    cat = analysis_data.get('suggested_category', 'contents')

    print(f"🤖 記事執筆中 ({theme})...", end="")

    target_comment_count = random.randint(10, 20)
    persona_instruction = get_natural_personas(target_comment_count)

    fact_instruction = ""
    if fact_check_data != "SEARCH_FAILED" and fact_check_data != "NO_SEARCH_MODULE":
        fact_instruction = f"""
    【Wiki情報（ここから選択肢を作れ）】
    {fact_check_data}
        """

    type_instruction = ""
    if a_type == "LIKE_DISLIKE":
        type_instruction = f"""
        **【対決型（2択）】**
        - タイトル: 「{title_idea}」
        - 選択肢: 2〜3個（例: 好き/嫌い/普通、アリ/ナシ）
        - **解説文(text)**: 各選択肢を選ぶ理由を**200〜300文字程度**で熱く語ること。
        """
    elif a_type == "WHICH_BEST":
        type_instruction = f"""
        **【多選択型（推し投票）】**
        - タイトル: 「{title_idea}」
        - **選択肢のルール**: 絶対にWiki情報にある固有名詞のみ使うこと。5〜10個列挙。「その他」も必須。
        - **解説文(text)**: その選択肢の魅力や背景を**200〜300文字程度**で深掘り解説すること。
        """

    prompt = f"""
    トレンドテーマ「{theme}」について、読者参加型の「投票記事」を作成してください。

    【前提情報】
    ニュース: {original_headline}
    背景: {news_data}
    {fact_instruction}

    【★構成ルール】
    {type_instruction}

    【コメント生成指示】
    {persona_instruction}

    【★JSON形式（slugは英語小文字とハイフンのみ。数字禁止）】
    {{
        "title": "タイトル",
        "slug": "short-english-slug",
        "tags": ["タグ"],
        "category_slug": "{cat}",
        "h2_title": "導入H2見出し",
        "h2_text": "記事冒頭の導入文（400〜500文字程度）",
        "fact_h3": "豆知識の見出し",
        "info_fact": "豆知識の本文（300〜400文字程度）",
        "items": [
            {{ "name": "選択肢1", "text": "濃厚な解説(200文字以上)", "votes": 0 }},
            {{ "name": "選択肢2", "text": "濃厚な解説(200文字以上)", "votes": 0 }}
        ],
        "comments": [
            {{ "name": "匿名", "text": "コメント本文" }},
            {{ "name": "名無し", "text": ">>1 返信元の内容を踏まえた具体的な反応" }}
        ]
    }}
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {'Content-Type': 'application/json'}
    data = { "contents": [{"parts": [{"text": prompt}]}], "safetySettings": SAFETY_SETTINGS }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=120)
        if res.status_code != 200: return None
        text = res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        text = text.replace('```json', '').replace('```', '').strip()
        start = text.find('{'); end = text.rfind('}') + 1
        data_json = json.loads(text[start:end])
        print(f" -> 完了 (コメント{len(data_json.get('comments', []))}件生成)")
        return data_json
    except:
        print(" -> 生成エラー")
        return None

def get_term_id(slug):
    try:
        res = requests.get(f"{WP_URL}/wp-json/wp/v2/categories?slug={slug}", headers=get_auth_header_get())
        if res.json(): return res.json()[0]['id']
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/categories", headers=get_auth_header(), json={'name':slug, 'slug':slug})
        return res.json()['id']
    except: return 1

def post_comments_with_threads(pid, comments, post_time, now):
    """★新規: スレッド返信対応のコメント投稿関数"""
    comment_id_map = {}  # {投稿順番号(1始まり): WPコメントID}

    print(f"💬 コメント投稿中({len(comments)}件)...", end="")

    for i, com in enumerate(comments):
        text = com['text']
        parent_id = 0

        # >>数字 を検出して親コメントIDを特定
        match = re.search(r'>>(\d+)', text)
        if match:
            ref_num = int(match.group(1))
            parent_id = comment_id_map.get(ref_num, 0)

        c_time = post_time + timedelta(minutes=random.randint(5, 55))
        if c_time > now: c_time = now

        try:
            payload = {
                'post': pid,
                'author_name': com['name'],
                'content': text,
                'status': 'approve',
                'date': c_time.strftime('%Y-%m-%dT%H:%M:%S'),
                'parent': parent_id
            }
            res = requests.post(
                f"{WP_URL}/wp-json/wp/v2/comments",
                headers=get_auth_header(),
                json=payload,
                timeout=10
            )
            if res.status_code == 201:
                wp_id = res.json()['id']
                comment_id_map[i + 1] = wp_id
        except:
            pass

        time.sleep(0.3)

    print(f" 完了 (スレッド構造: {len(comment_id_map)}件成功)")

# ==========================================
# メイン処理
# ==========================================
print("\n🔥 完全自動トレンド記事作成 (V97: 415修正・スレッド返信・関連性強化) 開始...")

success_count = 0
processed_core_keywords = set()

existing_titles = get_all_existing_titles()
selected_items = select_best_topics(get_raw_trends())

if not selected_items:
    print("❌ ネタ切れ")
else:
    for item in selected_items:
        if success_count >= ARTICLES_TO_CREATE:
            print(f"🎉 目標記事数（{ARTICLES_TO_CREATE}記事）に達したため、処理を終了します。")
            break

        print(f"\n🚀 候補: {item['headline']}")

        core_kw = extract_pure_keyword(item['headline'], item['keyword'])

        if core_kw == "EXTRACT_FAILED":
            print(" -> ⚠️ キーワード抽出失敗のためスキップ")
            continue

        if core_kw in processed_core_keywords:
            print(f" -> 🚫 重複テーマ（{core_kw}）のためスキップ")
            continue
        processed_core_keywords.add(core_kw)

        fact_check_data = perform_fact_check(core_kw)
        news_data = perform_news_research(core_kw)
        source_type = item.get('source', '不明')
        analysis_data = analyze_and_extract_core(core_kw, item['headline'], fact_check_data, news_data, source_type)

        if analysis_data['article_type'] == "SKIP":
            print(" -> ⚠️ 投票化が難しいためスキップします。")
            continue

        if analysis_data['article_type'] == "WHICH_BEST" and fact_check_data == "SEARCH_FAILED":
            print(f" -> ⚠️情報不足: 好き嫌い形式に変更します。")
            analysis_data['article_type'] = "LIKE_DISLIKE"
            analysis_data['proposed_title'] = f"【{analysis_data['core_keyword']}】好き？普通？苦手？"
            analysis_data['suggested_category'] = "people"

        print("☕ 制限回避のため10秒休憩中...", end="")
        time.sleep(10)
        print(" 再開")

        data = generate_article_content(analysis_data, item['headline'], fact_check_data, news_data)
        if not data: continue

        if analysis_data['article_type'] == "WHICH_BEST" and len(data.get('items', [])) < 2:
            print(" -> ⚠️選択肢生成失敗: 好き嫌いに差し替えます。")
            analysis_data['article_type'] = "LIKE_DISLIKE"
            data = generate_article_content(analysis_data, item['headline'], fact_check_data, news_data)
            if not data: continue

        if clean_title(data['title']) in existing_titles:
            print(f" -> 🚫 タイトル重複のためSKIP: {data['title']}")
            continue

        print(f"📝 作成決定: {data['title']}")

        items_str = []
        meta = {
            'post_views_count': '0',
            'wiki_h2_title': data.get('h2_title', ''),
            'wiki_h2_text': data.get('h2_text', ''),
            'wiki_fact_h3': data.get('fact_h3', ''),
            'wiki_info_fact': data.get('info_fact', '')
        }

        vote_mode = random.choice(['接戦', '圧倒的', '中程度', '僅差'])
        print(f"   📊 投票演出モード: {vote_mode}")

        for i, item_choice in enumerate(data['items']):
            idx = i + 1
            if idx > 10: break
            name = item_choice['name']

            meta[f'wiki_info{idx}_h3'] = name
            meta[f'wiki_info_{idx}'] = item_choice.get('text', '')
            meta[f'wiki_item_name_{idx}'] = name
            meta[f'wiki_item_img_{idx}'] = ""

            if vote_mode == '接戦':
                votes = random.randint(180, 230)
            elif vote_mode == '圧倒的':
                votes = random.randint(450, 700) if i == 0 else random.randint(10, 40)
            elif vote_mode == '僅差':
                votes = random.randint(300, 350) if i == 0 else random.randint(250, 290)
            else:
                votes = random.randint(350, 500) if i == 0 else random.randint(100, 200)

            if votes % 10 == 0: votes += random.randint(1, 9)

            meta[f'vote_multi_idx_{i}'] = str(votes)

            if len(data['items']) == 2:
                k = 'vote_count_a' if i == 0 else 'vote_count_b'
                meta[k] = str(votes)

            items_str.append(name)

        cat_id = get_term_id(data.get('category_slug', 'contents'))

        if len(items_str) == 2:
            sc = f'[vote_bar name_a="{items_str[0]}" name_b="{items_str[1]}"]\n\n[vote_summary name_a="{items_str[0]}" name_b="{items_str[1]}"]'
        else:
            sc = f'[vote_bar items="{", ".join(items_str)}"]\n\n[vote_summary items="{", ".join(items_str)}"]'

        now = datetime.now()
        post_time = now - timedelta(hours=1)
        clean_slug = data.get('slug', 'post')

        post_data = {
            'title': data['title'],
            'content': sc,
            'status': 'publish',
            'date': post_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'categories': [cat_id],
            'slug': clean_slug,
            'meta': meta
        }

        try:
            res = requests.post(
                f"{WP_URL}/wp-json/wp/v2/posts",
                headers=get_auth_header(),
                json=post_data,
                timeout=60
            )
            if res.status_code == 201:
                res_data = res.json()
                pid = res_data['id']
                post_link = res_data.get('link')
                print(f"✅ 投稿完了 (ID:{pid})")

                # ★新規: スレッド返信対応コメント投稿
                post_comments_with_threads(pid, data.get('comments', []), post_time, now)

                send_discord_notification(pid, data['title'], post_link)

                success_count += 1
                existing_titles.append(clean_title(data['title']))
            else:
                print(f"❌ WP投稿エラー ({res.status_code}): {res.text[:200]}")
        except Exception as e:
            print(f"❌ 投稿エラー: {e}")

        print("☕ 制限回避のため65秒休憩中...")
        time.sleep(65)

print(f"\n🎉 完了 ({success_count}記事)")
