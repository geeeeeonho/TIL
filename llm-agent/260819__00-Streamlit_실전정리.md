# Streamlit 실전 코드 정리 — LV1 → LV3

> 목표: Streamlit 기능을 따로 외우는 것이 아니라 **대시보드 → AI 연동 → 멀티페이지 서비스**로 확장되는 실제 제작 흐름을 이해.
>
> 원본의 LV1·LV2·LV3 구성을 유지하되, 반복 설명은 줄이고 미완성 부분은 앞 단원에서 사용한 패턴으로 보강.

---

# LV1. 전체 Streamlit 대시보드 만들어보기

LV1은 **데이터 → UI 입력 → 필터링 → 결과 출력 → 상태 유지**까지 Streamlit의 기본 흐름을 한 앱에서 사용하는 단계.

```text
① 데이터 준비
   df
    ↓
② UI에서 조건 입력
   multiselect / radio / slider
    ↓
③ 입력값을 변수에 저장
   selected_classes / selected_sex / age_range
    ↓
④ 변수로 데이터 필터링
   filtered_df
    ↓
⑤ 결과 출력
   dataframe / metric / countplot
    ↓
⑥ 다시 실행되어도 기억할 값
   session_state
```

## 1. 타이타닉 대시보드 완성 코드

```python
# 실행
# uv run streamlit run 과제_LV1_기초/app.py

import os
os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st


# ---------------------------------------------------------
# 1) 기본 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="타이타닉 탑승객 대시보드",
    page_icon="🚢",
    layout="wide",
)

PROJECT_ROOT = next(
    (p for p in Path(__file__).resolve().parents if (p / "core").is_dir()),
    Path(__file__).resolve().parent,
)
sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / "data"

from core.fonts import apply_korean_font
apply_korean_font()


# ---------------------------------------------------------
# 2) 데이터 로딩
# ---------------------------------------------------------
@st.cache_data
def load_data():
    return pd.read_csv(DATA_DIR / "titanic.csv")


df = load_data()

st.title("타이타닉 탑승객 대시보드")
st.caption("타이타닉 탑승객 데이터를 필터링하고 생존 현황을 살펴보는 대시보드")


# ---------------------------------------------------------
# 3) 원본 데이터 확인 + 핵심 지표
# ---------------------------------------------------------
st.subheader("데이터 미리보기")
st.dataframe(df.head(), width="stretch")
st.write("전체 데이터 크기:", df.shape)

survival_rate = df["survived"].mean() * 100
average_fare = df["fare"].mean()

c1, c2, c3, c4 = st.columns(4)
c1.metric("탑승객 수", f"{len(df):,}명")
c2.metric("생존자 수", f"{int(df['survived'].sum()):,}명")
c3.metric("생존율", f"{survival_rate:.1f}%")
c4.metric("평균 요금", f"{average_fare:.2f}")


# ---------------------------------------------------------
# 4) 사이드바 필터
# ---------------------------------------------------------
with st.sidebar:
    st.header("필터")

    class_options = df["class"].dropna().unique().tolist()
    selected_classes = st.multiselect(
        "객실 등급",
        options=class_options,
        default=class_options,
    )

    selected_sex = st.radio(
        "성별",
        ["전체", "male", "female"],
    )

    min_age = int(df["age"].min())
    max_age = int(df["age"].max())

    age_range = st.slider(
        "나이 범위",
        min_value=min_age,
        max_value=max_age,
        value=(min_age, max_age),
    )


# ---------------------------------------------------------
# 5) 필터 적용
# ---------------------------------------------------------
filtered_df = df[df["class"].isin(selected_classes)]

if selected_sex != "전체":
    filtered_df = filtered_df[
        filtered_df["sex"] == selected_sex
    ]

filtered_df = filtered_df[
    (filtered_df["age"] >= age_range[0])
    & (filtered_df["age"] <= age_range[1])
]


# ---------------------------------------------------------
# 6) 결과 표시
# ---------------------------------------------------------
tab1, tab2 = st.tabs(["데이터 표", "시각화"])

with tab1:
    st.write(f"필터 결과: {len(filtered_df):,}명")
    st.dataframe(filtered_df, width="stretch")

with tab2:
    survivors = filtered_df[
        filtered_df["survived"] == 1
    ]

    fig, ax = plt.subplots(figsize=(7, 4))

    sns.countplot(
        data=survivors,
        x="class",
        ax=ax,
    )

    ax.set_title("객실 등급별 생존자 수")
    ax.set_xlabel("객실 등급")
    ax.set_ylabel("생존자 수")

    st.pyplot(fig)
    plt.close(fig)


# ---------------------------------------------------------
# 7) session_state로 값 유지
# ---------------------------------------------------------
if "view_count" not in st.session_state:
    st.session_state["view_count"] = 0

if st.button("조회수 증가"):
    st.session_state["view_count"] += 1

st.write("조회수:", st.session_state["view_count"])
```

