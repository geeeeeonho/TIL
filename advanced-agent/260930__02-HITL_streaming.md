# LangGraph HITL · 스트리밍 압축 정리

> 핵심 목표: **그래프 실행 중 사람의 판단을 받고 멈췄다가 재개하는 방법(HITL)**과  
> **실행 과정·LLM 출력·State 변화를 스트리밍으로 확인하는 방법**을 익힘.

---

# 1. HITL 핵심 구조

## HITL(Human In The Loop)

자동 실행 중 사람이 직접 판단하여 다음 흐름을 결정하는 방식.

주요 사용 예:

- 사용자에게 추가 정보 요청
- 생성 결과 검토
- 수정 요청
- 승인 / 반려
- 권한이 필요한 작업 승인

### 기본 흐름

```text
START
  ↓
초안 작성
  ↓
사람 검토
  │
  ├─ approve ─→ 확정 ─→ END
  │
  ├─ edit ─────→ 수정
  │               ↓
  │            사람 재검토
  │               ↺
  │
  └─ reject ───→ END
```

LangGraph에서는 주로 다음 조합을 사용함.

```text
interrupt()
    ↓
실행 중단 + 체크포인트 저장
    ↓
사람의 입력
    ↓
Command(resume=...)
    ↓
중단된 작업 재개
```

---

# 2. HITL을 위한 State와 핵심 문법

## State 정의

검토할 원문, 최신 초안, 사람의 결정 등을 State에 저장.

```python
from typing import TypedDict

class NoticeState(TypedDict):
    brief: str
    draft: str
    decision: str
    feedback: str
    published_text: str
```

예시 의미:

| 필드 | 역할 |
|---|---|
| `brief` | 변경하면 안 되는 확정 정보 |
| `draft` | 사람이 검토할 최신 문서 |
| `decision` | `approve`, `edit`, `reject` |
| `feedback` | 수정 요청 내용 |
| `published_text` | 최종 승인된 결과 |

노드는 **변경할 필드만 반환**함.

```python
def publish(state: NoticeState):
    return {"published_text": state["draft"]}
```

반환하지 않은 State 필드는 그대로 유지됨.

---

## `interrupt()` : 사람의 입력을 기다리기

```python
from langgraph.types import interrupt

def human_review(state: NoticeState):
    decision = interrupt({
        "stage": "notice_review",
        "draft": state["draft"],
        "actions": ["approve", "edit", "reject"],
    })

    return {
        "decision": decision["action"],
        "feedback": decision.get("feedback", ""),
        "draft": decision.get("edited_text", state["draft"]),
    }
```

`interrupt()`에 넣은 값은 **사람에게 보여 줄 검토 요청 데이터**임.

```text
human_review 실행
        ↓
interrupt({...})
        ↓
그래프 실행 중단
        ↓
사람의 입력 대기
```

`actions`는 선택지를 설명하는 데이터일 뿐, LangGraph가 입력값을 자동 검증하지는 않음.

---

## `Command(resume=...)` : 중단된 그래프 재개

```python
from langgraph.types import Command

graph.invoke(
    Command(resume={"action": "approve"}),
    config,
)
```

수정 요청:

```python
graph.invoke(
    Command(
        resume={
            "action": "edit",
            "feedback": "첫 문장을 더 명확하게 수정"
        }
    ),
    config,
)
```

### 특정 interrupt에 응답

현재 중단 ID를 읽은 뒤 ID와 응답을 연결할 수도 있음.

```python
snapshot = graph.get_state(config)
request = snapshot.interrupts[0]

graph.invoke(
    Command(
        resume={
            request.id: {
                "action": "edit",
                "feedback": "내용 수정"
            }
        }
    ),
    config,
)
```

특히 여러 interrupt를 구분할 때 유용함.

---

## `interrupt()` 재개 시 중요한 특징

`Command(resume=...)`로 재개하면 **중단된 노드는 처음부터 다시 실행**됨.

```text
write_draft
    ↓ 완료
human_review
    ↓
interrupt 발생
    ↓
[대기]
    ↓ resume
human_review 처음부터 다시 실행
    ↓
interrupt 위치에서 resume 값 반환
```

이미 완료된 이전 노드인 `write_draft`까지 다시 실행되는 것은 아님.

따라서 중복 실행되면 안 되는 작업은 `interrupt()` 이전에 두지 않는 것이 중요함.

```text
나쁜 예

human_review
 ├─ 결제 실행
 └─ interrupt()
```

```text
권장

human_review
 └─ interrupt()
       ↓ approve
결제 실행 노드
```

