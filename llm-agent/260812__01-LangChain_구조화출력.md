# LangChain 구조화 출력 · 도구 · 에이전트

> 핵심 흐름: **자연어 입력을 스키마로 정형화 → 필요한 기능을 도구로 정의 → 에이전트가 도구를 선택·실행 → 최종 결과도 다시 구조화**

## 0. 전체 제작 흐름

```text
사용자 입력
   ↓
[1] 스키마 설계
    - Literal: 허용 값 제한
    - Optional: 없을 수 있는 값
    - Field(description=...): 필드 의미/규칙 설명
   ↓
[2] 구조화 모델 생성
    model.with_structured_output(Schema)
   ↓
[3] invoke / batch로 구조화 결과 생성
    - 단건: invoke
    - 여러 건: batch
   ↓
[4] 필요한 기능을 @tool로 도구화
    - 함수 이름 → tool.name
    - docstring → tool.description
    - 타입 힌트 → 입력 스키마
   ↓
[5] create_agent에 도구 연결
    - 모델이 필요한 도구와 호출 순서를 판단
   ↓
[6] 메시지 궤적 확인
    HumanMessage → AIMessage(tool_calls) → ToolMessage → AIMessage
   ↓
[7] 필요하면 에이전트 최종 응답까지 구조화
    response_format=ProviderStrategy(Schema, strict=True)
   ↓
[8] 후처리
    객체 → model_dump() → DataFrame / 집계 / 저장
```

---

# 1. 기본 환경 준비

```python
import os
from dotenv import load_dotenv

# 현재 폴더 또는 상위 폴더의 .env 로드
load_dotenv(".env")
load_dotenv("../.env")

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError(
        "OPENAI_API_KEY를 찾지 못했습니다.\n"
        "1) .env.example을 복사해 .env 생성\n"
        "2) .env에 본인 키 입력\n"
        "3) 커널 재시작 후 다시 실행"
    )

print("OpenAI 키 확인 완료")

from langchain_openai import ChatOpenAI

# 수업 예시 모델
model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
```

- `temperature=0`: 같은 입력에 비교적 일정한 결과를 얻기 위한 설정.
- 모델명은 수업 예시 기준. 사용 시점의 지원 모델은 별도 확인 필요.

---

# 2. 구조화된 출력

## 2.1 구조화 출력이 필요한 이유

일반 LLM 응답은 자유로운 문자열.

구조화 출력은 응답을 **정해진 필드와 타입을 가진 객체**로 받는 방식.

```text
일반 출력
"이 문의는 네트워크 문제이고 긴급합니다."

구조화 출력
Ticket(
    category="네트워크",
    urgency="긴급",
    asset_tag=None,
    summary="VPN 연결 불안정으로 업무 중단"
)
```

정형화되면 바로 다음 작업으로 연결 가능.

- 특정 필드만 꺼내기
- 조건 분기
- 개수 세기
- 그룹화
- DataFrame 변환
- DB 저장

---

## 2.2 스키마 설계 규칙

| 원칙 | 작성 방식 | 의미 |
|---|---|---|
| 값의 후보를 제한 | `Literal[...]` | 목록 밖의 값을 막음 |
| 값이 없을 수 있음 | `Optional[T]` + `default=None` | 없는 정보를 억지로 생성하지 않음 |
| 필드 의미 설명 | `Field(description="...")` | 모델에게 필드의 의미·판단 규칙 전달 |
| 일반 값 | `str`, `int`, `bool` 등 | 필드의 자료형 지정 |

### `Literal`

```python
category: Literal["하드웨어", "소프트웨어", "계정", "네트워크", "기타"]
```

정해진 값 중 하나만 허용.

분류·집계처럼 값의 종류를 고정해야 할 때 사용.

### `Optional`

```python
asset_tag: Optional[str] = Field(default=None)
```

정보가 없으면 `None`.

없는 정보를 모델이 임의로 채우게 하지 않을 때 중요.

### `Field(description=...)`

```python
asset_tag: Optional[str] = Field(
    default=None,
    description="IT-#### 형태의 자산 관리번호. 문의에 없으면 null"
)
```

`description`은 단순 주석이 아님.

모델이 해당 필드를 어떻게 채워야 하는지 이해하는 지침으로 사용됨.

---

