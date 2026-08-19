# Streamlit UI와 챗봇·RAG 연동

## 1. 전체 구조

핵심은 **AI 로직을 Streamlit 안에서 새로 만드는 것이 아니라, 이미 만든 로직을 UI에 연결하는 것**.

```text
[Streamlit UI]
    ↓ 사용자 입력
[기존 Python 로직]
    ├─ chatbot_core : 일반 챗봇
    ├─ rag_core     : 검색 + 답변 생성
    └─ keys.py      : API 키 준비
    ↓
[OpenAI / 검색 시스템]
    ↓
[Streamlit 화면에 답변·출처 표시]
```

역할을 분리하면 UI를 바꿔도 챗봇/RAG 로직은 그대로 재사용 가능.

```text
UI 담당
- st.chat_message
- st.chat_input
- st.write_stream
- st.expander
- st.session_state

AI·검색 담당
- chatbot_core
- rag_core

환경·준비 담당
- core.keys
- st.secrets
- st.cache_resource
```

특히 Streamlit은 위젯을 조작할 때 스크립트를 다시 실행하므로, 챗봇에서는 **대화 이력을 `st.session_state`에 저장하고 매번 다시 그리는 구조**가 중요.

---

## 2. 채팅 UI 만들기

채팅 화면에서 핵심적으로 사용하는 요소는 세 가지.

| 기능 | 코드 | 역할 |
|---|---|---|
| 말풍선 | `st.chat_message(role)` | user / assistant 메시지 표시 |
| 입력창 | `st.chat_input()` | 사용자 입력 받기 |
| 스트리밍 | `st.write_stream()` | 답변을 조각 단위로 표시 |

### 기본 사용

```python
import streamlit as st

with st.chat_message("user"):
    st.write("안녕하세요!")

with st.chat_message("assistant"):
    st.write("무엇을 도와드릴까요?")

if prompt := st.chat_input("메시지를 입력하세요"):
    st.write("입력:", prompt)
```

`st.chat_input()`은 입력이 들어오면 문자열을 반환하고, 입력 전에는 `None`.

```python
if prompt := st.chat_input("메시지"):
```

위 코드는 대략 다음 흐름을 한 줄로 합친 것.

```python
prompt = st.chat_input("메시지")

if prompt:
    ...
```

`:=`는 **값을 변수에 저장하면서 그 값을 바로 조건식에서도 사용하는 대입 표현식**.

### 스트리밍 출력

LLM처럼 답변을 조금씩 출력하려면 제너레이터를 `st.write_stream()`에 전달.

```python
import time
import streamlit as st


def stream_words():
    for word in "안녕하세요 스트리밍 출력 예시입니다".split():
        yield word + " "
        time.sleep(0.1)


if st.button("스트리밍 시작"):
    answer = st.write_stream(stream_words())
```

여기서 중요한 구조:

```text
제너레이터
→ yield로 문자열 조각 전달
→ st.write_stream이 순서대로 화면에 표시
→ 스트리밍 완료
→ 완성된 문자열을 반환
```

즉, 실제 챗봇의 스트리밍 함수도 같은 방식으로 연결 가능.

---

## 3. Echo 챗봇으로 전체 구조 이해

채팅 UI만 있다고 챗봇이 되는 것은 아님.

Streamlit은 입력할 때마다 재실행되므로 다음 구조가 필요.

```text
1. session_state에 대화 이력 준비
2. 저장된 이전 대화를 화면에 다시 출력
3. 새 사용자 입력을 이력에 저장
4. 답변 생성
5. 답변도 이력에 저장
```

이를 가장 단순하게 만든 것이 Echo 챗봇.

```python
import streamlit as st


# 1. 대화 이력 준비
if "messages" not in st.session_state:
    st.session_state.messages = []


# 2. 이전 대화 다시 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])


# 3. 새 입력 처리
if prompt := st.chat_input("아무 말이나 해보세요"):

    # 사용자 메시지 저장 + 출력
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
    })

    with st.chat_message("user"):
        st.write(prompt)

    # 임시 답변
    answer = f"당신은 '{prompt}'라고 했습니다."

    # AI 메시지 저장 + 출력
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
    })

    with st.chat_message("assistant"):
        st.write(answer)
```

예상 동작:

```text
사용자: 안녕하세요

AI: 당신은 '안녕하세요'라고 했습니다.
```

대화 데이터는 다음처럼 누적.

```python
[
    {
        "role": "user",
        "content": "안녕하세요",
    },
    {
        "role": "assistant",
        "content": "당신은 '안녕하세요'라고 했습니다.",
    },
]
```

핵심은 Echo 답변 자체가 아니라 **대화 이력을 저장하고 다시 그리는 구조**.

이 구조가 만들어지면 아래 한 줄만 실제 AI 함수로 교체하면 됨.