---

# 3. 체크포인터와 `thread_id`

HITL은 실행을 중간에 멈췄다가 이어야 하므로 **체크포인터가 필요**함.

```python
from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()

graph = builder.compile(
    checkpointer=checkpointer
)
```

실행할 때 `thread_id`로 작업을 구분함.

```python
config = {
    "configurable": {
        "thread_id": "notice-001"
    }
}
```

### 세 식별자의 차이

```text
thread_id
└─ 전체 작업 / 대화 식별

    interrupt.id
    └─ 현재 대기 중인 개별 중단 요청 식별

        stage
        └─ 어떤 종류의 검토인지 사람이 구분하기 위한 값
```

| 값 | 역할 |
|---|---|
| `thread_id` | 전체 작업 기록 구분 |
| `interrupt.id` | 응답할 중단 요청 구분 |
| `stage` | 내용 검토 / 게시 승인 등 업무 단계 표시 |

`stage`는 LangGraph의 특별한 예약어가 아니라 **사용자가 직접 넣는 데이터**임.

---

## 현재 중단 상태 확인

```python
snapshot = graph.get_state(config)

print(snapshot.values)
print(snapshot.interrupts)
print(snapshot.next)
```

현재 interrupt:

```python
request = snapshot.interrupts[0]

print(request.id)
print(request.value)
```

### 핵심 관계

```text
체크포인터
    ↓ 저장
thread_id
    ↓ 작업 선택
State + interrupt + 다음 실행 위치
    ↓
Command(resume=...)
    ↓
동일 작업 재개
```

`thread_id`만 설정한다고 저장되는 것은 아님.  
`compile(checkpointer=...)`가 함께 필요함.

`InMemorySaver`는 메모리에만 저장하므로 커널이 종료되면 기록도 사라짐.

---

# 4. 조건부 엣지로 승인 · 수정 · 반려 연결

## 라우팅 함수

사람의 선택을 읽어 다음 경로를 반환.

```python
from typing import Literal

def route_review(
    state: NoticeState
) -> Literal["approve", "edit", "reject"]:

    if state["decision"] == "approve":
        return "approve"

    if state["decision"] == "edit":
        return "edit"

    return "reject"
```

LLM이 판단하는 것이 아니라 **State에 저장된 사람의 선택값으로 분기**함.

---

## 그래프 연결

```python
from langgraph.graph import START, END, StateGraph

builder = StateGraph(NoticeState)

builder.add_node("write_draft", write_draft)
builder.add_node("human_review", human_review)
builder.add_node("revise_draft", revise_draft)
builder.add_node("publish", publish)

builder.add_edge(START, "write_draft")
builder.add_edge("write_draft", "human_review")

builder.add_conditional_edges(
    "human_review",
    route_review,
    {
        "approve": "publish",
        "edit": "revise_draft",
        "reject": END,
    }
)

builder.add_edge("revise_draft", "human_review")
builder.add_edge("publish", END)

graph = builder.compile(
    checkpointer=InMemorySaver()
)
```

### 구조

```text
START
  ↓
write_draft
  ↓
human_review
  │
  ├─ approve → publish → END
  │
  ├─ edit → revise_draft
  │             │
  │             └────────→ human_review
  │
  └─ reject → END
```

수정 결과는 자동 승인하지 않고 다시 사람에게 검토받음.

---

## 사람이 직접 편집한 문장 승인

LLM 수정 대신 사람이 직접 최종 문장을 바꿀 수도 있음.

```python
Command(
    resume={
        "action": "approve",
        "edited_text": reviewed_text,
    }
)
```

검토 노드에서:

```python
"draft": decision.get(
    "edited_text",
    state["draft"]
)
```

따라서 두 방식이 구분됨.

```text
action="edit"
→ feedback을 LLM 수정 노드에 전달

action="approve" + edited_text
→ 사람이 직접 편집한 문장을 바로 승인
```

---

# 5. 스트리밍

## 스트리밍이 필요한 이유

일반 실행:

```text
실행 시작
   ↓
전체 작업 완료
   ↓
최종 결과 한 번에 반환
```

스트리밍:

```text
실행 시작
   ↓
중간 진행 정보
   ↓
생성되는 문장 조각
   ↓
State 변화
   ↓
사람 검토 대기
   ↓
최종 결과
```

챗봇, 문서 생성, 에이전트 진행 상황, HITL 대기 화면 등에 사용 가능.

---

## `stream()`의 주요 모드

