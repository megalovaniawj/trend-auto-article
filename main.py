# -*- coding: utf-8 -*-
# V104: gemini-2.5-flash-lite対応版（V98プロンプト移植版）

import os
import sys
import warnings
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

WP_URL = "https://docchiyo.com"
WP_USER = "bear"
WP_APP_PASS = os.environ.get("WP_APP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF")

if not WP_APP_PASS or not GEMINI_API_KEY:
    print("Error: env not set")
    sys.exit(1)

MODEL_NAME = "gemini-2.5-flash-lite"
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

def get_auth_header():
    creds = WP_USER.strip() + ":" + WP_APP_PASS.strip()
    token = base64.b64encode(creds.encode()).decode()
    return {'Authorization': 'Basic ' + token, 'Content-Type': 'application/json'}

def get_auth_header_get():
    creds = WP_USER.strip() + ":" + WP_APP_PASS.strip()
    token = base64.b64encode(creds.encode()).decode()
    return {'Authorization': 'Basic ' + token}

def clean_title(text):
    if not text:
        return ""
    return re.sub(r'[^\w\s]', '', text).replace(' ', '').replace('\u3000', '')

def get_all_existing_titles():
    print("📚 過去記事を全件チェック中...", end="")
    titles = []
    page = 1
    while True:
        try:
            url = WP_URL + "/wp-json/wp/v2/posts?per_page=100&page=" + str(page) + "&fields=title"
            res = requests.get(url, headers=get_auth_header_get(), timeout=10)
            if res.status_code != 200:
                break
            posts = res.json()
            if not posts:
                break
            for p in posts:
                titles.append(clean_title(p['title']['rendered']))
            if len(posts) < 100:
                break
            page += 1
        except:
            break
    print(" -> 合計 " + str(len(titles)) + " 件取得完了")
    return titles

def send_discord_notification(post_id, title, post_url):
    if not DISCORD_WEBHOOK_URL:
        return
    edit_url = WP_URL.rstrip('/') + "/wp-admin/post.php?post=" + str(post_id) + "&action=edit"
    msg = "🔥 **AI編集長が記事を投稿しました！**\n\n**タイトル**\n" + title + "\n\n**URL**\n" + post_url + "\n\n**編集**\n" + edit_url
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=10)
        print(" 🔔 Discord通知送信完了")
    except Exception as e:
        print(" ⚠️ Discord通知失敗: " + str(e))

def call_gemini(prompt, timeout=60):
    url = "https://generativelanguage.googleapis.com/v1beta/models/" + MODEL_NAME + ":generateContent?key=" + GEMINI_API_KEY.strip()
    headers = {'Content-Type': 'application/json'}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "safetySettings": SAFETY_SETTINGS,
        "generationConfig": {
            "maxOutputTokens": 8192,
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }
    for attempt in range(3):
        try:
            res = requests.post(url, headers=headers, json=data, timeout=timeout)
            if res.status_code == 200:
                return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            elif res.status_code in [429, 503, 500]:
                wait = (attempt + 1) * 30
                print(" [" + str(res.status_code) + " リトライ" + str(attempt + 1) + "/3 " + str(wait) + "秒待機]", end="")
                time.sleep(wait)
            else:
                print(" [APIエラー:" + str(res.status_code) + "]")
                return None
        except Exception as e:
            print(" [例外:" + str(e) + "]")
            if attempt < 2:
                time.sleep(20)
    return None

def parse_json_from_text(text):
    try:
        text = text.replace('```json', '').replace('```', '').strip()
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end > 0:
            candidate = json.loads(text[start:end])
            title = candidate.get('title', '')
            if title in ['タイトル', 'title', '...', '']:
                return None
            return candidate
    except:
        pass
    return None

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
                if not title and story.get('entityNames'):
                    title = story['entityNames'][0]
                if title:
                    items.append((title, headline, "Googleトレンド"))
            print("OK (" + str(len(items)) + "件)")
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
        print("    👉 " + source_name + ": ", end="")
        entries = []
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.content)
                entries = feed.entries
        except:
            pass
        if not entries:
            try:
                feed = feedparser.parse(url)
                entries = feed.entries
            except:
                pass
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
                if count >= 8:
                    break
            print("OK (" + str(count) + "件)")
        else:
            print("取得失敗")

    cleaned_data = []
    seen = set()
    for kw, headline, source in raw_data:
        kw = kw.strip()
        if not kw or kw in seen:
            continue
        is_ng = any(ng in kw or ng in headline for ng in NG_KEYWORDS)
        if not is_ng:
            cleaned_data.append({'keyword': kw, 'headline': headline, 'source': source})
            seen.add(kw)

    print(" -> 有効候補: " + str(len(cleaned_data)) + "件")
    return cleaned_data

