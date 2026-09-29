# LangGraph 기초 실습 정리

State를 정의하고, Node를 연결하고, 조건 분기와 반복 대화를 구성하는 기초 예제.

> **코드 전제**
> - 기존 코드 흐름과 결과를 유지함.
> - `llm`, `service_request`, `required_fields`는 앞 단계에서 준비된 값으로 가정함.
> - `Markdown`, `Image`도 노트북 환경에서 import된 상태로 가정함.
> - 원본의 코드 스크린샷은 중복이므로 제거하고, 그래프 이미지만 텍스트 도식으로 변환함.

---

# A. 서비스 의뢰를 구조화하고 첫 상담 답변 만들기

전체 흐름:

```text
[START]
   ↓
[extract_requirements]
   ↓
[find_missing]
   ↓
[draft_brief]
   ↓
 [END]
```

핵심은 하나의 `RequestState`를 여러 Node가 공유하면서 필요한 필드만 갱신하는 구조.

## 1. 서비스 의뢰를 공유할 State 만들기

`TypedDict`로 그래프 전체에서 공유할 State 구조를 정의함.

```python
from typing_extensions import TypedDict

# 그래프 노드 사이에서 공유할 상태 구조
class RequestState(TypedDict):
    request_text: str
    requirements: dict
    missing_fields: list[str]
    brief: str

# 그래프 실행 전 초기 상태
request_input: RequestState = {
    "request_text": service_request,
    "requirements": {},      # 추출된 요구사항
    "missing_fields": [],    # 아직 정해지지 않은 항목
    "brief": "",             # 최종 정리문
}

display(request_input)
```

### 결과

```text
{
  'request_text': '대학생을 위한 스터디룸 예약 서비스를 만들고 싶습니다.\n학생들은 휴대폰 웹에서 이용하고, 운영자는 스터디룸 4개의 예약 현황을 확인합니다.\n학생에게는 빈 시간 확인, 예약 신청, 내 예약 조회와 취소 기능이 필요합니다.\n같은 방의 같은 시간에 중복 예약이 생기지 않아야 합니다.\n한 번에 최대 몇 시간 예약할 수 있는지와 예약 시작 몇 시간 전까지 취소할 수 있는지는 아직 정하지 않았습니다.\n출시일도 미정입니다.',
  'requirements': {},
  'missing_fields': [],
  'brief': ''
}
```

**핵심**
- `State`는 Node 사이에서 공유되는 데이터 구조.
- 각 Node는 전체 State를 직접 다시 만들기보다 필요한 값만 반환해 갱신함.

---

## 2. LLM으로 요구사항 추출하기

자연어 의뢰를 코드가 다루기 쉬운 구조화 데이터로 변환함.

```python
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

# LLM이 추출할 요구사항의 형식
class ServiceRequirements(BaseModel):
    service_name: str = Field(description="의뢰에서 확인되는 서비스 종류")
    target_users: list[str] = Field(description="서비스를 이용할 대상")
    platform: str = Field(description="의뢰인이 말한 이용 환경")
    room_count: int = Field(description="운영할 스터디룸 수")
    features: list[str] = Field(description="의뢰에서 요청한 기능과 제약")
    max_hours_per_booking: int | None = Field(
        description="1회 최대 예약 시간. 미정이면 null"
    )
    cancellation_deadline_hours: int | None = Field(
        description="예약 시작 몇 시간 전까지 취소 가능한지. 미정이면 null"
    )
    launch_date: str | None = Field(
        description="의뢰인이 정한 출시일. 미정이면 null"
    )

# 원문에 없는 조건을 확정하지 않는 추출 기준
requirements_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "서비스 제작 의뢰에서 명시된 요구사항만 추출하세요. "
        "학생 기능, 운영자의 예약 현황 확인, 같은 방과 시간의 중복 예약 방지 조건을 보존하세요. "
        "미정인 예약 시간, 취소 기한, 출시일은 null로 반환하세요. "
        "통상적인 서비스 관행을 근거로 원문에 없는 결제, 로그인, 알림, 일정, 금액을 추가하지 마세요."
    ),
    ("human", "{request_text}"),
])

# LLM 출력을 ServiceRequirements 구조로 받기
requirements_chain = (
    requirements_prompt
    | llm.with_structured_output(ServiceRequirements)
)
```