## 2.3 Pydantic 스키마 만들기

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Ticket(BaseModel):
    """헬프데스크 문의 한 건을 분류한 결과."""

    category: Literal[
        "하드웨어",
        "소프트웨어",
        "계정",
        "네트워크",
        "기타",
    ] = Field(description="문의가 어떤 갈래인지")

    urgency: Literal["긴급", "보통", "낮음"] = Field(
        description=(
            "긴급: 업무가 지금 멈춤 / "
            "보통: 불편하지만 진행 가능 / "
            "낮음: 단순 질문"
        )
    )

    asset_tag: Optional[str] = Field(
        default=None,
        description="IT-#### 형태의 자산 관리번호. 문의에 없으면 반드시 null",
    )

    summary: str = Field(description="문의 내용을 한 문장으로 요약")


print("스키마 필드:", list(Ticket.model_fields))
```

**결과**

```text
스키마 필드: ['category', 'urgency', 'asset_tag', 'summary']
```

여기까지는 LangChain이 아니라 **Pydantic 스키마 정의**.

---

## 2.4 모델에 스키마 씌우기

```python
INQ_URGENT = (
    "사무실 노트북(IT-2043)이 어제부터 전원이 안 들어옵니다. "
    "오늘 오후에 발표가 있어서 급합니다."
)

# 스키마가 적용된 새 Runnable 생성
classifier = model.with_structured_output(Ticket)

# 단건 처리
result = classifier.invoke(INQ_URGENT)

print("결과 종류:", type(result).__name__)
print(result)
print("갈래:", result.category)
```

핵심:

```python
classifier = model.with_structured_output(Ticket)
```

스키마를 매번 다시 만들 필요 없음.

한 번 만든 `classifier`를 계속 재사용.

---

## 2.5 여러 입력은 `batch()`

```python
inquiries = [
    "사내 메신저 알림이 안 오는데 어디서 켜나요?",
    "사내 포털 비밀번호를 세 번 틀려서 계정이 잠겼습니다. 풀어 주세요.",
    "재택인데 VPN이 연결됐다 끊겼다 합니다. 지금 업무가 멈춰 있습니다.",
]

results = classifier.batch(inquiries)

for ticket in results:
    print(f"{ticket.category} / {ticket.urgency} / {ticket.summary}")
```

**결과 예시**

```text
소프트웨어 / 보통 / 사내 메신저 알림 설정 방법 문의
계정 / 긴급 / 사내 포털 비밀번호 잠금 해제 요청
네트워크 / 긴급 / VPN 연결 불안정으로 업무 중단
```

- `invoke()`: 입력 1개.
- `batch()`: 여러 입력을 한 번에 처리.
- 결과는 입력 순서에 맞춰 받음.

---

## 2.6 구조화 객체 → DataFrame

구조화의 최종 목적은 이후 코드가 데이터를 안정적으로 사용하게 만드는 것.

```python
import pandas as pd

rows = [ticket.model_dump() for ticket in results]
df = pd.DataFrame(rows)

print(df)
print(df["urgency"].value_counts())
```

흐름:

```text
Pydantic 객체
   ↓ model_dump()
딕셔너리
   ↓ 여러 개를 리스트로 묶기
list[dict]
   ↓ pd.DataFrame(...)
DataFrame
   ↓
집계 / 분석 / 저장
```

---

## 2.7 연습: 회의실 요청 구조화

원문 예시에서는 `room_type`이 필수였지만, 문의에 회의실 종류가 없는 경우 모델이 임의 추론할 수 있음.

**없는 정보를 만들지 않는 목적이면 `Optional`이 더 안전함.**

```python
class RoomRequest(BaseModel):
    room_type: Optional[
        Literal["소회의실", "대회의실", "세미나실"]
    ] = Field(
        default=None,
        description="사용자가 직접 요청한 회의실 종류. 언급이 없으면 null",
    )

    head_count: int = Field(description="참석 인원 수")

    preferred_date: Optional[str] = Field(
        default=None,
        description="YYYY-MM-DD 형태의 희망 날짜. 문의에 없으면 null",
    )


room_parser = model.with_structured_output(RoomRequest)

room_texts = [
    "다음 주 화요일(2026-08-18)에 12명이 들어갈 회의실이 필요합니다.",
    "세미나실 하루 빌리려면 어떻게 신청하나요? 인원은 40명입니다.",
]

results = room_parser.batch(room_texts)

for result in results:
    print(result.room_type, result.head_count, result.preferred_date)
```

핵심 설계 기준:

> **입력에 없는 값을 추론해서 채워도 되는가?**
>
> 안 된다면 해당 필드를 `Optional`로 설계.

---

# 3. 도구 만들기

## 3.1 `@tool`의 역할

일반 Python 함수 위에 `@tool`을 붙이면 모델이 호출할 수 있는 LangChain 도구가 됨.

```python
from langchain.tools import tool
```

| Python 함수의 요소 | 도구에서 | 모델에게 주는 정보 |
|---|---|---|
| 함수 이름 | `.name` | 어떤 이름으로 도구를 호출할지 |
| docstring | `.description` | 언제·왜 이 도구를 사용할지 |
| 타입 힌트 | `.args` / 입력 스키마 | 어떤 인자를 어떤 타입으로 전달할지 |
| 반환값 | ToolMessage의 내용 | 도구 실행 결과 |

### 좋은 도구 함수의 기본 형태

```python
@tool
def tool_name(arg1: str, arg2: int) -> str:
    """이 도구가 언제 필요하며 무엇을 반환하는지 설명."""
    ...
