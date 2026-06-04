from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time, random, os, sys, re, requests
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
DISCORD_WEBHOOK = os.environ.get('DISCORD_WEBHOOK', '')
TARGET_MARKETS = ['プライム', 'スタンダード', 'グロース']
EXCLUDE_KEYWORDS = ['ETF', 'REIT', 'リート', 'ファンド', 'インフラ', 'eMAXIS']

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

def get_52week_highs():
    stocks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='ja-JP'
        )
        page = context.new_page()
        page.goto('https://kabutan.jp/', wait_until='networkidle', timeout=30000)
        time.sleep(2)
        page.goto('https://kabutan.jp/warning/?mode=52high', wait_until='networkidle', timeout=30000)
        time.sleep(3)
        content = page.content()
        browser.close()

    soup = BeautifulSoup(content, 'lxml')
    seen = set()

    for a in soup.find_all('a', href=re.compile(r'/stock/\?code=\d{4}')):
        m = re.search(r'code=(\d{4})', a['href'])
        if not m: continue
        code = m.group(1)
        if code in seen or int(code) < 1000: continue
        seen.add(code)

        name = a.get_text(strip=True)
        if not name or any(kw in name for kw in EXCLUDE_KEYWORDS): continue

        row = a.find_parent('tr')
        market = ''
        if row:
            for td in row.find_all('td'):
                td_text = td.get_text(strip=True)
                if any(mk in td_text for mk in TARGET_MARKETS):
                    market = td_text
                    break

        if market and not any(mk in market for mk in TARGET_MARKETS):
            continue

        stocks.append({'code': code, 'name': name, 'market': market})

    return stocks

def get_financial_growth(session, code):
    res = session.get(f'https://kabutan.jp/stock/finance?code={code}', timeout=20)
    if res.status_code != 200:
        return None, None

    soup = BeautifulSoup(res.text, 'lxml')
    sales_growth = None
    profit_growth = None

    for table in soup.find_all('table'):
        if '売上高' not in table.get_text():
            continue
        rows = table.find_all('tr')
        metric = None
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(['th', 'td'])]
            if not cells: continue
            first = cells[0]
            if '売上高' in first: metric = 'sales'
            elif '経常利益' in first: metric = 'profit'
            elif metric and any(x in first for x in ['前年比', '前期比', '前年同期比']):
                for cell in cells[1:]:
                    clean = cell.replace(',', '').replace('％', '').replace('%', '').strip()
                    try:
                        val = float(clean)
                        if -500 < val < 5000:
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
        stocks = get_52week_highs()
        print(f"取得銘柄数: {len(stocks)}")

        if not stocks:
            send_discord(f'⚠️ **スクリーニングエラー** ({now})\n銘柄が取得できませんでした。')
            return

        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'ja,en-US;q=0.9',
        })

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
        send_discord(
            f'⚠️ **スクリーニングエラー** ({now})\n'
            f'エラー: {str(e)}\n```\n{traceback.format_exc()[-800:]}\n```'
        )
        sys.exit(1)

if __name__ == '__main__':
    main()
