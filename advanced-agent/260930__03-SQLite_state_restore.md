# LangGraph SQLite 상태 저장·복원 압축 정리

> 핵심 목표: `InMemorySaver`처럼 메모리에만 저장하지 않고,  
> **LangGraph의 State·다음 실행 위치·interrupt 정보를 SQLite 파일에 저장하고 프로그램 재시작 후 이어서 실행**하는 방법 정리.

---

# 1. 핵심 개념

## 체크포인트와 체크포인터

- **Checkpoint**: 특정 실행 시점의 State와 실행 위치를 저장한 기록
- **Checkpointer**: Checkpoint를 실제 저장·조회하는 기능

```text
그래프 실행
   ↓
State 변화
   ↓
Checkpoint 생성
   ↓
Checkpointer
   ↓
SQLite 파일 저장
```

### 저장 방식 비교

| 방식 | 저장 위치 | 커널 재시작 후 |
|---|---|---|
| `InMemorySaver` | Python 메모리 | 사라짐 |
| `SqliteSaver` | `.sqlite` 파일 | 복원 가능 |

SQLite에 저장되는 핵심:

```text
State
+ 다음 실행 노드(next)
+ interrupt 대기 정보
```

---

# 2. 전체 저장·복원 구조

```text
[첫 실행]

StateGraph 정의
     ↓
SqliteSaver 연결
     ↓
compile(checkpointer=...)
     ↓
thread_id 지정
     ↓
invoke()
     ↓
SQLite 파일에 Checkpoint 저장


[프로그램 재시작]

State / Node / Edge 다시 정의
     ↓
같은 SQLite 파일 연결
     ↓
compile(checkpointer=...)
     ↓
같은 thread_id 지정
     ↓
get_state()
     ↓
이전 State 복원
```

중요:

- Python 변수와 그래프 객체는 재시작하면 사라짐
- **SQLite 파일의 Checkpoint는 남음**
- 복원하려면 그래프 구조를 다시 정의해야 함
- 같은 작업을 이어가려면 **같은 DB 파일 + 같은 `thread_id`** 필요

---

# 3. SQLite 체크포인터 기본 문법

## 설치 패키지

```text
langgraph-checkpoint-sqlite
```

## DB 파일 경로

```python
from pathlib import Path
from langgraph.checkpoint.sqlite import SqliteSaver

output_dir = Path("output")
output_dir.mkdir(parents=True, exist_ok=True)

chat_db = output_dir / "lesson03_chat.sqlite"
```

---

## `SqliteSaver.from_conn_string()`

```python
with SqliteSaver.from_conn_string(str(chat_db)) as checkpointer:
    graph = builder.compile(
        checkpointer=checkpointer
    )
```

`with`가 끝나면 DB 연결은 닫힘.

```text
with 종료
  ↓
DB 연결 종료
  ↓
SQLite 파일은 그대로 유지
```

별도 `setup()` 호출은 필요하지 않음.

---

# 4. `thread_id`로 대화 분리

같은 SQLite 파일 안에서도 `thread_id`가 다르면 서로 다른 State로 관리됨.

```python
config_a = {
    "configurable": {
        "thread_id": "service-reservation-v1"
    }
}

config_b = {
    "configurable": {
        "thread_id": "service-catalog-v1"
    }
}
```

```text
lesson03_chat.sqlite
│
├─ service-reservation-v1
│    └─ 예약 서비스 대화
│
└─ service-catalog-v1
     └─ 상품 소개 서비스 대화
```

`thread_id`는 사용자 ID가 아니라 **대화·작업 실행 단위 ID**.

같은 사용자도 여러 `thread_id`를 가질 수 있음.

---

# 5. 대화 State 저장

## 메시지 누적 State

```python
from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class ChatState(TypedDict):
    policy: str
    messages: Annotated[
        list[AnyMessage],
        add_messages
    ]
```

`add_messages`를 사용하면 새 메시지를 기존 메시지 목록에 누적함.

```text
기존 messages
    +
새 HumanMessage
    +
새 AIMessage
    ↓
누적된 messages
```

---