```

---

## 3.2 재고 조회·재입고 비용 도구

```python
from langchain.tools import tool

_STOCK = {
    "무선 마우스": 40,
    "기계식 키보드": 15,
    "복사용지": 200,
    "보안 USB": 10,
}

_PRICE = {
    "무선 마우스": 18000,
    "기계식 키보드": 65000,
    "복사용지": 4500,
    "보안 USB": 32000,
}


@tool
def supply_stock(item_name: str) -> int:
    """비품 이름을 받아 현재 창고 재고 수량을 반환한다."""
    return _STOCK.get(item_name.strip(), 0)


@tool
def restock_cost(item_name: str, count: int) -> int:
    """비품 이름과 재입고 수량을 받아 총 재입고 비용을 반환한다."""
    return _PRICE.get(item_name.strip(), 0) * count
```

---

## 3.3 도구 메타데이터 확인

```python
print("name       :", supply_stock.name)
print("description:", supply_stock.description)
print("args       :", supply_stock.args)
```

**결과**

```text
name       : supply_stock
description: 비품 이름을 받아 현재 창고 재고 수량을 반환한다.
args       : {'item_name': {'title': 'Item Name', 'type': 'string'}}
```

즉 모델은 함수 코드를 직접 읽는 것이 아니라 **도구 이름·설명·입력 스키마**를 이용해 호출을 판단.

---

## 3.4 모델에게 전달되는 JSON 스키마 확인

```python
import json

spec = supply_stock.tool_call_schema.model_json_schema()
print(json.dumps(spec, ensure_ascii=False, indent=2))
```

**결과 형태**

```json
{
  "description": "비품 이름을 받아 현재 창고 재고 수량을 반환한다.",
  "properties": {
    "item_name": {
      "title": "Item Name",
      "type": "string"
    }
  },
  "required": ["item_name"],
  "title": "supply_stock",
  "type": "object"
}
```

핵심:

```text
Python 함수
   ↓ @tool
도구 메타데이터 + JSON 입력 스키마
   ↓
모델이 도구 이름과 인자를 결정
```

---

## 3.5 도구 직접 실행

도구는 에이전트 없이도 직접 실행 가능.

```python
print(supply_stock.invoke({"item_name": "무선 마우스"}))
print(restock_cost.invoke({"item_name": "보안 USB", "count": 3}))
print("없는 비품:", supply_stock.invoke({"item_name": "3D 프린터"}))
```

**결과**

```text
40
96000
없는 비품: 0
```

도구를 에이전트에 연결하기 전에 직접 실행해 정상 동작을 확인하는 습관이 중요.

---

## 3.6 연습: 구내식당 메뉴 도구

```python
_MENU = {
    "월": "제육볶음",
    "화": "김치찌개",
    "수": "돈가스",
    "목": "비빔밥",
    "금": "해물순두부",
}


@tool
def cafeteria_menu(day_name: str) -> str:
    """요일을 입력받아 그날의 구내식당 점심 메뉴를 반환한다."""
    return _MENU.get(day_name.strip(), "그날은 메뉴가 없습니다.")


print(cafeteria_menu.name)
print(cafeteria_menu.description)
print(cafeteria_menu.args)
print(cafeteria_menu.invoke({"day_name": "수"}))
```

**결과**

```text
cafeteria_menu
요일을 입력받아 그날의 구내식당 점심 메뉴를 반환한다.
{'day_name': {'title': 'Day Name', 'type': 'string'}}
돈가스
```

---

# 4. 에이전트에 도구 연결

## 4.1 체인과 에이전트 차이

```text
체인
정해진 실행 순서대로 진행
A → B → C

에이전트
상황을 보고 필요한 도구와 실행 순서를 모델이 판단
질문 → 판단 → 도구 선택 → 결과 확인 → 다음 행동 판단
```

비유:

- 체인 = 정해진 레시피.
- 에이전트 = 상황을 보고 도구를 선택하는 요리사.

---

## 4.2 기본 에이전트 만들기

```python
from langchain.agents import create_agent
from langchain.messages import ToolMessage