구조화된 출력값으로 `requirements`만 갱신하는 Node를 작성함.

```python
def extract_requirements(state: RequestState):
    """의뢰를 구조화하고 딕셔너리로 변환한 요구사항만 반환합니다."""

    # 원문을 체인에 넣어 요구사항 추출
    result = requirements_chain.invoke({
        "request_text": state["request_text"]
    })

    # State의 requirements만 갱신
    return {
        "requirements": result.model_dump()
    }

# 간단한 테스트 실행
test_result = extract_requirements(request_input)
display(test_result)
```

### 결과

```text
{
  'requirements': {
    'service_name': '스터디룸 예약 서비스',
    'target_users': ['대학생', '운영자'],
    'platform': '학생: 휴대폰 웹, 운영자: 미정',
    'room_count': 4,
    'features': [
      '학생의 빈 시간 확인',
      '학생의 예약 신청',
      '학생의 내 예약 조회',
      '학생의 예약 취소',
      '운영자의 스터디룸 예약 현황 확인',
      '같은 방과 시간의 중복 예약 방지'
    ],
    'max_hours_per_booking': None,
    'cancellation_deadline_hours': None,
    'launch_date': None
  }
}
```

**핵심**
- `with_structured_output()`으로 LLM 결과 형식을 고정함.
- 원문에 없는 정보는 임의 생성하지 않고 `None`으로 유지함.
- Node는 `{"requirements": ...}`만 반환해 해당 State 필드만 갱신함.

---

## 3. Python Node로 미정 항목 찾기

LLM이 아니라 일반 Python 로직으로 `None`인 필드를 찾음.

```python
def find_missing(state: RequestState):
    """필수 확인 필드 중 값이 None인 필드 이름을 반환합니다."""
    missing_fields = []

    for field in required_fields:
        if state["requirements"][field] is None:
            missing_fields.append(field)

    return {"missing_fields": missing_fields}
```

간단한 테스트.

```python
missing_test: RequestState = {
    "request_text": "확인용 입력",
    "requirements": {
        "max_hours_per_booking": 0,
        "cancellation_deadline_hours": None,
        "launch_date": "",
    },
    "missing_fields": [],
    "brief": "",
}

print(find_missing(missing_test))
```

### 결과

```text
{'missing_fields': ['cancellation_deadline_hours']}
```

**핵심**
- `None`만 미정값으로 판단함.
- `0`, `""`는 `None`이 아니므로 누락 목록에 포함되지 않음.

---

## 4. 첫 상담 답변을 작성하는 Node 만들기

확정된 제작 범위와 아직 정하지 않은 조건을 구분해 답변을 생성함.

```python
import json

# 확인한 조건과 미정 조건을 구분하는 첫 상담 답변
brief_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "서비스 제작 의뢰를 받은 담당자로서 첫 상담 답변을 한국어로 짧게 작성하세요. "
        "'서비스 목표', '확정 요구사항', '확인 질문'으로 나누세요. "
        "확정 요구사항에는 사용자, 모바일 웹, 방 수, 요청 기능, 중복 예약 방지를 빠뜨리지 마세요. "
        "확인 질문은 전달된 확인 항목에 대해 한 항목당 하나씩 작성하세요. "
        "null인 운영 규칙이나 출시일을 임의로 정하지 말고, 없는 기능·일정·비용을 약속하지 마세요."
    ),
    (
        "human",
        "의뢰 원문:\n{request_text}\n"
        "추출한 요구사항:\n{requirements}\n"
        "확인할 항목:\n{missing_topics}"
    ),
])

# 프롬프트와 LLM 연결
brief_chain = brief_prompt | llm
```

