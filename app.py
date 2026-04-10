import streamlit as st
import FinanceDataReader as fdr
import OpenDartReader
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import os
import time

# 1. 페이지 설정 및 제목
st.set_page_config(page_title="POR Master", page_icon="📈", layout="wide")

# 2. 보안 비밀(Secrets) 설정
DART_KEY = os.environ.get('DART_API_KEY')

# 3. 사이드바 메뉴
st.sidebar.header("⚙️ 분석 설정")
if not DART_KEY:
    DART_KEY = st.sidebar.text_input("DART API KEY", type="password")

company_name = st.sidebar.text_input("회사 이름", placeholder="예: 씨에스윈드")
manual_code = st.sidebar.text_input("종목코드 직접입력 (선택)", placeholder="이름으로 안 찾아질 때만 입력")

# 초기값 None 설정 (0 안 뜨게 수정)
exp_profit = st.sidebar.number_input("올해 예상 영업이익 (억원)", value=None, placeholder="예상 이익 입력")
target_price = st.sidebar.number_input("목표 주가 (원)", value=None, placeholder="목표가 입력")

# 4. 기능 함수 정의 (캐싱 및 에러 방지 강화)

@st.cache_data(ttl=3600)
def get_krx_list():
    """한국거래소 종목 리스트 로드"""
    try:
        # 가장 안정적인 코스피/코스닥 개별 호출 후 병합 방식
        df1 = fdr.StockListing('KOSPI')
        df2 = fdr.StockListing('KOSDAQ')
        df = pd.concat([df1, df2])
        return df if not df.empty else pd.DataFrame()
    except:
        return pd.DataFrame()

@st.cache_resource
def get_dart_client(key):
    """DART 클라이언트 연결 (재시도 횟수 및 대기시간 대폭 강화)"""
    for i in range(5):  # 5번까지 재시도
        try:
            # OpenDartReader 초기화 시 타임아웃 문제를 피하기 위해 시도
            return OpenDartReader(key)
        except Exception:
            if i < 4:
                time.sleep(5) # 5초씩 대기하며 재시도
                continue
    return None

@st.cache_data(ttl=3600)
def fetch_dart_data(_dart_client, s_code):
    """10년치 재무 데이터 추출"""
    fs_list = []
    current_year = datetime.now().year
    for year in range(current_year - 10, current_year):
        try:
            fs = _dart_client.finstate(s_code, year, reprt_code='11011')
            if fs is not None and not fs.empty:
                op = fs.loc[(fs['account_nm'].str.contains('영업이익')) & (fs['fs_div'].isin(['CFS', 'OFS']))]
                op_v = int(float(str(op.iloc[0]['thstrm_amount']).replace(',', ''))/100000000) if not op.empty else 0
                if op_v != 0:
                    fs_list.append({'Date': f"{year}-12-31", '영업이익_억원': op_v})
        except: continue
    return pd.DataFrame(fs_list)

# 5. 분석 실행 메인 로직
if st.sidebar.button("분석 실행"):
    if not DART_KEY:
        st.error("API 키를 입력해주세요.")
    elif not company_name and not manual_code:
        st.error("회사 이름을 입력해주세요.")
    elif exp_profit is None or exp_profit <= 0:
        st.error("올해 예상 영업이익을 입력해주세요.")
    else:
        with st.spinner('DART 서버에 연결하여 데이터를 가져오는 중입니다... (최대 30초 소요)'):
            s_code = manual_code if manual_code else None
            s_name = company_name
            
            # (1) 종목코드 찾기
            if not s_code:
                df_krx = get_krx_list()
                if not df_krx.empty:
                    s_term = company_name.replace(" ", "").upper()
                    target = df_krx[df_krx['Name'].str.replace(" ", "").str.upper().str.contains(s_term)]
                    if not target.empty:
                        s_name, s_code = target.iloc[0]['Name'], target.iloc[0]['Code']

            if not s_code:
                st.error(f"'{company_name}' 종목을 찾을 수 없습니다.")
                st.stop()

            # (2) 주가 데이터 (yfinance)
            stock = yf.Ticker(f"{s_code}.KS")
            hist = stock.history(period="10y")
            if hist.empty:
                stock = yf.Ticker(f"{s_code}.KQ")
                hist = stock.history(period="10y")

            if hist.empty:
                st.error("주가 데이터를 가져오지 못했습니다.")
                st.stop()

            hist = hist.reset_index()
            hist['Date'] = pd.to_datetime(hist['Date']).dt.tz_localize(None).astype('datetime64[ns]')
            curr_price = hist['Close'].iloc[-1]

            # (3) DART 연결
            dart = get_dart_client(DART_KEY)
            if dart is None:
                st.error("❌ DART 서버 응답이 너무 늦습니다. 잠시 후 'Reboot' 버튼을 누르거나 다시 시도해 주세요.")
                st.stop()
            
            df_fs = fetch_dart_data(dart, s_code)
            
            if df_fs.empty:
                st.warning("과거 실적 데이터를 불러오지 못했습니다. (종목코드 확인 필요)")
            else:
                df_fs['Date'] = pd.to_datetime(df_fs['Date']).astype('datetime64[ns]')
                st.title(f"🏢 {s_name} ({s_code}) 분석 결과")

                shares = 1
                try: shares = stock.info.get('sharesOutstanding', 1)
                except: pass

                mcap_billion = int((curr_price * shares) / 100000000)
                now_por = (curr_price * shares) / (exp_profit * 100000000)
                
                c1, c2, c3 = st.columns(3)
                c1.metric("현재 주가", f"{curr_price:,.0f}원")
                c2.metric("예상 POR", f"{now_por:.2f}배")
                c3.metric("시가총액", f"{mcap_billion:,.0f}억")

                # (4) POR 그래프
                hist['MarketCap'] = hist['Close'] * shares
                merged = pd.merge_asof(hist.sort_values('Date'), df_fs.sort_values('Date'), on='Date', direction='backward')
                merged['POR'] = merged['MarketCap'] / (merged['영업이익_억원'] * 100000000)
                avg_por = merged['POR'].mean()

                fig = go.Figure()
                fig.add_trace(go.Scatter(x=merged['Date'], y=merged['POR'], name='과거 POR', line=dict(color='lightgray')))
                fig.add_hline(y=avg_por, line_dash="dot", annotation_text=f"평균: {avg_por:.2f}")
                fig.add_hline(y=now_por, line_color="red", line_width=2, annotation_text=f"현재: {now_por:.2f}")
                
                if target_price and target_price > 0:
                    t_por = (target_price * shares) / (exp_profit * 100000000)
                    fig.add_hline(y=t_por, line_color="blue", line_dash="dash", annotation_text=f"목표 POR: {t_por:.2f}")

                fig.update_layout(title=f"📈 {s_name} 10년 POR 히스토리", template="plotly_white")
                st.plotly_chart(fig, use_container_width=True)

                st.subheader("📋 최근 10년 실적 (억원)")
                st.table(df_fs.tail(10).set_index('Date').T)