def select_best_topics(candidates):
    if not candidates:
        return []
    print("🤔 AI編集長が厳選中...", end="")

    candidates_str = "\n".join(["- " + c['keyword'] + " (" + c['source'] + "): " + c['headline'] for c in candidates[:80]])
    prompt = (
        "以下のニュースリストから、読者が熱狂的に投票したくなるものを10個選んでください。\n\n"
        "優先順位:\n"
        "1. アニメ・漫画・ゲームの具体的な新作・キャラ\n"
        "2. VTuber・YouTuberの話題\n"
        "3. チェーン店グルメ・商品\n"
        "4. アイドル・芸能（ゴシップ除く）\n\n"
        "除外: 事件、事故、政治、暗いニュース\n\n"
        "ニュースリスト:\n" + candidates_str + "\n\n"
        "選んだ10個のキーワードをカンマ区切りで答えてください。キーワードのみ、説明不要。"
    )

    text = call_gemini(prompt, timeout=30)
    final_selection = []
    if text:
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        kw_line = lines[-1] if lines else ""
        selected_keywords = [x.strip() for x in re.split(r'[,、]', kw_line) if x.strip()]
        for kw in selected_keywords:
            for item in candidates:
                if (item['keyword'] in kw) or (kw in item['keyword']):
                    if item not in final_selection:
                        final_selection.append(item)
                    break

    if len(final_selection) < ARTICLES_TO_CREATE:
        print("    ⚠️ AI選出不足(" + str(len(final_selection)) + "件)。不足分を自動補充します。")
        current_kws = [x['keyword'] for x in final_selection]
        for c in candidates:
            if c['keyword'] not in current_kws:
                final_selection.append(c)
                if len(final_selection) >= 10:
                    break

    print(" -> 👑 選抜: " + str([item['keyword'] for item in final_selection[:5]]) + "...")
    return final_selection

def extract_pure_keyword(headline, raw_keyword):
    print("    🧹 見出しから核KWを純粋抽出中...", end="")
    # 正規表現で「」『』から優先抽出
    matches = re.findall(r'[「『](.*?)[」』]', headline)
    for m in matches:
        m = m.strip()
        jp_chars = len(re.findall(r'[\u3040-\u9fff]', m))
        if m and len(m) <= 20 and jp_chars >= 1:
            print(" -> [" + m + "] (正規表現)")
            return m

    prompt = (
        "以下のニュース見出しを読んでください。\n\n"
        "見出し: " + headline + "\n\n"
        "この見出しに含まれるWikipediaで検索できる固有名詞（作品名・人名・サービス名）を1つだけ答えてください。\n"
        "説明不要。固有名詞のみ答えてください。"
    )
    text = call_gemini(prompt, timeout=20)
    if text:
        for line in text.split('\n'):
            line = line.strip()
            if ':' in line or '：' in line:
                line = re.split(r'[:：]', line)[-1].strip()
            line = re.sub(r'^[\*\-\#\>\d\.\s]+', '', line).strip()
            line = re.sub(r'[\(\)\[\]"\'\.]', '', line).strip()
            if len(line) > 30 or line.startswith('*') or 'Input' in line or 'Task' in line:
                continue
            english_ratio = len(re.findall(r'[a-zA-Z]', line)) / max(len(line), 1)
            if english_ratio > 0.5 and len(line) > 8:
                continue
            jp_chars = len(re.findall(r'[\u3040-\u9fff]', line))
            if line and len(line) <= 20 and jp_chars >= 1:
                print(" -> [" + line + "]")
                return line

    print(" -> 失敗")
    return "EXTRACT_FAILED"

