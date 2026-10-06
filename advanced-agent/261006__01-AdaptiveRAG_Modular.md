# Adaptive RAG와 Modular RAG

> 업무 문서 검색과 주문 조회를 하나의 LangGraph 흐름으로 연결하는 실습

---

## 1. 핵심 개념

### Adaptive RAG

질문에 따라 **필요한 처리 경로를 선택**하는 방식.

이 실습에서는 질문을 4가지 경로로 분류한다.

| 경로 | 의미 | 예시 |
|---|---|---|
| `knowledge` | 일반 업무 문서 검색 | 최소 주문 수량은? |
| `orders` | 특정 주문 상태 조회 | `MG-20260921-002`의 배송 완료 수량은? |
| `both` | 주문 상태 + 일반 조건 모두 필요 | 이 주문은 제작을 시작해도 되나? |
| `clarify` | 정보 부족으로 추가 질문 필요 | 우리 주문 배송 끝났나? |

```text
사용자 질문
    ↓
route_query
    ├─ knowledge ─→ search_knowledge ─→ generate ─→ END
    ├─ orders ─────→ lookup_order ─────→ generate ─→ END
    │                         └─ 조회 실패 ─→ respond ─→ END
    ├─ both ───────→ lookup_order ─────→ search_knowledge ─→ generate ─→ END
    │                         └─ 조회 실패 ─→ respond ─→ END
    └─ clarify ─────────────────────────→ respond ─→ END
```

핵심은 **질문마다 모든 검색을 수행하지 않고 필요한 경로만 선택**하는 것.

### Modular RAG

RAG를 하나의 고정 파이프라인이 아니라 **기능 모듈과 실행 흐름의 조합**으로 보는 설계 방식.

교안에서 제시한 주요 모듈은 다음과 같다.

```text
인덱싱
  ↓
검색 전 처리
  ↓
검색
  ↓
검색 후 처리
  ↓
생성
  ↓
오케스트레이션
```

- **라우팅**: 어떤 경로를 실행할지 선택
- **스케줄링**: 중간 결과를 보고 다음 작업 결정
- **융합**: 여러 검색 결과나 답변 결합
- **RAG Flow**: 선형·분기·조건부·반복 형태로 모듈 연결

> Adaptive RAG는 **어떤 처리 전략을 선택할지**, Modular RAG는 **RAG 구성 요소를 어떻게 조합할지**에 초점.
>
> 둘은 배타적인 개념이 아니며 하나의 시스템에 같이 적용할 수 있다.

---

## 2. 실습 데이터 구조

가상 기업 **모아기프트**의 두 종류 데이터를 사용한다.

| 데이터 | 저장소 | 역할 |
|---|---|---|
| 업무 문서 | Chroma | 주문·제작·배송 등의 일반 기준 검색 |
| 주문 기록 | SQLite | 주문번호별 실제 상태 정확 조회 |

업무 문서는 총 120개이며, 폐지 문서 3개를 제외한 **117개를 검색 대상으로 사용**한다.

```text
질문
 ├─ 일반 기준 필요 → Chroma + BM25
 ├─ 개별 주문 상태 → SQLite
 └─ 판단 필요      → SQLite 조회 후 업무 문서 검색
```

특정 주문을 판단할 때는 질문에 없는 상품명·수량을 추측하지 않는다.
먼저 주문 DB에서 확인한 뒤 업무 문서 검색어에 추가한다.

---

## 3. 환경 준비와 하이브리드 검색

### 3-1. 기본 설정

```python
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, TypedDict

import pandas as pd
from dotenv import find_dotenv, load_dotenv
from kiwipiepy import Kiwi
from pydantic import BaseModel, Field

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_chroma import Chroma
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langgraph.graph import StateGraph, START, END

material_dir = Path(".")
data_dir = material_dir / "data"

load_dotenv(find_dotenv(usecwd=True))
load_dotenv(material_dir.resolve().parent / ".env")

llm = ChatOpenAI(
    model=os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-luna"),
    use_responses_api=True,
)

embedding_model = OpenAIEmbeddings(
    model="text-embedding-3-large",
    dimensions=768,
    check_embedding_ctx_length=False,
)

chroma_dir = data_dir / "본실습" / "knowledge" / "chroma"
```