agent = create_agent(
    model,
    tools=[supply_stock, restock_cost],
)
```

현재 공식 문서형 입력 형태:

```python
result = agent.invoke(
    {
        "messages": [
            {"role": "user", "content": "무선 마우스 창고에 몇 개 남았어?"}
        ]
    }
)
```

---

## 4.3 메시지 궤적

도구 호출이 발생하면 메시지가 다음 흐름으로 쌓임.

| 순서 | 메시지 | 의미 |
|---|---|---|
| 1 | `HumanMessage` | 사용자 질문 |
| 2 | `AIMessage` + `.tool_calls` | 모델이 도구와 인자를 결정 |
| 3 | `ToolMessage` | 도구 실행 결과 |
| 4 | `AIMessage` | 도구 결과를 반영한 최종 답 |

```text
사용자 질문
   ↓
HumanMessage
   ↓
AIMessage
  └─ tool_calls = [{name, args}]
   ↓
ToolMessage
  └─ 실제 도구 실행 결과
   ↓
AIMessage
  └─ 최종 자연어 답변
```

---

## 4.4 궤적 직접 확인

```python
result = agent.invoke(
    {
        "messages": [
            {"role": "user", "content": "무선 마우스 창고에 몇 개 남았어?"}
        ]
    }
)

for message in result["messages"]:
    kind = type(message).__name__

    if getattr(message, "tool_calls", None):
        calls = [
            (call["name"], call["args"])
            for call in message.tool_calls
        ]
        print(kind, "-> 도구 호출:", calls)
    else:
        print(kind, "->", message.content or "(내용 없음)")
```

**결과 예시**

```text
HumanMessage -> 무선 마우스 창고에 몇 개 남았어?
AIMessage -> 도구 호출: [('supply_stock', {'item_name': '무선 마우스'})]
ToolMessage -> 40
AIMessage -> 무선 마우스가 현재 40개 남아 있습니다.
```

---

## 4.5 필요한 정보만 추출

### 호출된 도구

```python
tool_messages = [
    message
    for message in result["messages"]
    if isinstance(message, ToolMessage)
]

print("불린 도구:", [(m.name, m.content) for m in tool_messages])
```

### 최종 답

```python
final_answer = result["messages"][-1].content
print("최종 답:", final_answer)
```

---

## 4.6 `system_prompt`로 역할 지정

도구는 그대로 두고 에이전트의 역할·말투·행동 기준만 변경 가능.

```python
polite_agent = create_agent(
    model,
    tools=[supply_stock, restock_cost],
    system_prompt=(
        "너는 친절한 사내 헬프데스크 상담원이다. "
        "항상 정중한 존댓말로 답한다."
    ),
)

result = polite_agent.invoke(
    {
        "messages": [
            {"role": "user", "content": "무선 마우스 창고에 몇 개 남았어?"}
        ]
    }
)
```

핵심:

```text
도구 = 할 수 있는 행동
system_prompt = 행동 방식과 역할
```

---

## 4.7 에이전트는 도구가 필요할 때만 호출

```python
result = agent.invoke(
    {
        "messages": [
            {
                "role": "user",
                "content": "헬프데스크가 하는 일이 뭐야? 한 문장으로 알려줘.",
            }
        ]
    }
)

used_tools = [
    m.name
    for m in result["messages"]
    if isinstance(m, ToolMessage)
]

print("도구 호출 수:", len(used_tools))
print("최종 답:", result["messages"][-1].content)
```

**결과 예시**

```text
도구 호출 수: 0
최종 답: 헬프데스크는 고객이나 직원의 기술적 문제를 해결하고 지원하는 서비스입니다.
```

`create_agent`에 도구를 붙였다고 매번 호출하는 것은 아님.

모델이 질문을 보고 도구가 필요한지 먼저 판단.

---

# 5. 도구 사용 + 최종 응답 구조화

## 5.1 모델 구조화 출력과 에이전트 구조화 출력 비교

| 구분 | `model.with_structured_output(S)` | `create_agent(..., response_format=...)` |
|---|---|---|
| 스키마 적용 대상 | 모델 호출 결과 | 에이전트 최종 결과 |
| 도구 사용 | 기본적으로 모델 단독 호출 | 도구를 사용한 뒤 응답 가능 |
| 결과 위치 | `invoke()` 반환값 | `res["structured_response"]` |
| 메시지 궤적 | 별도 에이전트 궤적 없음 | `res["messages"]`에 유지 |
| 용도 | 추출·분류·정형화 | 도구 기반 업무 처리 + 정형 결과 |

---

## 5.2 `ProviderStrategy`

```python
from langchain.agents.structured_output import ProviderStrategy
```

```python
response_format=ProviderStrategy(Schema, strict=True)
```

- Provider가 지원하는 네이티브 구조화 출력을 사용.
- `strict=True`: 스키마 준수를 더 엄격하게 요구.
- `strict` 인자는 **LangChain 1.2 이상**에서 사용 가능.

---

## 5.3 재고 보고서 스키마

```python
class StockReport(BaseModel):
    """재고 문의 한 건을 처리한 결과."""

    item_name: str = Field(description="문의한 비품 이름")

    stock: int = Field(
        description="도구가 알려 준 현재 재고 수량"
    )

    status: Literal["충분", "부족", "없음"] = Field(
        description="재고 20개 이상이면 충분, 1~19개면 부족, 0개면 없음"
    )

    note: str = Field(description="담당자에게 남길 한 문장")
