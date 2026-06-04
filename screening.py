import yfinance as yf
import pandas as pd
import requests
import time
import os
import sys
import io
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

def get_jpx_stocks():
    """JPXから全上場銘柄リスト取得→プライム・スタンダード・グロースに絞る"""
    url = 'https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls'
    res = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
    res.raise_for_status()

    df = pd.read_excel(io.BytesIO(res.content))
    print(f"列名: {list(df.columns)}")

    market_col = next((c for c in df.columns if '市場' in str(c)), None)
    code_col   = next((c for c in df.columns if 'コード' in str(c)), None)
    name_col   = next((c for c in df.columns if '銘柄' in str(c) or '名称' in str(c)), None)

    if not market_col or not code_col:
        raise Exception(f"必要な列が見つかりません: {list(df.columns)}")

    target = ['プライム（内国株式）', 'スタンダード（内国株式）', 'グロース（内国株式）']
    filtered = df[df[market_col].isin(target)].copy()

    stocks = []
    for _, row in filtered.iterrows():
        try:
            code = str(int(float(row[code_col]))).zfill(4)
        except:
            continue
        name   = str(row[name_col]) if name_col else ''
        market = str(row[market_col]).replace('（内国株式）', '')
        stocks.append({'code': code, 'name': name, 'market': market})

    return stocks

def find_52week_highs(stocks):
    """yfinanceで1年分の株価を一括取得し52週高値更新銘柄を特定"""
    tickers = [s['code'] + '.T' for s in stocks]
    ticker_map = {s['code'] + '.T': s for s in stocks}
    results = []
    batch_size = 200

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        print(f"株価取得中: {i+1}〜{min(i+batch_size, len(tickers))}/{len(tickers)}")
        try:
            data = yf.download(batch, period='1y', progress=False,
                               threads=True, auto_adjust=True)
            if data.empty:
                continue

            if isinstance(data.columns, pd.MultiIndex):
                high = data['High']
            else:
                high = data[['High']].rename(columns={'High': batch[0]})

            for ticker in batch:
                if ticker not in high.columns:
                    continue
                series = high[ticker].dropna()
                if len(series) < 20:
                    continue
                today_high = series.iloc[-1]
                prev_high  = series.iloc[:-1].max()
                if today_high >= prev_high:
                    results.append(ticker_map[ticker])
        except Exception as e:
            print(f"バッチエラー: {e}")
        time.sleep(2)

    return results

def _calc_yoy(stmt, profit=False):
    """四半期データで前年同期比を計算"""
    keys = ['Operating Income', 'EBIT'] if profit else ['Total Revenue', 'Operating Revenue']
    for key in keys:
        if key in stmt.index:
            series = stmt.loc[key].dropna()
            if len(series) >= 5:
                latest, year_ago = series.iloc[0], series.iloc[4]
                if year_ago > 0:
                    return (latest - year_ago) / year_ago * 100
    return None

def _calc_yoy_annual(stmt, profit=False):
    """年次データで前年比を計算"""
    keys = ['Operating Income', 'EBIT'] if profit else ['Total Revenue', 'Operating Revenue']
    for key in keys:
        if key in stmt.index:
            series = stmt.loc[key].dropna()
            if len(series) >= 2:
                latest, prev = series.iloc[0], series.iloc[1]
                if prev > 0:
                    return (latest - prev) / prev * 100
    return None

def get_financials(code):
    """yfinanceで売上高・営業利益の前年比(%)を取得（四半期→年次の順で試す）"""
    try:
        ticker = yf.Ticker(code + '.T')

        # まず四半期データを試す
        q = ticker.quarterly_income_stmt
        if q is not None and not q.empty and q.shape[1] >= 5:
            sg = _calc_yoy(q, profit=False)
            pg = _calc_yoy(q, profit=True)
            if sg is not None and pg is not None:
                return sg, pg

        # 四半期がダメなら年次データにフォールバック
        a = ticker.income_stmt
        if a is not None and not a.empty and a.shape[1] >= 2:
            sg = _calc_yoy_annual(a, profit=False)
            pg = _calc_yoy_annual(a, profit=True)
            return sg, pg

        return None, None
    except:
        return None, None

def main():
    now = datetime.now(JST).strftime('%Y/%m/%d')
    print(f"=== スクリーニング開始 {now} ===")

    try:
        # Step1: 銘柄リスト取得
        stocks = get_jpx_stocks()
        print(f"対象銘柄: {len(stocks)}銘柄")
        send_discord(f'⏳ スクリーニング開始 ({now})\n対象: {len(stocks)}銘柄（プライム・スタンダード・グロース）\n完了まで15〜25分かかります。')

        # Step2: 52週高値更新銘柄を特定
        high_stocks = find_52week_highs(stocks)
        print(f"52週高値更新: {len(high_stocks)}銘柄")

        if not high_stocks:
            send_discord(f'📊 **スクリーニング結果** ({now})\n\n本日は52週高値更新銘柄がありませんでした。')
            return

        # Step3: 決算チェック
        print(f"決算確認中（{len(high_stocks)}銘柄）...")
        qualifying = []
        none_count = 0

        for i, s in enumerate(high_stocks):
            sg, pg = get_financials(s['code'])
            if sg is None or pg is None:
                none_count += 1
            print(f"[{i+1}/{len(high_stocks)}] {s['code']} {s['name']} 売上:{sg} 営業利益:{pg}")
            if sg is not None and pg is not None and sg >= 10 and pg >= 20:
                s['sales_growth']  = sg
                s['profit_growth'] = pg
                qualifying.append(s)
            time.sleep(0.3)

        print(f"財務データなし: {none_count}/{len(high_stocks)}銘柄")

        # Step4: Discord通知
        if qualifying:
            lines = [
                f'📈 **本日の52週高値×好決算スクリーニング結果** ({now})\n',
                '✅ **条件:** 52週高値更新 / 売上高+10%以上 / 営業利益+20%以上\n',
                '---'
            ]
            for s in qualifying:
                lines.append(
                    f'【{s["code"]}】{s["name"]}（{s.get("market","")}）\n'
                    f'　売上高: +{s["sales_growth"]:.1f}%　営業利益: +{s["profit_growth"]:.1f}%\n'
                    f'　https://kabutan.jp/stock/?code={s["code"]}\n'
                )
            lines.append(f'---\n合計 {len(qualifying)}銘柄')
            send_discord('\n'.join(lines))
        else:
            send_discord(
                f'📊 **本日の52週高値×好決算スクリーニング結果** ({now})\n\n'
                f'条件を満たす銘柄がありませんでした。\n'
                f'（52週高値更新: {len(high_stocks)}銘柄　財務データあり: {len(high_stocks)-none_count}銘柄　条件合致: 0銘柄）'
            )

    except Exception as e:
        import traceback
        send_discord(
            f'⚠️ **エラー** ({now})\n{str(e)}\n```\n{traceback.format_exc()[-600:]}\n```'
        )
        sys.exit(1)

if __name__ == '__main__':
    main()