def perform_fact_check(pure_keyword):
    print("    🕵️ ファクトチェック中...", end="")
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
        fact_text = "【「" + pure_keyword + "」に関するWikipediaの事実データ】\n" + extract[:4000]
        print(" [取得完了]")
        return fact_text
    except:
        print(" [APIエラー]")
        return "SEARCH_FAILED"

def perform_news_research(pure_keyword):
    print("    📰 背景調査中...", end="")
    url = "https://news.google.com/rss/search?q=" + quote(pure_keyword) + "&hl=ja&gl=JP&ceid=JP:ja"
    try:
        res = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=10)
        if res.status_code == 200:
            feed = feedparser.parse(res.content)
            if feed.entries:
                news_text = "【「" + pure_keyword + "」の最新ニュース（トレンド背景）】\n"
                print(" [調査完了]")
                for i, entry in enumerate(feed.entries[:3]):
                    title = re.sub(r' [-|–|:|：].*', '', entry.title).strip()
                    news_text += "・" + title + "\n"
                    print("      👉 記事" + str(i+1) + ": " + title)
                return news_text
    except:
        pass
    print(" [ニュースなし]")
    return "（直近のニュースは見つかりませんでした）"

def analyze_and_extract_core(pure_keyword, headline, fact_check_data, news_data, source_type):
    print("    🧠 AI編集長が企画を考案中...", end="")
    ai_fact_input = fact_check_data if fact_check_data != "SEARCH_FAILED" else "Wiki情報なし"

    prompt = (
        "あなたは凄腕のWeb編集者です。\n"
        "トレンドの「文脈」と「事実（Wiki）」を読み解き、一番盛り上がる投票企画を立案してください。\n\n"
        "【★最重要：柔軟な企画レシピ（状況に応じて使い分けろ）】\n\n"
        "1. ゲームが話題の場合 (ソース: " + source_type + ")\n"
        "   - WHICH_BEST: 「好きなNPCは？」「最強の武器は？」「倒せないボスは？」\n"
        "   - ※Wikiにリスト（登場人物・武器等）がある場合のみ選択。なければLIKE_DISLIKEへ。\n\n"
        "2. 歌手・アーティストが話題の場合\n"
        "   - WHICH_BEST: 「一番好きな曲は？」「最高傑作のアルバムは？」\n"
        "   - ※Wikiにディスコグラフィがある場合のみ選択。\n\n"
        "3. キャラクター・人物が話題の場合\n"
        "   - パターンA: 技・セリフが話題なら「かっこいい？微妙？（LIKE_DISLIKE）」\n"
        "   - パターンB: 作品全体の人気投票「推しキャラは誰？（WHICH_BEST）」\n"
        "   - パターンC: 好感度「好き？嫌い？（LIKE_DISLIKE）」\n\n"
        "4. 映画・イベントが話題の場合\n"
        "   - WHICH_BEST: 「どのシリーズが好き？」\n"
        "   - LIKE_DISLIKE: 「面白かった？つまらなかった？」\n\n"
        "【★鉄の掟】\n"
        "- 捏造禁止: WHICH_BESTの選択肢は必ずWiki情報にある固有名詞のみ使うこと。\n"
        "- ゲーム系ソースはセキュリティソフトと混同しないこと。\n\n"
        "【入力情報】\n"
        "KW: " + pure_keyword + " (ソース: " + source_type + ")\n"
        "見出し: " + headline + "\n"
        "トレンド背景: " + news_data + "\n"
        "Wikiデータ: " + ai_fact_input + "\n\n"
        "以下のJSON形式のみで答えてください（説明不要）:\n"
        "{\n"
        "    \"core_keyword\": \"" + pure_keyword + "\",\n"
        "    \"article_type\": \"LIKE_DISLIKE\" or \"WHICH_BEST\" or \"SKIP\",\n"
        "    \"proposed_title\": \"一番盛り上がるタイトル\",\n"
        "    \"reason\": \"企画の意図\",\n"
        "    \"suggested_category\": \"contents\" または \"people\"\n"
        "}"
    )

    text = call_gemini(prompt, timeout=45)
    if text:
        result = parse_json_from_text(text)
        if result and 'article_type' in result:
            print(" -> [" + result['article_type'] + "] " + result.get('proposed_title', ''))
            print("      👀 意図: " + result.get('reason', ''))
            return result

    print(" -> フォールバック")
    return {
        "core_keyword": pure_keyword,
        "article_type": "LIKE_DISLIKE",
        "proposed_title": "【" + pure_keyword + "】好き？嫌い？あなたはどっち？",
        "reason": "フォールバック",
        "suggested_category": "contents"
    }

