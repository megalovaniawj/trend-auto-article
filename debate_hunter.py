import feedparser
import requests
import re
import time
import random
import base64
import os
import json
from datetime import datetime, timedelta

# ==========================================
# ★設定エリア
# ==========================================
WP_URL = os.environ.get("WP_URL", "https://docchiyo.com")
WP_USER = os.environ.get("WP_USER", "bear")
WP_APP_PASS = os.environ.get("WP_APP_PASS")

# Discord Webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF"

# 情報源リスト (社会・エンタメ・トレンドを強化)
RSS_URLS = [
    "https://news.livedoor.com/topics/rss/dom.xml",   # 社会・政治・事件
    "https://news.livedoor.com/topics/rss/ent.xml",   # 芸能・エンタメ
    "https://news.livedoor.com/topics/rss/eco.xml",   # 経済・IT
    "https://www.4gamer.net/rss/index.xml",           # ゲーム
    "https://www.gizmodo.jp/index.xml",               # ガジェット
    "https://rocketnews24.com/feed/",                 # グルメ・ネタ
    "https://feeds.cinematoday.jp/cinematoday/rss",   # 映画
    "https://mantan-web.jp/rss/rss.xml"               # アニメ
]

# 除外ワード (訃報のみNG、政治・事件はOK)
NG_WORDS = ["セール", "決算", "インタビュー", "レポート", "舞台", "オーディション", "求人", "人事", "放送", "プレゼント", "まとめ", "訃報", "死去", "ご冥福"]

# ターゲットワード (ニュース系ワードを追加)
TARGET_WORDS = ["事前登録", "発売", "リリース", "決定", "発表", "登場", "開始", "新商品", "新メニュー", "販売", "公開", "放送開始", "実写化", "映画化", "アニメ化", "検討", "方針", "批判", "物議", "話題", "炎上", "逮捕", "容疑", "可決", "辞任", "疑惑"]

# ==========================================
# 関数定義
# ==========================================

def get_auth_header():
    if not WP_USER or not WP_APP_PASS: return None
    creds = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(creds.encode()).decode()
    return {'Authorization': f'Basic {token}'}

def check_exists(title):
    headers = get_auth_header()
    if not headers: return False
    clean_search = re.sub(r'【.*?】', '', title).strip()[:15]
    endpoint = f"{WP_URL}/wp-json/wp/v2/posts?search={clean_search}&status=any"
    try:
        res = requests.get(endpoint, headers=headers, timeout=10)
        if res.status_code == 200:
            for post in res.json():
                if clean_search in post['title']['rendered']: return True
    except: pass
    return False

