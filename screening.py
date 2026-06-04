import requests
from bs4 import BeautifulSoup
import time
import random
import os
import sys
import re
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
DISCORD_WEBHOOK = os.environ.get('DISCORD_WEBHOOK', '')
TARGET_MARKETS = ['プライム', 'スタンダード', 'グロース']
EXCLUDE_KEYWORDS = ['ETF', 'REIT', 'リート', 'ファンド', 'インフラ', 'eMAXIS']


def send_discord(message):
    if not DISCORD_WEBHOOK:
        print(message)
        return
    chunks = []
    while len(message) > 1900:
        pos = message[:1900].rfind('\n')
        if pos == -1:
            pos = 1900
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
        'Upgrade-Insecure-Requests': '1',
    })
    return session


def get_52week_highs(session):
    session.get('https://kabutan.jp/', timeout=20)
    time.sleep(random.uniform(2, 3))

    response = session.get('https://kabutan.jp/warning/?mode=52high', timeout=20)
    if response.status_code != 200:
        raise Exception(f'アクセス失敗: HTTP {response.status_code}')

    soup = BeautifulSoup(response.text, 'lxml')
    stocks = []
    seen = set()

    # 銘柄リンク（/stock/?code=XXXX）を全て取得
    links = soup.find_all('a', href=re.compile(r'/stock/\?code=\d{4}'))
    for link in links:
        code = re.search(r'code=(\d{4})', link['href'])
        if not code:
            continue
        code = code.group(1)
        if code in seen:
            continue
        seen.add(code)

        name = link.get_text(strip=True)
        if not name or any(kw in name for kw in EXCLUDE_KEYWORDS):
            continue

        # 親のtrから市場情報を取得
        row = link.find_parent('tr')
        market = ''
        if row:
            for td in row.find_all('td'):
                td_text = td.get_text(strip=True)
                if any(m in td_text for m in TARGET_MARKETS):
                    market = td_text
                    break

        # 市場フィルタ（情報があれば対象外除外）
        if market and not any(m in market for m in TARGET_MARKETS):
            continue

        stocks.append({'code': code, 'name': name, 'market': market})

    return stocks


def get_financial_growth(session, code):
    """直近決算の売上高・経常利益の前年比（%）を返す"""
    url = f'https://kabutan.jp/stock/finance?code={code}'
    res = session.get(url, timeout=20)
    if res.status_code != 200:
        return None, None

    soup = BeautifulSoup(res.text, 'lxml')

    sales_growth = None
    profit_growth = None

    # 株探の決算テーブルを解析
    # 「前年比」または「前期比」の行から%値を取得
    for table in soup.find_all('table'):
        text = table.get_text()
        if '売上高' not in text:
            continue

        rows = table.find_all('tr')
        metric = None

        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(['th', 'td'])]
            if not cells:
                continue

            first = cells[0]

            # 現在何の指標の行かを判定
            if '売上高' in first:
                metric = 'sales'
            elif '経常利益' in first:
                metric = 'profit'
            elif metric and ('前年比' in first or '前期比' in first or '前年同期比' in first):
                # 最初の数値（直近）を取得
                for cell in cells[1:]:
                    cell = cell.replace(',', '').replace('％', '').replace('%', '').strip()
                    try:
                        val = float(cell)
                        if -200 < val < 2000:  # 妥当な範囲
                            if metric == 'sales' and sales_growth is None:
                                sales_growth = val
                            elif metric == 'profit' and profit_growth is None:
                                profit_growth = val
                            break
                    except ValueError:
                        continue

        if sales_growth is not None and profit_growth is not None:
            break

    return sales_growth, profit_growth


def main():
    now = datetime.now(JST).strftime('%Y/%m/%d')
    print(f"=== スクリーニング開始 {now} ===")

    try:
        session = get_session()

        # Step1: 52週高値銘柄取得
        stocks = get_52week_highs(session)
        print(f"52週高値更新銘柄: {len(stocks)}件")

        if not stocks:
            send_discord(
                f'⚠️ **スクリーニングエラー** ({now})\n'
                '52週高値更新銘柄が取得できませんでした。\n'
                'サイト構造が変わった可能性があります。'
            )
            return

        # Step2: 決算チェック
        qualifying = []
        for i, s in enumerate(stocks):
            time.sleep(random.uniform(1.0, 2.0))
            try:
                sg, pg = get_financial_growth(session, s['code'])
                print(f"[{i+1}/{len(stocks)}] {s['code']} {s['name']} 売上:{sg} 経常:{pg}")
                if sg is not None and pg is not None and sg >= 10 and pg >= 20:
                    s['sales_growth'] = sg
                    s['profit_growth'] = pg
                    qualifying.append(s)
            except Exception as e:
                print(f"エラー ({s['code']}): {e}")

        # Step3: Discord通知
        if qualifying:
            lines = [
                f'📈 **本日の52週高値×好決算スクリーニング結果** ({now})\n',
                '✅ **条件:** 52週高値更新 / 売上高+10%以上 / 経常利益+20%以上\n',
                '---'
            ]
            for s in qualifying:
                lines.append(
                    f'【{s["code"]}】{s["name"]}（{s.get("market","不明")}）\n'
                    f'　売上高: +{s["sales_growth"]:.1f}%　経常利益: +{s["profit_growth"]:.1f}%\n'
                    f'　https://kabutan.jp/stock/?code={s["code"]}\n'
                )
            lines.append(f'---\n合計 {len(qualifying)}銘柄')
            send_discord('\n'.join(lines))
        else:
            send_discord(
                f'📊 **本日の52週高値×好決算スクリーニング結果** ({now})\n\n'
                f'本日は条件を満たす銘柄がありませんでした。\n'
                f'（52週高値更新銘柄数: {len(stocks)}銘柄）'
            )

    except Exception as e:
        import traceback
        tb = traceback.format_exc()[-800:]
        send_discord(
            f'⚠️ **スクリーニングエラー** ({now})\n'
            f'エラー: {str(e)}\n```\n{tb}\n```'
        )
        sys.exit(1)


if __name__ == '__main__':
    main()