def get_natural_personas(count):
    return (
        "以下のネットユーザーになりきって、掲示板のような自然なコメントを【必ず " + str(count) + " 個】生成してください。\n\n"
        "【★コメントの鉄則（絶対遵守）】\n"
        "1. 「【選択肢名】」のような機械的な前置きは絶対に書かない。\n"
        "2. 「〇〇に一票」「私は△△を選びます」のような説明口調は避ける。\n"
        "3. 「やっぱこれだわ」「いや普通に考えてそれはないだろ」のような感情的で生の声を意識する。\n"
        "4. " + str(count) + "件のうち2〜3件は >>数字 の形で特定のコメントへの返信を含めること。\n"
        "5. 返信する場合は必ず返信元のコメント内容を踏まえた関連性のある内容にすること。\n"
        "   賛成・反論・補足を明確にすること。\n"
        "6. ★重要: >>数字 の数字は、必ずそのコメント自身の番号より小さい数字にすること。\n"
        "   例: 3番目のコメントが返信する場合は >>1 または >>2 のみ使用可。\n"
        "   例: 7番目のコメントが返信する場合は >>1〜>>6 のみ使用可。\n"
        "   これにより、返信元が必ず先に投稿済みの状態になります。\n"
    )

def generate_article_content(analysis_data, original_headline, fact_check_data, news_data):
    theme = analysis_data['core_keyword']
    a_type = analysis_data['article_type']
    title_idea = analysis_data['proposed_title']
    cat = analysis_data.get('suggested_category', 'contents')

    print("🤖 記事執筆中 (" + theme + ")...", end="")

    target_comment_count = random.randint(10, 20)
    persona_instruction = get_natural_personas(target_comment_count)

    fact_instruction = ""
    if fact_check_data != "SEARCH_FAILED":
        fact_instruction = "\n【Wiki情報（ここから選択肢を作れ）】\n" + fact_check_data

    if a_type == "LIKE_DISLIKE":
        type_instruction = (
            "【対決型（2択）】\n"
            "- タイトル: 「" + title_idea + "」\n"
            "- 選択肢: 2〜3個（例: 好き/嫌い/普通、アリ/ナシ）\n"
            "- 解説文(text): 各選択肢を選ぶ理由を200〜300文字程度で熱く語ること。"
        )
    else:
        type_instruction = (
            "【多選択型（推し投票）】\n"
            "- タイトル: 「" + title_idea + "」\n"
            "- 選択肢のルール: 絶対にWiki情報にある固有名詞のみ使うこと。5〜10個列挙。「その他」も必須。\n"
            "- 解説文(text): その選択肢の魅力や背景を200〜300文字程度で深掘り解説すること。"
        )

    prompt = (
        "トレンドテーマ「" + theme + "」について、読者参加型の「投票記事」を作成してください。\n\n"
        "【前提情報】\n"
        "ニュース: " + original_headline + "\n"
        "背景: " + news_data + "\n"
        + fact_instruction + "\n\n"
        "【★構成ルール】\n"
        + type_instruction + "\n\n"
        "【コメント生成指示】\n"
        + persona_instruction + "\n\n"
        "【★JSON形式（slugは英語小文字とハイフンのみ）】\n"
        "{\n"
        "    \"title\": \"タイトル\",\n"
        "    \"slug\": \"short-english-slug\",\n"
        "    \"tags\": [\"タグ1\", \"タグ2\", \"タグ3\"],\n"
        "    \"category_slug\": \"" + cat + "\",\n"
        "    \"h2_title\": \"導入H2見出し\",\n"
        "    \"h2_text\": \"記事冒頭の導入文（400〜500文字程度）\",\n"
        "    \"fact_h3\": \"豆知識の見出し\",\n"
        "    \"info_fact\": \"豆知識の本文（300〜400文字程度）\",\n"
        "    \"items\": [\n"
        "        {\"name\": \"選択肢1\", \"text\": \"濃厚な解説(200文字以上)\", \"votes\": 0},\n"
        "        {\"name\": \"選択肢2\", \"text\": \"濃厚な解説(200文字以上)\", \"votes\": 0}\n"
        "    ],\n"
        "    \"comments\": [\n"
        "        {\"name\": \"匿名\", \"text\": \"コメント本文（返信なし）\"},\n"
        "        {\"name\": \"名無し\", \"text\": \"コメント本文（返信なし）\"},\n"
        "        {\"name\": \"ハンドルネーム\", \"text\": \">>1 返信元の内容を踏まえた具体的な反応\"}\n"
        "    ]\n"
        "}\n\n"
        "JSONのみ出力してください（説明文不要、コードブロック不要）:"
    )

    text = call_gemini(prompt, timeout=120)
    if text:
        result = parse_json_from_text(text)
        if result and result.get('title', '') not in ['タイトル', '', '...']:
            # itemsが存在しない場合はデフォルト値を設定
            if not result.get('items'):
                result['items'] = [
                    {"name": "好き", "text": theme + "が好きな理由を教えてください。", "votes": 0},
                    {"name": "嫌い", "text": theme + "が嫌いな理由を教えてください。", "votes": 0},
                    {"name": "普通", "text": "どちらでもない派の意見をどうぞ。", "votes": 0}
                ]
            if not result.get('comments'):
                result['comments'] = []
            print(" -> 完了 (コメント" + str(len(result.get('comments', []))) + "件)")
            return result
        else:
            print(" -> JSONパース失敗 RAW先頭200: " + text[:200])
    else:
        print(" -> API応答なし")

    return None

