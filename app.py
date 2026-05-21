import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import requests
import warnings

warnings.filterwarnings("ignore")

# ======================================================
# CONFIG
# ======================================================
st.set_page_config(
    page_title="TEA Saisonnalité PRO",
    layout="wide"
)

# ======================================================
# SECRETS
# ======================================================
try:
    POLYGON_API_KEY = st.secrets["POLYGON_API_KEY"]
    DISCORD_WEBHOOK_URL = st.secrets["DISCORD_WEBHOOK_URL"]

except Exception as e:

    st.error(f"❌ Secrets manquants : {e}")

    st.stop()

# ======================================================
# UI
# ======================================================
st.title("📈 Saisonnalité TEA PRO (Polygon)")

st.write(
    f"🕒 Dernière mise à jour : "
    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
)

# ======================================================
# SESSION STATE
# ======================================================
if "top_m" not in st.session_state:
    st.session_state.top_m = pd.DataFrame()

if "top_2w" not in st.session_state:
    st.session_state.top_2w = pd.DataFrame()

if "top_3m" not in st.session_state:
    st.session_state.top_3m = pd.DataFrame()

# ======================================================
# FETCH SP500
# ======================================================
@st.cache_data(ttl=3600)
def fetch_sp500():

    url = (
        "https://raw.githubusercontent.com/"
        "datasets/s-and-p-500-companies/"
        "master/data/constituents.csv"
    )

    try:

        df = pd.read_csv(url)

        symbols = (
            df["Symbol"]
            .astype(str)
            .str.replace(".", "-", regex=False)
            .tolist()
        )

        return symbols

    except Exception as e:

        st.error(f"❌ Erreur chargement SP500 : {e}")

        return []

# ======================================================
# POLYGON DATA
# ======================================================
@st.cache_data(ttl=1800)
def get_data(ticker, start, end):

    url = (
        f"https://api.polygon.io/v2/aggs/ticker/"
        f"{ticker}/range/1/day/"
        f"{start}/{end}"
        f"?adjusted=true"
        f"&sort=asc"
        f"&limit=5000"
        f"&apiKey={POLYGON_API_KEY}"
    )

    try:

        r = requests.get(url, timeout=10)

        if r.status_code != 200:

            print(f"{ticker} status error: {r.status_code}")

            return None

        data = r.json()

        if "results" not in data:
            return None

        df = pd.DataFrame(data["results"])

        if df.empty:
            return None

        df["Date"] = pd.to_datetime(df["t"], unit="ms")

        df.set_index("Date", inplace=True)

        return df["c"]

    except Exception as e:

        print(f"{ticker} data error: {e}")

        return None

# ======================================================
# SEASONALITY
# ======================================================
def seasonality_doy(close, start_doy, end_doy):

    df = close.to_frame("c").copy()

    df["doy"] = df.index.dayofyear

    df["year"] = df.index.year

    returns = []

    for y in df["year"].unique():

        df_year = df[df["year"] == y]

        if start_doy <= end_doy:

            window = df_year[
                (df_year["doy"] >= start_doy)
                &
                (df_year["doy"] <= end_doy)
            ]

        else:

            window = df_year[
                (df_year["doy"] >= start_doy)
                |
                (df_year["doy"] <= end_doy)
            ]

        if len(window) > 2:

            r = (
                window["c"].iloc[-1]
                /
                window["c"].iloc[0]
                - 1
            ) * 100

            returns.append(r)

    if len(returns) < 3:
        return None

    s = pd.Series(returns)

    return {
        "mean": s.mean(),
        "winrate": (s > 0).mean() * 100,
        "count": len(s)
    }

# ======================================================
# RANKING
# ======================================================
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

    return (
        df.sort_values(
            by=["winrate", "mean"],
            ascending=False
        )
        .head(10)
        .reset_index(drop=True)
    )

