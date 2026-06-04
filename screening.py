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
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })
    return session

def main():
    now = datetime.now(JST).strftime('%Y/%m/%d')
    session = get_session()

    session.get('https://kabutan.jp/', timeout=20)
    time.sleep(2)

    session.headers['Referer'] = 'https://kabutan.jp/'
    res = session.get('https://kabutan.jp/warning/?mode=52high', timeout=20)

    soup = BeautifulSoup(res.text, 'lxml')

    # 全リンクのhrefパターンを収集
    all_hrefs = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if re.search(r'\d{4}', href):
            all_hrefs.add(href)

    href_list = sorted(all_hrefs)[:30]
    send_discord(f'🔍 **4桁数字を含むリンク一覧**:\n' + '\n'.join(href_list))

    # テーブルの内容を確認
    tables = soup.find_all('table')
    send_discord(f'テーブル数: {len(tables)}')
    for i, table in enumerate(tables[:5]):
        rows = table.find_all('tr')
        # 最初の3行を表示
        preview = []
        for row in rows[:3]:
            cells = [td.get_text(strip=True) for td in row.find_all(['td','th'])]
            if cells:
                preview.append(' | '.join(cells[:6]))
        if preview:
            send_discord(f'テーブル[{i}] ({len(rows)}行):\n```\n' + '\n'.join(preview) + '\n```')

if __name__ == '__main__':
    main()
