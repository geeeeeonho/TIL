# LangGraph 사이클 · 체크포인터 압축 정리

> 개념과 코드 문법 중심으로 압축. 긴 프롬프트·출력은 생략하고, 이미지 흐름은 텍스트 도식으로 변환.

## 1. 핵심 개념

이 교안의 핵심은 **반복 실행(Cycle)** 과 **상태 저장(Checkpointer)** 이다.

- **Cycle**: 이전 노드로 다시 돌아가는 그래프 흐름.
- **Self-correction**: `작성 → 검토 → 수정 → 재검토`를 반복하는 구조.
- **State**: 여러 노드가 공유하는 현재 데이터.
- **Conditional Edge**: State 값을 보고 다음 노드를 선택.
- **Checkpointer**: State와 실행 위치를 저장해 다음 `invoke()`에서 이어서 사용.
- **thread_id**: 하나의 체크포인터 안에서 대화/실행 기록을 구분하는 ID.

### 전체 구조

```text
[입력 자료]
  ├─ 채용 공고
  ├─ 회사 정보
  └─ 지원자 정보
       │
       ▼
START
  │
  ▼
[초안 작성]
  │
  ▼
[검토]
  ├─ 통과 ----------------------→ END
  ├─ 검토 상한 도달 ------------→ END
  └─ 수정 필요
        │
        ▼
     [수정]
        │
        └──────────────→ [검토]
```

반복 자체가 품질 향상을 보장하지 않으므로 **검토 기준 + 최대 반복 횟수**를 같이 둔다.

---

## 2. 작성 → 검토 → 수정 Cycle

### State 정의

`TypedDict`로 그래프가 공유할 필드를 정의한다.

```python
from typing_extensions import TypedDict

class ResumeState(TypedDict):
    job_posting: str
    company_info: str
    applicant_info: str
    draft: str
    feedback: str
    passed: bool
    review_count: int
    max_reviews: int
```

초기 State는 일반 딕셔너리 형태.

```python
initial_state: ResumeState = {
    "job_posting": job_posting,
    "company_info": company_info,
    "applicant_info": applicant_info,
    "draft": "",
    "feedback": "",
    "passed": False,
    "review_count": 0,
    "max_reviews": 3,
}
```

### 핵심 원칙

노드는 전체 State를 다시 만들 필요가 없다. **변경할 필드만 딕셔너리로 반환**하면 된다.

```python
def draft_resume(state: ResumeState):
    response = resume_chain.invoke({...})
    return {"draft": response.text}
```

```text
기존 State
   +
노드 반환값 {"draft": ...}
   ↓
갱신된 State
```

---

### Prompt → LLM 체인

```python
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([
    ("system", "작성 규칙 ..."),
    ("human", "공고:\n{job_posting}\n지원자:\n{applicant_info}"),
])

chain = prompt | llm
```

실행:

```python
response = chain.invoke({
    "job_posting": state["job_posting"],
    "applicant_info": state["applicant_info"],
})

text = response.text
```

핵심 문법:

```text
Prompt | LLM
      ↓
   .invoke({...})
      ↓
 response.text
```

---

### 구조화된 검토 결과

검토 결과는 `passed`, `feedback`처럼 정해진 형식이 필요하므로 Pydantic 사용.

```python
from pydantic import BaseModel, Field

class ResumeReview(BaseModel):
    passed: bool
    feedback: str
```

```python
review_chain = review_prompt | llm.with_structured_output(
    ResumeReview,
    strict=True,
)
```

검토 노드:

```python
def review_resume(state: ResumeState):
    review = review_chain.invoke({...})

    return {
        "passed": review.passed,
        "feedback": review.feedback,
        "review_count": state["review_count"] + 1,
    }
```

`with_structured_output()`은 **출력 형식**을 맞추는 기능이다. 내용 자체의 사실성을 자동 보장하는 것은 아니다.

---

### 수정 노드

검토 의견을 다음 생성에 다시 넣는다.

```python
def revise_resume(state: ResumeState):
    response = revise_chain.invoke({
        "job_posting": state["job_posting"],
        "company_info": state["company_info"],
        "applicant_info": state["applicant_info"],
        "draft": state["draft"],
        "feedback": state["feedback"],
    })

    return {"draft": response.text}
```

핵심 흐름:

```text
review_resume
   │
   └─ feedback 저장
          │
          ▼
revise_resume
   │
   └─ feedback을 이용해 draft 수정
```

---

## 3. 조건부 엣지로 반복 제어

