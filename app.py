​<details>
<summary>
import streamlit as st
import FinanceDataReader as fdr
import OpenDartReader
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import os

st.set_page_config(page_title="POR Master", page_icon="📈", layout="wide")

# API 키 설정 (Streamlit Secrets용)
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
def fetch_dart_data(_dart_client, s_code):
    fs_list = []
    current_year = datetime.now().year
    for year in range(current_year - 10, current_year):
        try:
            fs = _dart_client.finstate(s_code, year, reprt_code='11011')
            if fs is not None and not fs.empty:
                op = fs.loc[(fs['account_nm'].str.contains('영업이익')) & (fs['fs_div'].isin(['CFS', 'OFS']))]
                ni = fs.loc[(fs['account_nm'].str.contains('당기순이익')) & (fs['fs_div'].isin(['CFS', 'OFS']))]
                op_v = int(float(str(op.iloc[0]['thstrm_amount']).replace(',', ''))/100000000) if not op.empty else 0
                ni_v = int(float(str(ni.iloc[0]['thstrm_amount']).replace(',', ''))/100000000) if not ni.empty else 0
                if op_v != 0:
                    fs_list.append({'Date': f"{year}-12-31", '영업이익_억원': op_v, '당기순이익_억원': ni_v})
        except: continue
    return pd.DataFrame(fs_list)

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
                # 날짜 단위 통일 (에러 방지)
                hist['Date'] = pd.to_datetime(hist['Date']).dt.tz_localize(None).astype('datetime64[ns]')
                curr_price = hist['Close'].iloc[-1]
                shares = row['Stocks']
                mcap_billion = int((curr_price * shares) / 100000000)

                dart = OpenDartReader(DART_KEY)
                df_fs = fetch_dart_data(dart, s_code)
                df_fs['Date'] = pd.to_datetime(df_fs['Date']).astype('datetime64[ns]')
                
                if df_fs.empty:
                    st.warning("재무 데이터를 불러오지 못했습니다.")
                else:
                    st.title(f"🏢 {s_name} ({s_code}) 분석 결과")
                    now_por = (curr_price * shares) / (exp_profit * 100000000)
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
 </summary></details>