### 3-2. 근거 ID와 문서 복원

모든 근거는 `source_id`로 식별한다.

```python
def evidence_id(doc):
    return doc.metadata["source_id"]


vector_store = Chroma(
    collection_name="day54_main_documents",
    persist_directory=str(chroma_dir),
    embedding_function=embedding_model,
    create_collection_if_not_exists=False,
)

stored_documents = vector_store.get(include=["documents", "metadatas"])

documents = [
    Document(
        id=doc_id,
        page_content=text,
        metadata={**meta, "source_type": "knowledge"},
    )
    for doc_id, text, meta in zip(
        stored_documents["ids"],
        stored_documents["documents"],
        stored_documents["metadatas"],
        strict=True,
    )
]
```

**결과 예시**

```text
업무 문서: 120 / 검색 대상: 117
```

### 3-3. BM25 + Dense Hybrid Search

Kiwi 기반 BM25와 Chroma 의미 검색을 **0.5 : 0.5 RRF**로 결합한다.

```python
kiwi = Kiwi()


def kiwi_tokenize(text):
    return [
        token.form.lower()
        for token in kiwi.tokenize(text.replace("･", "·"))
        if token.tag.startswith("N") or token.tag in {"SL", "SN"}
    ]


bm25 = BM25Retriever.from_documents(
    [doc for doc in documents if doc.metadata["active"]],
    preprocess_func=kiwi_tokenize,
    k=12,
)

dense = vector_store.as_retriever(
    search_kwargs={"k": 12, "filter": {"active": True}}
)

hybrid = EnsembleRetriever(
    retrievers=[bm25, dense],
    weights=[0.5, 0.5],
    c=60,
    id_key="source_id",
)


def search_documents(search_query, top_k=6):
    return hybrid.invoke(search_query)[:top_k]
```

`top_k=6`은 각 검색기가 찾는 후보 수가 아니라 **RRF 결합 후 다음 노드로 넘길 문서 수의 상한**이다.

---

## 4. State 구성

그래프 전체에서 사용할 상태를 하나의 `TypedDict`로 정의한다.

```python
class RAGState(TypedDict):
    # 입력
    question: str
    top_k: int

    # 경로 선택
    route: Literal["knowledge", "orders", "both", "clarify"]
    reason: str
    search_query: str
    order_ids: list[str]
    clarification: str

    # 주문 조회
    order_notice: str

    # 공통 근거
    documents: list[Document]
    search_log: list[dict]

    # 최종 답변
    draft: str
    evidence_ids: list[str]


def make_initial_state(question, top_k=6) -> RAGState:
    return {
        "question": question,
        "top_k": top_k,
        "route": "clarify",
        "reason": "",
        "search_query": "",
        "order_ids": [],
        "clarification": "",
        "order_notice": "",
        "documents": [],
        "search_log": [],
        "draft": "",
        "evidence_ids": [],
    }
```

각 요청마다 새로운 리스트를 생성해 State 간 데이터가 섞이지 않게 한다.

---

## 5. 경로 선택: `route_query`

### 역할

1. LLM이 질문을 4개 경로 중 하나로 분류
2. 주문번호는 **LLM 출력이 아니라 원질문에서 정규표현식으로 직접 추출**
3. 주문 조회가 필요한데 주문번호가 없으면 `clarify`로 변경
4. 경로에 필요 없는 검색어·주문번호는 제거

### 구조화 출력

```python
class SearchPlan(BaseModel):
    route: Literal["knowledge", "orders", "both", "clarify"] = Field(
        description="질문에 필요한 처리 경로"
    )
    reason: str = Field(
        description="해당 경로를 선택한 이유",
        max_length=100,
    )
    search_query: str = Field(
        description="knowledge 또는 both에서 사용할 일반 업무 조건 검색어"
    )
    clarification: str = Field(
        description="clarify 경로에서 사용자에게 요청할 추가 정보"
    )
```

### 계획 프롬프트