```

> 학습 예시에서는 `status` 판단 규칙을 `description`에 둠.
>
> 실제 업무에서 반드시 정확해야 하는 규칙이면 모델 판단보다 **Python 코드로 계산**하는 편이 안전.

---

## 5.4 구조화 응답 에이전트

```python
report_agent = create_agent(
    model,
    tools=[supply_stock, restock_cost],
    response_format=ProviderStrategy(StockReport, strict=True),
)

res_report = report_agent.invoke(
    {
        "messages": [
            {"role": "user", "content": "보안 USB 재고 상태를 정리해줘."}
        ]
    }
)

print("결과 키:", list(res_report))

print(
    "불린 도구:",
    [
        m.name
        for m in res_report["messages"]
        if isinstance(m, ToolMessage)
    ],
)

report = res_report["structured_response"]

print("결과 종류:", type(report).__name__)
print(report)
print("상태:", report.status)
```

**결과 예시**

```text
결과 키: ['messages', 'structured_response']
불린 도구: ['supply_stock']
결과 종류: StockReport
item_name='보안 USB' stock=10 status='부족' note='재고가 부족합니다. 추가 재고가 필요합니다.'
상태: 부족
```

핵심:

```text
도구 실행 과정 확인 → res["messages"]
최종 정형 결과 확인 → res["structured_response"]
```

---

# 6. 간단한 에이전트 전체 예시

```python
_SEATS = {
    "소회의실": 6,
    "대회의실": 20,
    "세미나실": 50,
}


@tool
def room_seats(room_name: str) -> int:
    """회의실 이름을 받아 최대 수용 인원을 반환한다."""
    return _SEATS.get(room_name.strip(), -1)


room_agent = create_agent(
    model,
    tools=[room_seats],
    system_prompt="너는 사내 헬프데스크 안내원이다. 제공된 정보를 활용해 답한다.",
)

result = room_agent.invoke(
    {
        "messages": [
            {"role": "user", "content": "세미나실에 몇 명까지 들어갈 수 있어?"}
        ]
    }
)

used_tools = [
    m.name
    for m in result["messages"]
    if isinstance(m, ToolMessage)
]

print("불린 도구:", used_tools)
print("최종 답:", result["messages"][-1].content)
```

**결과**

```text
불린 도구: ['room_seats']
최종 답: 세미나실에는 최대 50명까지 들어갈 수 있습니다.
```

---

# 7. 도구 실패 처리

## 7.1 핵심 원칙

예상 가능한 실패는 에이전트가 이해할 수 있는 결과로 돌려주는 것이 좋음.

```text
잘못된 입력
없는 데이터
외부 API 일시 실패
```

이런 경우 무조건 예외로 종료시키기보다, 상황을 설명하는 값을 반환하면 모델이 다음 답변을 만들 수 있음.

단, **모든 예외를 무조건 문자열로 숨기면 디버깅이 어려워짐.**

업무적으로 예상되는 실패와 실제 시스템 오류를 구분하는 것이 좋음.

---

## 7.2 자산 담당자 조회

원문에서는 `IT-9999`를 "형식 오류"처럼 설명했지만 실제 형식 `IT-####`에는 맞음.

따라서 **형식 오류**와 **등록되지 않은 번호**를 분리.

```python
_OWNER = {
    "IT-2043": "김서연 / 개발팀",
    "IT-1188": "박도윤 / 총무팀",
}


@tool
def asset_owner(asset_tag: str) -> str:
    """자산 관리번호(IT-####)로 장비 담당자와 부서를 찾는다."""
    tag = asset_tag.strip().upper()

    # 형식 검사
    valid_format = (
        tag.startswith("IT-")
        and len(tag) == 7
        and tag[3:].isdigit()
    )

    if not valid_format:
        return (
            f"형식 오류: {tag}. "
            "관리번호는 'IT-' 뒤에 숫자 네 자리입니다. 예: IT-2043"
        )

    # 형식은 맞지만 데이터에 없음
    if tag not in _OWNER:
        return f"등록된 자산을 찾을 수 없음: {tag}"

    return _OWNER[tag]
```