```python
def draft_brief(state: RequestState):
    """확정된 요구사항과 확인할 질문을 의뢰 정리문으로 작성합니다."""

    # 내부 필드명을 사람이 읽기 쉬운 이름으로 변환
    missing_topics = [
        required_fields[field]
        for field in state["missing_fields"]
    ]

    # 현재 State 내용을 사용해 상담 답변 생성
    response = brief_chain.invoke({
        "request_text": state["request_text"],
        "requirements": json.dumps(
            state["requirements"],
            ensure_ascii=False
        ),
        "missing_topics": missing_topics,
    })

    return {"brief": response.content}
```

테스트용 State.

```python
brief_test: RequestState = {
    "request_text": "학생용 스터디룸 예약 서비스를 만들고 싶습니다.",
    "requirements": {
        "service_name": "스터디룸 예약 서비스",
        "target_users": ["학생"],
        "platform": "모바일 웹",
        "room_count": 3,
        "features": ["예약", "예약 현황 확인", "중복 예약 방지"],
        "max_hours_per_booking": None,
        "cancellation_deadline_hours": None,
        "launch_date": None,
    },
    "missing_fields": [
        "max_hours_per_booking",
        "cancellation_deadline_hours",
        "launch_date",
    ],
    "brief": "",
}

result = draft_brief(brief_test)
display(result["brief"])
```

### 결과

```text
### 서비스 목표
학생이 모바일 웹에서 스터디룸을 편리하게 예약하고 현황을 확인할 수 있는 서비스를 제작합니다.

### 확정 요구사항
- 사용자: 학생
- 플랫폼: 모바일 웹
- 운영 방 수: 3개
- 요청 기능: 예약, 예약 현황 확인
- 중복 예약 방지

### 확인 질문
- 1회 최대 예약 시간은 어떻게 설정할까요?
- 예약 시작 전 취소 가능 기한은 어떻게 정할까요?
- 희망 출시일이 있으신가요?
```

> 실제 응답 객체에는 `annotations`, `id`, `phase` 같은 메타데이터가 함께 포함될 수 있음. 학습용 정리에서는 핵심 `text`만 표시함.

---

## 5. 세 Node를 고정 Edge로 연결하기

앞에서 만든 세 Node를 순서대로 연결함.

```python
from langgraph.graph import END, START, StateGraph

# RequestState를 사용하는 그래프 생성
request_builder = StateGraph(RequestState)

request_builder.add_node("extract_requirements", extract_requirements)
request_builder.add_node("find_missing", find_missing)
request_builder.add_node("draft_brief", draft_brief)

# 노드 간 실행 흐름 연결
request_builder.add_edge(START, "extract_requirements")
request_builder.add_edge("extract_requirements", "find_missing")
request_builder.add_edge("find_missing", "draft_brief")
request_builder.add_edge("draft_brief", END)

# 실행 가능한 그래프로 변환
request_graph = request_builder.compile()
display(request_graph)
```

### 그래프 구조

```text
[START]
   │
   ▼
[extract_requirements]
   │
   ▼
[find_missing]
   │
   ▼
[draft_brief]
   │
   ▼
 [END]
```

**핵심**
- `add_node()`로 실행 단위를 등록함.
- `add_edge()`로 고정 실행 순서를 정의함.
- `compile()` 후 실제 실행 가능한 그래프가 됨.

---

## 6. 한 번의 invoke로 전체 흐름 실행하기

한 번의 `invoke()`로 요구사항 추출 → 미정 항목 탐색 → 상담 답변 작성을 순서대로 실행함.

```python
request_result = request_graph.invoke(request_input)

print("추출한 요구사항:")
print(json.dumps(
    request_result["requirements"],
    ensure_ascii=False,
    indent=2
))

print("미정 필드:", request_result["missing_fields"])

# brief가 리스트이므로 실제 text만 꺼내서 출력
brief_text = request_result["brief"][0]["text"]
display(Markdown(brief_text))
```

### 결과