### 실행 화면 예시

> 아래 화면은 **구조를 보여 주기 위한 목업**. 숫자는 예시이며 실제 값은 `titanic.csv`와 선택한 필터에 따라 달라짐.

![LV1 타이타닉 대시보드 실행 화면 목업](assets/lv1_mockup.png)

이 예제에서 실제로 연결되는 핵심은 다음 한 줄 흐름.

```text
사이드바 위젯
→ 선택값을 Python 변수에 저장
→ DataFrame 조건식에 사용
→ filtered_df 생성
→ 표·그래프가 filtered_df 기준으로 다시 출력
```

Streamlit은 위젯을 바꿀 때 스크립트를 다시 실행하므로 별도의 이벤트 코드를 복잡하게 만들지 않아도 됨. 반대로 재실행 후에도 값이 남아야 하는 `view_count` 같은 값은 `st.session_state`에 저장.

> `age`가 결측치인 행은 범위 비교식에서 `False`가 되어 필터 결과에서 제외됨. 결측 행까지 유지해야 한다면 별도 조건을 추가해야 함.

---

# LV2. 기존 챗봇·RAG 시스템과 대시보드 연동

LV2는 Streamlit이 직접 AI 로직을 만드는 단계가 아니라 **이미 만든 Python 시스템을 UI에 연결하는 단계**.

```text
[챗봇]
사용자 입력
 → 대화 기록 불러오기
 → chatbot_core.stream_reply()
 → st.write_stream()
 → 대화 기록 저장

[RAG]
질문 입력
 → rag_core.ask()
 → 답변 + sources
 → 답변 출력 + 참고 문서 표시

[대시보드]
taxis.csv
 → 지표 계산
 → Plotly figure 생성
 → st.plotly_chart()
```

즉 하나의 앱 안에서 **상태를 가진 챗봇 / 문서 검색 / 데이터 분석**을 탭으로 묶는 구조.

## 1. 통합 앱 예시

