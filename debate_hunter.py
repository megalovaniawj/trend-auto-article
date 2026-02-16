import feedparser
import requests
import re
import time
import random
import base64
import os
import html
import json
from datetime import datetime, timedelta

# ==========================================
# ★設定エリア
# ==========================================
WP_URL = os.environ.get("WP_URL", "https://docchiyo.com")
WP_USER = os.environ.get("WP_USER", "bear")
WP_APP_PASS = os.environ.get("WP_APP_PASS")

# Discord Webhook
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471795668791070783/YpkOhjLQ6pETVn6Vr1_9HKazcE4QLG7bPb1hBvsajtWm5W9SFbCL3_mF5c0YSgi1dvOF"

# ★カテゴリーID設定
CATEGORY_IDS = {
    "social": 194,  "food": 11, "tech": 24,
    "anime": 155, "entame": 95, "game": 13
}

# RSSリスト
RSS_URLS = [
    "https://news.yahoo.co.jp/rss/topics/dom.xml",    # 社会
    "https://news.yahoo.co.jp/rss/topics/ent.xml",    # エンタメ
    "https://news.livedoor.com/topics/rss/dom.xml",   # 国内
    "https://www.4gamer.net/rss/index.xml",           # ゲーム
    "https://rocketnews24.com/feed/",                 # グルメ
    "https://feeds.cinematoday.jp/cinematoday/rss",   # 映画
    "https://mantan-web.jp/rss/rss.xml"               # アニメ
]

NG_WORDS = ["セール", "決算", "インタビュー", "レポート", "舞台", "オーディション", "求人", "人事", "放送", "プレゼント", "まとめ", "訃報", "死去", "ご冥福", "亡く", "逝去"]
TARGET_WORDS = ["発売", "リリース", "決定", "発表", "開始", "新商品", "新メニュー", "公開", "実写化", "映画化", "アニメ化", "検討", "方針", "批判", "物議", "炎上", "逮捕", "容疑", "可決", "辞任", "疑惑", "増税", "義務化", "中止", "話題"]

# ==========================================
# 関数定義
# ==========================================

def get_auth_header():
    if not WP_USER or not WP_APP_PASS: return None
    creds = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(creds.encode()).decode()
    return {'Authorization': f'Basic {token}'}

