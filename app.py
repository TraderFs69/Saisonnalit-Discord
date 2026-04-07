import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import requests
import time

# ---------------- CONFIG ----------------
POLYGON_API_KEY = st.secrets["POLYGON_API_KEY"]
DISCORD_WEBHOOK_URL = st.secrets["DISCORD_WEBHOOK_URL"]

# ---------------- HELPERS ----------------
@st.cache_data(ttl=86400)
def fetch_sp500():
    url = "https://datahub.io/core/s-and-p-500-companies/r/constituents.csv"
    df = pd.read_csv(url)
    return df["Symbol"].str.replace(".", "-", regex=False).tolist()


@st.cache_data(ttl=86400)
def get_data(ticker, start, end):
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}?adjusted=true&sort=asc&limit=5000&apiKey={POLYGON_API_KEY}"
    r = requests.get(url)
    data = r.json()

    if "results" not in data:
        return None

    df = pd.DataFrame(data["results"])
    df["Date"] = pd.to_datetime(df["t"], unit="ms")
    df.set_index("Date", inplace=True)

    return df["c"]


def seasonality(close, years, start_md, end_md):
    returns = []

    for y in years:
        try:
            start = pd.Timestamp(f"{y}-{start_md}")
            end = pd.Timestamp(f"{y}-{end_md}")

            df = close[(close.index >= start) & (close.index <= end)]

            if len(df) > 2:
                r = (df.iloc[-1] / df.iloc[0] - 1) * 100
                returns.append(r)
        except:
            continue

    if len(returns) < 10:
        return None

    s = pd.Series(returns)

    return {
        "mean": s.mean(),
        "winrate": (s > 0).mean() * 100,
        "count": len(s)
    }


def send_to_discord(msg):
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
        print(r.status_code, r.text)
    except Exception as e:
        print(e)


# ---------------- MAIN ----------------
if st.button("RUN TEA SAISONNALITÉ"):

    tickers = fetch_sp500()[:200]  # limiter pour vitesse

    today = datetime.today()
    current_month = today.month

    start_year = today.year - 15
    years = list(range(start_year, today.year + 1))

    start_all = f"{start_year}-01-01"
    end_all = f"{today.year}-12-31"

    results_month = []
    results_2w = []
    results_3m = []

    for i, t in enumerate(tickers):

        close = get_data(t, start_all, end_all)
        if close is None:
            continue

        # ---------------- MOIS ----------------
        m = f"{current_month:02d}"
        stats_m = seasonality(close, years, f"{m}-01", f"{m}-28")

        if stats_m:
            results_month.append((t, stats_m))

        # ---------------- 2 SEMAINES ----------------
        start_2w = today.strftime("%m-%d")
        end_2w = (today + timedelta(days=14)).strftime("%m-%d")

        stats_2w = seasonality(close, years, start_2w, end_2w)

        if stats_2w:
            results_2w.append((t, stats_2w))

        # ---------------- 3 MOIS ----------------
        future = today + timedelta(days=90)
        stats_3m = seasonality(close, years, start_2w, future.strftime("%m-%d"))

        if stats_3m:
            results_3m.append((t, stats_3m))

        time.sleep(0.01)

    def rank(data):
        df = pd.DataFrame([
            {
                "ticker": t,
                "winrate": s["winrate"],
                "mean": s["mean"]
            }
            for t, s in data
        ])

        return df.sort_values(
            by=["winrate", "mean"],
            ascending=False
        ).head(10)

    top_m = rank(results_month)
    top_2w = rank(results_2w)
    top_3m = rank(results_3m)

    # ---------------- DISCORD ----------------
    report = "SAISONNALITÉ TEA\n\n"

    report += "MOIS:\n"
    for _, r in top_m.iterrows():
        report += f"{r['ticker']} | WR {round(r['winrate'])}% | {round(r['mean'],2)}%\n"

    report += "\n2 SEMAINES:\n"
    for _, r in top_2w.iterrows():
        report += f"{r['ticker']} | WR {round(r['winrate'])}% | {round(r['mean'],2)}%\n"

    report += "\n3 MOIS:\n"
    for _, r in top_3m.iterrows():
        report += f"{r['ticker']} | WR {round(r['winrate'])}% | {round(r['mean'],2)}%\n"

    st.dataframe(top_m)

    if st.button("SEND DISCORD"):
        send_to_discord(report)
        st.success("Envoyé")
