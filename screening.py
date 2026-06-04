import requests
from bs4 import BeautifulSoup
import time, random, os, sys, re
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
DISCORD_WEBHOOK = os.environ.get('DISCORD_WEBHOOK', '')

def send_discord(message):
    if not DISCORD_WEBHOOK:
        print(message)
        return
    chunks = []
    while len(message) > 1900:
        pos = message[:1900].rfind('\n')
        if pos == -1: pos = 1900
        chunks.append(message[:pos])
        message = message[pos:].lstrip('\n')
    chunks.append(message)
    for chunk in chunks:
        if chunk.strip():
            requests.post(DISCORD_WEBHOOK, json={"content": chunk}, timeout=10)
            time.sleep(0.5)

def get_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    })
    return session

def main():
    now = datetime.now(JST).strftime('%Y/%m/%d')
    session = get_session()

    try:
        # トップページでセッション確立
        session.get('https://kabutan.jp/', timeout=20)
        time.sleep(2)

        # 52週高値ページ取得
        res = session.get('https://kabutan.jp/warning/?mode=52high', timeout=20)
        send_discord(f'🔍 **デバッグ情報** ({now})\nHTTPステータス: {res.status_code}\nHTMLサイズ: {len(res.text)}文字')

        soup = BeautifulSoup(res.text, 'lxml')

        # リンク形式1: /stock/?code=XXXX
        links1 = soup.find_all('a', href=re.compile(r'/stock/\?code=\d{4}'))
        # リンク形式2: /stock/XXXX
        links2 = soup.find_all('a', href=re.compile(r'/stock/\d{4}'))

        send_discord(f'リンク形式1 (/stock/?code=): {len(links1)}件\nリンク形式2 (/stock/XXXX): {len(links2)}件')

        # 全テーブルのサイズ確認
        tables = soup.find_all('table')
        table_info = '\n'.join([f'table[{i}]: {len(t.find_all("tr"))}行' for i, t in enumerate(tables[:10])])
        send_discord(f'テーブル数: {len(tables)}\n{table_info}')

        # 最初の銘柄の決算ページも確認
        codes = []
        for link in links1[:3]:
            m = re.search(r'code=(\d{4})', link['href'])
            if m:
                codes.append(m.group(1))
        for link in links2[:3]:
            m = re.search(r'/stock/(\d{4})', link['href'])
            if m and m.group(1) not in codes:
                codes.append(m.group(1))

        if codes:
            send_discord(f'サンプル銘柄コード: {codes[:5]}')
            # 最初の銘柄の決算ページを確認
            code = codes[0]
            time.sleep(2)
            fin_res = session.get(f'https://kabutan.jp/stock/finance?code={code}', timeout=20)
            fin_soup = BeautifulSoup(fin_res.text, 'lxml')
            fin_tables = fin_soup.find_all('table')

            # 売上高・経常利益を含むテーブルのテキストを送信
            for i, t in enumerate(fin_tables):
                t_text = t.get_text(separator=' | ', strip=True)
                if '売上高' in t_text or '経常' in t_text:
                    send_discord(f'📊 銘柄{code} 決算テーブル[{i}]:\n```\n{t_text[:1500]}\n```')
                    break
        else:
            send_discord('⚠️ 銘柄コードが1件も取得できませんでした')

    except Exception as e:
        import traceback
        send_discord(f'❌ エラー: {str(e)}\n```\n{traceback.format_exc()[-600:]}\n```')

if __name__ == '__main__':
    main()