라우팅 함수는 LLM을 호출하지 않고 **현재 State만 읽어 문자열을 반환**한다.

```python
from typing import Literal

def choose_next(state: ResumeState) -> Literal["revise", "end"]:
    if state["passed"] or state["review_count"] >= state["max_reviews"]:
        return "end"
    return "revise"
```

그래프 연결:

```python
from langgraph.graph import START, END, StateGraph

builder = StateGraph(ResumeState)

builder.add_node("draft_resume", draft_resume)
builder.add_node("review_resume", review_resume)
builder.add_node("revise_resume", revise_resume)

builder.add_edge(START, "draft_resume")
builder.add_edge("draft_resume", "review_resume")

builder.add_conditional_edges(
    "review_resume",
    choose_next,
    {
        "revise": "revise_resume",
        "end": END,
    },
)

builder.add_edge("revise_resume", "review_resume")

resume_graph = builder.compile()
```

### 문법 구조

```python
builder.add_conditional_edges(
    "조건을 판단할 노드",
    routing_function,
    {
        "라우팅 함수 반환값": "다음 노드",
    },
)
```

### 검토 횟수 계산

`max_reviews = 3`일 때 계속 미통과하면:

```text
초안 작성 1회
→ 검토 1
→ 수정 1
→ 검토 2
→ 수정 2
→ 검토 3
→ 종료
```

최대 LLM 호출 수:

```text
초안 1 + 검토 N + 수정 (N-1)
= 2N
```

따라서 `max_reviews=3`이면 최대 **6회** 호출.

---

## 4. Checkpointer로 대화 상태 저장

### 메시지를 누적하는 State

일반 `list` 필드는 새 값으로 덮어쓸 수 있다. 대화 메시지는 `add_messages` reducer를 붙여 누적한다.

```python
from typing import Annotated
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class CareerChatState(TypedDict):
    job_posting: str
    company_info: str
    applicant_info: str
    messages: Annotated[list[AnyMessage], add_messages]
```

`add_messages` 동작:

```text
새 message ID   → 추가
같은 message ID → 교체
```

---

### 이전 대화를 Prompt에 넣기

```python
from langchain_core.prompts import MessagesPlaceholder

career_prompt = ChatPromptTemplate.from_messages([
    ("system", "상담 규칙 ..."),
    MessagesPlaceholder("messages"),
])
```

```text
State["messages"]
      │
      ▼
MessagesPlaceholder
      │
      ▼
LLM이 이전 대화 + 현재 질문을 함께 읽음
```

---

### InMemorySaver 연결

```python
from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()

chat_builder = StateGraph(CareerChatState)
chat_builder.add_node("answer_career", answer_career)
chat_builder.add_edge(START, "answer_career")
chat_builder.add_edge("answer_career", END)

chat_graph = chat_builder.compile(checkpointer=checkpointer)
```

`InMemorySaver` 특징:

- 현재 Python 프로세스 메모리에 저장.
- 같은 `checkpointer` 객체를 계속 사용해야 함.
- 커널/프로세스가 종료되면 기록이 사라짐.
- `END`는 현재 실행의 종료일 뿐 저장 State를 삭제하지 않음.

---

## 5. thread_id로 대화 분리

### 첫 호출

첫 호출에는 저장할 기본 자료와 첫 메시지를 같이 전달한다.

```python
from langchain_core.messages import HumanMessage

config_a = {
    "configurable": {
        "thread_id": "career-A"
    }
}

result = chat_graph.invoke({
    "job_posting": job_posting,
    "company_info": company_info,
    "applicant_info": applicant_info,
    "messages": [HumanMessage(content="질문")],
}, config_a)
```

### 후속 호출

같은 `thread_id`라면 저장된 State를 불러오므로 새 메시지만 전달 가능.

```python
result = chat_graph.invoke({
    "messages": [HumanMessage(content="후속 질문")]
}, config_a)
```

### 다른 사용자/대화

```python
config_b = {
    "configurable": {
        "thread_id": "career-B"
    }
}
```

```text
Checkpointer
├─ thread_id = career-A
│   ├─ 지원자 A 정보
│   └─ A 대화 기록
│
└─ thread_id = career-B
    ├─ 지원자 B 정보
    └─ B 대화 기록
```

즉:

```text
같은 thread_id  = 같은 대화 이어가기
다른 thread_id  = 서로 독립된 State
```

---

## 6. 현재 State와 실행 이력 조회

### 현재 상태

```python
snapshot = chat_graph.get_state(config_a)
```

주요 속성:

```python
snapshot.values   # 저장된 State
snapshot.next     # 다음 실행 노드. 완료되면 ()
snapshot.config   # 해당 체크포인트 설정
```

### 과거 이력

```python
history = list(chat_graph.get_state_history(config_a))
```

`get_state_history()`는 **최신 → 과거** 순서.

```python
for saved in history:
    print(saved.metadata["step"])
    print(saved.next)
    print(saved.values)
```

시간 흐름대로 보고 싶으면:

```python
for saved in reversed(history):
    ...
```

```text
현재 State        → get_state()
전체 체크포인트   → get_state_history()
```

조회만으로 LLM을 다시 호출하지 않는다.

---

## 7. 그래프 밖의 입력 반복

교안의 직접 상담 입력은 LangGraph 내부 Cycle이 아니라 **Python `while` 반복문**이다.

```python
while True:
    question = input("User: ").strip()

    if question == "종료":
        break
    if not question:
        continue

    result = chat_graph.invoke({
        "messages": [HumanMessage(content=question)]
    }, config_a)
```

구분:

```text
LangGraph Cycle
review → revise → review

Python 입력 반복
while → graph.invoke() → while → graph.invoke()
```

---

## 8. 결과 파일 저장

```python
from pathlib import Path

output_dir = Path("output")
output_dir.mkdir(parents=True, exist_ok=True)

output_path = output_dir / "resume_draft.md"
output_path.write_text(result_text, encoding="utf-8")
```

파일 읽기:

```python
text = Path("data/file.txt").read_text(encoding="utf-8")
```

핵심:

```text
read_text()  → 파일 읽기
write_text() → 파일 저장
```

---

## 9. 함께 따라하기 구조: 지원동기 개선 Cycle

이력서 Cycle과 구조는 동일하고 State 필드와 노드 이름만 바뀐다.

```text
START
  │
  ▼
draft_motivation
  │
  ▼
review_motivation
  ├─ passed=True --------------------------→ END
  ├─ review_count >= max_reviews ----------→ END
  └─ revise
       │
       ▼
revise_motivation
       │
       └────────────→ review_motivation
```

체크포인터까지 연결:

```python
motivation_memory = InMemorySaver()

motivation_graph = motivation_builder.compile(
    checkpointer=motivation_memory
)

motivation_config = {
    "configurable": {
        "thread_id": "motivation-doyun"
    }
}

result = motivation_graph.invoke(
    motivation_input,
    motivation_config,
)
```

---

## 10. 교안 코드에서 수정해야 할 부분

따라하기 영역에는 실행 결과가 우연히 첫 검토에서 통과하면서 드러나지 않은 오타가 있다.

### 1) `MotivationState` 초기값 타입/변수

교안 코드:

```python
initial_state: ResumeState = {
    ...
    "applicant_info": applicant_info,
    ...
}
```

의도에 맞는 형태:

```python
motivation_input: MotivationState = {
    "job_posting": job_posting,
    "company_info": company_info,
    "applicant_info": motivation_applicant,
    "motivation": "",
    "feedback": "",
    "passed": False,
    "review_count": 0,
    "max_reviews": 3,
}
```

따라하기용 지원자 `motivation_applicant`를 사용해야 한다.

### 2) `feedback` 키 오타

교안 코드:

```python
"motivfeedbackation": state["feedback"]
```

수정:

```python
"feedback": state["feedback"]
```

이 오타는 `revise_motivation`이 실제 실행될 때 Prompt 변수 누락 오류를 만들 수 있다.

---

## 11. 문법만 빠르게 보기

```python
# State
class MyState(TypedDict):
    value: str

# Node
def node(state: MyState):
    return {"value": "new"}

# Graph
builder = StateGraph(MyState)
builder.add_node("node", node)
builder.add_edge(START, "node")
builder.add_edge("node", END)
graph = builder.compile()

# Conditional Edge
builder.add_conditional_edges(
    "review",
    route,
    {"again": "revise", "end": END},
)

# Checkpointer
memory = InMemorySaver()
graph = builder.compile(checkpointer=memory)

# Thread
config = {"configurable": {"thread_id": "user-A"}}
graph.invoke(input_state, config)

# Current State
snapshot = graph.get_state(config)

# History
history = list(graph.get_state_history(config))

# Message Accumulation
messages: Annotated[list[AnyMessage], add_messages]
```

## 핵심 한 줄 정리

```text
State에 실행 정보를 저장하고
→ 조건부 엣지로 반복 여부를 판단하며
→ Checkpointer + thread_id로 여러 invoke 사이의 상태를 이어간다.
```