```python
plan_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "사용자 질문에 필요한 정보의 종류를 판단해 처리 경로를 선택하세요. "
        "knowledge는 일반 업무 기준·절차·조건 조회, "
        "orders는 주문번호로 특정 주문 기록 조회, "
        "both는 특정 주문 기록과 일반 업무 기준이 모두 필요한 경우, "
        "clarify는 필요한 정보가 부족한 경우입니다. "
        "질문에 없는 상품명·수량·상태는 추측하지 마세요.",
    ),
    ("human", "{question}"),
])

plan_chain = plan_prompt | llm.with_structured_output(SearchPlan, strict=True)
```

### 노드

```python
def route_query(state: RAGState):
    plan = plan_chain.invoke({"question": state["question"]})

    route = plan.route
    reason = plan.reason
    search_query = plan.search_query
    clarification = plan.clarification

    order_ids = list(dict.fromkeys(re.findall(
        r"(?<![A-Z0-9-])MG-\d{8}-\d{3}(?![A-Z0-9-])",
        state["question"].upper(),
    )))

    # 주문 조회가 필요한데 번호가 없는 경우
    if route in {"orders", "both"} and not order_ids:
        route = "clarify"
        reason = "개별 주문을 조회하려면 주문번호가 필요합니다."
        clarification = "확인할 주문번호를 알려 주세요. 예: MG-12345678-123"

    # 검색 경로가 아니면 검색어 제거
    if route in {"knowledge", "both"}:
        search_query = search_query.strip() or state["question"]
    else:
        search_query = ""

    # 주문 조회 경로가 아니면 주문번호 제거
    if route not in {"orders", "both"}:
        order_ids = []

    if route != "clarify":
        clarification = ""

    return {
        "route": route,
        "reason": reason,
        "search_query": search_query,
        "order_ids": order_ids,
        "clarification": clarification,
    }
```

**예시**

```text
질문:
MG-20260928-001 주문의 현재 미완료 항목과 제작 시작일 확정 절차를 알려 주세요.

결과:
route        = both
search_query = 제작 시작일 확정 절차
order_ids    = ['MG-20260928-001']
```

---

## 6. 주문 조회: `lookup_order`

### 역할

- 여러 주문번호를 SQLite에서 한 번에 조회
- 각 주문을 `Document`로 변환
- 조회되지 않은 번호는 `order_notice`에 기록
- 기존 근거와 검색 기록을 보존

```python
order_db_path = data_dir / "본실습" / "orders" / "orders.sqlite3"
```

### 주문 결과를 공통 Document 형식으로 변환

```python
def order_document(record):
    display_values = {
        key: "기록 없음" if value is None or value == "" else value
        for key, value in record.items()
    }

    lines = [
        f"주문번호: {display_values['order_id']}",
        f"상품: {display_values['product']}",
        f"주문 수량: {display_values['quantity']}",
        f"주문 상태: {display_values['order_status']}",
        f"입금 상태: {display_values['payment_status']}",
        f"시안 승인 상태: {display_values['proof_status']}",
        f"확정 제작 시작일: {display_values['production_start']}",
        f"출고 수량: {display_values['shipped_count']}",
        f"배송 완료 수량: {display_values['delivered_count']}",
        f"미완료 확인 사항: {display_values['pending_item']}",
        f"행 갱신시각: {display_values['updated_at']}",
    ]

    doc_id = f"order:{record['order_id']}"

    return Document(
        id=doc_id,
        page_content="\n".join(lines),
        metadata={
            "order_id": record["order_id"],
            "product": record["product"],
            "quantity": record["quantity"],
            "source_id": doc_id,
            "title": f"주문 {record['order_id']} 조회 기록",
            "source_type": "order_snapshot",
            "source": "모아기프트 주문 자료",
            "updated": record["updated_at"],
        },
    )
```

### 조회 노드

