# LangGraph State · Node · Edge 핵심 정리

> 목적: LangGraph 워크플로의 핵심인 **State → Node → Edge → compile → invoke** 구조 이해.
> 긴 프롬프트·실행 결과는 생략하고, 개념과 재사용 가능한 코드 문법 중심으로 정리.

---

## 1. 전체 구조

LangGraph 워크플로는 크게 3개 요소로 구성.

| 요소 | 의미 | 예시 |
|---|---|---|
| **State** | 노드 사이에서 공유하는 데이터 | 질문, 정책, 분류 결과, 답변 |
| **Node** | State를 읽고 작업하는 함수 | 문의 분류, 답변 생성 |
| **Edge** | 노드의 실행 순서·분기 | 분류 → 답변 |

### 기본 흐름

```text
초기 State
   ↓
START
   ↓
[Node A]
   │  필요한 State 읽기
   │  변경할 필드만 반환
   ↓
State 갱신
   ↓
[Node B]
   ↓
END
   ↓
최종 State
```

### LangChain과 LangGraph

```text
LangChain
└─ Prompt / LLM / Retriever / Tool 같은 AI 구성 요소 연결

LangGraph
└─ State를 중심으로 Node 실행 순서·분기·반복 관리
```

- **LangChain**: 개별 AI 기능 구성.
- **LangGraph**: 여러 작업의 실행 흐름 관리.
- 실행 그래프의 Node는 **데이터가 아니라 실행 함수**.

---

## 2. State 정의

State는 같은 그래프의 노드들이 공유하는 데이터.

```python
from typing_extensions import TypedDict

class InquiryState(TypedDict):
    question: str
    policy: str
    category: str
    answer: str
```

초기 상태는 일반 딕셔너리로 전달.

```python
inquiry_input: InquiryState = {
    "question": customer_question,
    "policy": policy_text,
    "category": "",
    "answer": "",
}
```

### 핵심 규칙

```text
State = 그래프 전체에서 공유할 값
지역 변수 = 한 함수 내부에서만 사용할 값
```

노드는 State 전체를 다시 만들 필요 없음.
**변경할 필드만 딕셔너리로 반환**.

```python
def classify_inquiry(state: InquiryState):
    return {"category": "환불"}
```

결과:

```text
기존 State
{question, policy, category="", answer=""}

        ↓ Node 반환
{"category": "환불"}

        ↓ LangGraph가 병합

새 State
{question, policy, category="환불", answer=""}
```

즉 `question`, `policy`, `answer`는 사라지지 않음.

### TypedDict와 BaseModel 차이

| 방식 | 주 용도 | 특징 |
|---|---|---|
| `TypedDict` | LangGraph State 정의 | 일반 dict 형태, 가벼움 |
| `BaseModel` | LLM 구조화 출력 검증 | 타입·형식 검증 가능 |

---

## 3. Node 정의

Node는 보통 다음 형태.

```python
def node_name(state: StateType):
    # 1. State에서 필요한 값 읽기
    value = state["field"]

    # 2. 작업 수행
    result = ...

    # 3. 변경할 State 필드만 반환
    return {"result_field": result}
```

### LLM Node 예시

구조화 출력 형식 정의.

```python
from typing import Literal
from pydantic import BaseModel, Field

class InquiryCategory(BaseModel):
    category: Literal["환불", "배송", "일반"] = Field(
        description="고객 문의의 주된 요청"
    )
```

Prompt + LLM 연결.

```python
from langchain_core.prompts import ChatPromptTemplate

classify_prompt = ChatPromptTemplate.from_messages([
    ("system", "문의 유형을 환불/배송/일반 중 하나로 분류하세요."),
    ("human", "{question}"),
])

classify_chain = (
    classify_prompt
    | llm.with_structured_output(InquiryCategory, strict=True)
)
```

Node에서 실행.

```python
def classify_inquiry(state: InquiryState):
    decision = classify_chain.invoke({
        "question": state["question"]
    })

    return {"category": decision.category}
```

### 일반 LLM 응답 Node

```python
answer_chain = answer_prompt | llm


def answer_inquiry(state: InquiryState):
    response = answer_chain.invoke({
        "question": state["question"],
        "category": state["category"],
        "policy": state["policy"],
    })

    return {"answer": response.text}
```