def clean_text(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def check_exists(title):
    headers = get_auth_header()
    if not headers: return False
    clean_search = clean_text(title)[:15]
    endpoint = f"{WP_URL}/wp-json/wp/v2/posts?search={clean_search}&status=any"
    try:
        res = requests.get(endpoint, headers=headers, timeout=10)
        if res.status_code == 200:
            for post in res.json():
                if clean_search in post['title']['rendered']: return True
    except: pass
    return False

def determine_category(text):
    text = text.lower()
    if any(w in text for w in ["バーガー", "丼", "定食", "飲み放題", "食べ放題", "スタバ", "マック", "マクド", "ランチ", "味", "美味しい", "不味い", "試食", "グルメ", "スイーツ", "コンビニ", "ローソン", "セブン", "ファミマ", "ピザ", "カレー"]): return "food"
    if any(w in text for w in ["apple", "iphone", "android", "pixel", "galaxy", "pc", "スペック", "イヤホン", "ヘッドホン", "カメラ", "スマホ", "watch", "windows", "mac", "cpu", "gpu", "キーボード", "モニタ"]): return "tech"
    if any(w in text for w in ["アニメ", "声優", "マンガ", "漫画", "連載", "ジャンプ", "プリキュア", "ガンダム"]): return "anime"
    if any(w in text for w in ["映画", "実写", "ドラマ", "興行収入", "視聴率", "ディズニー", "usj", "ジブリ"]): return "entame"
    if any(w in text for w in ["首相", "内閣", "政府", "議員", "選挙", "増税", "減税", "給付金", "逮捕", "容疑", "判決", "事故", "事件", "物議", "炎上", "批判", "迷惑", "異次元", "少子化", "不倫", "パパ活", "詐欺"]): return "social"
    return "game"

# --- 情報収集 ---

def fetch_og_description(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            match = re.search(r'<meta property="og:description" content="(.*?)"', r.text)
            if match: return clean_text(match.group(1))
            match2 = re.search(r'<meta name="description" content="(.*?)"', r.text)
            if match2: return clean_text(match2.group(1))
    except: pass
    return None

def get_wikipedia_summary(keyword):
    try:
        clean_kw = re.sub(r'【.*?】', '', keyword).strip()
        url = "https://ja.wikipedia.org/w/api.php"
        params = { "action": "query", "format": "json", "prop": "extracts", "exintro": True, "explaintext": True, "redirects": 1, "titles": clean_kw }
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid == "-1": continue
            summary = page.get("extract", "")
            if summary: return summary
    except: pass
    return None

def extract_specific_info(text):
    """テキストから価格と日付を抽出する"""
    price = re.search(r'(\d{1,3}(,\d{3})*|\d+)円', text)
    date = re.search(r'(\d{4}年)?\d{1,2}月\d{1,2}日', text)
    return price.group(0) if price else None, date.group(0) if date else None

# --- ★重要：コメント生成ロジック (PHP版の完全移植) ---

def generate_persona_comment(category, title):
    """
    PHP版のロジックに基づき、確率で人格を選定し、口調を変換して返す
    """
    
    # 1. 人格の重み付け (PHP版準拠)
    personas = [
        'normal', 'polite', 'rough', 'excited', 'question', # 主要5人格 (各16%)
        'slang', 'kansai', 'otaku', 'gal', 'simple'         # レア5人格 (各4%)
    ]
    weights = [16, 16, 16, 16, 16, 4, 4, 4, 4, 4]
    
    persona = random.choices(personas, weights=weights, k=1)[0]
    
    # 2. ベースコメントの選択 (カテゴリ別)
    base_comments = {
        "social": [
            "これに関しては支持するわ。もっと早くやるべきだった。",
            "日本終わったな。{title}とか正気かよ。",
            "批判してるやつ多いけど、対案あるの？",
            "国民を舐めてるとしか思えない対応だな。",
            "どっちもどっちだな。冷静になろうぜ。",
            "これマスコミの切り取りじゃないの？事実確認が先。",
            "増税とか規制ばっかり。いい加減にしてほしい。",
            "これは評価できる。英断だと思うよ。"
        ],
        "food": [
            "{title}食べてきた！マジで美味かったからおすすめ。",
            "写真詐欺すぎて草。実物ちっさ！",
            "カロリー見てそっと閉じたわｗ",
            "期待してたのに味が薄かった...。",
            "売り切れで買えなかったんだけど！",
            "値段の割に満足度高いね。リピ確。",
            "これ食べるなら牛丼3杯食うわ。"
        ],
        "tech": [
            "{title}のスペックえぐいな。即買い決定。",
            "高すぎワロタ。誰が買うねんこれ。",
            "デザインはいいけどバッテリー持ちが心配。",
            "前モデルで十分じゃね？買い換える必要なし。",
            "やっと求めてた機能が来た！遅すぎるわ。",
            "レビュー待ちかな。人柱にはなりたくない。",
            "信者専用アイテム乙。"
        ],
        "anime": [
            "神回確定。作画班生きてるか？",
            "原作改変ひどすぎ。脚本家出てこい。",
            "声優の演技に鳥肌立ったわ。",
            "今期の覇権はこれで決まりだな。",
            "展開遅すぎて切ったわ。",
            "キャラデザがどうしても受け付けない...",
            "2期あるかな？円盤買わなきゃ。"
        ],
        "entame": [
            "実写化とか誰得だよ。やめてくれ。",
            "キャストがハマり役すぎる。見てよかった。",
            "脚本がガバガバ。時間の無駄だった。",
            "ラストの展開で泣いた。ハンカチ必須。",
            "ポリコレ配慮しすぎて内容薄っぺらいな。",
            "賛否両論あるけど俺は好きだな。"
        ],
        "game": [
            "神ゲー確定演出きたあああ！",
            "どうせまた集金ゲーだろ。騙されんぞ。",
            "リセマラ地獄が見える...",
            "PV詐欺じゃなければ覇権取れる。",
            "運営があそこだから期待できないわ。",
            "無課金でも遊べるならやる。",
            "容量デカすぎｗスマホ爆発するわ。"
        ]
    }
    
    # テンプレート取得 (なければgame用)
    templates = base_comments.get(category, base_comments["game"])
    text = random.choice(templates)
    
    # タイトル置換 (長すぎる場合は短縮)
    short_title = title[:10]
    text = text.replace("{title}", short_title)

    # 3. 人格ごとの口調変換ロジック
    if persona == 'normal':   # 普通
        pass
    elif persona == 'polite': # 丁寧
        text = text.replace("だろ", "でしょう").replace("草", "面白いですね").replace("ねん", "のでしょうか").replace("乙", "お疲れ様です").replace("わ。", "ですね。") + " と思います。"
    elif persona == 'rough':  # 雑・男言葉
        text = text.replace("です", "だろ").replace("ます", "る").replace("すごい", "ヤバい").replace("私", "俺").replace("ない。", "ねぇよ。")
    elif persona == 'excited':# 興奮
        text = text.replace("。", "！！！").replace("すごい", "神すぎ！").replace("美味かった", "優勝した").replace("！", "！！") + " マジでヤバい！"
    elif persona == 'question':# 弱気・疑問
        text = text.replace("だ。", "かな...？").replace("よ。", "かも？").replace("ね。", "だよね？") + " 間違ってたらごめん。"
    elif persona == 'slang':  # ネットスラング
        text = text.replace("。", "ｗ").replace("！", "ｗｗ") + " 草不可避ｗｗｗ"
    elif persona == 'kansai': # 関西弁
        text = text.replace("だろ", "やろ").replace("だ。", "やな。").replace("ねん", "んや").replace("すごい", "えぐい").replace("ない。", "あらへん。")
    elif persona == 'otaku':  # オタク
        text = text + " というか、結論これ一択なんだよなぁ（早口）"
    elif persona == 'gal':    # ギャル
        text = text.replace("。", "⤴︎").replace("すごい", "神").replace("美味かった", "優勝").replace("微妙", "ビミョー") + " 尊い..."
    elif persona == 'simple': # 一言
        text = text.split("。")[0] + "。"

    return text

# --- コンテンツ生成 ---

def create_post(entry, category):
    title = clean_text(entry.title)
    link = entry.link
    
    # 情報収集 (優先度: スクレイピング > RSS)
    real_desc = fetch_og_description(link)
    rss_desc = clean_text(entry.description)
    main_text = real_desc if real_desc and len(real_desc) > 30 else rss_desc
    
    # Wikipedia検索
    wiki_text = get_wikipedia_summary(title)
    
    # 具体情報の抽出
    price, date_str = extract_specific_info(main_text)
    
    clean_title = re.sub(r'【.*?】', '', title).split("」")[0].replace("「", "").strip()
    if len(clean_title) > 35: clean_title = clean_title[:35] + "..."

    # 選択肢の生成
    if category == "social":
        wp_title = f"【議論】『{clean_title}』はあり？なし？世間の反応まとめ"
        options = ["支持する（あり）", "理解できない（なし）", "どちらとも言えない", "もっと議論が必要"]
        weights = [30, 40, 20, 10]
        box1_title = "ニュース概要"
    elif category == "food":
        wp_title = f"【評価】『{clean_title}』はウマい？写真詐欺？食べた感想まとめ"
        options = ["神ウマ（リピ確）", "普通に美味しい", "期待外れ（微妙）", "金返せ（マズい）"]
        weights = [50, 30, 10, 10]
        box1_title = "商品詳細"
    else: # tech, game, entame, anime
        wp_title = f"【評価】『{clean_title}』は神？微妙？本音評価まとめ"
        options = ["最高（神）", "普通（良）", "微妙（期待外れ）", "ダメ（論外）"]
        weights = [40, 30, 20, 10]
        box1_title = "概要"

    # HTMLタグを含まないプレーンテキストで構成
    content = f"""
[vote_bar items="{",".join([f"{o}|" for o in options])}"][vote_summary items="{",".join([f"{o}|" for o in options])}"]<p>話題の『{clean_title}』について、皆さんの本音を聞かせてください。<br><strong>「支持する？」それとも「反対？」</strong><br>忖度なしの評価を投票で決定します！</p>"""

    # 導入文 (Wikiがあれば追加)
    intro_text = main_text[:250] + "..."
    if wiki_text: intro_text += "\n\n【Wikipedia概要】\n" + wiki_text[:200] + "..."

    # メタデータセット (固定文言を全廃)
    meta = {
        'wiki_h2_title': f"{clean_title} について",
        'wiki_h2_text': intro_text,
        'wiki_info1_h3': box1_title, 'wiki_info_1': main_text,
        
        'wiki_info3_h3': "みんなの反応",
        'wiki_info_3': "SNSや掲示板では既に様々な意見が飛び交っています。下のコメント欄で、あなたの直感的な意見や感想を書き込んでください。",
        'post_views_count': '0'
    }

    # ★重要：情報がある場合のみメタデータに追加 (ない場合は空欄)
    idx = 2
    if date_str:
        meta[f'wiki_info{idx}_h3'] = "日時・期間"
        meta[f'wiki_info_{idx}'] = f"関連日時: {date_str}"
        idx += 1
    
    if price:
        meta[f'wiki_info{idx}_h3'] = "価格情報"
        meta[f'wiki_info_{idx}'] = f"価格: {price}"
        idx += 1

    # Wikiがあれば豆知識へ
    if wiki_text:
        meta['wiki_fact_h3'] = "関連知識 (Wikipedia)"
        meta['wiki_info_fact'] = wiki_text[:400] + "..."

    # 投票初期値
    initial_votes = [0] * 4
    total_sakura = random.randint(40, 60)
    for _ in range(total_sakura):
        i = random.choices([0, 1, 2, 3], weights=weights)[0]
        initial_votes[i] += 1
    for i, opt in enumerate(options, 1):
        meta[f'wiki_item_name_{i}'] = opt; meta[f'wiki_item_img_{i}'] = ""; meta[f'vote_multi_idx_{i-1}'] = str(initial_votes[i-1])

    post_data = {
        'title': wp_title, 'content': content, 'status': 'draft', 
        'date': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'categories': [CATEGORY_IDS.get(category, 1)], 'meta': meta
    }

    headers = get_auth_header()
    if not headers: return None, None, None

    try:
        res = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", headers=headers, json=post_data, timeout=30)
        if res.status_code == 201:
            pid = res.json()['id']
            print(f"✅ 作成成功({category}): {clean_title}")
            return pid, main_text, options
    except Exception as e: print(f"❌ エラー: {e}")
    return None, None, None

def post_sakura_comment(post_id, text_source, options):
    if not post_id: return
    url = f"{WP_URL}/wp-json/wp/v2/comments"
    headers = get_auth_header()
    if not headers: return
    
    print(f"   💬 コメント投稿開始...")
    
    # 5〜8件のコメントを生成して投稿
    for i in range(random.randint(5, 8)):
        # ★PHP版ロジックでコメント生成
        c_body = generate_persona_comment(category, title)
        
        c_dt = datetime.now() - timedelta(minutes=random.randint(5, 300))
        data = {
            'post': post_id,
            'author_name': '匿名', 
            'content': c_body,
            'status': 'approve',
            'date': c_dt.isoformat()
        }
        try:
            r = requests.post(url, headers=headers, json=data, timeout=10)
            if r.status_code == 201:
                print(f"      - コメント{i+1} OK: {c_body[:20]}...")
            else:
                print(f"      - コメント{i+1} 失敗: {r.status_code}")
        except: pass
        time.sleep(1.5) # 連投規制回避

def send_discord(title, cat):
    if not DISCORD_WEBHOOK_URL or "ここに" in DISCORD_WEBHOOK_URL: return
    msg = f"📰 **{cat.upper()}記事を作成**\n**題名:** {title}\n{WP_URL}/wp-admin/"
    try: requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=5)
    except: pass

def main():
    print("🤖 議論ハンター(debate_hunter) v24 起動")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'}
    total = 0
    for rss in RSS_URLS:
        print(f"\n📡 取得中: {rss} ...")
        try:
            r = requests.get(rss, headers=headers, timeout=15)
            if r.status_code != 200: continue
            feed = feedparser.parse(r.content)
            
            rss_count = 0
            for entry in feed.entries:
                if total >= 3 or rss_count >= 1: break
                
                title = clean_text(entry.title)
                if not any(w in title for w in TARGET_WORDS): continue
                if any(w in title for w in NG_WORDS): continue
                if check_exists(title): continue
                
                cat = determine_category(title + entry.description)
                print(f"\n✨ ヒット({cat}): {title}")
                
                pid, text_src, opts = create_post(entry, cat)
                if pid:
                    # ★修正：カテゴリを渡して正確なコメントを生成させる
                    # post_sakura_comment(pid, text_src, opts) 
                    # ↓ 関数内で再定義した generate_advanced_persona_comment を使うため
                    # ここでループを回して投稿する形に修正（関数呼び出し変更）
                    
                    print(f"   💬 コメント投稿開始...")
                    for i in range(random.randint(5, 8)):
                        c_body = generate_advanced_persona_comment(cat, title)
                        c_dt = datetime.now() - timedelta(minutes=random.randint(5, 300))
                        data = {'post': pid, 'author_name': '匿名', 'content': c_body, 'status': 'approve', 'date': c_dt.isoformat()}
                        try: requests.post(f"{WP_URL}/wp-json/wp/v2/comments", headers=get_auth_header(), json=data, timeout=10)
                        except: pass
                        time.sleep(1.5)

                    send_discord(title, cat)
                    total += 1
                    rss_count += 1
        except Exception as e: print(f"エラー: {e}")
        if total >= 3: break
    print(f"🏁 完了: {total}件作成")

if __name__ == "__main__":
    main()