```python
# Echo
answer = f"당신은 '{prompt}'라고 했습니다."

# 실제 챗봇
answer = chatbot_core.stream_reply(...)
```

---

## 4. 기존 챗봇 시스템을 Streamlit에 연결

기존 챗봇 로직은 `core/chatbot_core.py`에 있고, Streamlit에서는 가져와 사용만 함.

주요 함수:

```text
chatbot_core.reply(message, history)
→ 전체 답변 문자열 반환

chatbot_core.stream_reply(message, history)
→ 답변을 조각 단위로 반환하는 스트리밍 제너레이터

chatbot_core.is_live()
→ API 키 준비 여부 확인
```

대화 이력 형식:

```python
[
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},
]
```

### 핵심 연동 코드

```python
import streamlit as st

from core import chatbot_core
from core.keys import require_openai_key_or_stop


# API 키가 없으면 안내 후 실행 중단
require_openai_key_or_stop()


# 체인은 매번 만들 필요가 없으므로 캐싱
@st.cache_resource
def get_chain():
    return chatbot_core.build_chain()


chain = get_chain()


# 대화 이력 준비
if "messages" not in st.session_state:
    st.session_state.messages = []


# 이전 대화 다시 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])


# 새 메시지 처리
if prompt := st.chat_input("무엇이든 물어보세요"):

    # 사용자 메시지 저장
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
    })

    with st.chat_message("user"):
        st.write(prompt)

    # AI 답변 스트리밍
    with st.chat_message("assistant"):
        answer = st.write_stream(
            chatbot_core.stream_reply(
                prompt,
                st.session_state.messages[:-1],
                chain=chain,
            )
        )

    # 완성된 AI 답변 저장
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
    })
```

전체 흐름:

```text
사용자 입력
→ messages에 user 메시지 저장
→ chatbot_core.stream_reply() 호출
→ st.write_stream()으로 실시간 출력
→ 완성된 답변 반환
→ messages에 assistant 답변 저장
```

### 왜 `messages[:-1]`을 넘기는가

입력 직후에는 이미 현재 사용자 메시지가 이력 끝에 들어 있음.

```python
st.session_state.messages.append({
    "role": "user",
    "content": prompt,
})
```

하지만 현재 질문은 첫 번째 인자 `prompt`로도 전달.

```python
chatbot_core.stream_reply(
    prompt,
    history,
)
```

따라서 전체 이력을 그대로 넘기면 현재 질문이 중복될 수 있음.

```text
prompt
→ "안녕하세요"

history 마지막
→ {"role": "user", "content": "안녕하세요"}

결과
→ 같은 사용자 입력을 두 번 전달
```

그래서 마지막 메시지를 제외.

```python
st.session_state.messages[:-1]
```

즉:

```text
prompt = 현재 질문

messages[:-1]
= 현재 질문 이전까지의 대화 이력
```

이 구분이 챗봇 연동에서 중요.

---

## 5. 대화 초기화와 재실행 처리

대화 내용은 결국 `st.session_state.messages` 리스트에 저장되어 있음.

따라서 리스트를 비우면 대화 초기화.

```python
with st.sidebar:
    st.header("설정")

    if st.button("대화 초기화"):
        st.session_state.messages = []
        st.rerun()
```

동작:

```text
대화 초기화 버튼
→ messages = []
→ 기존 이력 삭제
→ st.rerun()
→ 화면 즉시 다시 출력
→ 빈 대화 화면
```

`st.rerun()`을 함께 사용하는 이유는 **상태를 바꾼 직후 새 상태를 기준으로 화면을 다시 그리기 위해서**.

### 챗봇에서 기억해야 할 상태

```text
st.session_state
→ 사용자와 주고받은 대화처럼 재실행 후에도 유지할 값

st.cache_resource
→ 체인·모델·검색 인덱스처럼 매번 다시 만들 필요가 없는 무거운 객체
```

둘의 목적이 다름.

```python
# 대화 기록
st.session_state.messages

# 재사용할 챗봇 체인
@st.cache_resource
def get_chain():
    return chatbot_core.build_chain()
```

---

## 6. 기존 RAG 시스템을 UI에 연결

RAG도 UI 안에서 검색 로직을 다시 구현하지 않고 `core/rag_core.py`를 호출.

자료에서 사용하는 RAG는 FAQ 문서에 대해 검색하고 답변을 만드는 구조.

주요 함수:

```text
rag_core.search(question, k)
→ 관련 문서 상위 k개 검색

rag_core.ask(question, k)
→ 답변 + 검색된 출처 반환

rag_core.is_live()
→ API 키 준비 여부 확인
```

`ask()`의 결과 구조:

```python
{
    "answer": "생성된 답변",
    "sources": [
        {
            "id": "...",
            "title": "...",
            "text": "...",
            "score": ...,
        },
        ...
    ],
}
```

