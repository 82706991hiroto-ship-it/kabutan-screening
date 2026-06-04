import requests
from bs4 import BeautifulSoup
import time, os, re
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
DISCORD_WEBHOOK = os.environ.get('DISCORD_WEBHOOK', '')

def send_discord(message):
    if not DISCORD_WEBHOOK:
        print(message); return
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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
    })
    return session

def main():
    now = datetime.now(JST).strftime('%Y/%m/%d')
    session = get_session()
    results = []

    # トップページでCookie取得
    r0 = session.get('https://kabutan.jp/', timeout=20)
    results.append(f'トップページ: HTTP {r0.status_code}')
    time.sleep(2)

    # 試すURLリスト
    urls = [
        'https://kabutan.jp/warning/?mode=52high',
        'https://kabutan.jp/warning/index.html?mode=52high',
        'https://kabutan.jp/warning/?mode=52high&page=1',
        'https://kabutan.jp/stock/warning/?mode=52high',
    ]

    for url in urls:
        session.headers['Referer'] = 'https://kabutan.jp/'
        r = session.get(url, timeout=20)
        results.append(f'URL: {url}\n→ HTTP {r.status_code} / {len(r.text)}文字')

        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'lxml')
            links = soup.find_all('a', href=re.compile(r'code=\d{4}'))
            results.append(f'→ 銘柄リンク数: {len(links)}件')
            if links:
                samples = []
                for l in links[:5]:
                    m = re.search(r'code=(\d{4})', l['href'])
                    if m:
                        samples.append(f'{m.group(1)}: {l.get_text(strip=True)}')
                results.append('サンプル:\n' + '\n'.join(samples))
            break
        time.sleep(2)

    send_discord('🔍 **デバッグ結果** ({})\n\n{}'.format(now, '\n'.join(results)))

if __name__ == '__main__':
    main()