| 모드 | 받는 값 | 용도 |
|---|---|---|
| `updates` | 노드가 변경한 State | 어떤 노드가 무엇을 바꿨는지 확인 |
| `values` | 단계별 전체 State | 현재 상태 표시 |
| `messages` | LLM 메시지 조각 + 메타데이터 | 토큰/문장 스트리밍 |
| `custom` | 직접 전송한 사용자 정의 데이터 | 진행 상태 표시 |

추가 진단용:

- `checkpoints`
- `tasks`
- `debug`

---

## `custom` 스트림 보내기

노드 내부에서:

```python
from langgraph.config import get_stream_writer

def write_draft(state: NoticeState):
    writer = get_stream_writer()

    writer({
        "node": "write_draft",
        "status": "안내문 작성 중"
    })

    response = draft_chain.invoke({
        "brief": state["brief"]
    })

    return {"draft": response.text}
```

`writer(...)`는 State를 수정하지 않고 진행 정보만 보냄.

---

## `stream(..., version="v2")`

```python
for part in graph.stream(
    input_data,
    config,
    stream_mode=[
        "updates",
        "values",
        "messages",
        "custom",
    ],
    version="v2",
):
    print(part)
```

각 결과는 기본적으로 다음 구조로 구분함.

```python
part["type"]
part["data"]
```

### `messages`

```python
if part["type"] == "messages":
    message, metadata = part["data"]

    print(message.text, end="")
```

특정 노드의 LLM 출력만 선택:

```python
if (
    metadata.get("langgraph_node") == "write_draft"
    and message.text
):
    print(message.text, end="")
```

---

### `updates`

```python
if part["type"] == "updates":
    update = part["data"]

    if "__interrupt__" in update:
        print("사람의 검토 대기")
```

일반 노드 업데이트는 대략 다음 의미.

```text
{
    "write_draft": {
        "draft": "..."
    }
}
```

---

### `values`

```python
if part["type"] == "values":
    state = part["data"]

    print(state["draft"])
    print(state["decision"])
```

각 단계의 **전체 State** 확인에 사용.

---

### `custom`

```python
if part["type"] == "custom":
    print(part["data"]["status"])
```

`get_stream_writer()`로 직접 보낸 진행 정보를 받음.

---

## 스트리밍 중 interrupt

```text
messages
→ 생성 중 문장 표시

updates
→ 노드 변화 표시

values
→ 현재 State 표시

custom
→ "작성 중" 등 진행 상황

__interrupt__
→ 사람의 입력 대기
```

스트리밍으로 시작했더라도 재개 방식은 동일함.

```python
graph.invoke(
    Command(resume={"action": "approve"}),
    config,
)
```

반드시 같은 `thread_id`를 사용해야 함.

---

# 6. `stream_events(version="v3")`

교안에서는 `stream()`과 별도로 `stream_events()` 방식도 소개함.

## 차이

| 방식 | 읽는 방법 |
|---|---|
| `stream(..., version="v2")` | `part["type"]`, `part["data"]` |
| `stream_events(..., version="v3")` | `run.messages`, `run.values`, `run.output` |

교안 기준으로 v3 API는 **실험 단계**임.

---

## 기본 형태

```python
run = graph.stream_events(
    input_data,
    config,
    version="v3",
)
```

주요 접근:

```python
run.messages
run.values
run.output
run.interrupted
run.interrupts
```

### 상태와 메시지를 함께 읽기

```python
for kind, item in run.interleave(
    "values",
    "messages",
):
    if kind == "values":
        print(item)

    elif kind == "messages":
        for text in item.text:
            print(text, end="")
```

최종 상태:

```python
result = run.output
```

interrupt 확인:

```python
if run.interrupted:
    for item in run.interrupts:
        print(item.id)
        print(item.value)
```

재개:

```python
resumed_run = graph.stream_events(
    Command(resume={"action": "approve"}),
    config,
    version="v3",
)

result = resumed_run.output
```

---

# 7. HITL이 여러 단계일 때

교안의 채용 공고 예제는 HITL을 두 번 사용함.

```text
START
  ↓
공고 작성
  ↓
내용 검토 HITL
  │
  ├─ edit → 수정 → 내용 검토 HITL ↺
  │
  ├─ reject → END
  │
  └─ approve
         ↓
     게시 승인 HITL
         │
         ├─ reject → END
         │
         └─ approve
                ↓
             최종 확정
                ↓
               END
```

**내용 승인과 게시 승인은 서로 다른 판단**이므로 State도 따로 관리함.

```python
class JobState(TypedDict):
    requirements: str
    post: str

    decision: str
    feedback: str

    publication_decision: str
    approved_post: str
```

