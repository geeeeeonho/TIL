# Streamlit 기초 핵심 정리

> Python 스크립트를 웹 화면으로 빠르게 구성하는 프레임워크.

---

## 1. 실행과 가장 중요한 동작 원리

```bash
# 실행
uv run streamlit run <파일>.py

# 종료
Ctrl + C
```

### 핵심: 위젯을 조작하면 스크립트가 다시 실행됨

```text
위젯 조작
   ↓
파이썬 스크립트를 처음부터 다시 실행(rerun)
   ↓
일반 변수        → 다시 초기화될 수 있음
st.session_state → 재실행 후에도 값 유지
st.cache_*       → 같은 작업의 재계산을 줄임

예외
- st.form      : 제출할 때 입력을 한 번에 반영
- @st.fragment : 해당 조각만 부분 재실행 가능
```

Streamlit을 이해할 때 가장 먼저 기억할 구조.

---

## 2. 화면에 출력하기

| 목적 | 함수 | 핵심 |
|---|---|---|
| 일반 출력 | `st.write()` | 문자열·숫자·리스트 등 대부분 출력 |
| 제목 | `st.title()` / `st.header()` / `st.subheader()` | 제목 단계 구분 |
| 보조 설명 | `st.caption()` | 작은 설명 |
| 마크다운 | `st.markdown()` | 굵게·목록·코드 조각 등 |
| 일반 텍스트 | `st.text()` | 서식 없이 그대로 표시 |
| 코드 | `st.code()` | 복사 가능한 코드 블록 |
| 인터랙티브 표 | `st.dataframe()` | 정렬·스크롤·크기 조절 |
| 정적 표 | `st.table()` | 작은 요약표에 적합 |
| 핵심 지표 | `st.metric()` | KPI 카드 |
| 구조화 데이터 | `st.json()` | 딕셔너리·API 응답 확인 |
| 편집 가능한 표 | `st.data_editor()` | 수정된 DataFrame을 새 값으로 반환 |

### 최소 예시

```python
import streamlit as st

st.title("판매 대시보드")
st.write("총 매출:", 320000)
st.metric("주문 수", "128건", delta="+12건")
st.markdown("**오늘의 요약**")
```

**화면 결과**
- 큰 제목 표시
- 일반 값 출력
- 주문 수를 KPI 카드 형태로 표시
- Markdown 서식 적용

### DataFrame 출력

```python
st.dataframe(df.head(), width="stretch")
st.table(df["species"].value_counts())
```

- `dataframe` → 큰 데이터·탐색용
- `table` → 작은 고정 요약표

---

## 3. 사용자 입력 받기

### 자주 쓰는 입력 위젯

| 입력 종류 | 함수 | 반환값/용도 |
|---|---|---|
| 한 줄 문자 | `st.text_input()` | 문자열 |
| 여러 줄 문자 | `st.text_area()` | 문자열 |
| 정확한 숫자 | `st.number_input()` | 숫자 |
| 범위 선택 | `st.slider()` | 숫자 또는 범위 튜플 |
| 하나 선택 | `st.selectbox()` / `st.radio()` | 선택값 |
| 여러 개 선택 | `st.multiselect()` | 리스트 |
| 참/거짓 | `st.checkbox()` / `st.toggle()` | `True` / `False` |
| 버튼 | `st.button()` | 누른 순간의 재실행에서 `True` |
| 날짜 | `st.date_input()` | 날짜 또는 기간 |
| 파일 | `st.file_uploader()` | 업로드 객체 또는 `None` |
| 색 | `st.color_picker()` | `#RRGGBB` 문자열 |

### 입력 예시를 하나로 합치기

```python
name = st.text_input("이름")
age = st.number_input("나이", min_value=0, max_value=120, value=25)
city = st.selectbox("도시", ["서울", "부산", "대구"])
tags = st.multiselect("관심사", ["AI", "데이터", "웹"])
agree = st.checkbox("약관 동의")

if st.button("제출", type="primary"):
    st.success(f"{name} / {age}세 / {city} / {tags} / 동의={agree}")
```

### 파일 업로드는 `None` 확인이 필수

```python
up = st.file_uploader("CSV 올리기", type=["csv"])

if up is not None:
    user_df = pd.read_csv(up)
    st.dataframe(user_df.head(), width="stretch")
else:
    st.caption("아직 올린 파일이 없습니다.")
```

---

## 4. 레이아웃 구성