## 기본 상담 그래프

```python
from langgraph.graph import (
    START,
    END,
    StateGraph,
)

chat_builder = StateGraph(ChatState)

chat_builder.add_node(
    "answer",
    answer,
)

chat_builder.add_edge(
    START,
    "answer",
)

chat_builder.add_edge(
    "answer",
    END,
)
```

### 구조

```text
START
  ↓
answer
  ↓
END
```

---

# 6. 첫 실행과 저장

```python
from langchain_core.messages import HumanMessage

with SqliteSaver.from_conn_string(
    str(chat_db)
) as checkpointer:

    chat_graph = chat_builder.compile(
        checkpointer=checkpointer
    )

    chat_graph.invoke(
        {
            "policy": policy_text,
            "messages": [
                HumanMessage(
                    content="예약 서비스를 만들고 싶어요."
                )
            ],
        },
        config_a,
    )
```

핵심 관계:

```python
graph.invoke(
    input_data,
    config,
)
```

- `input_data`: State에 넣을 실제 데이터
- `config`: 실행 설정
- `thread_id`: 사용할 저장 기록 선택

---

# 7. 저장 상태 조회

## `get_state()`

```python
saved = graph.get_state(config)
```

주요 값:

```python
saved.values
saved.next
saved.interrupts
```

| 값 | 의미 |
|---|---|
| `values` | 저장된 State |
| `next` | 다음 실행 노드 |
| `interrupts` | 응답 대기 중인 interrupt |

완료된 그래프:

```python
saved.next == ()
```

`get_state()`는 저장 기록만 읽으므로 LLM을 호출하지 않음.

---

# 8. 재시작 후 대화 복원

커널 재시작 후 다음은 다시 정의해야 함.

```text
모델
State
Node
Edge
Builder
DB 경로
```

그 후 같은 DB와 `thread_id` 사용.

```python
with SqliteSaver.from_conn_string(
    str(chat_db)
) as checkpointer:

    chat_graph = chat_builder.compile(
        checkpointer=checkpointer
    )

    saved = chat_graph.get_state(config_a)
```

### 복원 흐름

```text
커널 종료
   ↓
Python 객체 삭제

SQLite 파일
   ↓
Checkpoint 유지

커널 재시작
   ↓
그래프 코드 다시 정의
   ↓
같은 DB 연결
   ↓
같은 thread_id
   ↓
이전 State 조회
```

---

# 9. 완료된 대화에 새 질문 추가

이미 완료된 대화에 새로운 발화를 넣을 때는 **새 입력**을 전달함.

```python
question = HumanMessage(
    content="견적을 받으려면 무엇을 더 정해야 하나요?"
)

graph.invoke(
    {"messages": [question]},
    config_a,
)
```

이전 `policy`와 `messages`는 Checkpoint에서 읽음.

```text
저장된 대화
   +
새 HumanMessage
   ↓
answer 실행
   ↓
새 AIMessage 추가
   ↓
다시 SQLite 저장
```

---

# 10. 일반 입력과 `Command(resume)` 구분

둘은 용도가 다름.

## 완료된 대화 이어가기

```python
graph.invoke(
    {"messages": [new_message]},
    config,
)
```

## `interrupt()` 대기 작업 재개

```python
graph.invoke(
    Command(resume="승인"),
    config,
)
```

정리:

```text
새 질문
→ State 입력 딕셔너리

사람의 승인·반려 응답
→ Command(resume=...)
```

---

# 11. 메시지 ID로 중복 입력 방지

`thread_id`는 전체 대화 ID.

개별 메시지는 별도 `id`를 가질 수 있음.

```python
question = HumanMessage(
    content="추가로 무엇을 정해야 하나요?",
    id="reservation-followup",
)
```

이미 저장된 메시지 확인:

```python
messages = saved.values.get(
    "messages",
    [],
)

exists = any(
    message.id == "reservation-followup"
    for message in messages
)
```

```text
thread_id
└─ 하나의 전체 대화

message.id
└─ 대화 안의 개별 발화
```

---

# 12. SQLite 저장 + 스트리밍