핵심:

```text
Node 입력  = 현재 State
Node 작업  = Python / LLM / 검색 / Tool 등
Node 출력  = 갱신할 State 일부
```

---

## 4. Edge와 그래프 생성

### 기본 문법

```python
from langgraph.graph import START, END, StateGraph

builder = StateGraph(InquiryState)

builder.add_node("classify_inquiry", classify_inquiry)
builder.add_node("answer_inquiry", answer_inquiry)

builder.add_edge(START, "classify_inquiry")
builder.add_edge("classify_inquiry", "answer_inquiry")
builder.add_edge("answer_inquiry", END)

graph = builder.compile()
```

### 텍스트 도식

```text
START
  ↓
classify_inquiry
  ↓
answer_inquiry
  ↓
END
```

### 각 문법 의미

| 문법 | 의미 |
|---|---|
| `StateGraph(State)` | 사용할 State 스키마 지정 |
| `add_node(name, func)` | 함수를 Node로 등록 |
| `add_edge(A, B)` | A 실행 후 B 실행 |
| `compile()` | 실행 가능한 그래프로 변환 |
| `invoke(input)` | 초기 State로 그래프 실행 |

실행.

```python
result = graph.invoke(inquiry_input)
```

`invoke()` 결과는 최종 State.

```python
print(result["category"])
print(result["answer"])
```

> Node 함수를 수정했다면 보통 **Node 등록 → Edge 연결 → compile**까지 다시 실행해야 새 그래프에 반영됨.

---

## 5. 전체 코드 생성 순서

```text
1. State 정의
      ↓
2. Node 함수 정의
      ↓
3. StateGraph 생성
      ↓
4. add_node()로 Node 등록
      ↓
5. add_edge() / add_conditional_edges()로 연결
      ↓
6. compile()
      ↓
7. invoke()
```

최소 형태:

```python
class MyState(TypedDict):
    input: str
    output: str


def my_node(state: MyState):
    result = state["input"] + " 처리"
    return {"output": result}


builder = StateGraph(MyState)
builder.add_node("my_node", my_node)
builder.add_edge(START, "my_node")
builder.add_edge("my_node", END)

graph = builder.compile()

result = graph.invoke({
    "input": "질문",
    "output": "",
})
```

---

## 6. Reducer: State 값을 누적하는 방법

일반 State 필드는 새 값이 들어오면 기존 값을 대체.

```text
기존 category = ""
새 category   = "환불"
→ "환불"로 교체
```

대화처럼 기존 값에 계속 추가해야 하는 경우 **Reducer** 사용.

### 메시지 누적 State

```python
from typing import Annotated
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class ChatState(TypedDict):
    policy: str
    messages: Annotated[list[AnyMessage], add_messages]
```

의미:

```text
기존 messages
[질문1, 답변1]

새 반환값
[질문2]

add_messages 적용
        ↓
[질문1, 답변1, 질문2]
```

일반 리스트로 선언하면 새 리스트가 기존 값을 덮어쓸 수 있음.

---

## 7. MessagesPlaceholder로 이전 대화 전달

State에 메시지를 저장하는 것만으로는 LLM이 자동으로 읽지 않음.
Prompt에 직접 전달해야 함.

```python
from langchain_core.prompts import MessagesPlaceholder

chat_prompt = ChatPromptTemplate.from_messages([
    ("system", "정책에 근거해 답하세요.\n정책:\n{policy}"),
    MessagesPlaceholder("messages"),
])

chat_chain = chat_prompt | llm
```

Node:

```python
def reply(state: ChatState):
    response = chat_chain.invoke({
        "policy": state["policy"],
        "messages": state["messages"],
    })

    return {"messages": [response]}
```

`add_messages`가 기존 대화에 새 `AIMessage`를 합침.

### 메시지 객체

```python
from langchain_core.messages import HumanMessage, AIMessage

HumanMessage(content="반품하고 싶어요")
AIMessage(content="7일 이내 신청 가능합니다.")
```

---

## 8. 조건부 Edge

고정 Edge:

```python
builder.add_edge("A", "B")
```

항상 A 다음 B 실행.

조건부 Edge:

```python
builder.add_conditional_edges(
    "user_input",
    route_chat,
    {
        "계속": "reply",
        "종료": END,
    },
)
```