```python
print(asset_owner.invoke({"asset_tag": "IT-2043"}))
print(asset_owner.invoke({"asset_tag": "sddsdssdds"}))
print(asset_owner.invoke({"asset_tag": "IT-9999"}))
```

**결과**

```text
김서연 / 개발팀
형식 오류: SDDSDSSDDS. 관리번호는 'IT-' 뒤에 숫자 네 자리입니다. 예: IT-2043
등록된 자산을 찾을 수 없음: IT-9999
```

---

# 8. 실무형 도구 설계

## 8.1 대표적인 도구 종류

| 종류 | 역할 | 도구로 만드는 이유 |
|---|---|---|
| 사내 데이터 조회 | CSV·DB·내부 시스템 검색 | 모델 자체가 사내 최신 데이터를 알 수 없음 |
| 규칙 계산 | 회사 규정·요금·점수 계산 | 결과가 결정적이고 정확해야 함 |
| 외부 REST API | 최신 외부 데이터 조회 | 모델 학습 이후 값은 실시간 조회 필요 |

핵심 분리:

```text
모델
→ 무엇을 해야 하는지 판단

도구
→ 실제 데이터 조회·계산·외부 요청 수행
```

---

# 9. 실무형 도구 1: 사내 데이터 조회

```python
import pandas as pd

faq_df = pd.read_csv("data/helpdesk_faq.csv")


@tool
def faq_answer(keyword: str) -> str:
    """사내 헬프데스크 FAQ에서 키워드와 관련된 안내문을 찾는다."""
    word = keyword.strip().split()[0]

    # 제목 우선 검색
    hit = faq_df[
        faq_df["title"].str.contains(word, na=False, regex=False)
    ]

    # 제목에 없으면 본문 검색
    if hit.empty:
        hit = faq_df[
            faq_df["text"].str.contains(word, na=False, regex=False)
        ]

    if hit.empty:
        return (
            f"'{word}' 안내문이 없습니다. "
            "'VPN', '비밀번호', '프린터' 같은 낱말로 다시 찾아보세요."
        )

    row = hit.iloc[0]
    return f"[{row['title']}] {row['text']}"
```

### 처리 흐름

```text
사용자 문장
"비밀번호 재설정 방법 알려줘"
   ↓
keyword.strip().split()[0]
   ↓
"비밀번호"
   ↓
제목 검색
   ↓ 없으면
본문 검색
   ↓
첫 번째 검색 결과 반환
```

> `split()[0]`은 수업용 단순화 방식.
>
> 실제 검색에서는 키워드 추출·형태소 처리·벡터 검색 등으로 확장 가능.

---

# 10. 실무형 도구 2: 규칙 계산

정확한 업무 규칙은 LLM에게 계산시키기보다 코드로 고정.

```python
@tool
def delivery_fee(total_price: int, is_express: bool) -> str:
    """주문 금액과 빠른배송 여부로 배송비를 계산한다."""
    base = 0 if total_price >= 50000 else 3000
    express = 3000 if is_express else 0

    total = base + express
    return f"기본 {base}원 + 빠른배송 {express}원 = 총 {total}원"
```

```python
print(
    delivery_fee.invoke(
        {"total_price": 40000, "is_express": False}
    )
)

print(
    delivery_fee.invoke(
        {"total_price": 60000, "is_express": True}
    )
)
```

**결과**

```text
기본 3000원 + 빠른배송 0원 = 총 3000원
기본 0원 + 빠른배송 3000원 = 총 3000원
```

핵심:

```text
LLM → 계산 필요 여부와 입력값 판단
Python 도구 → 실제 규칙 계산
```

---

# 11. 실무형 도구 3: 외부 REST API

```python
import requests


@tool
def usd_krw_rate() -> str:
    """최근 원/달러 환율을 외부 환율 API에서 조회한다."""
    try:
        response = requests.get(
            "https://api.frankfurter.dev/v1/latest",
            params={"from": "USD", "to": "KRW"},
            timeout=10,
        )

        # 4xx / 5xx 응답을 예외로 처리
        response.raise_for_status()
        data = response.json()

    except requests.RequestException as error:
        return (
            f"환율을 가져오지 못했습니다: {error}. "
            "잠시 뒤 다시 시도해 주세요."
        )

    return (
        f"{data['date']} 기준 "
        f"1 USD = {data['rates']['KRW']} KRW"
    )
```

원문 실행 당시 예시 결과:

```text
2026-08-11 기준 1 USD = 1412.17 KRW
```