저장 기능과 `stream()`을 같이 사용 가능.

```python
for update in graph.stream(
    {"messages": [question]},
    config,
    stream_mode="updates",
    version="v2",
):
    print(update["data"])
```

실행 변화는 스트리밍하면서 동시에 Checkpoint에 저장됨.

---

# 13. `with` 없이 SQLite 연결

직접 `sqlite3.Connection`을 만들어 사용할 수도 있음.

```python
import sqlite3

conn = sqlite3.connect(
    chat_db,
    check_same_thread=False,
)

checkpointer = SqliteSaver(conn)

graph = chat_builder.compile(
    checkpointer=checkpointer
)

result = graph.invoke(
    input_data,
    config,
)

conn.close()
```

### 구조

```text
sqlite3.connect()
      ↓
SqliteSaver(conn)
      ↓
compile(checkpointer)
      ↓
invoke()
      ↓
conn.close()
```

`check_same_thread=False`는 다른 스레드에서 해당 DB 연결을 사용할 수 있도록 설정.

연결을 직접 열었으면 작업 후 직접 닫아야 함.

---

# 14. SQLite에 HITL 승인 대기 저장

SQLite는 일반 대화뿐 아니라 `interrupt()` 상태도 저장 가능.

## State

```python
class ApprovalState(TypedDict):
    draft: str
    decision: str
    status: str
```

---

## 검토 노드

```python
from langgraph.types import (
    Command,
    interrupt,
)

def review(state: ApprovalState):
    decision = interrupt({
        "draft": state["draft"],
        "choices": [
            "승인",
            "반려",
        ],
    })

    return {
        "decision": decision
    }
```

---

## 결과 처리

```python
def finalize(state: ApprovalState):

    status = (
        "안내확정"
        if state["decision"] == "승인"
        else "수정필요"
    )

    return {
        "status": status
    }
```

---

## 그래프

```text
START
  ↓
review
  ↓
interrupt()
  ↓
[SQLite에 대기 상태 저장]
  ↓
Command(resume=...)
  ↓
finalize
  ↓
END
```

```python
approval_builder.add_edge(
    START,
    "review",
)

approval_builder.add_edge(
    "review",
    "finalize",
)

approval_builder.add_edge(
    "finalize",
    END,
)
```

조건에 따라 이동하는 노드는 같고 `status`만 달라지므로 조건부 엣지가 필요하지 않음.

---

# 15. interrupt 대기 상태 확인

```python
saved = graph.get_state(config)
```

대기 중:

```python
saved.next
saved.interrupts
```

예:

```text
next
→ ('review',)

interrupts
→ 승인/반려 응답 대기
```

중요:

```text
next가 존재한다
≠ 반드시 사람 입력 대기
```

사람 응답 대기는 `saved.interrupts`로 확인.

---

# 16. 재시작 후 승인·반려

같은 SQLite 파일과 같은 `thread_id`로 다시 연결.

```python
saved = graph.get_state(config)

if saved.interrupts:
    graph.invoke(
        Command(resume="승인"),
        config,
    )
```

반려:

```python
Command(resume="반려")
```

완료 후:

```python
current = graph.get_state(config)

current.values["decision"]
current.values["status"]
current.next
```

완료된 경우:

```python
current.next == ()
```

---

# 17. interrupt 재개 시 주의

`interrupt()`가 있던 노드는 재개할 때 **노드 처음부터 다시 실행**됨.

```text
review 시작
   ↓
interrupt()
   ↓
SQLite 저장
   ↓
프로그램 종료
   ↓
Command(resume)
   ↓
review 처음부터 재실행
   ↓
interrupt 위치에서 resume 값 반환
```

따라서 외부 부작용 작업은 주의해야 함.

```text
위험

메일 전송
  ↓
interrupt()
```

재개 시 메일 전송이 반복될 수 있음.

가능하면:

```text
interrupt()
  ↓
승인
  ↓
메일 전송 노드
```

외부 작업에는 별도의 업무 ID 기반 중복 방지도 필요.

---

# 18. 여행 플래너 예제의 핵심 구조