```python
def lookup_order(state: RAGState):
    placeholders = ", ".join(["?"] * len(state["order_ids"]))
    uri = order_db_path.resolve().as_uri() + "?mode=ro"

    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT order_id, product, quantity, order_status, payment_status, "
            "proof_status, production_start, shipped_count, delivered_count, "
            "pending_item, updated_at "
            f"FROM orders WHERE order_id IN ({placeholders}) ORDER BY order_id",
            state["order_ids"],
        ).fetchall()

    found = [order_document(dict(row)) for row in rows]

    found_ids = {row["order_id"] for row in rows}
    missing_ids = [
        order_id
        for order_id in state["order_ids"]
        if order_id not in found_ids
    ]

    order_notice = (
        f"주문 자료에서 다음 번호를 찾지 못했습니다: {', '.join(missing_ids)}"
        if missing_ids
        else ""
    )

    log = {
        "source": "orders",
        "query": state["order_ids"],
        "candidate_ids": [evidence_id(doc) for doc in found],
    }

    return {
        "order_notice": order_notice,
        "documents": state["documents"] + found,
        "search_log": state["search_log"] + [log],
    }
```

> DB 연결 오류나 SQL 오류는 **주문 없음과 다른 문제**이므로 예외를 조회 실패로 숨기지 않는다.

---

## 7. 업무 조건 검색: `search_knowledge`

### 핵심

`both` 경로에서는 주문 DB에서 얻은 **상품명 + 수량**을 기존 검색어에 붙여 검색어를 보강한다.

```text
원질문
  ↓
route_query
  ↓
search_query = "제작 시작일 확정 절차"
  ↓
lookup_order
  ↓
product = "신입사원 선물 세트"
quantity = 80
  ↓
확장 검색어
"신입사원 선물 세트 80개 / 제작 시작일 확정 절차"
```

같은 검색어가 만들어지는 주문은 한 번만 검색하고 해당 주문번호를 `order_ids`에 묶는다.

```python
def search_knowledge(state: RAGState):
    documents = list(state["documents"])
    search_log = list(state["search_log"])

    order_docs = [
        doc
        for doc in state["documents"]
        if doc.metadata.get("source_type") == "order_snapshot"
    ]

    queries = {}

    if order_docs:
        for doc in order_docs:
            query = (
                f"{doc.metadata['product']} {doc.metadata['quantity']}개 / "
                f"{state['search_query']}"
            )
            queries.setdefault(query, []).append(doc.metadata["order_id"])
    else:
        queries[state["search_query"]] = []

    for query, order_ids in queries.items():
        found = search_documents(query, top_k=state["top_k"])
        documents.extend(found)

        search_log.append({
            "source": "knowledge",
            "query": query,
            "order_ids": order_ids,
            "candidate_ids": [evidence_id(doc) for doc in found],
        })

    # 기존 주문 근거까지 포함해 source_id 기준 중복 제거
    unique_documents = {}
    for doc in documents:
        unique_documents.setdefault(evidence_id(doc), doc)

    return {
        "documents": list(unique_documents.values()),
        "search_log": search_log,
    }
```

**검색 결과 예시**

```text
operations:production-schedule
- 확정 주문서
- 최종 로고 시안 승인
- 입금 완료
- 생산 슬롯 확인 후 제작 시작일 확정

operations:production-slot
- 실제 공정 여유와 구성품 준비 상태 확인
- 과거 출고 기록만으로 현재 시작일 확정 불가

...
```

긴 본문 출력은 학습용 MD에서는 핵심만 남긴다.

---

## 8. 근거 기반 답변 생성: `generate`

주문 조회 결과와 업무 문서를 같은 `Document` 구조로 전달한다.

### 출력 구조

```python
class GroundedAnswer(BaseModel):
    answer: str = Field(
        description="근거 기반 답변. 확인된 사실에 [근거 ID]를 표시"
    )
    evidence_ids: list[str] = Field(
        description="답변에서 실제 사용한 근거 ID 목록"
    )
```

### 근거 포맷

```python
def format_documents(docs):
    return "\n\n".join(
        f"[{evidence_id(doc)}] {doc.metadata['title']}\n"
        f"출처: {doc.metadata['source']}\n"
        f"기록 유형: {doc.metadata.get('source_type', 'knowledge')} / "
        f"자료 갱신일: {doc.metadata.get('updated', '본문 참조')}\n"
        f"{doc.page_content}"
        for doc in docs
    )
```

### 생성 원칙

프롬프트에서는 다음을 강제한다.