실시간 API 결과이므로 실행 시점마다 값이 달라질 수 있음.

### 외부 API 도구의 기본 흐름

```text
에이전트
   ↓ 도구 호출
requests.get(...)
   ↓
HTTP 응답
   ↓
raise_for_status()
   ↓
JSON 파싱
   ↓
필요한 값만 반환
```

외부 API는 네트워크·서버 오류가 발생할 수 있으므로 실패 처리가 특히 중요.

---

# 12. 서로 다른 도구를 한 에이전트에 연결

```python
office_agent = create_agent(
    model,
    tools=[
        faq_answer,
        delivery_fee,
        usd_krw_rate,
    ],
)

result = office_agent.invoke(
    {
        "messages": [
            {
                "role": "user",
                "content": "오늘 1달러는 몇 원이야? 그리고 프린터 관련 FAQ도 찾아줘.",
            }
        ]
    }
)

used_tools = [
    m.name
    for m in result["messages"]
    if isinstance(m, ToolMessage)
]

print("불린 도구:", used_tools)
print("최종 답:", result["messages"][-1].content)
```

**결과 예시**

```text
불린 도구: ['usd_krw_rate', 'faq_answer']
```

질문에 배송비 요청이 없으므로 `delivery_fee`는 호출하지 않음.

즉 도구가 여러 개 있어도 모델이 질문에 필요한 도구만 선택.

---

# 13. 전체 프로세스를 기능별로 보기

## 13.1 구조화 출력 프로세스

```text
자연어
   ↓
Pydantic Schema
   ↓
with_structured_output()
   ↓
Pydantic 객체
   ↓
model_dump()
   ↓
DataFrame / DB / 분석
```

## 13.2 도구 호출 프로세스

```text
Python 함수
   ↓
@tool
   ↓
name + description + args schema
   ↓
에이전트에 등록
   ↓
모델이 필요 여부 판단
   ↓
ToolMessage 반환
```

## 13.3 에이전트 프로세스

```text
사용자 질문
   ↓
AIMessage
   ↓
도구가 필요한가?
   ├─ 아니오 → 최종 답
   └─ 예
       ↓
     tool_calls
       ↓
     ToolMessage
       ↓
     모델이 결과 해석
       ↓
     최종 AIMessage
```

## 13.4 구조화 에이전트 프로세스

```text
사용자 질문
   ↓
에이전트 판단
   ↓
필요한 도구 실행
   ↓
도구 결과 반영
   ↓
ProviderStrategy(Schema)
   ↓
res["structured_response"]
```

---

# 14. 도구 설계 체크리스트

1. **한 도구는 한 역할에 집중**
   - 조회 도구와 수정 도구를 불필요하게 섞지 않기.

2. **함수 이름을 명확하게 작성**
   - `do_it()`보다 `supply_stock()`처럼 목적이 보이게.

3. **docstring을 구체적으로 작성**
   - 모델이 "언제 이 도구를 써야 하는가" 판단할 수 있게.

4. **타입 힌트를 정확히 작성**
   - `str`, `int`, `bool` 등 입력 스키마의 기반.

5. **입력값을 정리**
   - `strip()`, 대소문자 통일 등.

6. **예상 가능한 실패를 처리**
   - 없는 데이터·잘못된 입력·외부 API 실패 등.

7. **정확한 업무 규칙은 코드로 계산**
   - 모델 설명문에만 의존하지 않기.

8. **도구 단독 테스트 후 에이전트에 연결**

```text
함수 작성
→ @tool
→ tool.invoke() 직접 테스트
→ create_agent에 연결
→ 메시지 궤적 확인
```

9. **도구의 권한을 필요한 범위로 제한**
   - 읽기만 필요한 작업에 불필요한 수정 권한을 주지 않기.

---

# 15. 핵심 코드 패턴

## 구조화 출력

```python
structured_model = model.with_structured_output(MySchema)
result = structured_model.invoke(text)
```

## 여러 건 구조화

```python
results = structured_model.batch(texts)
```

## 객체 → 딕셔너리

```python
row = result.model_dump()
```

## 객체 여러 개 → DataFrame

```python
df = pd.DataFrame([item.model_dump() for item in results])
```

## 도구 정의

```python
@tool
def my_tool(value: str) -> str:
    """도구 설명."""
    return ...
```

## 도구 직접 실행

```python
my_tool.invoke({"value": "입력"})
```

## 에이전트 생성

```python
agent = create_agent(
    model,
    tools=[tool1, tool2],
)
```

## 에이전트 실행

```python
result = agent.invoke(
    {
        "messages": [
            {"role": "user", "content": "질문"}
        ]
    }
)
```

