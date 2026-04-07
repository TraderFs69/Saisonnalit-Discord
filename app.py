import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
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


# 🔥 LOGIQUE DOY (corrige tout)
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

    rows = []
    for t, s in data:
        if s is None:
            continue
        rows.append({
            "ticker": t,
            "winrate": s["winrate"],
            "mean": s["mean"]
        })

    if len(rows) == 0:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    return df.sort_values(
        by=["winrate", "mean"],
        ascending=False
    ).head(10)


def send_to_discord(msg):
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
        st.write("Discord status:", r.status_code)
    except Exception as e:
        st.write("Erreur Discord:", e)


# ---------------- UI ----------------
st.title("Saisonnalité TEA PRO (Polygon)")
st.write("Connexion API OK")

if st.button("RUN ANALYSE"):

    tickers = fetch_sp500()[:150]

    today = datetime.today()
    current_month = today.month

    start_year = today.year - 15
    start_all = f"{start_year}-01-01"
    end_all = f"{today.year}-12-31"

    results_month = []
    results_2w = []
    results_3m = []

    progress = st.progress(0)

    for i, ticker in enumerate(tickers):

        close = get_data(ticker, start_all, end_all)

        if close is None or len(close) < 50:
            progress.progress((i+1)/len(tickers))
            continue

        # -------- MOIS --------
        start_doy = datetime(today.year, current_month, 1).timetuple().tm_yday
        end_doy = datetime(today.year, current_month, 28).timetuple().tm_yday

        stats_m = seasonality_doy(close, start_doy, end_doy)
        if stats_m:
            results_month.append((ticker, stats_m))

        # -------- 2 SEMAINES --------
        start_doy = today.timetuple().tm_yday
        end_doy = (today + timedelta(days=14)).timetuple().tm_yday

        stats_2w = seasonality_doy(close, start_doy, end_doy)
        if stats_2w:
            results_2w.append((ticker, stats_2w))

        # -------- 3 MOIS --------
        end_3m = (today + timedelta(days=90)).timetuple().tm_yday

        stats_3m = seasonality_doy(close, start_doy, end_3m)
        if stats_3m:
            results_3m.append((ticker, stats_3m))

        progress.progress((i+1)/len(tickers))
        time.sleep(0.01)

    # -------- RANKING --------
    top_m = rank(results_month)
    top_2w = rank(results_2w)
    top_3m = rank(results_3m)

    # -------- DISPLAY --------
    st.subheader("📅 Mois courant")
    if not top_m.empty:
        st.dataframe(top_m)
    else:
        st.warning("Aucun résultat")

    st.subheader("📆 2 prochaines semaines")
    if not top_2w.empty:
        st.dataframe(top_2w)
    else:
        st.warning("Aucun résultat")

    st.subheader("📊 3 prochains mois")
    if not top_3m.empty:
        st.dataframe(top_3m)
    else:
        st.warning("Aucun résultat")

    # -------- DISCORD --------
    report = "SAISONNALITÉ TEA\n\n"

    def block(title, df):
        if df.empty:
            return f"{title}: Aucun résultat\n\n"
        txt = f"{title}:\n"
        for _, r in df.iterrows():
            txt += f"{r['ticker']} | WR {round(r['winrate'])}% | {round(r['mean'],2)}%\n"
        return txt + "\n"

    report += block("MOIS", top_m)
    report += block("2 SEMAINES", top_2w)
    report += block("3 MOIS", top_3m)

    if st.button("ENVOYER DISCORD"):
        send_to_discord(report)
        st.success("Envoyé dans Discord")
        
if st.button("TEST DISCORD"):
    r = requests.post(DISCORD_WEBHOOK_URL, json={"content": "TEST TEA"})
    st.write("Status:", r.status_code)
    st.write(r.text)