```python
# 실행
# uv run streamlit run 과제_LV2_응용/app.py

import os
os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


# ---------------------------------------------------------
# 1) 프로젝트 준비
# ---------------------------------------------------------
st.set_page_config(
    page_title="AI 어시스턴트 + 대시보드",
    page_icon="🚕",
    layout="wide",
)

PROJECT_ROOT = next(
    (p for p in Path(__file__).resolve().parents if (p / "core").is_dir()),
    Path(__file__).resolve().parent,
)
sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / "data"

from core import chatbot_core, rag_core
from core.keys import require_openai_key_or_stop

st.title("AI 어시스턴트 + 택시 대시보드")

# 챗봇·RAG에서 실제 OpenAI 호출을 사용
require_openai_key_or_stop()


# ---------------------------------------------------------
# 2) 반복해서 만들 필요 없는 자원 / 데이터 준비
# ---------------------------------------------------------
@st.cache_resource
def get_chain():
    return chatbot_core.build_chain()


@st.cache_data
def load_taxis():
    return pd.read_csv(DATA_DIR / "taxis.csv")


chain = get_chain()
taxis = load_taxis()


# ---------------------------------------------------------
# 3) 공통 사이드바
# ---------------------------------------------------------
with st.sidebar:
    st.header("설정")

    top_k = st.slider(
        "RAG 참고 문서 수",
        min_value=1,
        max_value=5,
        value=3,
    )

    if st.button("대화 초기화"):
        st.session_state["messages"] = []
        st.rerun()


# ---------------------------------------------------------
# 4) 기능별 탭
# ---------------------------------------------------------
tab_chat, tab_rag, tab_dash = st.tabs(
    ["챗봇", "문서 Q&A", "택시 대시보드"]
)


# =========================================================
# A. 챗봇
# =========================================================
with tab_chat:
    st.subheader("무엇이든 물어보세요")

    # 대화 이력 최초 준비
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    # 이전 대화 다시 출력
    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    # 새 사용자 입력
    prompt = st.chat_input("메시지를 입력하세요")

    if prompt:
        # 1) 사용자 메시지 저장
        st.session_state["messages"].append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        # 2) 화면에 사용자 메시지 표시
        with st.chat_message("user"):
            st.write(prompt)

        # 3) 기존 챗봇 로직 호출
        # 현재 질문은 message=prompt로 이미 전달하므로
        # history에는 그 직전까지의 이력만 전달
        stream = chatbot_core.stream_reply(
            message=prompt,
            history=st.session_state["messages"][:-1],
            chain=chain,
        )

        # 4) AI 답변 스트리밍
        with st.chat_message("assistant"):
            response = st.write_stream(stream)

        # 5) 완성된 답변 저장
        st.session_state["messages"].append(
            {
                "role": "assistant",
                "content": response,
            }
        )


# =========================================================
# B. RAG 문서 Q&A
# =========================================================
with tab_rag:
    st.subheader("문서 기반 질문")

    question = st.text_input(
        "질문",
        placeholder="예: 파일 용량 제한이 얼마인가요?",
    )

    # 버튼을 눌렀을 때만 검색 + 생성 호출
    if st.button("문서에서 답 찾기"):
        if not question.strip():
            st.warning("질문을 입력하세요.")
        else:
            with st.spinner("관련 문서를 찾고 답변을 생성하는 중..."):
                result = rag_core.ask(
                    question,
                    k=top_k,
                )

            st.markdown("### 답변")
            st.write(result["answer"])

            st.markdown("### 참고 문서")
            for source in result["sources"]:
                with st.expander(
                    f"{source['title']} · 유사도 {source['score']}"
                ):
                    st.write(source["text"])


# =========================================================
# C. 택시 데이터 대시보드
# =========================================================
with tab_dash:
    st.subheader("택시 데이터 분석")

    # 숫자 계산에 필요한 열만 결측 제거
    taxi_numeric = taxis.dropna(
        subset=["fare", "distance"]
    ).copy()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("운행 건수", f"{len(taxis):,}")
    c2.metric("평균 요금", f"${taxi_numeric['fare'].mean():.2f}")
    c3.metric("평균 거리", f"{taxi_numeric['distance'].mean():.2f} mi")

    if "tip" in taxis.columns:
        c4.metric("평균 팁", f"${taxis['tip'].mean():.2f}")
    else:
        c4.metric("데이터 열 수", len(taxis.columns))

    # pickup 시간을 날짜로 변환해 일별 운행량 계산
    taxis_chart = taxis.copy()
    taxis_chart["pickup"] = pd.to_datetime(
        taxis_chart["pickup"],
        errors="coerce",
    )

    daily = (
        taxis_chart.dropna(subset=["pickup"])
        .assign(date=lambda x: x["pickup"].dt.date)
        .groupby("date")
        .size()
        .reset_index(name="trips")
    )

    col_left, col_right = st.columns(2)

    with col_left:
        fig_daily = px.line(
            daily,
            x="date",
            y="trips",
            markers=True,
            title="일별 택시 운행량",
        )
        st.plotly_chart(fig_daily, width="stretch")

    with col_right:
        fig_scatter = px.scatter(
            taxi_numeric,
            x="distance",
            y="fare",
            opacity=0.5,
            title="이동 거리와 요금의 관계",
        )
        st.plotly_chart(fig_scatter, width="stretch")

    with st.expander("원본 데이터 보기"):
        st.dataframe(taxis.head(100), width="stretch")
```

### 실행 화면 예시