## 호출된 도구 확인

```python
used_tools = [
    m.name
    for m in result["messages"]
    if isinstance(m, ToolMessage)
]
```

## 최종 답

```python
final_answer = result["messages"][-1].content
```

## 에이전트 최종 결과까지 구조화

```python
agent = create_agent(
    model,
    tools=[tool1, tool2],
    response_format=ProviderStrategy(MySchema, strict=True),
)

result = agent.invoke(
    {
        "messages": [
            {"role": "user", "content": "질문"}
        ]
    }
)

structured_result = result["structured_response"]
```

---

# 16. 총정리

| 개념 | 핵심 | 대표 코드 |
|---|---|---|
| 구조화 출력 | 자유 문장을 정해진 필드로 받음 | `model.with_structured_output(Schema)` |
| 스키마 | 출력 구조와 타입 정의 | `BaseModel`, `Field` |
| `Literal` | 허용 값 제한 | `Literal["A", "B"]` |
| `Optional` | 값이 없을 수 있음 | `Optional[str] = None` |
| `description` | 필드 의미·규칙 전달 | `Field(description="...")` |
| 단건 실행 | 입력 1개 처리 | `.invoke(...)` |
| 여러 건 실행 | 입력 여러 개 처리 | `.batch(...)` |
| 객체 변환 | Pydantic → dict | `.model_dump()` |
| 도구 정의 | Python 함수를 모델이 호출 가능하게 만듦 | `@tool` |
| 도구 이름 | 호출 이름 | `.name` |
| 도구 설명 | 사용 시점 판단 근거 | `.description` |
| 도구 입력 스키마 | 인자 타입·필수값 정보 | `.args` |
| 도구 JSON 명세 | 모델에게 전달되는 입력 구조 | `.tool_call_schema.model_json_schema()` |
| 에이전트 | 도구 사용 여부·순서를 판단 | `create_agent(...)` |
| 메시지 궤적 | 질문→도구 호출→결과→최종 답 | `result["messages"]` |
| 호출 도구 확인 | 실제 사용된 도구 확인 | `isinstance(m, ToolMessage)` |
| 최종 자연어 답 | 마지막 AI 메시지 | `result["messages"][-1].content` |
| 역할 설정 | 에이전트 행동 기준 지정 | `system_prompt=...` |
| 구조화 에이전트 | 도구 사용 뒤 최종 응답도 스키마화 | `response_format=ProviderStrategy(...)` |
| 구조화 결과 | 에이전트의 정형 응답 | `result["structured_response"]` |
| 실무형 도구 | 사내 데이터·규칙 계산·외부 API | Python 함수 + `@tool` |

---

# 17. 최종 기억할 흐름

```text
[구조화 출력]
자연어 → 스키마 → Pydantic 객체 → 데이터 처리

[도구]
Python 함수 → @tool → 모델이 호출 가능한 기능

[에이전트]
질문 → 도구 필요 여부 판단 → 도구 실행 → 결과 해석 → 답변

[구조화 에이전트]
질문 → 도구 실행 → 최종 결과를 다시 스키마 객체로 반환
```

**한 문장 정리**

> **LLM은 판단하고, 도구는 실제 작업을 수행하며, 스키마는 결과의 형태를 고정한다.**

---

# 18. 문서 검사 및 교정 사항

- 문서의 표·시각 자료를 확인해 Markdown 표와 프로세스 흐름으로 재구성.
- 중복 설명을 통합하고 `구조화 출력 → 도구 → 에이전트 → 구조화 에이전트 → 실무 도구` 순서로 재배치.
- 파이썬 프롬프트 표시는 제거하고 모두 `결과` 형식으로 통일.
- 코드 줄바꿈으로 깨진 문법과 들여쓰기 정리.
- `cafeteria_menu()` 반환 타입을 `-> str`로 명확화.
- 중첩 따옴표 때문에 깨지는 f-string 예시 수정.
- 에이전트 입력을 현재 공식 문서의 `messages=[{"role": ..., "content": ...}]` 형태로 통일.
- 현재 공식 문서의 상위 import 경로인 `langchain.tools`, `langchain.messages`를 사용하도록 정리.
- `IT-9999`는 형식 오류가 아니라 **형식은 맞지만 등록되지 않은 번호**라는 점을 교정.
- `RoomRequest.room_type`처럼 입력에 없는 정보를 필수값으로 두면 모델이 추론할 수 있다는 문제를 보완.
- 정확성이 필요한 업무 규칙은 스키마 설명보다 Python 코드로 구현하는 원칙을 명확화.
- `ProviderStrategy(..., strict=True)`의 `strict`는 LangChain 1.2 이상 필요.
