import streamlit as st
import FinanceDataReader as fdr
import OpenDartReader
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import os
import time

# 1. 페이지 기본 설정
st.set_page_config(page_title="10Y POR Analyzer", page_icon="📈", layout="wide")

# 2. 보안 비밀 설정 (DART 키)
DART_KEY = os.environ.get('DART_API_KEY')

# 3. 사이드바 구성
st.sidebar.header("⚙️ 분석 설정")
if not DART_KEY:
    DART_KEY = st.sidebar.text_input("DART API KEY", type="password")

company_name = st.sidebar.text_input("회사 이름", placeholder="예: 삼성전자")
manual_code = st.sidebar.text_input("종목코드 직접입력 (선택)", placeholder="예: 005930")
exp_profit = st.sidebar.number_input("올해 예상 영업이익 (억원)", value=None, placeholder="예상익 입력")
target_price = st.sidebar.number_input("목표 주가 (원)", value=None, placeholder="목표가 입력")

# 4. 고속화를 위한 캐시 함수들
@st.cache_data(ttl=3600)
def get_stock_list():
    try:
        return fdr.StockListing('KRX')
    except:
        return pd.DataFrame()

@st.cache_resource
def get_dart(key):
    try: return OpenDartReader(key)
    except: return None

@st.cache_data(ttl=86400) # 재무 데이터는 하루 동안 저장
def fetch_10y_data(_dart, s_code):
    fs_list = []
    curr_year = datetime.now().year
    
    # 진행 상황을 사용자에게 보여줍니다 (지루함 방지)
    progress_text = st.empty()
    bar = st.progress(0)
    
    for i, year in enumerate(range(curr_year - 10, curr_year)):
        progress_text.text(f"🔍 {year}년 재무제표 읽는 중... ({i+1}/10)")
        bar.progress((i + 1) / 10)
        try:
            # DART 서버에 부담을 주지 않기 위한 아주 짧은 휴식
            time.sleep(0.1)
            fs = _dart.finstate(s_code, year, reprt_code='11011')
            if fs is not None and not fs.empty:
                op = fs.loc[fs['account_nm'].str.contains('영업이익')].iloc[0]
                val = int(float(str(op['thstrm_amount']).replace(',',''))/100000000)
                if val != 0:
                    fs_list.append({'Date': pd.to_datetime(f"{year}-12-31"), 'OP': val})
        except: continue
        
    progress_text.empty()
    bar.empty()
    return pd.DataFrame(fs_list)

# 5. 실행 로직
if st.sidebar.button("10년 데이터 분석 시작"):
    if not DART_KEY or (not company_name and not manual_code) or exp_profit is None:
        st.error("설정창에 내용을 모두 입력해주세요!")
        st.stop()

    with st.spinner('🎯 10년 치 데이터를 수집하고 있습니다. 잠시만 기다려주세요...'):
        # (1) 종목 찾기
        s_code = manual_code
        display_name = company_name
        if not s_code:
            df_krx = get_stock_list()
            if not df_krx.empty:
                target = df_krx[df_krx['Name'].str.contains(company_name.replace(" ",""))]
                if not target.empty:
                    s_code = target.iloc[0]['Code']
                    display_name = target.iloc[0]['Name']
        
        if not s_code:
            st.error("종목을 찾을 수 없습니다. 종목코드를 직접 입력해 보세요.")
            st.stop()

        # (2) 주가 데이터 (10년)
        ticker = f"{s_code}.KS" if not s_code.startswith('0') else f"{s_code}.KQ"
        hist = yf.Ticker(ticker).history(period="10y")
        if hist.empty:
            ticker = f"{s_code}.KQ" if ".KS" in ticker else f"{s_code}.KS"
            hist = yf.Ticker(ticker).history(period="10y")

        # (3) DART 데이터 (10년)
        dart = get_dart(DART_KEY)
        if not dart:
            st.error("DART 서버 연결 실패. 잠시 후 Reboot 해주세요.")
            st.stop()
            
        df_fs = fetch_10y_data(dart, s_code)
        
        if df_fs.empty:
            st.warning("재무 데이터를 가져오지 못했습니다. 종목코드를 다시 확인해 주세요.")
            st.stop()

        # (4) 결과 대시보드
        st.title(f"🏢 {display_name} ({s_code}) 10년 POR 리포트")
        
        curr_price = hist['Close'].iloc[-1]
        shares = yf.Ticker(ticker).info.get('sharesOutstanding', 1)
        now_por = (curr_price * shares) / (exp_profit * 100000000)
        
        col1, col2, col3 = st.columns(3)
        col1.metric("현재 주가", f"{curr_price:,.0f}원")
        col2.metric("현재 POR (예상익 기준)", f"{now_por:.2f}배")
        col3.metric("올해 예상 영업이익", f"{exp_profit:,.0f}억")

        # (5) 10년 POR 히스토리 그래프
        hist = hist.reset_index()
        hist['Date'] = pd.to_datetime(hist['Date']).dt.tz_localize(None)
        hist['MCap'] = hist['Close'] * shares
        merged = pd.merge_asof(hist.sort_values('Date'), df_fs.sort_values('Date'), on='Date', direction='backward')
        merged['POR'] = merged['MCap'] / (merged['OP'] * 100000000)
        
        avg_por = merged['POR'].mean()

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=merged['Date'], y=merged['POR'], name='과거 POR', line=dict(color='lightgray', width=1.5)))
        fig.add_hline(y=avg_por, line_dash="dot", line_color="orange", annotation_text=f"10년 평균: {avg_por:.2f}")
        fig.add_hline(y=now_por, line_color="red", line_width=2.5, annotation_text=f"현재 위치: {now_por:.2f}")
        
        if target_price:
            t_por = (target_price * shares) / (exp_profit * 100000000)
            fig.add_hline(y=t_por, line_color="blue", line_dash="dash", annotation_text=f"목표가 POR: {t_por:.2f}")

        fig.update_layout(title="📈 10년 POR 밴드 차트", template="plotly_white", height=600)
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("📋 10년 실적 데이터 (단위: 억원)")
        st.table(df_fs.set_index('Date').sort_index(ascending=False).T)
