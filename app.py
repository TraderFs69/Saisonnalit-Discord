import streamlit as st
import pandas as pd
from datetime import datetime
import requests
import time
import warnings
warnings.filterwarnings("ignore")

# ---------------- CONFIG ----------------
try:
    POLYGON_API_KEY = st.secrets["POLYGON_API_KEY"]
    DISCORD_WEBHOOK_URL = st.secrets["DISCORD_WEBHOOK_URL"]
except:
    st.error("Clés manquantes dans secrets.toml")
    st.stop()

# ---------------- UI ----------------
st.title("Saisonnalité S&P 500 (Polygon)")

col1, col2, col3 = st.columns(3)

with col1:
    n_years = st.number_input("Années", 1, 30, 15)
with col2:
    end_year = st.number_input("Fin", 2000, datetime.today().year, 2024)
with col3:
    debug_limit = st.number_input("Tickers", 0, 500, 0)

st.write("API Polygon connectée")

# ---------------- HELPERS ----------------
@st.cache_data(ttl=86400)
def fetch_sp500():
    url = "https://datahub.io/core/s-and-p-500-companies/r/constituents.csv"
    df = pd.read_csv(url)
    return df["Symbol"].str.replace(".", "-", regex=False).tolist()


@st.cache_data(ttl=86400)
def get_polygon_data(ticker, start, end):

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


def compute_seasonality(close, years, start_mmdd, end_mmdd):

    returns = []

    for y in years:
        try:
            start = pd.Timestamp(f"{y}-{start_mmdd}")
            end = pd.Timestamp(f"{y}-{end_mmdd}")

            df = close[(close.index >= start) & (close.index <= end)]

            if len(df) > 2:
                r = (df.iloc[-1] / df.iloc[0] - 1) * 100
                returns.append(r)

        except:
            continue

    if len(returns) == 0:
        return None

    s = pd.Series(returns)

    return {
        "mean": s.mean(),
        "winrate": (s > 0).mean() * 100,
        "count": len(s)
    }


def send_to_discord(msg):
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    except:
        pass


# ---------------- MAIN ----------------
if st.button("Lancer analyse"):

    tickers = fetch_sp500()

    if debug_limit:
        tickers = tickers[:debug_limit]

    start_year = end_year - n_years + 1
    years = list(range(start_year, end_year + 1))

    current_month = datetime.today().month
    month_str = f"{current_month:02d}"

    start_date = f"{start_year}-01-01"
    end_date = f"{end_year}-12-31"

    results = []

    progress = st.progress(0)

    for i, ticker in enumerate(tickers):

        close = get_polygon_data(ticker, start_date, end_date)

        if close is None or len(close) < 50:
            progress.progress((i + 1) / len(tickers))
            continue

        stats = compute_seasonality(
            close,
            years,
            f"{month_str}-01",
            f"{month_str}-28"
        )

        if stats:
            results.append({
                "ticker": ticker,
                "mean": stats["mean"],
                "winrate": stats["winrate"]
            })

        progress.progress((i + 1) / len(tickers))

        time.sleep(0.02)  # limite API


    if not results:
        st.warning("Aucun résultat")
        st.stop()

    df = pd.DataFrame(results).sort_values(by="mean", ascending=False)

    top10 = df.head(10)

    # ---------------- MOIS SUIVANT ----------------
    next_month = current_month + 1 if current_month < 12 else 1
    nm = f"{next_month:02d}"

    alt = []

    for ticker in tickers[:100]:

        close = get_polygon_data(ticker, start_date, end_date)

        if close is None:
            continue

        stats = compute_seasonality(close, years, f"{nm}-01", f"{nm}-28")

        if stats and stats["mean"] > 3 and stats["winrate"] > 65:
            alt.append((ticker, stats["mean"]))

    alt = sorted(alt, key=lambda x: x[1], reverse=True)[:5]

    # ---------------- REPORT ----------------
    report = "SAISONNALITÉ TEA\n\n"

    report += f"Mois: {month_str}\n\n"

    report += "Top 10:\n\n"
    for _, r in top10.iterrows():
        report += f"{r['ticker']} | {round(r['mean'],2)}% | WR {round(r['winrate'],0)}%\n"

    report += "\nÀ surveiller:\n\n"
    for t, m in alt:
        report += f"{t} | {round(m,2)}%\n"

    # ---------------- UI ----------------
    st.dataframe(top10, use_container_width=True)

    if st.button("Envoyer Discord"):
        send_to_discord(report)
        st.success("Envoyé dans Discord")