def extract_release_str(text):
    patterns = [
        r'\d{4}年\d{1,2}月\d{1,2}日', r'\d{1,2}月\d{1,2}日',
        r'\d{4}年\d{1,2}月下旬', r'\d{4}年\d{1,2}月上旬', r'\d{4}年\d{1,2}月中旬',
        r'\d{4}年\d{1,2}月', r'今冬', r'今春', r'今夏', r'今秋'
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match: return match.group(0)
    return "近日中（公式発表待ち）"

def determine_category(text):
    text = text.lower()
    # 1. グルメ
    if any(w in text for w in ["バーガー", "丼", "定食", "飲み放題", "食べ放題", "スタバ", "マック", "マクド", "カフェ", "ランチ", "味", "美味しい", "不味い", "試食", "グルメ", "スイーツ", "コンビニ", "ローソン", "セブン", "ファミマ", "ピザ", "カレー"]):
        return "food"
    # 2. ガジェット
    if any(w in text for w in ["apple", "iphone", "android", "pixel", "galaxy", "pc", "スペック", "イヤホン", "ヘッドホン", "カメラ", "スマホ", "watch", "windows", "mac", "cpu", "gpu", "キーボード", "モニタ"]):
        return "tech"
    # 3. エンタメ（映画・アニメ）
    if any(w in text for w in ["映画", "実写", "ドラマ", "アニメ", "声優", "興行収入", "視聴率", "マンガ", "漫画", "連載", "ディズニー", "usj", "ジブリ"]):
        return "entame"
    # 4. 社会・政治・事件 (New!)
    if any(w in text for w in ["首相", "内閣", "政府", "議員", "選挙", "増税", "減税", "給付金", "逮捕", "容疑", "判決", "事故", "事件", "物議", "炎上", "批判", "迷惑", "異次元", "少子化", "不倫"]):
        return "social"
    
    return "game"

def get_wikipedia_summary(keyword):
    try:
        url = "https://ja.wikipedia.org/w/api.php"
        params = { "action": "query", "format": "json", "prop": "extracts", "exintro": True, "explaintext": True, "redirects": 1, "titles": keyword }
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid == "-1": continue
            summary = page.get("extract", "")
            if summary: return summary[:400] + "..."
    except: pass
    return None

def generate_persona_comments(category, title, options):
    comments = []
    
    templates = {
        "social": { # 社会・政治・事件用（辛口・議論）
            "positive": [
                "これは評価できる。やっとまともな判断をしたな。",
                "{title}に関しては支持するわ。当然の流れ。",
                "遅すぎたけど、やらないよりはマシ。",
                "批判もあるだろうけど、英断だと思う。",
                "これが日本のスタンダードになるべき。"
            ],
            "negative": [
                "日本終わったな。{title}とか正気か？",
                "国民を舐めてるとしか思えない。",
                "こんなことに税金使うなよ...呆れた。",
                "理解できない。誰が得するんだこれ？",
                "即刻撤回すべき。許されないだろ。"
            ],
            "neutral": [
                "どっちもどっちだな。冷静になれよ。",
                "事実確認が先だろ。踊らされるな。",
                "今後の展開次第かな。注視が必要。",
                "これマスコミの切り取りじゃないの？"
            ]
        },
        "food": {
            "positive": ["これマジで美味かった！{title}はリピ確。", "見た目詐欺かと思ったけど味はガチ。", "カロリー爆弾だけど食う価値あるｗ", "飛ぶぞ。", "値段以上の満足感はある。"],
            "negative": ["写真と実物が違いすぎて草。もう買わん。", "期待してたのに微妙すぎた...。", "味が薄い。物足りない。", "これでこの値段は高すぎ。", "話題になってるけど美味しくない。"],
            "neutral": ["売り切れてたわ...人気すぎ。", "美味そうだけどカロリー見てそっと閉じたｗ", "期間中に一度は食べてみたい。", "みんなの感想見てから決める。"]
        },
        "tech": {
            "positive": ["{title}のスペックえぐい。即買い。", "デザイン最高。Apple超えた？", "やっと求めてた機能が来た！", "コスパ最強。迷ってるなら買え。", "レビュー見る限り良さげ。"],
            "negative": ["高すぎワロタ。誰が買うねん。", "期待外れ。前モデルと何が違うの？", "バッテリー持ち悪そう。", "このスペックでこの値段は舐めてる。", "信者専用乙。"],
            "neutral": ["実機触ってから決める。", "YouTuberのレビュー待ち。", "欲しいけど金がない...", "機能はいいけど色が微妙。"]
        },
        "entame": {
            "positive": ["{title}見たけど涙止まらん。神作。", "キャストがハマり役すぎる。", "作画クオリティ高すぎ。", "脚本が天才。伏線回収すごい。", "これは社会現象になる。"],
            "negative": ["原作改変が酷すぎる。", "時間の無駄だった。", "ポリコレ配慮しすぎて内容薄い。", "声優が合ってない。違和感すごい。", "予告詐欺だわこれ。"],
            "neutral": ["賛否両論あるけど嫌いじゃない。", "来週の展開次第。", "原作知らないけど楽しめる？", "とりあえず1話切りはせずに見る。"]
        },
        "game": {
            "positive": ["神ゲー確定演出きた！", "PVで鳥肌立った。絶対やる。", "声優豪華すぎｗ", "システムかなり良かったぞ。", "覇権ゲーの予感。"],
            "negative": ["どうせまた集金ゲーだろ。", "グラフィックは良いけどシステムが...", "リセマラ地獄が見える。", "運営があそこだから期待できない。", "即サ終しそう。"],
            "neutral": ["無課金でも遊べるなら。", "容量デカすぎｗ", "とりあえずDLだけしてみる。", "評判見てから始める。"]
        }
    }

    def apply_persona(text, persona):
        if persona == "rough": return text.replace("です", "だろ").replace("ます", "る").replace("すごい", "ヤバい").replace("私", "ワイ") + " 草"
        elif persona == "otaku": return text + " というか、結論これ一択なんだよなぁ。"
        elif persona == "gal": return text.replace("。", "！").replace("すごい", "神").replace("美味い", "優勝").replace("微妙", "ビミョー") + " 尊い..."
        elif persona == "question": return text.replace("だ。", "かな...？").replace("る。", "るかも。")
        return text 

    target_temps = templates.get(category, templates["game"])
    num_comments = random.randint(5, 10)
    
    for _ in range(num_comments):
        rand_val = random.randint(1, 100)
        # 社会ネタはネガティブ意見（批判）が出やすいので比率調整
        if category == "social":
            if rand_val <= 40: base_text = random.choice(target_temps["positive"])
            elif rand_val <= 80: base_text = random.choice(target_temps["negative"])
            else: base_text = random.choice(target_temps["neutral"])
        else:
            if rand_val <= 70: base_text = random.choice(target_temps["positive"])
            elif rand_val <= 90: base_text = random.choice(target_temps["negative"])
            else: base_text = random.choice(target_temps["neutral"])
            
        short_title = title[:15]
        text = base_text.replace("{title}", short_title)
        persona = random.choice(["standard", "standard", "rough", "otaku", "gal", "question"])
        comments.append(apply_persona(text, persona))
        
    return comments

def generate_content_data(category, title):
    clean_title = re.sub(r'【.*?】', '', title).split("」")[0].replace("「", "")
    clean_title = re.sub(r'\[.*?\]', '', clean_title).strip()
    if len(clean_title) > 35: clean_title = clean_title[:35] + "..."

    # --- A. 社会・政治・事件 (New) ---
    if category == "social":
        wp_title = f"【議論】『{clean_title}』はあり？なし？世間の反応まとめ"
        options = ["支持する（あり）", "理解できない（なし）", "どちらとも言えない", "もっと議論が必要"]
        weights = [30, 40, 20, 10]
        spec_h2 = "ニュースの概要・背景"
        spec_text = "本件に関する詳細な経緯や、関係者のコメントについては、各報道機関のニュースソースをご確認ください。\nSNS上では賛否両論の意見が飛び交っています。"

    # --- B. グルメ ---
    elif category == "food":
        wp_title = f"【評価】『{clean_title}』はウマい？写真詐欺？食べた感想まとめ"
        options = ["神ウマ（リピ確）", "普通に美味しい", "期待外れ（微妙）", "金返せ（マズい）"]
        weights = [50, 30, 10, 10]
        spec_h2 = "カロリー・価格・販売期間"
        spec_text = "気になるカロリーや最新の価格情報は、公式サイトまたは店頭の表示をご確認ください。\n期間限定メニューの場合、早期終了の可能性もあるためご注意ください。"

    # --- C. ガジェット ---
    elif category == "tech":
        wp_title = f"【評価】『{clean_title}』は買いか？コスパと性能を議論するスレ"
        options = ["即買い（神機）", "様子見（レビュー待ち）", "高すぎ（見送り）", "ゴミ（解散）"]
        weights = [45, 35, 15, 5]
        spec_h2 = "スペック・発売日・価格"
        spec_text = "詳細な技術仕様（スペック）や国内販売価格については、メーカー公式発表をご確認ください。\n予約開始日や発売日についても随時更新予定です。"

    # --- D. エンタメ ---
    elif category == "entame":
        wp_title = f"【評価】『{clean_title}』は面白い？つまらない？感想・評判まとめ"
        options = ["最高（神作品）", "普通に楽しめる", "期待外れ（微妙）", "時間の無駄（駄作）"]
        weights = [40, 30, 20, 10]
        spec_h2 = "キャスト・スタッフ・公開情報"
        spec_text = "主要キャストや監督、制作スタッフなどの詳細は、公式サイトまたは公式発表をご確認ください。\n原作がある作品の場合、改変ポイントも注目されています。"

    # --- E. ゲーム ---
    else: 
        wp_title = f"【評価】『{clean_title}』は神ゲー？クソゲー？本音評価まとめ"
        options = ["神ゲー（覇権）", "良ゲー（普通）", "様子見（地雷臭）", "クソゲー（返金）"]
        weights = [40, 30, 20, 10]
        spec_h2 = "対応ハード・システム"
        spec_text = "対応プラットフォームや課金形態（基本無料/買い切り）については、公式サイトの最新情報をご確認ください。"

    return clean_title, wp_title, options, weights, spec_h2, spec_text

def create_post(entry, category):
    title = entry.title
    link = entry.link
    description = entry.description
    
    clean_title, wp_title, options, weights, spec_h2, spec_text = generate_content_data(category, title)
    comments_pool = generate_persona_comments(category, clean_title, options)
    
    initial_votes = [0] * 4
    total_sakura = random.randint(40, 60)
    for _ in range(total_sakura):
        idx = random.choices([0, 1, 2, 3], weights=weights)[0]
        initial_votes[idx] += 1
    
    items_str = ",".join([f"{opt}|" for opt in options])
    release_str = extract_release_str(title + description)
    wiki_summary = get_wikipedia_summary(clean_title)
    
    intro_text = description[:200] + "..."
    if wiki_summary: intro_text += "\n\n<h3>💡 Wikipedia概要</h3>\n<p>" + wiki_summary + "</p>"

    content = f"""
[vote_bar items="{items_str}"]
[vote_summary items="{items_str}"]
<p>話題の『{clean_title}』について、皆さんの本音を聞かせてください。<br><strong>「支持する？」それとも「反対？」</strong><br>忖度なしの評価を投票で決定します！</p>
"""

    meta = {
        'wiki_h2_title': f"{clean_title} について",
        'wiki_h2_text': intro_text,
        'wiki_info1_h3': "日時・期間",
        'wiki_info_1': f"関連日時: {release_str}",
        'wiki_info2_h3': spec_h2,
        'wiki_info_2': spec_text,
        'wiki_info3_h3': "みんなの口コミ・評判",
        'wiki_info_3': "SNSや掲示板では既に様々な意見が飛び交っています。\n下のコメント欄で、あなたの率直な意見やリーク情報、感想を書き込んでください。\n匿名で投稿可能です。",
        'wiki_fact_h3': "情報ソース",
        'wiki_info_fact': f"『{clean_title}』に関する最新情報や詳細は、以下の情報元をご確認ください。\n引用元: {link}",
        'post_views_count': '0'
    }

    for i, opt in enumerate(options, 1):
        meta[f'wiki_item_name_{i}'] = opt
        meta[f'wiki_item_img_{i}'] = ""
        meta[f'vote_multi_idx_{i-1}'] = str(initial_votes[i-1])

    current_time = datetime.now()
    status = 'draft' # 安全のため下書き
    post_date = current_time.strftime('%Y-%m-%dT%H:%M:%S')
    
    post_data = {'title': wp_title, 'content': content, 'status': status, 'date': post_date, 'categories': [1], 'meta': meta}

    headers = get_auth_header()
    if not headers: return None, None

    try:
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", headers=headers, json=post_data, timeout=30)
        if res.status_code == 201:
            pid = res.json()['id']
            print(f"✅ 作成成功({category}): {clean_title} (投票数: {sum(initial_votes)})")
            return pid, comments_pool
    except Exception as e: print(f"❌ エラー: {e}")
    return None, None

def post_sakura_comment(post_id, comments_pool):
    if not comments_pool: return
    url = f"{WP_URL}/wp-json/wp/v2/comments"
    headers = get_auth_header()
    if not headers: return
    for text in comments_pool:
        c_dt = datetime.now() - timedelta(minutes=random.randint(5, 300))
        data = {'post': post_id, 'author_name': '匿名', 'content': text, 'status': 'approve', 'date': c_dt.isoformat()}
        try: requests.post(url, headers=headers, json=data, timeout=5)
        except: pass
    print(f"   💬 コメントを{len(comments_pool)}件投稿しました")

def send_discord(title, cat, status):
    if not DISCORD_WEBHOOK_URL or "ここに" in DISCORD_WEBHOOK_URL: return
    status_ja = {'publish': '🚀 即時公開', 'future': '📅 予約投稿', 'draft': '📝 下書き'}.get(status, status)
    msg = f"📰 **{cat.upper()}記事を作成**\n**題名:** {title}\n**状態:** {status_ja}\n{WP_URL}/wp-admin/"
    try: requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=5)
    except: pass

def main():
    print("🤖 議論ハンター(debate_hunter) v18 起動")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'}
    total = 0
    for rss in RSS_URLS:
        print(f"\n📡 取得中: {rss} ...")
        try:
            r = requests.get(rss, headers=headers, timeout=15)
            if r.status_code != 200: continue
            feed = feedparser.parse(r.content)
            for entry in feed.entries:
                if total >= 3: break
                title = entry.title
                if not any(w in title for w in TARGET_WORDS): continue
                if any(w in title for w in NG_WORDS):
                    print(f"✖️ NG: {title[:20]}...")
                    continue
                if check_exists(title):
                    print(f"🔷 済: {title[:20]}...")
                    continue
                
                cat = determine_category(title + entry.description)
                print(f"\n✨ ヒット({cat}): {title}")
                pid, comments_pool = create_post(entry, cat)
                if pid:
                    post_sakura_comment(pid, comments_pool)
                    clean_title = re.sub(r'【.*?】', '', title).split("」")[0]
                    send_discord(clean_title, cat, "draft")
                    total += 1
        except Exception as e: print(f"エラー: {e}")
        if total >= 3: break
    print(f"🏁 完了: {total}件作成")

if __name__ == "__main__":
    main()
