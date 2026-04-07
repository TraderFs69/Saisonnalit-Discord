import pandas as pd
from datetime import datetime, timedelta
import requests
import time
import os

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def fetch_sp500():
    df = pd.read_csv("https://datahub.io/core/s-and-p-500-companies/r/constituents.csv")
    return df["Symbol"].str.replace(".", "-", regex=False).tolist()

def get_data(ticker, start, end):
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}?adjusted=true&sort=asc&limit=5000&apiKey={POLYGON_API_KEY}"
    try:
        r = requests.get(url)
        data = r.json()
        if "results" not in data:
            return None
        df = pd.DataFrame(data["results"])
        df["Date"] = pd.to_datetime(df["t"], unit="ms")
        df.set_index("Date", inplace=True)
        return df["c"]
    except:
        return None

def seasonality(close, start_doy, end_doy):

    df = close.to_frame("c").copy()
    df["doy"] = df.index.dayofyear
    df["year"] = df.index.year

    returns = []

    for y in df["year"].unique():
        df_year = df[df["year"] == y]

        if start_doy <= end_doy:
            window = df_year[(df_year["doy"] >= start_doy) & (df_year["doy"] <= end_doy)]
        else:
            window = df_year[(df_year["doy"] >= start_doy) | (df_year["doy"] <= end_doy)]

        if len(window) > 2:
            r = (window["c"].iloc[-1] / window["c"].iloc[0] - 1) * 100
            returns.append(r)

    if len(returns) < 3:
        return None

    s = pd.Series(returns)

    return {
        "mean": s.mean(),
        "winrate": (s > 0).mean() * 100
    }

def rank(data):
    df = pd.DataFrame([
        {"ticker": t, "winrate": s["winrate"], "mean": s["mean"]}
        for t, s in data if s
    ])
    return df.sort_values(by=["winrate","mean"], ascending=False).head(10)

def send(title, df):
    msg = f"**{title}**\n"
    for _, r in df.iterrows():
        msg += f"{r['ticker']} | WR {round(r['winrate'])}% | {round(r['mean'],2)}%\n"
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})

# -------- RUN --------
today = datetime.today()
tickers = fetch_sp500()[:150]

start_year = today.year - 15
start_all = f"{start_year}-01-01"
end_all = f"{today.year}-12-31"

results_m, results_2w, results_3m = [], [], []

for t in tickers:
    close = get_data(t, start_all, end_all)
    if close is None:
        continue

    # mois
    start = datetime(today.year, today.month, 1).timetuple().tm_yday
    end = datetime(today.year, today.month, 28).timetuple().tm_yday
    s = seasonality(close, start, end)
    if s: results_m.append((t, s))

    # 2 semaines
    start = today.timetuple().tm_yday
    end = (today + timedelta(days=14)).timetuple().tm_yday
    s = seasonality(close, start, end)
    if s: results_2w.append((t, s))

    # 3 mois
    end = (today + timedelta(days=90)).timetuple().tm_yday
    s = seasonality(close, start, end)
    if s: results_3m.append((t, s))

send("MOIS", rank(results_m))
send("2 SEMAINES", rank(results_2w))
send("3 MOIS", rank(results_3m))