라우팅 함수:

```python
def route_chat(state: ChatState):
    if state["messages"][-1].text.strip() == "/종료":
        return "종료"

    return "계속"
```

### 구조

```text
                ┌───────────────┐
                │   user_input  │
                └───────┬───────┘
                        │
                 route_chat()
                  /           \
             "계속"          "종료"
               ↓               ↓
            reply             END
               │
               └──────────────→ user_input
```

중요:

```text
add_conditional_edges(
    "분기 시작 노드",
    "라우팅 함수",
    {라우팅 반환값: 다음 노드}
)
```

라우팅 함수는 **State를 갱신하는 Node가 아니라 다음 경로를 선택하는 함수**.

---

## 9. 반복 그래프

대화 그래프 구조:

```text
START
  ↓
user_input
  ├─ 계속 → reply ─┐
  │                │
  └─ 종료 → END    │
                   │
                   └──→ user_input
```

Node 등록과 연결:

```python
chat_builder = StateGraph(ChatState)

chat_builder.add_node("user_input", user_input)
chat_builder.add_node("reply", reply)

chat_builder.add_edge(START, "user_input")

chat_builder.add_conditional_edges(
    "user_input",
    route_chat,
    {"계속": "reply", "종료": END},
)

chat_builder.add_edge("reply", "user_input")

chat_graph = chat_builder.compile()
```

반복 그래프 실행 시 진행 단계 제한 가능.

```python
result = chat_graph.invoke(
    chat_input,
    config={"recursion_limit": 100},
)
```

`recursion_limit`은 질문 개수가 아니라 **그래프 진행 단계 수의 상한**.

---

## 10. config 핵심 문법

```python
config = {
    "recursion_limit": 100,
    "run_name": "refund_consultation",
    "tags": ["web_chat", "production"],
    "metadata": {
        "request_id": "req_001",
        "policy_version": "2026-09",
    },
}

result = graph.invoke(input_state, config=config)
```

| 설정 | 의미 |
|---|---|
| `recursion_limit` | 최대 그래프 진행 단계 |
| `run_name` | 실행 이름 |
| `tags` | 실행 분류용 태그 |
| `metadata` | 요청 ID, 정책 버전 등 추가 정보 |

---

## 11. 실습 예제: 회의 메모 → 담당자별 메일

교안의 최종 실습 흐름.

```text
회의 메모
   ↓
extract_actions
- 담당자 / 할 일 / 기한 추출
   ↓
group_by_owner
- 담당자별 작업 묶기
- 담당자 미정 작업 분리
   ↓
draft_emails
- 담당자별 메일 초안 작성
   ↓
END
```

### State

```python
class MeetingState(TypedDict):
    meeting_notes: str
    action_items: list[dict]
    tasks_by_owner: dict[str, list[dict]]
    unassigned_items: list[dict]
    email_drafts: dict[str, dict]
```

### 1) 구조화 추출 Node

```python
class ActionItem(BaseModel):
    owner: str | None
    task: str
    due_date: str | None


class ActionItems(BaseModel):
    action_items: list[ActionItem]
```

```python
actions_chain = (
    actions_prompt
    | llm.with_structured_output(ActionItems, strict=True)
)


def extract_actions(state: MeetingState):
    result = actions_chain.invoke({
        "meeting_notes": state["meeting_notes"]
    })

    return {
        "action_items": result.model_dump()["action_items"]
    }
```

### 2) Python 처리 Node

LLM이 필요 없는 단순 묶기는 Python으로 처리.

```python
def group_by_owner(state: MeetingState):
    tasks_by_owner = {}
    unassigned_items = []

    for item in state["action_items"]:
        owner = item["owner"]

        if owner is None:
            unassigned_items.append(item)
        else:
            tasks_by_owner.setdefault(owner, []).append(item)

    return {
        "tasks_by_owner": tasks_by_owner,
        "unassigned_items": unassigned_items,
    }
```

### `setdefault()` 핵심

```python
tasks_by_owner.setdefault(owner, []).append(item)
```

동작:

```text
owner 키 없음 → 빈 리스트 [] 생성 → item 추가
owner 키 있음 → 기존 리스트 반환 → item 추가
```

### 3) 담당자별 LLM 호출 Node

