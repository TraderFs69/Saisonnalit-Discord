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
    df = pd.read_csv("https://datahub.io/core/s-and-p-500-companies/r/constituents.csv")
    return df["Symbol"].str.replace(".", "-", regex=False).tolist()


@st.cache_data(ttl=86400)
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


def seasonality_doy(close, start_doy, end_doy):

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

    # 🔥 IMPORTANT : on assouplit
    if len(returns) < 3:
        return None

    s = pd.Series(returns)

    return {
        "mean": s.mean(),
        "winrate": (s > 0).mean() * 100,
        "count": len(s)
    }


def rank(data):
    if len(data) == 0:
        return pd.DataFrame()

    df = pd.DataFrame([
        {
            "ticker": t,
            "winrate": s["winrate"],
            "mean": s["mean"]
        }
        for t, s in data if s is not None
    ])

    if df.empty:
        return df

    return df.sort_values(by=["winrate", "mean"], ascending=False).head(10)


def send_to_discord(msg):
    r = requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    st.write("Discord status:", r.status_code)


# ---------------- UI ----------------
st.title("Saisonnalité TEA DEBUG")

if st.button("RUN"):

    tickers = fetch_sp500()[:100]  # 🔥 debug rapide

    today = datetime.today()
    current_month = today.month

    start_year = today.year - 15
    start_all = f"{start_year}-01-01"
    end_all = f"{today.year}-12-31"

    results_month = []

    debug_data_ok = 0

    for i, ticker in enumerate(tickers):

        close = get_data(ticker, start_all, end_all)

        if close is None:
            continue

        debug_data_ok += 1

        # MOIS
        start_doy = datetime(today.year, current_month, 1).timetuple().tm_yday
        end_doy = datetime(today.year, current_month, 28).timetuple().tm_yday

        stats = seasonality_doy(close, start_doy, end_doy)

        if stats:
            results_month.append((ticker, stats))

    # DEBUG
    st.write("Tickers avec données Polygon:", debug_data_ok)
    st.write("Résultats valides:", len(results_month))

    top = rank(results_month)

    if top.empty:
        st.error("AUCUN RESULTAT → problème logique ou API")
    else:
        st.dataframe(top)

        report = "SAISONNALITÉ TEA\n\n"

        for _, r in top.iterrows():
            report += f"{r['ticker']} | WR {round(r['winrate'])}% | {round(r['mean'],2)}%\n"

        if st.button("SEND"):
            send_to_discord(report)
            st.success("Envoyé")