교안 마지막 실습은 다음 흐름을 SQLite에 저장함.

```text
START
  ↓
load_weather
  │  날씨 API 조회
  ↓
research_destination
  │  Agent → 검색 Tool
  ↓
prepare_travel
  │  LLM으로 일정 생성
  ↓
review_travel
  │
  └─ interrupt()
       ↓
   SQLite 저장
       ↓
  사람 승인 / 반려
       ↓
finish_travel
  ↓
END
```

핵심은 API 구현 자체보다 **조회한 근거와 생성 결과까지 State에 담아 함께 저장**하는 것.

---

# 19. 여행 State 구조

```python
class TravelState(TypedDict):

    request: dict

    weather: dict

    research_messages: list[AnyMessage]

    research: str

    sources: list[str]

    plan: str

    weather_reason: str

    pending_items: list[str]

    decision: str

    status: str
```

역할:

| 필드 | 저장 내용 |
|---|---|
| `request` | 여행 조건 |
| `weather` | 조회한 날씨 원자료 |
| `research_messages` | Agent와 Tool 실행 기록 |
| `research` | 조사 요약 |
| `sources` | 검색 출처 |
| `plan` | 생성 일정 |
| `weather_reason` | 날씨 반영 이유 |
| `pending_items` | 추가 확인 사항 |
| `decision` | 승인 / 반려 |
| `status` | 진행 상태 |

대화 누적이 목적이 아니므로 이 State에는 `add_messages`를 사용하지 않음.

---

# 20. 여행 그래프 노드의 반환 구조

## 날씨

```python
def load_weather(state):
    weather = fetch_weather(
        state["request"]
    )

    return {
        "weather": weather
    }
```

---

## 조사 Agent

```python
response = travel_researcher.invoke({
    "messages": [
        HumanMessage(content=query)
    ]
})
```

반환:

```python
return {
    "research_messages":
        response["messages"],

    "research":
        response["messages"][-1].text,

    "sources":
        sources,
}
```

Tool의 실제 응답에서 URL을 추출하여 `sources`에 저장함.

---

## 여행 계획 생성

```python
response = travel_plan_chain.invoke(
    payload
)

return {
    "plan":
        response.plan,

    "weather_reason":
        response.weather_reason,

    "pending_items":
        response.pending_items,

    "status":
        "승인대기",
}
```

---

## 승인 대기

```python
def review_travel(state):

    request = {
        "plan":
            state["plan"],

        "weather_reason":
            state["weather_reason"],

        "sources":
            state["sources"],

        "pending_items":
            state["pending_items"],

        "choices":
            ["승인", "반려"],
    }

    decision = interrupt(request)

    return {
        "decision": decision
    }
```

---

## 최종 상태

```python
def finish_travel(state):

    status = (
        "계획확정"
        if state["decision"] == "승인"
        else "재검토필요"
    )

    return {
        "status": status
    }
```

---

# 21. 저장 기록이 있을 때 실행 판단

교안의 핵심 실전 패턴.

```python
saved = graph.get_state(config)
```

## 기록 없음

```python
if not saved.values:
    graph.invoke(
        initial_input,
        config,
    )
```

→ 최초 실행

---

## 실행할 노드는 남았지만 interrupt는 없음

```python
elif (
    saved.next
    and not saved.interrupts
):
    graph.invoke(
        None,
        config,
    )
```

→ 중간 오류 등으로 멈춘 작업을 마지막 Checkpoint부터 계속 실행

---

## interrupt 존재

```python
if saved.interrupts:
    graph.invoke(
        Command(resume=decision),
        config,
    )
```

→ 사람의 판단으로 재개

---

# 22. 저장 상태에 따라 무엇을 보내는가

```text
저장 기록 없음
       ↓
초기 input

완료된 대화
       ↓
새 input

interrupt 대기
       ↓
Command(resume=...)

미완료 + interrupt 없음
       ↓
invoke(None, config)
```

---

# 23. 복원 시 외부 API 재호출 방지

여행 플래너에서는 승인 대기 직전까지 다음 값이 이미 SQLite에 저장됨.