즉 일반 챗봇과 가장 큰 차이는 **답변만 보여 주는 것이 아니라 답변의 근거 문서도 같이 보여 준다는 것**.

### 문서 Q&A UI

```python
import streamlit as st

from core import rag_core
from core.keys import require_openai_key_or_stop


require_openai_key_or_stop()


question = st.text_input(
    "FAQ에 대해 물어보세요",
    placeholder="예: 파일 용량 제한이 얼마인가요?",
)

top_k = st.slider(
    "참고할 문서 수",
    min_value=1,
    max_value=5,
    value=3,
)


if question:
    result = rag_core.ask(
        question,
        k=top_k,
    )

    st.markdown("### 답변")
    st.write(result["answer"])

    st.markdown("### 근거 문서")

    for source in result["sources"]:
        with st.expander(
            f"{source['title']} (유사도 {source['score']})"
        ):
            st.write(source["text"])
```

화면 구조:

```text
[질문 입력]
파일 용량 제한이 얼마인가요?

[참고 문서 수]
1 ── 3 ── 5

[답변]
RAG가 생성한 답변

[근거 문서]
▶ 문서 제목 A (유사도 ...)
▶ 문서 제목 B (유사도 ...)
▶ 문서 제목 C (유사도 ...)
```

`top_k`는 검색할 문서 수.

```text
k가 작음
→ 핵심 문서만 사용
→ 필요한 근거를 놓칠 수 있음

k가 큼
→ 더 많은 근거 확인 가능
→ 관련 없는 문서가 섞일 수도 있음
```

따라서 무조건 크게 잡는 것이 아니라 질문과 데이터에 맞게 조정.

RAG UI의 핵심 목적:

```text
질문
→ 관련 문서 검색
→ 검색 결과를 바탕으로 답변 생성
→ 답변 표시
→ 근거 문서까지 같이 표시
```

---

## 7. API 키 관리

실제 OpenAI 모델을 사용하려면 API 키가 필요.

키를 Python 코드에 직접 작성하지 않고 Streamlit의 secrets를 사용.

```toml
# .streamlit/secrets.toml

OPENAI_API_KEY = "sk-..."
```

구조:

```text
로컬 실행
.streamlit/secrets.toml
        ↓
   st.secrets
        ↓
core/keys.py
        ↓
OPENAI_API_KEY 환경변수
        ↓
LangChain / OpenAI
```

자료의 `core/keys.py`는 Streamlit secrets에서 키를 읽어 LangChain이 사용하는 환경변수로 옮기는 역할.

요지:

```python
def _from_st_secrets():
    try:
        return st.secrets["OPENAI_API_KEY"]

    except (StreamlitSecretNotFoundError, KeyError):
        return None


def load_key():
    # 이미 환경변수에 있으면 그대로 사용
    if os.getenv("OPENAI_API_KEY"):
        return

    # secrets 등에서 키 탐색
    key = _from_st_secrets() or _from_unit_folder()

    if key:
        os.environ["OPENAI_API_KEY"] = key
```

이 과정이 필요한 이유:

```text
Streamlit
→ st.secrets에서 키 관리

LangChain의 ChatOpenAI / OpenAIEmbeddings
→ OPENAI_API_KEY 환경변수 사용
```

즉 두 시스템이 키를 보는 위치가 다르므로 연결 과정이 필요.

자료에서는 단원 폴더와 실습자료 루트 등 여러 위치에서 앱을 실행할 수 있어 `_from_unit_folder()`로 가까운 `.streamlit/secrets.toml`도 탐색.

### 앱 시작 시 키 확인

```python
from core.keys import require_openai_key_or_stop

require_openai_key_or_stop()

st.success("OpenAI 연결됨")
```

키가 없다면:

```text
오류 안내
→ st.stop()
→ 이후 OpenAI 호출 코드 실행하지 않음
```

중요:

```text
API 키
→ 코드에 직접 적지 않기

로컬
→ .streamlit/secrets.toml

배포
→ Streamlit Cloud의 Secrets 설정

secrets.toml
→ Git에 커밋하지 않기
```

자료의 키 로더에서는 secrets 파일 자체가 없을 때의 예외도 처리하므로 직접 `st.secrets`를 조회하는 대신 준비된 `core.keys` 함수를 사용하는 구조.

---

## 8. 무거운 객체는 `st.cache_resource`로 재사용

Streamlit은 위젯 조작 시 스크립트가 재실행됨.

그때마다 아래 작업을 다시 하면 비효율적.

```text
LLM 체인 생성
RAG 문서 임베딩
벡터 저장소 생성
검색 인덱스 준비
DB 연결
```

이처럼 계속 다시 만들 필요가 없는 자원은 `@st.cache_resource`.

### 챗봇 체인

```python
@st.cache_resource
def get_chain():
    return chatbot_core.build_chain()


chain = get_chain()
```