```python
def draft_emails(state: MeetingState):
    email_drafts = {}

    for owner, items in state["tasks_by_owner"].items():
        draft = mail_chain.invoke({
            "owner": owner,
            "action_items": json.dumps(items, ensure_ascii=False),
        })

        email_drafts[owner] = draft.model_dump()

    return {"email_drafts": email_drafts}
```

여러 담당자를 병렬에 가깝게 처리할 때 `batch()` 사용 가능.

```python
owners = list(state["tasks_by_owner"])

inputs = [
    {
        "owner": owner,
        "action_items": json.dumps(
            state["tasks_by_owner"][owner],
            ensure_ascii=False,
        ),
    }
    for owner in owners
]

drafts = mail_chain.batch(
    inputs,
    config={"max_concurrency": 3},
)
```

### 그래프 연결

```python
meeting_builder = StateGraph(MeetingState)

meeting_builder.add_node("extract_actions", extract_actions)
meeting_builder.add_node("group_by_owner", group_by_owner)
meeting_builder.add_node("draft_emails", draft_emails)

meeting_builder.add_edge(START, "extract_actions")
meeting_builder.add_edge("extract_actions", "group_by_owner")
meeting_builder.add_edge("group_by_owner", "draft_emails")
meeting_builder.add_edge("draft_emails", END)

meeting_graph = meeting_builder.compile()
```

---

## 12. 이미지 내용 텍스트 변환

### State → Node → Edge

```text
[State]
question / policy / category / answer
        ↓
[classify Node]
category만 반환
        ↓
[State]
기존 값 유지 + category 갱신
        ↓
[answer Node]
answer만 반환
        ↓
[최종 State]
모든 필드 유지 + 결과 저장
```

### Workflow와 Agent 차이

```text
Workflow
설계자가 실행 순서 지정
A → B → C

ReAct Agent
모델이 현재 상황과 Tool 결과를 보고
다음 행동 / Tool 사용 / 최종 응답을 선택
```

### LangChain과 LangGraph 관계

```text
LangGraph 실행 흐름
┌─────────────────────────────┐
│ Node                        │
│  └─ LangChain 구성요소 사용 │
│     Prompt → LLM → Parser   │
└─────────────────────────────┘
```

### 멀티턴 상담 그래프

```text
START
  ↓
[user_input]
  │
  ├─ 계속 ─→ [reply]
  │            │
  │            └── 다시 user_input
  │
  └─ 종료 ─→ END

messages는 add_messages로 계속 누적
```

### 회의 실습 그래프

```text
START
  ↓
extract_actions
  ↓
group_by_owner
  ↓
draft_emails
  ↓
END

별도 결과:
unassigned_items = 담당자 미정 작업
```

---

## 13. 핵심 문법만 다시 보기

```python
# 1. State
class MyState(TypedDict):
    field: str

# 2. Node
def my_node(state: MyState):
    return {"field": "new value"}

# 3. Graph
builder = StateGraph(MyState)

# 4. Node 등록
builder.add_node("my_node", my_node)

# 5. Edge
builder.add_edge(START, "my_node")
builder.add_edge("my_node", END)

# 6. 조건부 Edge
builder.add_conditional_edges(
    "node",
    router,
    {"A": "next_a", "B": END},
)

# 7. Compile
graph = builder.compile()

# 8. Execute
result = graph.invoke(initial_state)
```

대화 누적:

```python
messages: Annotated[list[AnyMessage], add_messages]
```

이전 대화 Prompt 삽입:

```python
MessagesPlaceholder("messages")
```

구조화 출력:

```python
llm.with_structured_output(OutputModel, strict=True)
```

병렬 입력 처리:

```python
chain.batch(inputs, config={"max_concurrency": 3})
```

---

## 핵심 요약

```text
State
= Node들이 공유하는 데이터

Node
= State를 읽고 작업한 뒤 변경할 필드만 반환하는 함수

Edge
= Node 실행 순서 또는 분기

Reducer
= 새 State 값과 기존 값을 합치는 규칙

compile()
= 설계한 그래프를 실행 가능한 객체로 변환

invoke()
= 초기 State를 넣어 그래프 실행
```

가장 중요한 흐름:

```text
State 정의
→ Node 정의
→ Node 등록
→ Edge 연결
→ compile
→ invoke
```