```text
날씨 원자료
검색 Tool 결과
Agent 메시지
출처
생성된 일정
```

재시작 후:

```python
restored = graph.get_state(
    travel_config
)
```

저장 내용을 그대로 읽음.

```text
SQLite
  ↓
저장 당시 날씨
검색 결과
계획
  ↓
사용자 검토
```

따라서 승인만 재개하면 날씨 API·검색·LLM을 다시 호출하지 않음.

단, DB에 저장된 날씨는 **저장 당시의 날씨 데이터**이며 자동으로 최신화되지는 않음.

최신 자료로 새 계획을 만들려면 새로운 `thread_id`로 다시 실행.

---

# 24. `thread_id` 사용 원칙

| 목적 | 사용 방법 |
|---|---|
| 같은 대화에 새 질문 | 같은 `thread_id` |
| 새로운 대화 시작 | 새 `thread_id` |
| 프로그램 재시작 후 복원 | 같은 DB + 같은 `thread_id` |
| 승인 대기 재개 | 같은 `thread_id` + `Command(resume=...)` |
| 최신 자료로 완전히 새 작업 | 새 `thread_id` |

---

# 25. 실무에서 주의할 점

## SQLite 용도

`SqliteSaver`는 로컬·학습·소규모 실행에 적합.

```text
단일 PC / 로컬 실행
→ SQLite

여러 서버가 같은 상태 공유
→ PostgreSQL 등 서버형 Checkpointer 검토
```

---

## `thread_id`는 인증 수단이 아님

```text
thread_id
= 저장된 작업을 찾는 식별자

로그인 / 권한 검사
= 별도 구현
```

사용자가 특정 `thread_id`를 안다고 해서 해당 대화를 볼 권한이 있는 것은 아님.

---

# 26. 핵심 문법 모음

```python
# SQLite Checkpointer
with SqliteSaver.from_conn_string(
    str(db_path)
) as checkpointer:

    graph = builder.compile(
        checkpointer=checkpointer
    )
```

```python
# thread
config = {
    "configurable": {
        "thread_id": "job-v1"
    }
}
```

```python
# 최초 / 새 입력
graph.invoke(
    input_data,
    config,
)
```

```python
# 저장 상태 조회
saved = graph.get_state(
    config
)
```

```python
saved.values
saved.next
saved.interrupts
```

```python
# interrupt 재개
graph.invoke(
    Command(resume="승인"),
    config,
)
```

```python
# 저장 지점부터 계속 실행
graph.invoke(
    None,
    config,
)
```

```python
# SQLite 직접 연결
conn = sqlite3.connect(
    db_path,
    check_same_thread=False,
)

checkpointer = SqliteSaver(conn)
```

---

# 최종 정리

```text
InMemorySaver
= 현재 프로세스 안에서만 State 유지

SqliteSaver
= State를 파일에 영속 저장

Checkpoint
= State + next + interrupt 기록

thread_id
= 어떤 작업의 Checkpoint를 사용할지 지정

get_state()
= 저장된 실행 상태 조회

같은 DB + 같은 thread_id
= 이전 실행 복원

새 input
= 완료된 작업에 새로운 데이터 추가

Command(resume)
= interrupt 대기 작업 재개
```

### 전체 흐름

```text
             ┌──────────────┐
             │  StateGraph  │
             └──────┬───────┘
                    ↓
           compile(checkpointer)
                    ↓
             SQLiteSaver
                    ↓
        ┌──── thread_id ────┐
        │                   │
        ↓                   ↓
      State               next
      messages            interrupt
        │                   │
        └────── SQLite ──────┘
                    │
              프로그램 종료
                    │
              프로그램 재시작
                    ↓
         State / Node / Edge 재정의
                    ↓
            같은 DB에 재연결
                    ↓
             같은 thread_id
                    ↓
               get_state()
                    ↓
        ┌───────────┴───────────┐
        │                       │
     새 입력                 interrupt 대기
        │                       │
 invoke(input)         Command(resume)
        │                       │
        └───────────┬───────────┘
                    ↓
               실행 계속
                    ↓
             SQLite 다시 저장
```