- 제공된 근거만 사용
- 일반 업무 조건과 개별 주문 상태 구분
- 기록 없음 ≠ 완료
- 출고 ≠ 배송 완료
- 일부 조건 충족 ≠ 전체 조건 충족
- 여러 주문의 상태를 서로 섞지 않음
- 실시간 정보처럼 표현하지 않음
- 조회되지 않은 주문에 임의 근거를 붙이지 않음
- 답변에서 실제 사용한 ID만 `evidence_ids`에 저장

긴 프롬프트 전문은 교안의 원문을 유지하고, 핵심 연결 부분만 보면 다음과 같다.

```python
answer_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "제공 근거로만 원질문에 답하세요. "
        "확인된 사실에는 [근거 ID]를 붙이고, "
        "일반 조건과 개별 주문 상태를 구분하세요. "
        "기록이 없는 항목은 완료로 간주하지 마세요.",
    ),
    (
        "human",
        "원질문: {question}\n"
        "인용 가능한 ID: {allowed_ids}\n"
        "근거:\n{context}",
    ),
])

answer_chain = answer_prompt | llm.with_structured_output(GroundedAnswer)
```

### 생성 노드

```python
def generate(state: RAGState):
    if not state["documents"]:
        return {
            "draft": "제공 자료에서 답변 근거를 찾지 못했습니다.",
            "evidence_ids": [],
        }

    allowed_ids = [evidence_id(doc) for doc in state["documents"]]
    context = format_documents(state["documents"])

    if state["order_notice"]:
        context += f"\n\n조회 안내: {state['order_notice']}"

    answer = answer_chain.invoke({
        "question": state["question"],
        "allowed_ids": allowed_ids,
        "context": context,
    })

    return {
        "draft": answer.answer,
        "evidence_ids": answer.evidence_ids,
    }
```

---

## 9. 추가 질문과 조건부 분기

### `respond`

우선순위는 **조회 없음 안내 → 추가 질문 → 기본 안내**.

```python
def respond(state: RAGState):
    return {
        "draft": (
            state["order_notice"]
            or state["clarification"]
            or "어떤 업무나 주문을 확인할까요?"
        ),
        "evidence_ids": [],
    }
```

### 계획 이후 분기

```python
def route_after_plan(state: RAGState):
    if state["route"] == "knowledge":
        return "search_knowledge"

    if state["route"] in {"orders", "both"}:
        return "lookup_order"

    return "respond"
```

### 주문 조회 이후 분기

```python
def route_after_order(state: RAGState):
    # 주문을 하나도 찾지 못함
    if not state["documents"]:
        return "respond"

    # 주문 상태를 확보한 뒤 일반 조건까지 검색
    if state["route"] == "both":
        return "search_knowledge"

    # orders 경로는 주문 근거로 바로 답변
    return "generate"
```

---

## 10. LangGraph 완성

```python
builder = StateGraph(RAGState)

builder.add_node("route_query", route_query)
builder.add_node("lookup_order", lookup_order)
builder.add_node("search_knowledge", search_knowledge)
builder.add_node("generate", generate)
builder.add_node("respond", respond)

builder.add_edge(START, "route_query")

builder.add_conditional_edges(
    "route_query",
    route_after_plan,
    {
        "search_knowledge": "search_knowledge",
        "lookup_order": "lookup_order",
        "respond": "respond",
    },
)

builder.add_conditional_edges(
    "lookup_order",
    route_after_order,
    {
        "search_knowledge": "search_knowledge",
        "generate": "generate",
        "respond": "respond",
    },
)

builder.add_edge("search_knowledge", "generate")
builder.add_edge("generate", END)
builder.add_edge("respond", END)

adaptive_app = builder.compile()
```

전체 흐름은 다음과 같다.

```text
START
  ↓
route_query
  ├─ knowledge → search_knowledge → generate → END
  │
  ├─ orders → lookup_order
  │               ├─ 조회 성공 → generate → END
  │               └─ 조회 실패 → respond → END
  │
  ├─ both → lookup_order
  │             ├─ 조회 성공 → search_knowledge → generate → END
  │             └─ 조회 실패 → respond → END
  │
  └─ clarify → respond → END
```

---

## 11. 실행 예시

### 11-1. 주문 상태 + 업무 조건