# ======================================================
# DISCORD
# ======================================================
def send_block(title, df):

    if df.empty:

        msg = f"**{title}**\nAucun résultat"

    else:

        msg = f"**{title}**\n\n"

        for _, r in df.iterrows():

            msg += (
                f"`{r['ticker']}` | "
                f"WR {round(r['winrate'])}% | "
                f"{round(r['mean'], 2)}%\n"
            )

    try:

        r = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": msg},
            timeout=10
        )

        st.write(
            f"{title} envoyé | "
            f"Status: {r.status_code}"
        )

    except Exception as e:

        st.error(f"Discord error: {e}")

# ======================================================
# RUN
# ======================================================
if st.button("🚀 RUN ANALYSE"):

    tickers = fetch_sp500()

    if len(tickers) == 0:

        st.error("❌ Aucun ticker chargé")

        st.stop()

    # DEBUG
    tickers = tickers[:150]

    st.success(f"✅ {len(tickers)} tickers chargés")

    today = datetime.today()

    current_month = today.month

    start_year = today.year - 15

    start_all = f"{start_year}-01-01"

    end_all = f"{today.year}-12-31"

    results_month = []

    results_2w = []

    results_3m = []

    progress = st.progress(0)

    status = st.empty()

    for i, ticker in enumerate(tickers):

        status.text(
            f"Analyse {ticker} "
            f"({i + 1}/{len(tickers)})"
        )

        close = get_data(
            ticker,
            start_all,
            end_all
        )

        if close is None or len(close) < 50:

            progress.progress(
                (i + 1) / len(tickers)
            )

            continue

        # ======================================================
        # MOIS
        # ======================================================
        try:

            start_doy = datetime(
                today.year,
                current_month,
                1
            ).timetuple().tm_yday

            end_doy = datetime(
                today.year,
                current_month,
                28
            ).timetuple().tm_yday

            stats_m = seasonality_doy(
                close,
                start_doy,
                end_doy
            )

            if stats_m:
                results_month.append(
                    (ticker, stats_m)
                )

        except:
            pass

        # ======================================================
        # 2 SEMAINES
        # ======================================================
        try:

            start_doy = (
                today.timetuple().tm_yday
            )

            end_doy = (
                today + timedelta(days=14)
            ).timetuple().tm_yday

            stats_2w = seasonality_doy(
                close,
                start_doy,
                end_doy
            )

            if stats_2w:
                results_2w.append(
                    (ticker, stats_2w)
                )

        except:
            pass

        # ======================================================
        # 3 MOIS
        # ======================================================
        try:

            end_3m = (
                today + timedelta(days=90)
            ).timetuple().tm_yday

            stats_3m = seasonality_doy(
                close,
                start_doy,
                end_3m
            )

            if stats_3m:
                results_3m.append(
                    (ticker, stats_3m)
                )

        except:
            pass

        progress.progress(
            (i + 1) / len(tickers)
        )

    # ======================================================
    # STORE
    # ======================================================
    st.session_state.top_m = rank(results_month)

    st.session_state.top_2w = rank(results_2w)

    st.session_state.top_3m = rank(results_3m)

    st.success("✅ Analyse terminée")

# ======================================================
# DISPLAY
# ======================================================
st.subheader("📅 Mois courant")

if not st.session_state.top_m.empty:
    st.dataframe(
        st.session_state.top_m,
        use_container_width=True
    )

st.subheader("📆 2 semaines")

if not st.session_state.top_2w.empty:
    st.dataframe(
        st.session_state.top_2w,
        use_container_width=True
    )

st.subheader("📊 3 mois")

if not st.session_state.top_3m.empty:
    st.dataframe(
        st.session_state.top_3m,
        use_container_width=True
    )

# ======================================================
# DISCORD
# ======================================================
if st.button("📨 ENVOYER DISCORD"):

    send_block(
        "📅 MOIS",
        st.session_state.top_m
    )

    send_block(
        "📆 2 SEMAINES",
        st.session_state.top_2w
    )

    send_block(
        "📊 3 MOIS",
        st.session_state.top_3m
    )

    st.success("🚀 Envoyé dans Discord")

# ======================================================
# CLEAR CACHE
# ======================================================
if st.button("🧹 Vider le cache"):

    st.cache_data.clear()

    st.success("✅ Cache vidé")