> 아래는 세 탭이 하나의 서비스 안에서 어떻게 배치되는지 보여 주기 위한 목업. 표시 수치는 예시.

![LV2 AI 어시스턴트와 택시 대시보드 실행 화면 목업](assets/lv2_mockup.png)

LV2에서 가장 중요한 것은 **각 기능이 서로 다른 종류의 상태를 사용한다는 점**.

| 대상 | 저장/처리 방식 | 이유 |
|---|---|---|
| 사용자 대화 이력 | `st.session_state` | rerun 후에도 현재 사용자의 대화 유지 |
| 챗봇 체인 | `st.cache_resource` | 매 메시지마다 체인을 다시 만들 필요 없음 |
| 택시 CSV | `st.cache_data` | 같은 파일을 매 rerun마다 다시 읽지 않음 |
| RAG 검색 결과 | `rag_core.ask()` | 질문할 때 검색·생성 수행 |
| RAG 문서 수 | `top_k` | UI에서 사용자가 검색 범위를 조절 |

### 챗봇에서 특히 주의할 부분

```python
st.session_state["messages"].append(
    {"role": "user", "content": prompt}
)

stream = chatbot_core.stream_reply(
    message=prompt,
    history=st.session_state["messages"][:-1],
)
```

현재 질문은 `message=prompt`로 이미 전달됨. 따라서 함수가 **현재 질문 + 과거 이력**을 따로 받는 구조라면 `history`에서 방금 저장한 현재 질문을 제외해야 중복 전달을 피할 수 있음.

### 실서비스에서의 구조

```text
Streamlit UI
├─ 챗봇 탭
│   └─ chatbot_core
├─ 문서 Q&A 탭
│   └─ rag_core
└─ 데이터 탭
    └─ pandas + Plotly

공통
├─ st.session_state : 사용자별 상태
├─ st.cache_data    : 데이터 결과
├─ st.cache_resource: 모델·체인·인덱스
└─ st.secrets       : API 키
```

---

# LV3. 멀티페이지 통합 웹 서비스 구현

LV2는 기능을 **탭**으로 나눴다면, LV3는 각 기능을 실제 **페이지 파일**로 분리.

```text
pages 딕셔너리
│
├─ 시작
│   └─ 홈 ← default=True
│
├─ 분석
│   └─ 대시보드
│
└─ AI
    ├─ 챗봇
    └─ 문서 QA
         ↓
st.navigation(pages)
         ↓
현재 선택 페이지 → pg
         ↓
pg.run()
```

## 1. 권장 프로젝트 구조

```text
과제_LV3_통합/
├─ main.py
│
├─ pages/
│  ├─ 1_홈.py
│  ├─ 2_대시보드.py
│  ├─ 3_챗봇.py
│  └─ 4_문서QA.py
│
├─ core/
│  ├─ chatbot_core.py
│  ├─ rag_core.py
│  └─ keys.py
│
├─ data/
│  ├─ taxis.csv
│  └─ faq_docs.csv
│
└─ .streamlit/
   └─ secrets.toml
```

핵심 변화는 **새 기능을 다시 만드는 것이 아니라 LV2 코드를 페이지별 파일로 이동하는 것**.

```text
LV2 탭                         LV3 파일
--------------------------------------------------
챗봇 탭          →            pages/3_챗봇.py
문서 Q&A 탭      →            pages/4_문서QA.py
택시 대시보드 탭 →            pages/2_대시보드.py
새 시작 화면     →            pages/1_홈.py
```

## 2. `main.py` — 페이지 등록과 실행