```python
question = (
    "MG-20260928-001 신입사원 선물 80세트 주문은 "
    "제작을 시작해도 되나요? 필요한 다음 조치도 알려 주세요."
)

result = adaptive_app.invoke(make_initial_state(question))

print("경로:", result["route"])
print("이유:", result["reason"])
print(result["search_log"])
print(result["draft"])
```

**핵심 결과**

```text
route = both

orders 조회
    ↓
업무 조건 검색
    ↓
두 근거를 함께 사용해 답변
```

### 11-2. 여러 주문 비교

```python
question = (
    "MG-20260928-001과 MG-20260929-005의 "
    "제작 시작 가능 여부와 다음 조치를 각각 알려 주세요."
)
```

```text
route = both
→ 주문별 상태를 따로 조회
→ 필요한 일반 제작 조건 검색
→ 주문번호별로 상태와 다음 조치를 분리해 답변
```

### 11-3. 조회된 주문 + 없는 주문

```python
question = (
    "MG-20260921-002와 MG-20990101-999의 "
    "배송 완료 수량을 각각 알려 주세요."
)
```

```text
route = orders
→ 존재하는 주문은 근거와 함께 답변
→ 없는 주문번호는 order_notice로 별도 안내
```

### 11-4. 주문번호가 없는 질문

```python
question = "우리 주문은 배송이 끝났나요?"
```

```text
route = clarify
→ 주문번호 요청
→ 검색/DB 조회는 수행하지 않음
```

### 11-5. 존재하지 않는 주문

```python
question = "MG-20990101-999의 입금 상태를 알려 주세요."
```

```text
route = orders
→ 조회 결과 없음
→ respond
→ 주문 자료에 해당 번호가 없다고 안내
```

---

## 12. 핵심 정리

### Adaptive RAG

질문의 종류에 따라 필요한 실행 경로를 선택한다.

```text
일반 조건 → knowledge
개별 상태 → orders
상태 + 조건 판단 → both
정보 부족 → clarify
```

### Modular RAG

검색·조회·생성 같은 기능을 독립된 모듈로 두고 조건부 흐름으로 연결한다.

이번 실습에서는 다음 모듈이 분리되어 있다.

```text
route_query       : 경로 선택
lookup_order      : 정확한 주문 조회
search_knowledge  : 하이브리드 문서 검색
generate          : 근거 기반 답변 생성
respond           : 추가 정보/조회 실패 안내
```

### 핵심 설계 원칙

- 질문에 없는 주문 정보는 추측하지 않음
- 주문번호는 LLM보다 정규표현식으로 직접 추출
- 주문 상태는 SQLite에서 정확 조회
- 일반 조건은 Hybrid Search로 검색
- `both`에서는 주문 조회 후 상품·수량으로 검색어 확장
- 기존 주문 근거를 유지한 채 업무 문서를 추가
- `source_id` 기준으로 근거 중복 제거
- 검색 기록과 실제 답변 근거를 함께 남김
- 조회 실패와 시스템 오류를 구분
- 조회되지 않은 상태를 완료로 해석하지 않음

---

## 13. 교안 코드에서 교정한 부분

정리하면서 교안의 요구사항과 맞지 않는 실습 작성 코드는 다음처럼 교정했다.

| 기존 작성 | 교정 |
|---|---|
| `evidence_id()`가 `...` 반환 | `doc.metadata["source_id"]` 반환 |
| 초기 `route`가 빈 문자열 | 기본값 `clarify` |
| `lookup_order` 반환 키가 `documents:` | `documents` |
| `prouduct` 오타 | `product` |
| `search_knowledge`가 State 리스트 직접 수정 | 복사 후 새 값 반환 |
| 주문 검색 시 기본 검색어까지 중복 검색 | 주문 문서가 있으면 확장 검색어만 사용 |
| `respond`가 `clarification` 우선 | `order_notice` 우선 |
| `route_after_order`가 함수 객체를 반환 | 노드 이름 문자열 반환 |
| 조회 성공/실패 분기 방향이 뒤바뀜 | 성공 시 `generate`/`search_knowledge`, 실패 시 `respond` |
| `respond → generate` 연결 | `respond → END` |

---

## 한 줄 흐름

```text
질문 분류 → 필요한 데이터만 조회 → 주문 정보로 검색어 보강 → 근거 통합 → 답변 생성
```