def get_term_id(slug):
    try:
        res = requests.get(WP_URL + "/wp-json/wp/v2/categories?slug=" + slug, headers=get_auth_header_get())
        if res.json():
            return res.json()[0]['id']
        res = requests.post(WP_URL + "/wp-json/wp/v2/categories", headers=get_auth_header(), json={'name': slug, 'slug': slug})
        return res.json()['id']
    except:
        return 1

def post_comments_with_threads(pid, comments, post_time, now):
    comment_id_map = {}
    print("💬 コメント投稿中(" + str(len(comments)) + "件)...", end="")

    for i, com in enumerate(comments):
        text = com['text']
        parent_id = 0
        match = re.search(r'>>(\d+)', text)
        if match:
            ref_num = int(match.group(1))
            parent_id = comment_id_map.get(ref_num, 0)

        c_time = post_time + timedelta(minutes=random.randint(5, 55))
        if c_time > now:
            c_time = now

        try:
            payload = {
                'post': pid,
                'author_name': com['name'],
                'content': text,
                'status': 'approve',
                'date': c_time.strftime('%Y-%m-%dT%H:%M:%S'),
                'parent': parent_id
            }
            res = requests.post(WP_URL + "/wp-json/wp/v2/comments", headers=get_auth_header(), json=payload, timeout=10)
            if res.status_code == 201:
                wp_id = res.json()['id']
                comment_id_map[i + 1] = wp_id
        except:
            pass
        time.sleep(0.3)

    print(" 完了 (スレッド構造: " + str(len(comment_id_map)) + "件成功)")

# メイン処理
print("\n🔥 完全自動トレンド記事作成 (V104: gemini-2.5-flash-lite / V98プロンプト移植版) 開始...")

success_count = 0
processed_core_keywords = set()

existing_titles = get_all_existing_titles()
selected_items = select_best_topics(get_raw_trends())

if not selected_items:
    print("❌ ネタ切れ")
