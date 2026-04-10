import streamlit as st
import FinanceDataReader as fdr
import OpenDartReader
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import os

# 1. 페이지 설정
st.set_page_config(page_title="POR Master", page_icon="📈", layout="wide")

# 2. API 키 설정 (Streamlit Secrets 우선, 없으면 사이드바 입력)
DART_KEY = os.environ.get('DART_API_KEY')

st.sidebar.header("⚙️ 분석 설정")
if not DART_KEY:
    DART_KEY = st.sidebar.text_input("DART API KEY", type="password", help="Streamlit Secrets에 키를 설정하면 이 창이 사라집니다.")

company_name = st.sidebar.text_input("회사 이름", placeholder="예: 씨에스윈드")
# [추가] 종목 리스트 로딩 실패 대비용 수동 코드 입력
manual_code = st.sidebar.text_input("종목코드 (선택)", placeholder="리스트 로딩 실패 시 직접 입력 (예: 112610)")
exp_profit = st.sidebar.number_input("올해 예상 영업이익 (억원)", value=0)
target_price = st.sidebar.number_input("목표 주가 (원)", value=0)

# 3. 데이터 로딩 함수 (에러 방지 강화)
@st.cache_data(ttl=3600)
def get_krx_list():
    try:
        # 가장 안정적인 방식으로 시도
        df = fdr.StockListing('KRX')
        if df is None or df.empty:
            return fdr.StockListing('KOSPI') # 코스피라도 시도
        return df
    except:
        return pd.DataFrame() # 실패 시 빈 상자 반환

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

# 4. 분석 실행 부분
if st.sidebar.button("분석 실행"):
    if not DART_KEY:
        st.error("DART API 키를 입력해주세요.")
    elif not company_name and not manual_code:
        st.error("회사 이름 또는 종목코드를 입력해주세요.")
    elif exp_profit <= 0:
        st.error("예상 영업이익을 입력해주세요.")
    else:
        with st.spinner('데이터 분석 중...'):
            s_code = None
            s_name = company_name
            
            # 종목코드 찾기 로직
            if manual_code:
                s_code = manual_code
            else:
                df_krx = get_krx_list()
                if not df_krx.empty and 'Name' in df_krx.columns:
                    s_term = company_name.replace(" ", "").upper()
                    target = df_krx[df_krx['Name'].str.replace(" ", "").str.upper().str.contains(s_term)]
                    if not target.empty:
                        row = target.iloc[0]
                        s_name, s_code = row['Name'], row['Code']
                
            if not s_code:
                st.error("종목을 찾을 수 없습니다. 종목코드를 직접 입력해 보세요.")
                st.stop()

            # 주가 데이터 (yfinance)
            yf_ticker = f"{s_code}.KS" # 기본 코스피 시도
            stock = yf.Ticker(yf_ticker)
            hist = stock.history(period="10y")
            
            if hist.empty: # 코스닥 시도
                yf_ticker = f"{s_code}.KQ"
                stock = yf.Ticker(yf_ticker)
                hist = stock.history(period="10y")

            if hist.empty:
                st.error("주가 데이터를 가져오지 못했습니다.")
                st.stop()

            hist = hist.reset_index()
            hist['Date'] = pd.to_datetime(hist['Date']).dt.tz_localize(None).astype('datetime64[ns]')
            curr_price = hist['Close'].iloc[-1]
            
            # 재무 데이터 (DART)
            dart = OpenDartReader(DART_KEY)
            df_fs = fetch_dart_data(dart, s_code)
            
            if df_fs.empty:
                st.warning("과거 재무 데이터를 불러오지 못했습니다. (DART 서버 응답 확인 필요)")
            else:
                df_fs['Date'] = pd.to_datetime(df_fs['Date']).astype('datetime64[ns]')
                st.title(f"🏢 {s_name} ({s_code}) 분석 리포트")
                
                # 시가총액 계산 (주식수 정보가 없을 경우 대비)
                shares = 1 # 기본값
                try:
                    shares_info = stock.info.get('sharesOutstanding', 0)
                    if shares_info > 0: shares = shares_info
                except: pass
                
                mcap_billion = int((curr_price * shares) / 100000000)
                now_por = (curr_price * shares) / (exp_profit * 100000000) if exp_profit > 0 else 0
                
                c1, c2, c3 = st.columns(3)
                c1.metric("현재가", f"{curr_price:,.0f}원")
                c2.metric("예상 POR", f"{now_por:.2f}배")
                c3.metric("올해 예상익", f"{exp_profit:,.0f}억")
                
                # 그래프 그리기
                hist['MarketCap'] = hist['Close'] * shares
                merged = pd.merge_asof(hist.sort_values('Date'), df_fs.sort_values('Date'), on='Date', direction='backward')
                merged['POR'] = merged['MarketCap'] / (merged['영업이익_억원'] * 100000000)
                avg_p = merged['POR'].mean()

                fig = go.Figure()
                fig.add_trace(go.Scatter(x=merged['Date'], y=merged['POR'], name='과거 POR', line=dict(color='gray', width=1)))
                fig.add_hline(y=avg_p, line_dash="dot", annotation_text="평균 POR")
                fig.add_hline(y=now_por, line_color="red", line_width=3, annotation_text="현재 POR")
                
                if target_price > 0:
                    t_por = (target_price * shares) / (exp_profit * 100000000)
                    fig.add_hline(y=t_por, line_color="blue", line_dash="dash", annotation_text="목표가 POR")
                
                fig.update_layout(title="📈 POR 밴드 히스토리", template="plotly_white")
                st.plotly_chart(fig, use_container_width=True)
                
                st.subheader("📋 과거 실적 요약 (억원)")
                st.table(df_fs.tail(5).set_index('Date').T)