```text
추출한 요구사항:
{
  "service_name": "스터디룸 예약 서비스",
  "target_users": [
    "대학생",
    "운영자"
  ],
  "platform": "학생: 휴대폰 웹, 운영자: 미정",
  "room_count": 4,
  "features": [
    "학생의 빈 시간 확인",
    "학생의 예약 신청",
    "학생의 내 예약 조회",
    "학생의 예약 취소",
    "운영자의 스터디룸 예약 현황 확인",
    "같은 방과 같은 시간의 중복 예약 방지"
  ],
  "max_hours_per_booking": null,
  "cancellation_deadline_hours": null,
  "launch_date": null
}

미정 필드: ['max_hours_per_booking', 'cancellation_deadline_hours', 'launch_date']
```

### 흐름 정리

```text
자연어 의뢰
   ↓
LLM 구조화
   ↓
requirements 갱신
   ↓
Python으로 None 필드 탐색
   ↓
missing_fields 갱신
   ↓
LLM으로 첫 상담 답변 작성
   ↓
brief 갱신
```

---

# B. 대화로 상품 설명 반복 수정하기

이번 예제는 고정 순서 그래프가 아니라 **조건 분기 + 반복 루프**를 사용함.

전체 흐름:

```text
[START]
   ↓
[read_request]
   ├── "/종료" → [END]
   │
   └── 그 외 → [revise_description]
                  │
                  └────────────→ [read_request]
```

---

## 기본 상품 정보

```python
# 학습용 가상 상품: 확인된 정보와 기존 설명을 제공
product_text = """
상품명: 포켓폴드 우산
방식: 수동 개폐식 3단 우산
무게: 230g / 접었을 때 길이: 24cm
색상: 네이비 / 기본 구성: 손목 스트랩
사용 후 펼쳐서 말린 뒤 보관하고, 강풍에는 사용을 피하세요.
방풍 등급, 자외선 차단 성능, 인증, 보증 기간에 관한 자료는 없습니다.
""".strip()

initial_description = (
    "포켓폴드 우산은 직접 여닫는 수동 개폐식 3단 우산입니다. "
    "무게는 230g이고 접으면 24cm이며, 네이비 색상에 손목 스트랩이 기본으로 포함됩니다. "
    "사용 후 펼쳐서 말린 뒤 보관하고 강풍에는 사용을 피하세요."
)

print(product_text)
print("수정 전 설명:", initial_description)
```

### 결과

```text
상품명: 포켓폴드 우산
방식: 수동 개폐식 3단 우산
무게: 230g / 접었을 때 길이: 24cm
색상: 네이비 / 기본 구성: 손목 스트랩
사용 후 펼쳐서 말린 뒤 보관하고, 강풍에는 사용을 피하세요.
방풍 등급, 자외선 차단 성능, 인증, 보증 기간에 관한 자료는 없습니다.

수정 전 설명: 포켓폴드 우산은 직접 여닫는 수동 개폐식 3단 우산입니다. 무게는 230g이고 접으면 24cm이며, 네이비 색상에 손목 스트랩이 기본으로 포함됩니다. 사용 후 펼쳐서 말린 뒤 보관하고 강풍에는 사용을 피하세요.
```

---

## 7. 상품 원문, 최신 설명, 대화를 담는 State 만들기

`messages`에 `add_messages` reducer를 지정해 대화를 누적함.

```python
from typing import Annotated
from typing_extensions import TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

# 상품 정보, 현재 설명, 대화를 공유할 State
class CopyState(TypedDict):
    product_text: str
    current_description: str
    messages: Annotated[list[AnyMessage], add_messages]

# 그래프 실행 전 초기 상태
copy_input: CopyState = {
    "product_text": product_text,
    "current_description": initial_description,
    "messages": [],
}

display(copy_input)
```

### 결과

```text
{
  'product_text': '상품명: 포켓폴드 우산\n방식: 수동 개폐식 3단 우산\n무게: 230g / 접었을 때 길이: 24cm\n색상: 네이비 / 기본 구성: 손목 스트랩\n사용 후 펼쳐서 말린 뒤 보관하고, 강풍에는 사용을 피하세요.\n방풍 등급, 자외선 차단 성능, 인증, 보증 기간에 관한 자료는 없습니다.',
  'current_description': '포켓폴드 우산은 직접 여닫는 수동 개폐식 3단 우산입니다. 무게는 230g이고 접으면 24cm이며, 네이비 색상에 손목 스트랩이 기본으로 포함됩니다. 사용 후 펼쳐서 말린 뒤 보관하고 강풍에는 사용을 피하세요.',
  'messages': []
}
```