else:
    for item in selected_items:
        if success_count >= ARTICLES_TO_CREATE:
            print("🎉 目標記事数（" + str(ARTICLES_TO_CREATE) + "記事）に達したため、処理を終了します。")
            break

        print("\n🚀 候補: " + item['headline'])

        core_kw = extract_pure_keyword(item['headline'], item['keyword'])

        if core_kw == "EXTRACT_FAILED":
            print(" -> ⚠️ キーワード抽出失敗のためスキップ")
            continue

        if core_kw in processed_core_keywords:
            print(" -> 🚫 重複テーマ（" + core_kw + "）のためスキップ")
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
            analysis_data['article_type'] = "LIKE_DISLIKE"
            analysis_data['proposed_title'] = "【" + analysis_data['core_keyword'] + "】好き？普通？苦手？"
            analysis_data['suggested_category'] = "people"

        print("☕ 制限回避のため15秒休憩中...", end="")
        time.sleep(15)
        print(" 再開")

        data = generate_article_content(analysis_data, item['headline'], fact_check_data, news_data)
        if not data:
            continue

        if analysis_data['article_type'] == "WHICH_BEST" and len(data.get('items', [])) < 2:
            analysis_data['article_type'] = "LIKE_DISLIKE"
            data = generate_article_content(analysis_data, item['headline'], fact_check_data, news_data)
            if not data:
                continue

        if clean_title(data['title']) in existing_titles:
            print(" -> 🚫 タイトル重複のためSKIP: " + data['title'])
            continue

        print("📝 作成決定: " + data['title'])

        items_str = []
        meta = {
            'post_views_count': '0',
            'wiki_h2_title': data.get('h2_title', ''),
            'wiki_h2_text': data.get('h2_text', ''),
            'wiki_fact_h3': data.get('fact_h3', ''),
            'wiki_info_fact': data.get('info_fact', '')
        }

        vote_mode = random.choice(['接戦', '圧倒的', '中程度', '僅差'])
        print("   📊 投票演出モード: " + vote_mode)

        for i, item_choice in enumerate(data.get('items', [])):
            idx = i + 1
            if idx > 10:
                break
            name = item_choice['name']
            meta['wiki_info' + str(idx) + '_h3'] = name
            meta['wiki_info_' + str(idx)] = item_choice.get('text', '')
            meta['wiki_item_name_' + str(idx)] = name
            meta['wiki_item_img_' + str(idx)] = ""

            if vote_mode == '接戦':
                votes = random.randint(180, 230)
            elif vote_mode == '圧倒的':
                votes = random.randint(450, 700) if i == 0 else random.randint(10, 40)
            elif vote_mode == '僅差':
                votes = random.randint(300, 350) if i == 0 else random.randint(250, 290)
            else:
                votes = random.randint(350, 500) if i == 0 else random.randint(100, 200)

            if votes % 10 == 0:
                votes += random.randint(1, 9)

            meta['vote_multi_idx_' + str(i)] = str(votes)
            if len(data.get('items', [])) == 2:
                k = 'vote_count_a' if i == 0 else 'vote_count_b'
                meta[k] = str(votes)

            items_str.append(name)

        if not items_str:
            print(" -> ⚠️ 選択肢なしのためスキップ")
            continue

        cat_id = get_term_id(data.get('category_slug', 'contents'))

        if len(items_str) == 2:
            sc = '[vote_bar name_a="' + items_str[0] + '" name_b="' + items_str[1] + '"]\n\n[vote_summary name_a="' + items_str[0] + '" name_b="' + items_str[1] + '"]'
        else:
            sc = '[vote_bar items="' + ", ".join(items_str) + '"]\n\n[vote_summary items="' + ", ".join(items_str) + '"]'

        now = datetime.now()
        post_time = now - timedelta(hours=1)

        post_data = {
            'title': data['title'],
            'content': sc,
            'status': 'publish',
            'date': post_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'categories': [cat_id],
            'slug': data.get('slug', 'post'),
            'meta': meta
        }

        try:
            res = requests.post(WP_URL + "/wp-json/wp/v2/posts", headers=get_auth_header(), json=post_data, timeout=60)
            if res.status_code == 201:
                res_data = res.json()
                pid = res_data['id']
                post_link = res_data.get('link')
                print("✅ 投稿完了 (ID:" + str(pid) + ")")
                post_comments_with_threads(pid, data.get('comments', []), post_time, now)
                send_discord_notification(pid, data['title'], post_link)
                success_count += 1
                existing_titles.append(clean_title(data['title']))
            else:
                print("❌ WP投稿エラー (" + str(res.status_code) + "): " + res.text[:200])
        except Exception as e:
            print("❌ 投稿エラー: " + str(e))

        print("☕ 制限回避のため65秒休憩中...")
        time.sleep(65)

print("\n🎉 完了 (" + str(success_count) + "記事)")