| 목적 | 함수 | 쓰임 |
|---|---|---|
| 옆 영역 | `st.sidebar` | 필터·설정 배치 |
| 가로 분할 | `st.columns()` | KPI를 나란히 배치 |
| 탭 | `st.tabs()` | 화면을 탭별로 분리 |
| 접기/펼치기 | `st.expander()` | 상세 설명 숨기기 |
| 묶음 | `st.container()` | 여러 요소를 한 영역으로 관리 |
| 자리 예약 | `st.empty()` | 나중에 같은 위치의 내용을 교체 |

### 사이드바 + KPI 열

```python
with st.sidebar:
    species = st.multiselect(
        "종",
        df["species"].unique(),
        default=list(df["species"].unique()),
    )

filtered = df[df["species"].isin(species)]

c1, c2, c3 = st.columns(3)
c1.metric("펭귄 수", len(filtered))
c2.metric("평균 체중", f"{filtered['body_mass_g'].mean():.0f} g")
c3.metric("종 수", filtered["species"].nunique())
```

### `container` vs `empty`

```python
# 여러 요소를 같은 영역에 계속 추가
box = st.container()
box.write("첫 줄")
box.write("둘째 줄")

# 한 자리의 내용을 교체
slot = st.empty()
slot.info("처리 중")
slot.success("완료")
```

---

## 5. 차트 표시

### Plotly: 대시보드용 인터랙티브 차트

```python
import plotly.express as px

mass = (
    df.groupby("species")["body_mass_g"]
      .mean()
      .reset_index()
)

fig = px.bar(
    mass,
    x="species",
    y="body_mass_g",
    title="종별 평균 체중(g)",
)
st.plotly_chart(fig, width="stretch")
```

### matplotlib / seaborn: 통계 그래프

```python
fig, ax = plt.subplots(figsize=(6, 4))
sns.boxplot(data=df, x="species", y="body_mass_g", ax=ax)
st.pyplot(fig)
plt.close(fig)
```

핵심 흐름: **figure 생성 → 그래프 작성 → `st.pyplot(fig)` 또는 `st.plotly_chart(fig)`로 출력**.

---

## 6. 상태 유지: `st.session_state`

일반 변수는 rerun 때 다시 만들어짐. 재실행 후에도 기억해야 하는 값은 `st.session_state`에 저장.

사용 예:
- 카운터
- 로그인/선택 상태
- 챗봇 대화 이력
- 사용자 입력 누적값

```python
if "count" not in st.session_state:
    st.session_state.count = 0

c1, c2 = st.columns(2)

if c1.button("증가"):
    st.session_state.count += 1

if c2.button("초기화"):
    st.session_state.count = 0

st.metric("현재 카운트", st.session_state.count)
```

**결과**
- 버튼을 눌러 rerun이 발생해도 `count` 값은 유지됨.

---

## 7. 캐싱: 반복 작업 줄이기

### 핵심 구분

| 데코레이터 | 대상 | 예시 |
|---|---|---|
| `@st.cache_data` | 계산 결과·데이터 | CSV, API 응답, 집계 결과 |
| `@st.cache_resource` | 한 번 만든 자원 | DB 연결, ML 모델, 검색 인덱스 |

### 데이터 캐싱

```python
@st.cache_data
def load_data():
    return pd.read_csv("data.csv")


df = load_data()
```

같은 인자로 다시 호출하면 저장된 결과를 사용해 반복 계산을 줄임.

### 캐시 갱신

```python
@st.cache_data(ttl=60)
def fetch_price():
    ...

if st.button("새로 불러오기"):
    fetch_price.clear()
    st.rerun()
```

- `ttl=60` → 60초 후 다시 계산
- `함수.clear()` → 해당 함수 캐시 삭제
- `st.cache_data.clear()` → `cache_data` 전체 삭제

---

## 8. 진행 상태 보여 주기

| 상황 | 함수 |
|---|---|
| 짧은 작업 | `st.spinner()` |
| 여러 단계 작업 | `st.status()` |
| 전체 진행률을 아는 반복 | `st.progress()` |

### Spinner

```python
with st.spinner("데이터를 불러오는 중..."):
    data = load_data()

st.success("완료")
```

### Progress

```python
bar = st.progress(0)

for i, name in enumerate(files, start=1):
    percent = int(i / len(files) * 100)
    bar.progress(percent, text=f"{name} 처리 ({percent}%)")

bar.empty()
```

`st.progress()` 값은 `0~100` 정수 또는 `0.0~1.0` 실수 형태 사용.

---

## 9. 재실행 제어: 콜백과 Form

### Callback

`on_click` / `on_change`에 연결한 함수는 위젯 조작 후 **전체 스크립트가 다시 그려지기 전에 먼저 실행**됨.