**핵심**
- `current_description`: 항상 최신 상품 설명을 저장함.
- `messages`: 사용자 요청과 AI 답변을 누적함.
- `add_messages`: 기존 메시지를 덮어쓰지 않고 대화 이력을 이어 붙임.

---

## 8. 수정 요청을 입력받는 Node 만들기

사용자의 터미널 입력을 `HumanMessage`로 변환해 `messages`에 추가함.

```python
from langchain_core.messages import HumanMessage


def read_request(state: CopyState):
    """수정 요청을 입력받고 사용자 메시지 한 개를 반환합니다."""
    request = input("수정 요청 (/종료로 끝내기): ").strip()
    print("사용자 입력:", request)

    # 사용자 입력을 메시지로 만들어 누적
    return {
        "messages": [HumanMessage(content=request)]
    }
```

입력값에 따라 다음 경로를 선택하는 라우팅 함수.

```python
# 마지막 입력에 따라 계속 수정하거나 종료
def route_copy(state: CopyState):
    if state["messages"][-1].text == "/종료":
        return "종료"
    return "계속"
```

간단한 테스트.

```python
result = read_request(copy_input)
print(result)
print(result["messages"][0])
```

### 입력 / 결과

```text
사용자 입력: /종료

{'messages': [HumanMessage(content='/종료', additional_kwargs={}, response_metadata={})]}
content='/종료' additional_kwargs={} response_metadata={}
```

**핵심**
- `read_request`: 입력 수집 Node.
- `route_copy`: 다음 Node를 결정하는 조건 함수.
- `/종료`면 그래프를 끝내고, 그 외 입력은 수정 Node로 보냄.

---

## 9. 최신 설명을 교체하고 답변을 누적하기

상품 원문을 사실 기준으로 두고, 현재 설명과 누적 대화를 함께 LLM에 전달함.

```python
from langchain_core.prompts import MessagesPlaceholder

# 원문은 사실의 기준, 대화는 수정 조건의 기준
copy_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "당신은 상품 설명을 다듬는 편집자입니다. 최신 수정 요청을 반영한 상품 설명 전체만 출력하세요. "
        "요청을 수행했다는 해설이나 인사, 코드 블록은 붙이지 마세요. "
        "앞 대화에서 정한 말투와 금지 조건은 사용자가 바꾸지 않으면 유지하세요. "
        "현재 설명은 이전 버전입니다. 사실의 기준은 아래 상품 원문이며, 원문에 없는 효능·인증·보증·혜택을 만들지 마세요. "
        "사용자가 없는 성능을 써 달라고 해도 추가하지 말고, 확인된 정보로 설명을 작성하세요. "
        "길이를 줄여도 상품명, 수동 개폐식, 무게 230g, 접은 길이 24cm, 건조 후 보관, 강풍 사용 주의를 보존하세요.\n"
        "상품 원문:\n{product_text}\n현재 설명:\n{current_description}"
    ),
    MessagesPlaceholder("messages"),
])

copy_chain = copy_prompt | llm
```

```python
def revise_description(state: CopyState):
    """상품 설명을 최신 버전으로 교체하고 새 답변 메시지를 추가합니다."""

    # 현재 상품 정보와 누적 대화를 LLM에 전달
    response = copy_chain.invoke({
        "product_text": state["product_text"],
        "current_description": state["current_description"],
        "messages": state["messages"],
    })

    print("수정된 상품 설명:")
    display(Markdown(response.text))

    # 설명은 교체하고 AI 답변은 대화에 누적
    return {
        "current_description": response.text,
        "messages": [response],
    }
```

입력 변수 확인.