### RAG 검색 인덱스

```python
import time
import streamlit as st

from core import rag_core


@st.cache_resource(
    show_spinner="검색 인덱스를 준비하는 중…"
)
def get_index():

    started = time.perf_counter()

    store = rag_core.prepare()

    return {
        "store": store,
        "걸린시간": round(
            time.perf_counter() - started,
            2,
        ),
    }


index = get_index()

st.write(
    f"인덱스 준비에 "
    f"{index['걸린시간']}초 걸렸습니다."
)
```

예시 결과:

```text
인덱스 준비에 16.0초 걸렸습니다.
```

첫 실행:

```text
rag_core.prepare()
→ 문서 임베딩
→ 벡터 저장소 준비
→ 결과 캐싱
```

이후 재실행:

```text
get_index()
→ 저장해 둔 자원 재사용
→ 무거운 준비 생략
```

따라서 역할을 구분하면 다음과 같음.

| 저장 대상 | 사용 |
|---|---|
| 사용자 대화 이력 | `st.session_state` |
| 챗봇 체인 | `st.cache_resource` |
| RAG 인덱스 | `st.cache_resource` |
| API 키 | `st.secrets` → 환경변수 |

---

## 9. 전체 연결 흐름

### 일반 챗봇

```text
사용자
  ↓
st.chat_input
  ↓
session_state에 user 메시지 저장
  ↓
chatbot_core.stream_reply()
  ↓
OpenAI 모델
  ↓
st.write_stream()
  ↓
완성 답변
  ↓
session_state에 assistant 메시지 저장
```

코드 기준으로 보면:

```python
prompt = 사용자 입력

history = 이전 대화

stream = chatbot_core.stream_reply(
    prompt,
    history,
    chain=chain,
)

answer = st.write_stream(stream)
```

UI와 AI의 역할이 명확히 분리됨.

```text
Streamlit
→ 입력·출력·상태 관리

chatbot_core
→ 모델 호출·체인 실행

core.keys
→ API 키 준비
```

### RAG

```text
사용자 질문
  ↓
rag_core.ask(question, k)
  ↓
관련 문서 검색
  ↓
검색 문서를 이용한 답변 생성
  ↓
{
  answer,
  sources
}
  ↓
Streamlit
  ├─ 답변 표시
  └─ 근거 문서 표시
```

RAG에서는 특히 `sources`를 화면에 함께 보여 주는 것이 중요.

```python
result = rag_core.ask(question, k=3)

st.write(result["answer"])

for source in result["sources"]:
    with st.expander(source["title"]):
        st.write(source["text"])
```

---

## 10. 실전에서 기억할 핵심

```text
1. UI와 AI 로직은 분리
   Streamlit에서 모델/RAG를 새로 구현하지 않고 core 모듈을 import해서 사용

2. 챗봇 대화는 session_state에 저장
   Streamlit은 재실행되므로 이력이 없으면 이전 대화가 사라짐

3. 이전 대화를 먼저 다시 그림
   session_state → for문 → st.chat_message

4. 현재 질문과 이전 이력을 구분
   prompt = 현재 질문
   messages[:-1] = 현재 질문 이전의 이력

5. 스트리밍 함수는 st.write_stream과 연결
   stream_reply() → st.write_stream() → 완성 답변 반환

6. 무거운 준비는 cache_resource
   체인·모델·RAG 인덱스를 매번 다시 만들지 않음

7. RAG는 답변과 출처를 같이 표시
   result["answer"]
   result["sources"]

8. API 키는 코드에 작성하지 않음
   st.secrets → 환경변수 → LangChain/OpenAI

9. 모델/API 호출은 필요한 순간에만 실행
   단순 화면 재실행 때문에 불필요한 호출이 반복되지 않게 구성
```

### 최종 압축

| 목적 | 핵심 코드 |
|---|---|
| 채팅 말풍선 | `st.chat_message()` |
| 채팅 입력 | `st.chat_input()` |
| 스트리밍 답변 | `st.write_stream()` |
| 대화 기억 | `st.session_state` |
| 대화 초기화 | `messages = []` + `st.rerun()` |
| 기존 챗봇 연결 | `chatbot_core.stream_reply()` |
| 전체 답변 호출 | `chatbot_core.reply()` |
| RAG 답변 + 출처 | `rag_core.ask()` |
| RAG 검색 | `rag_core.search()` |
| 근거 문서 표시 | `st.expander()` |
| API 키 | `st.secrets` / `core.keys` |
| 체인·인덱스 재사용 | `@st.cache_resource` |

가장 중요한 전체 패턴:

```text
입력
→ 상태 저장
→ 기존 로직 호출
→ 결과 출력
→ 상태 저장

무거운 준비물
→ cache_resource

비밀키
→ secrets

RAG
→ 답변 + 출처
```