콜백에서 위젯 값을 사용할 때는 `key`를 주고 `st.session_state[key]`로 읽는 방식 사용.

```python
if "log" not in st.session_state:
    st.session_state.log = []


def add_log():
    st.session_state.log.append(st.session_state.memo)


st.text_input("메모", key="memo")
st.button("기록", on_click=add_log)
st.write(st.session_state.log)
```

### `st.form`: 여러 입력을 한 번에 제출

일반 위젯은 값이 바뀔 때마다 rerun 발생. 여러 입력값을 다 받은 뒤 한 번만 처리하려면 Form 사용.

```python
with st.form("apply"):
    name = st.text_input("이름")
    size = st.number_input("인원", 1, 10, 2)
    submitted = st.form_submit_button("신청")

if submitted:
    st.success(f"접수: {name}, {size}명")
```

핵심: Form 안에는 `st.form_submit_button()`이 필요.

---

## 10. 부분 재실행: `@st.fragment`

전체 앱을 다시 돌릴 필요가 없는 영역은 fragment로 분리 가능.

```python
@st.fragment
def sort_panel():
    order = st.radio(
        "정렬",
        ["오름차순", "내림차순"],
        horizontal=True,
    )
    st.write("현재 정렬:", order)


sort_panel()
```

- fragment 안의 위젯 조작 → 해당 fragment만 재실행
- 무거운 로딩/집계는 fragment 밖에 두고, 자주 바꾸는 필터·정렬만 안에 두는 방식
- 전체 앱을 다시 그려야 하면 `st.rerun()` 사용

---

# 통합 미니 예제

기초 기능을 하나의 작은 대시보드로 합친 예시.

```python
import pandas as pd
import plotly.express as px
import streamlit as st


@st.cache_data
def load_data():
    return pd.DataFrame({
        "species": ["Adelie", "Adelie", "Chinstrap", "Gentoo", "Gentoo"],
        "body_mass_g": [3700, 3550, 3800, 5000, 5100],
    })


df = load_data()

if "count" not in st.session_state:
    st.session_state.count = 0

st.title("펭귄 미니 대시보드")

with st.sidebar:
    selected = st.multiselect(
        "종 선택",
        df["species"].unique(),
        default=list(df["species"].unique()),
    )

filtered = df[df["species"].isin(selected)]

c1, c2 = st.columns(2)
c1.metric("데이터 수", len(filtered))
c2.metric("평균 체중", f"{filtered['body_mass_g'].mean():.0f} g")

summary = (
    filtered.groupby("species")["body_mass_g"]
            .mean()
            .reset_index()
)

fig = px.bar(
    summary,
    x="species",
    y="body_mass_g",
    title="종별 평균 체중",
)
st.plotly_chart(fig, width="stretch")
st.dataframe(filtered, width="stretch")

if st.button("조회 횟수 +1"):
    st.session_state.count += 1

st.caption(f"현재 세션 조회 횟수: {st.session_state.count}")
```

실행:

```bash
uv run streamlit run streamlit_core_example.py
```

### 이 예제로 확인할 것

1. 사이드바에서 종을 바꾸면 화면이 rerun됨.
2. 필터 결과에 따라 KPI·차트·표가 함께 바뀜.
3. `load_data()` 결과는 `@st.cache_data`로 캐싱됨.
4. 버튼을 눌러도 `st.session_state.count` 값은 유지됨.

---

# 최종 압축표

| 하고 싶은 일 | 핵심 기능 |
|---|---|
| 화면에 값 출력 | `st.write`, `st.metric`, `st.dataframe` |
| 사용자 입력 | `text_input`, `number_input`, `selectbox`, `multiselect`, `button` |
| 필터 영역 | `st.sidebar` |
| 가로 배치 | `st.columns` |
| 차트 | `st.plotly_chart`, `st.pyplot` |
| 재실행 후 값 유지 | `st.session_state` |
| 반복 계산 줄이기 | `st.cache_data`, `st.cache_resource` |
| 여러 입력 한 번에 처리 | `st.form` |
| 처리 상태 표시 | `spinner`, `status`, `progress` |
| 일부 영역만 재실행 | `@st.fragment` |

## 기억할 핵심 3개

1. **Streamlit 위젯 조작 = 기본적으로 스크립트 rerun**
2. **값 유지 = `st.session_state`, 계산 재사용 = `st.cache_*`**
3. **화면 구성 = 입력 → 필터링/계산 → 출력 순서로 생각하면 됨**