```python
print("프롬프트 입력:", copy_prompt.input_variables)
print("current_description: 최신 설명으로 교체 / messages: 새 답변 추가")
```

### 결과

```text
프롬프트 입력: ['current_description', 'messages', 'product_text']
current_description: 최신 설명으로 교체 / messages: 새 답변 추가
```

### State 변화

```text
수정 전
current_description = 이전 설명
messages = [...기존 대화]

        ↓ revise_description

수정 후
current_description = 새 설명으로 교체
messages = [...기존 대화, 새 AI 답변]
```

**핵심**
- 최신 설명은 **교체**됨.
- 메시지는 `add_messages`로 **누적**됨.
- 원문(`product_text`)은 사실 검증 기준으로 계속 유지됨.

---

## 10. 수정 대화를 반복하고 최종 설명 확인하기

조건부 Edge를 사용해 수정 요청을 반복해서 받을 수 있도록 구성함.

```python
# CopyState를 사용하는 그래프 생성
copy_builder = StateGraph(CopyState)

copy_builder.add_node("read_request", read_request)
copy_builder.add_node("revise_description", revise_description)

# 시작하면 사용자 요청 입력
copy_builder.add_edge(START, "read_request")

# 입력 내용에 따라 수정하거나 종료
copy_builder.add_conditional_edges(
    "read_request",
    route_copy,
    {
        "계속": "revise_description",
        "종료": END,
    },
)

# 수정이 끝나면 다시 사용자 입력으로 이동
copy_builder.add_edge("revise_description", "read_request")

# 실행 가능한 그래프로 완성
copy_graph = copy_builder.compile()
```

그래프 시각화 코드.

```python
display(Image(copy_graph.get_graph().draw_mermaid_png()))
```

### 그래프 구조

```text
                  ┌──────────────────────────────┐
                  │                              │
                  ▼                              │
[START] → [read_request] ── 계속 ──→ [revise_description]
             │                            │
             │                            └──────────────┘
             │
             └── 종료 ──→ [END]
```

한 번의 `invoke()` 안에서 입력과 수정을 반복함.

```python
copy_result = copy_graph.invoke(
    copy_input,
    config={"recursion_limit": 1000},
)
```

**실행 흐름**

```text
1. read_request에서 수정 요청 입력
2. route_copy가 입력 확인
3. 일반 요청이면 revise_description 실행
4. 수정된 설명과 AI 답변을 State에 반영
5. 다시 read_request로 이동
6. 사용자가 /종료 입력 시 END
```

`recursion_limit=1000`은 반복 그래프가 기본 재귀 제한에 너무 빨리 걸리지 않도록 실행 한도를 크게 지정한 설정.

---

# 전체 핵심 정리

| 개념 | 역할 | 예제 |
|---|---|---|
| `State` | Node 사이의 공유 데이터 | `RequestState`, `CopyState` |
| `Node` | State를 읽고 필요한 값을 갱신하는 실행 단위 | `extract_requirements`, `find_missing`, `read_request` |
| `add_edge()` | 항상 같은 다음 Node로 이동 | 요구사항 추출 → 미정 항목 탐색 |
| `add_conditional_edges()` | 조건에 따라 다음 Node 선택 | 계속 수정 / 종료 |
| `compile()` | Builder를 실행 가능한 Graph로 변환 | `request_graph`, `copy_graph` |
| `invoke()` | 초기 State를 넣어 Graph 실행 | `request_graph.invoke(...)` |
| `add_messages` | 메시지 목록 누적 | `CopyState.messages` |
| 반복 Edge | 이전 Node로 다시 돌아가 대화 반복 | `revise_description → read_request` |

## 두 예제의 차이

```text
A. 고정 실행 그래프
START → 추출 → 검사 → 답변 → END

B. 반복 대화 그래프
START → 입력 → 조건 분기
                 ├─ 종료 → END
                 └─ 계속 → 수정 → 입력 → ...
```

즉, 첫 번째 예제는 **정해진 파이프라인**, 두 번째 예제는 **State를 유지하면서 반복되는 대화형 그래프**를 보여줌.