---

## 첫 번째 HITL

```python
def review_post(state: JobState):
    decision = interrupt({
        "stage": "content_review",
        "post": state["post"],
        "actions": [
            "approve",
            "edit",
            "reject",
        ],
    })

    return {
        "decision": decision["action"],
        "feedback": decision.get(
            "feedback",
            ""
        ),
    }
```

---

## 두 번째 HITL

```python
def approve_post(state: JobState):
    decision = interrupt({
        "stage": "publication_approval",
        "post": state["post"],
        "actions": [
            "approve",
            "reject",
        ],
    })

    return {
        "publication_decision":
            decision["action"]
    }
```

> **교안 코드 주의**  
> 실습 설명에서는 위처럼 `stage`, `post`, `actions`를 담도록 안내하지만, 실제 `approve_post` 코드 셀에는 단순 문자열을 `interrupt()`에 넘긴 부분이 있음.  
> 정리본에서는 **교안의 설명과 실습 요구사항에 맞는 딕셔너리 형태**를 기준으로 작성함.

---

## 두 라우팅 함수

```python
def route_post(state: JobState):
    return state["decision"]


def route_publication(state: JobState):
    return state["publication_decision"]
```

그래프 연결:

```python
builder.add_conditional_edges(
    "review_post",
    route_post,
    {
        "approve": "approve_post",
        "edit": "revise_post",
        "reject": END,
    }
)

builder.add_edge(
    "revise_post",
    "review_post"
)

builder.add_conditional_edges(
    "approve_post",
    route_publication,
    {
        "approve": "finalize_post",
        "reject": END,
    }
)
```

두 검토 모두 같은 작업이므로 **같은 `thread_id`를 유지**함.

단, 수정 후 새로운 interrupt가 만들어지면 **현재 대기 목록에서 새 interrupt ID를 다시 읽어야 함**.

```python
request = graph.get_state(config).interrupts[0]
```

---

# 8. 핵심 문법 요약

```python
# 1. 사람에게 검토 요청 후 대기
response = interrupt(data)
```

```python
# 2. 대기 중인 작업 재개
Command(resume=response)
```

```python
# 3. 특정 interrupt에 응답
Command(
    resume={
        interrupt_id: response
    }
)
```

```python
# 4. 체크포인터 연결
graph = builder.compile(
    checkpointer=InMemorySaver()
)
```

```python
# 5. 작업 구분
config = {
    "configurable": {
        "thread_id": "..."
    }
}
```

```python
# 6. 현재 상태 확인
snapshot = graph.get_state(config)

snapshot.values
snapshot.interrupts
snapshot.next
```

```python
# 7. 조건부 경로
builder.add_conditional_edges(
    node,
    route_function,
    {
        "A": "next_a",
        "B": "next_b",
    }
)
```

```python
# 8. 실행 스트리밍
graph.stream(
    input_data,
    config,
    stream_mode=[
        "updates",
        "values",
        "messages",
        "custom",
    ],
    version="v2",
)
```

```python
# 9. custom 진행 정보
writer = get_stream_writer()
writer({"status": "처리 중"})
```

```python
# 10. event streaming
run = graph.stream_events(
    input_data,
    config,
    version="v3",
)
```

---

# 최종 핵심

```text
HITL
= interrupt + checkpoint + thread_id + Command(resume)

interrupt
= 사람의 판단이 필요한 지점에서 실행 중단

Command(resume)
= 사람이 입력한 결과로 중단된 실행 재개

조건부 엣지
= approve / edit / reject에 따라 다음 노드 결정

수정 Cycle
= edit → 수정 → 다시 human_review

thread_id
= 하나의 작업 전체를 식별

interrupt.id
= 현재 응답할 개별 중단 요청 식별

stage
= 어떤 검토 단계인지 사람이 구분하기 위한 사용자 정의 값

stream
= 실행 중 State·노드 변화·LLM 출력·진행 정보를 순차적으로 확인
```

### 전체 흐름

```text
            ┌───────────────┐
            │   StateGraph   │
            └───────┬───────┘
                    ↓
              LLM 작업 노드
                    ↓
               interrupt()
                    ↓
        ┌──── 체크포인터 저장 ────┐
        │                         │
        │      사람의 검토         │
        │                         │
        └── Command(resume=...) ──┘
                    ↓
              조건부 엣지
            ↙       ↓       ↘
         승인      수정      반려
          ↓         ↓         ↓
        확정      재검토      END
          ↓
         END

실행 과정은
updates / values / messages / custom
스트림으로 관찰 가능
```