```python
# 실행
# uv run streamlit run 과제_LV3_통합/main.py

import os
os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

import streamlit as st


st.set_page_config(
    page_title="통합 AI 대시보드",
    page_icon="💎",
    layout="wide",
)


pages = {
    # -----------------------------------------------------
    # 시작
    # -----------------------------------------------------
    "시작": [
        st.Page(
            "pages/1_홈.py",
            title="홈",
            icon="🏠",
            default=True,
        )
    ],

    # -----------------------------------------------------
    # 분석
    # -----------------------------------------------------
    "분석": [
        st.Page(
            "pages/2_대시보드.py",
            title="대시보드",
            icon="📊",
        )
    ],

    # -----------------------------------------------------
    # AI
    # -----------------------------------------------------
    "AI": [
        st.Page(
            "pages/3_챗봇.py",
            title="챗봇",
            icon="💬",
        ),
        st.Page(
            "pages/4_문서QA.py",
            title="문서 QA",
            icon="📚",
        ),
    ],
}


# 네비게이션 생성
# → 현재 선택한 Page 객체가 pg에 들어감
pg = st.navigation(pages)

# 선택한 페이지 실행
pg.run()
```

### 실행 화면 예시

![LV3 멀티페이지 통합 서비스 실행 화면 목업](assets/lv3_mockup.png)

## 3. 페이지 파일은 LV2 기능을 분리

`main.py`에서는 페이지를 **등록하고 실행만 함**. 실제 UI·분석 코드는 `pages/`에 둠.

예를 들어 홈 페이지는 가볍게 서비스 입구 역할만 담당.

```python
# pages/1_홈.py

import streamlit as st

st.title("홈")
st.caption("데이터 분석과 AI 기능을 한 서비스에서 사용")

c1, c2, c3 = st.columns(3)

with c1:
    st.subheader("데이터 대시보드")
    st.write("택시 데이터를 지표와 Plotly 그래프로 분석")

with c2:
    st.subheader("AI 챗봇")
    st.write("대화 이력을 유지하면서 기존 챗봇 시스템 사용")

with c3:
    st.subheader("문서 QA")
    st.write("RAG로 문서를 검색하고 답변과 출처를 함께 표시")
```

나머지는 LV2의 각 탭 내부 코드를 옮기면 됨.

```python
# pages/2_대시보드.py
# → LV2의 with tab_dash: 내부 로직

# pages/3_챗봇.py
# → LV2의 with tab_chat: 내부 로직

# pages/4_문서QA.py
# → LV2의 with tab_rag: 내부 로직
```

이렇게 나누면 각 페이지가 독립적이어서 코드가 길어져도 한 파일에 모든 UI가 몰리지 않음.

### 페이지 이동의 실제 동작

```text
사용자가 사이드바에서 "문서 QA" 선택
                ↓
st.navigation(pages)가 해당 Page 선택
                ↓
pg = pages/4_문서QA.py에 해당하는 Page 객체
                ↓
pg.run()
                ↓
pages/4_문서QA.py 실행
                ↓
RAG 질문 화면 출력
```

---

# LV1 → LV3에서 달라지는 것

| 단계 | 목표 | 중심 기능 | 결과물 |
|---|---|---|---|
| **LV1** | Streamlit 기본 기능 통합 | 필터, metric, tabs, dataframe, seaborn, session_state | 단일 데이터 대시보드 |
| **LV2** | 기존 Python 시스템 연결 | chat UI, RAG, Plotly, cache, session_state | AI + 분석 통합 앱 |
| **LV3** | 앱 구조 확장 | `st.Page`, `st.navigation`, `pg.run()` | 멀티페이지 웹 서비스 |

전체 과정은 결국 다음 방향으로 확장됨.

```text
LV1
데이터를 화면에 보여 주는 앱
        ↓
LV2
데이터 + 기존 AI 로직을 연결한 앱
        ↓
LV3
기능을 페이지 단위로 분리한 하나의 웹 서비스
```

## 최종 핵심

```text
[데이터]
CSV / DataFrame
   ↓
[Streamlit 입력]
sidebar / slider / select / chat_input
   ↓
[Python 처리]
필터링 / 집계 / chatbot_core / rag_core
   ↓
[출력]
metric / dataframe / Plotly / chat_message / expander
   ↓
[상태·성능]
session_state / cache_data / cache_resource
   ↓
[서비스 확장]
st.Page / st.navigation / pg.run()
```

실전에서 중요한 것은 Streamlit 함수를 많이 사용하는 것이 아니라 **UI → Python 로직 → 출력 → 상태 관리**의 연결을 만들고, 기능이 커지면 **페이지와 core 모듈로 분리**하는 것.
