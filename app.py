import streamlit as st
import FinanceDataReader as fdr
import OpenDartReader
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import os

# 페이지 설정
st.set_page_config(page_title="POR Master", page_icon="📈", layout="wide")

# API 키 설정 (Streamlit Secrets에서 가져오기)
DART_KEY = os.environ.get('DART_API_KEY')

st.sidebar.header("⚙️ 분석 설정")
if not DART_KEY:
    DART_KEY = st.sidebar.text_input("DART API KEY", type="password")

company_name = st.sidebar.text_input("회사 이름", placeholder="예: 현대차")
exp_profit = st.sidebar.number_input("올해 예상 영업이익 (억원)", value=0)
target_price = st.sidebar.number_input("목표 주가 (원)", value=0)

@st.cache_data(ttl=3600)
def get_krx_list():
    return fdr.StockListing('KRX')

@st.cache_data(ttl=3600)
def get_krx_list():
    try:
        # KRX 전체 대신 코스피, 코스닥을 각각 가져와서 합칩니다.
        df_kospi = fdr.StockListing('KOSPI')
        df_kosdaq = fdr.StockListing('KOSDAQ')
        return pd.concat([df_kospi, df_kosdaq])
    except Exception as e:
        # 위 방법도 실패할 경우를 대비해 빈 데이터프레임 대신 에러 메시지를 띄웁니다.
        st.error(f"종목 리스트를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요. ({e})")
        return pd.DataFrame()


if st.sidebar.button("분석 실행"):
    if not DART_KEY or not company_name or exp_profit <= 0:
        st.error("정보를 모두 입력해주세요!")
    else:
        with st.spinner('데이터 분석 중...'):
            df_krx = get_krx_list()
            s_term = company_name.replace(" ", "").upper()
            target = df_krx[df_krx['Name'].str.replace(" ", "").str.upper().str.contains(s_term)]
            
            if target.empty:
                st.error("종목을 찾을 수 없습니다.")
            else:
                row = target.iloc[0]
                s_name, s_code = row['Name'], row['Code']
                yf_ticker = f"{s_code}.KS" if row['Market'] == 'KOSPI' else f"{s_code}.KQ"
                
                stock = yf.Ticker(yf_ticker)
                hist = stock.history(period="10y").reset_index()
                hist['Date'] = pd.to_datetime(hist['Date']).dt.tz_localize(None).astype('datetime64[ns]')
                curr_price = hist['Close'].iloc[-1]
                shares = row['Stocks']
                mcap_billion = int((curr_price * shares) / 100000000)

                dart = OpenDartReader(DART_KEY)
                df_fs = fetch_dart_data(dart, s_code)
                
                if df_fs.empty:
                    st.warning("재무 데이터를 불러오지 못했습니다.")
                else:
                    df_fs['Date'] = pd.to_datetime(df_fs['Date']).astype('datetime64[ns]')
                    st.title(f"🏢 {s_name} ({s_code}) 분석 리포트")
                    
                    latest_ni = df_fs.iloc[-1]['당기순이익_억원']
                    curr_per = mcap_billion / latest_ni if latest_ni > 0 else 0
                    now_por = (curr_price * shares) / (exp_profit * 100000000)
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("현재가", f"{curr_price:,.0f}원")
                    c2.metric("시가총액", f"{mcap_billion:,.0f}억")
                    c3.metric("현재 PER", f"{curr_per:.2f}배")
                    
                    st.info(f"🔥 현재가 기준 POR: **{now_por:.2f}배**")

                    hist['MarketCap'] = hist['Close'] * shares
                    merged = pd.merge_asof(hist.sort_values('Date'), df_fs.sort_values('Date'), on='Date', direction='backward')
                    merged['POR'] = merged['MarketCap'] / (merged['영업이익_억원'] * 100000000)
                    avg_p = merged['POR'].mean()

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=merged['Date'], y=merged['POR'], name='POR history'))
                    fig.add_hline(y=avg_p, line_dash="dot", annotation_text="Average")
                    fig.add_hline(y=now_por, line_color="red", line_width=3, annotation_text="Current")
                    st.plotly_chart(fig, use_container_width=True)
                    
                    st.table(df_fs.tail(5).set_index('Date').T)
