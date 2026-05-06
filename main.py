 -*- coding: utf-8 -*-
# V102: gemma-4-31b-it対応版

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

MODEL_NAME = "gemma-4-31b-it"
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

def call_gemini(prompt, timeout=30):
    url = "https://generativelanguage.googleapis.com/v1beta/models/" + MODEL_NAME + ":generateContent?key=" + GEMINI_API_KEY.strip()
    headers = {'Content-Type': 'application/json'}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "safetySettings": SAFETY_SETTINGS,
        "generationConfig": {"maxOutputTokens": 4096}
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=timeout)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        else:
            print(" [APIエラー:" + str(res.status_code) + "]")
    except Exception as e:
        print(" [例外:" + str(e) + "]")
    return None

def parse_json_from_text(text):
    try:
        text = text.replace('```json', '').replace('```', '').strip()
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end > 0:
            candidate = json.loads(text[start:end])
            # プレースホルダーチェック: titleが日本語でないものは除外
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

    candidates_str = "\n".join(["- " + c['keyword'] for c in candidates[:80]])
    prompt = (
        "以下からアニメ・漫画・ゲーム・エンタメ系を10個選びカンマ区切りで出力:\n"
        + candidates_str + "\n出力:"
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
    # ヘッドラインから直接抽出を試みる（AIを使わず正規表現で）
    # 「」『』の中の文字を優先的に取得
    matches = re.findall(r'[「『](.*?)[」』]', headline)
    for m in matches:
        m = m.strip()
        jp_chars = len(re.findall(r'[\u3040-\u9fff]', m))
        if m and len(m) <= 20 and jp_chars >= 1:
            print(" -> [" + m + "] (正規表現)")
            return m

    # AIで抽出
    prompt = "次の見出しに含まれる日本語のアニメ・漫画・ゲーム・人物の固有名詞を1つだけ答えてください。固有名詞のみ、説明不要。\n見出し: " + headline
    text = call_gemini(prompt, timeout=20)
    if text:
        for line in text.split('\n'):
            line = line.strip()
            if ':' in line or ':' in line:
                line = re.split(r'[:：]', line)[-1].strip()
            line = re.sub(r'^[\*\-\#\>\d\.\s]+', '', line).strip()
            line = re.sub(r'[\(\)\[\]"\'\.]', '', line).strip()
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
        print(" [取得完了]")
        return extract[:1500]
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
                news_text = ""
                print(" [調査完了]")
                for i, entry in enumerate(feed.entries[:3]):
                    title = re.sub(r' [-|–|:|：].*', '', entry.title).strip()
                    news_text += title + "\n"
                    print("      👉 記事" + str(i+1) + ": " + title)
                return news_text
    except:
        pass
    print(" [ニュースなし]")
    return ""

def analyze_and_extract_core(pure_keyword, headline, fact_check_data, news_data, source_type):
    print("    🧠 AI編集長が企画を考案中...", end="")
    wiki = fact_check_data[:500] if fact_check_data != "SEARCH_FAILED" else "なし"

    prompt = (
        "テーマ「" + pure_keyword + "」の投票記事企画を考えてください。\n"
        "Wiki情報がある場合はWHICH_BEST（推しキャラ等）、ない場合はLIKE_DISLIKE。\n"
        "Wiki情報: " + wiki + "\n\n"
        "以下のキーを持つJSONを出力してください:\n"
        "- core_keyword: 「" + pure_keyword + "」\n"
        "- article_type: WHICH_BEST または LIKE_DISLIKE\n"
        "- proposed_title: 日本語の記事タイトル\n"
        "- reason: 企画意図\n"
        "- suggested_category: contents\n"
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

def generate_article_content(analysis_data, original_headline, fact_check_data, news_data):
    theme = analysis_data['core_keyword']
    a_type = analysis_data['article_type']
    title_idea = analysis_data['proposed_title']
    cat = analysis_data.get('suggested_category', 'contents')

    print("🤖 記事執筆中 (" + theme + ")...", end="")

    comment_count = random.randint(10, 15)
    wiki = fact_check_data[:800] if fact_check_data != "SEARCH_FAILED" else "なし"

    if a_type == "WHICH_BEST":
        items_instruction = "Wiki情報にある登場人物や作品名を5〜8個リストアップして、それぞれ解説を書いてください。必ず「その他」も追加してください。"
    else:
        items_instruction = "「好き」「嫌い」「普通」の3択を作り、それぞれ150文字程度の解説を書いてください。"

    prompt = (
        "「" + title_idea + "」というタイトルの投票記事を日本語で書いてください。\n\n"
        "テーマ: " + theme + "\n"
        "Wiki情報: " + wiki[:600] + "\n\n"
        "記事の構成:\n"
        "1. h2_title: 導入の見出し\n"
        "2. h2_text: 200文字程度の導入文\n"
        "3. fact_h3: 豆知識の見出し\n"
        "4. info_fact: 200文字程度の豆知識\n"
        "5. items: " + items_instruction + "\n"
        "6. comments: 掲示板風コメントを" + str(comment_count) + "個。2〜3個は>>数字で返信する形式。\n\n"
        "slugはローマ字またはアルファベット小文字ハイフン区切りで作成してください。\n"
        "tagsは日本語で3つ。\n\n"
        "JSONのみ出力してください（説明文不要）:\n"
    )

    text = call_gemini(prompt, timeout=120)
    if text:
        result = parse_json_from_text(text)
        if result and result.get('title', '') not in ['タイトル', '', '...']:
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
print("\n🔥 完全自動トレンド記事作成 (V102: gemma-4-31b-it対応版) 開始...")

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

        if analysis_data['article_type'] == "WHICH_BEST" and fact_check_data == "SEARCH_FAILED":
            analysis_data['article_type'] = "LIKE_DISLIKE"
            analysis_data['proposed_title'] = "【" + analysis_data['core_keyword'] + "】好き？普通？苦手？"
            analysis_data['suggested_category'] = "people"

        print("☕ 制限回避のため10秒休憩中...", end="")
        time.sleep(10)
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

        for i, item_choice in enumerate(data['items']):
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
            if len(data['items']) == 2:
                k = 'vote_count_a' if i == 0 else 'vote_count_b'
                meta[k] = str(votes)

            items_str.append(name)

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
