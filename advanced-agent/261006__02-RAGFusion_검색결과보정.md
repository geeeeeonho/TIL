# RAG-Fusion과 검색 결과 보정

> 여러 검색 질의를 만들고, 각 검색 결과의 순위를 RRF로 융합한 뒤 사용할 근거만 선택하는 흐름 정리.

## 1. RAG-Fusion 핵심

### RAG-Fusion의 역할

**RAG-Fusion**은 하나의 질문을 여러 검색 표현으로 확장하고, 각 질의의 검색 순위를 합쳐 필요한 근거를 찾는 방식이다.

```text
사용자 질문
   ↓
Jev: 검색 모드 선택
   ├─ single        → 원질문 검색
   ├─ rewrite       → 원질문 + 재작성 질의 검색
   └─ decomposition → 확인 항목별 하위 질문 검색
                         ↓
                  질의별 Hybrid Search
                         ↓
                  질의 간 RRF Fusion
                         ↓
                  사용 가능한 원문 선택
                         ↓
                  원질문 기준 답변 생성
```

검색 모드는 질문의 형태에 따라 선택한다.

| 모드 | 사용 상황 | 검색 질의 |
|---|---|---|
| `single` | 하나의 요구가 명확함 | 원질문 |
| `rewrite` | 같은 정보를 다른 검색 표현으로 찾을 필요가 있음 | 원질문 + 재작성 질의 |
| `decomposition` | 서로 다른 확인 항목이 여러 개임 | 항목별 하위 질문 |

예시 질문:

```text
신입사원 선물 80세트를 주문하려고 합니다.
50세트는 본사로 먼저 받고, 나머지 30세트는 직원별로 나중에 받을 수 있나요?
배송을 나누면 추가 비용이 발생하나요?
```

확인 대상이 `분할 출고 조건`과 `추가 비용 기준`으로 나뉘므로 `decomposition`에 해당한다.

```text
원질문
 ├─ 분할 출고가 가능한 조건은?
 └─ 분할 배송 시 추가 비용 기준은?
```

최종 답변은 분해된 질문이 아니라 **원질문**을 기준으로 생성한다.

### Hybrid RRF와 Fusion RRF의 차이

RRF(Reciprocal Rank Fusion)는 문서의 순위를 점수로 바꿔 합산한다.

```text
RRF 점수 = 1 / (60 + rank)
```

| 적용 위치 | 합치는 대상 |
|---|---|
| Hybrid Search 내부 | 같은 질의의 BM25 + Dense 검색 순위 |
| RAG-Fusion | 서로 다른 질의의 Hybrid Search 순위 |

즉, 전체 구조는 다음과 같다.

```text
Query A → BM25 ─┐
                ├─ Hybrid RRF ─┐
Query A → Dense ┘              │
                               ├─ Fusion RRF → 최종 후보
Query B → BM25 ─┐              │
                ├─ Hybrid RRF ─┘
Query B → Dense ┘
```

RRF 점수가 높다고 해서 문서가 정확하거나 현재 사용 가능한 것은 아니다. **순위 융합 이후 별도의 사용 가능 여부 확인**이 필요하다.

---

## 2. 검색 환경 준비

실습에서는 가상 기업 모아기프트의 업무 문서를 검색한다.

| 문서 팀 | 주요 내용 |
|---|---|
| 영업팀 | 최소 주문 수량, 주문 변경, 접수 절차 |
| 브랜드팀 | 로고·색상·시안 승인 |
| 운영팀 | 제작 시작 조건, 제작 기간, 분할·개별 배송 |

전체 업무 문서 120개 중 폐지 문서 3개를 제외한 **117개**를 검색 대상으로 사용한다.

### 검색기 구성

```python
from pathlib import Path

from langchain_chroma import Chroma
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from kiwipiepy import Kiwi


def evidence_id(doc):
    """문서의 근거 ID 반환."""
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

**결과**

```text
업무 문서: 120 / 검색 대상: 117
```

### BM25 + Dense Hybrid Search

```python
kiwi = Kiwi()


def kiwi_tokenize(text):
    """명사·외국어·숫자를 같은 기준으로 추출."""
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
    """Hybrid Search 결과에서 최대 top_k개 반환."""
    return hybrid.invoke(search_query)[:top_k]
```

`top_k`는 Hybrid Search가 내부적으로 가져오는 문서 수를 줄이는 값이 아니라, **결합 이후 다음 단계에 전달할 후보 수**다.

---

## 3. Fusion State 설계

Fusion 검색은 다음 상태를 순서대로 채운다.

```text
question
   ↓ expand_queries
query_mode / queries
   ↓ search_many
search_log
   ↓ fuse
fused / contributions
   ↓ select_context
documents / selection_log
   ↓ generate
draft / evidence_ids
```

### State

```python
from typing import Literal, TypedDict
from langchain_core.documents import Document


class SearchQuery(TypedDict):
    kind: Literal["original", "rewrite", "subquestion"]
    query: str


class FusionState(TypedDict):
    # 입력
    question: str
    per_query_k: int
    final_k: int

    # expand_queries
    query_mode: Literal["single", "rewrite", "decomposition"]
    mode_probabilities: dict[str, float]
    queries: list[SearchQuery]

    # search_many
    search_log: list[dict]

    # fuse
    fused: list[dict]
    contributions: list[dict]

    # select_context
    documents: list[Document]
    selection_log: list[dict]

    # generate
    draft: str
    evidence_ids: list[str]


def make_fusion_state(question, per_query_k=3, final_k=6):
    return {
        "question": question,
        "per_query_k": per_query_k,
        "final_k": final_k,
        "query_mode": "",
        "mode_probabilities": {},
        "queries": [],
        "search_log": [],
        "fused": [],
        "contributions": [],
        "documents": [],
        "selection_log": [],
        "draft": "",
        "evidence_ids": [],
    }
```

> **교정:** 교안 설명에서는 입력 필드가 `per_query_k`인데 실습 작성 셀에서는 `top_k`로 사용된 부분이 있다. 정리본은 설명의 입출력 규약에 맞춰 `per_query_k`로 통일한다. `mode_probabilities`도 `dict[str, float]`이므로 `{}`로 초기화한다.

---

## 4. 검색 질의 구성 - `expand_queries`

### 역할

1. Jev가 `single / rewrite / decomposition` 중 하나를 선택한다.
2. `single`이면 원질문만 사용한다.
3. `rewrite`이면 원질문과 재작성 질의를 함께 사용한다.
4. `decomposition`이면 확인 항목별 하위 질문을 사용한다.

```python
from pydantic import BaseModel, Field
from langchain_typesafe import Choice


mode_question = Choice(
    instructions=(
        "질문에 필요한 검색 질의 구성을 하나 고르세요. "
        "독립적인 정보 요구가 여러 개이면 decomposition을 우선합니다. "
        "하나의 정보 요구이면 rewrite 또는 single을 선택합니다."
    ),
    criteria={
        "single": "정보 요구가 하나이며 원질문만으로 검색 대상과 내용이 명확함",
        "rewrite": "정보 요구는 하나지만 다른 검색 표현으로 다변화하면 도움이 됨",
        "decomposition": "독립적으로 확인할 정보 요구가 둘 이상임",
    },
)


class QueryVariants(BaseModel):
    queries: list[str] = Field(
        max_length=5,
        description=(
            "rewrite는 같은 정보를 다른 표현으로 작성하고, "
            "decomposition은 서로 다른 확인 항목을 하위 질문으로 분리한다."
        ),
    )
```

질의 생성 체인은 구조화 출력을 사용한다.

```python
query_chain = query_prompt | llm.with_structured_output(
    QueryVariants,
    strict=True,
)
```

### 노드

```python
def expand_queries(state: FusionState):
    """검색 모드를 선택하고 실제 검색 질의를 구성."""

    decision = query_classifier.invoke({
        "state": state["question"],
        "questions": {"query_mode": mode_question},
    })

    result = decision.choices["query_mode"]
    mode = result.choice
    probabilities = result.probabilities

    if mode == "single":
        queries = [{
            "kind": "original",
            "query": state["question"],
        }]

    else:
        variants = query_chain.invoke({
            "mode": mode,
            "question": state["question"],
        })

        if mode == "rewrite":
            queries = [
                {"kind": "original", "query": state["question"]},
                *[
                    {"kind": "rewrite", "query": query}
                    for query in variants.queries
                ],
            ]
        else:
            queries = [
                {"kind": "subquestion", "query": query}
                for query in variants.queries
            ]

    return {
        "query_mode": mode,
        "mode_probabilities": probabilities,
        "queries": queries,
    }
```

> **교정:** 교안 앞부분은 `decomposition`에서 **하위 질문만 검색**한다고 명시한다. 원본 작성 셀은 원질문을 먼저 넣고 하위 질문을 추가하고 있어 설명과 다르므로, 정리본은 하위 질문만 검색하도록 맞춘다.

**교안 실행 예시**

```text
query_mode: decomposition

확률:
- decomposition: 0.95
- single: 0.03
- rewrite: 0.02
```

원본 노트북 실행에서는 원질문과 하위 질문들이 함께 생성되었다. 위 정리본에서는 교안의 설명 규칙을 우선한다.

---

## 5. 질의별 검색 - `search_many`

각 검색 질의를 **독립적으로** Hybrid Search에 전달한다.

```python
def search_many(state: FusionState):
    """질의별 검색 결과를 순서대로 기록."""

    search_log = []

    for item in state["queries"]:
        found = search_documents(
            item["query"],
            top_k=state["per_query_k"],
        )

        search_log.append({
            "source": "knowledge",
            "kind": item["kind"],
            "query": item["query"],
            "candidate_ids": [evidence_id(doc) for doc in found],
        })

    return {"search_log": search_log}
```

이 단계에서는 검색 결과를 아직 합치지 않는다.

```text
Query A → [Doc1, Doc2, Doc3]
Query B → [Doc2, Doc4, Doc1]
Query C → [Doc5, Doc2, Doc3]
```

교안 검색 예시에서는 다음 문서들이 반복해서 상위에 나타났다.

```text
sales:welcome-order-v2
operations:split-shipping
operations:partial-shipment
sales:quote-scope
sales:ext-multi-delivery-quote
```

---

## 6. 질의 간 RRF - `fuse`

### 처리 원칙

1. 한 검색 목록 내부의 중복 ID 제거
2. 남은 순서에 1부터 rank 부여
3. `1 / (60 + rank)` 계산
4. 같은 문서가 여러 질의에서 검색되면 점수 합산
5. 점수 내림차순으로 최종 순위 생성

```python
def fuse(state: FusionState):
    """질의별 순위를 RRF로 융합."""

    scores = {}
    contributions = []

    for result in state["search_log"]:
        unique_ids = list(dict.fromkeys(result["candidate_ids"]))

        for rank, doc_id in enumerate(unique_ids, start=1):
            contribution = 1 / (60 + rank)
            scores[doc_id] = scores.get(doc_id, 0.0) + contribution

            contributions.append({
                "doc_id": doc_id,
                "source": result["source"],
                "kind": result["kind"],
                "query": result["query"],
                "rank": rank,
                "contribution": contribution,
            })

    fused = [
        {"doc_id": doc_id, "score": score}
        for doc_id, score in sorted(
            scores.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]

    return {
        "fused": fused,
        "contributions": contributions,
    }
```

`contributions`를 남기는 이유는 **어떤 질의가 해당 문서를 상위로 끌어올렸는지 추적**하기 위해서다.

### 고정 예시

```text
original
1위 sales:welcome-order-v1
2위 sales:welcome-order-v2

rewrite
1위 sales:welcome-order-v1
2위 sales:welcome-order-v2

subquestion
1위 operations:split-shipping
```

융합 결과:

| 문서 | RRF 점수 |
|---|---:|
| `sales:welcome-order-v1` | 0.032787 |
| `sales:welcome-order-v2` | 0.032258 |
| `operations:split-shipping` | 0.016393 |

`welcome-order-v1`이 가장 높은 점수지만, **폐지 문서라면 최종 근거로 사용할 수 없다.**

> **실습 셀 주의:** 원본 노트북에서 `search_many(node_state)` 결과를 `node_state.update(result)`로 반영하지 않고 `fuse(node_state)`를 실행해 빈 결과가 출력되는 셀이 있다. 수동 실행에서는 검색 결과를 State에 반영한 뒤 다음 노드를 호출해야 한다.

---

## 7. 최종 근거 선택 - `select_context`

RRF는 순위만 결정한다. 실제 답변에 사용할 수 있는지는 별도로 확인한다.

```text
RRF 순위
   ↓
원문 존재?
   ↓
active=True?
   ↓
final_k 이내?
   ↓
최종 근거 선택
```

### 문서 선택

```python
document_by_id = {
    evidence_id(doc): doc
    for doc in documents
}


def select_documents(fused, document_index, final_k):
    selected = []
    selection_log = []

    for item in fused:
        doc = document_index.get(item["doc_id"])

        if doc is None:
            reason = "원문 없음"
        elif not doc.metadata["active"]:
            reason = "폐지 문서"
        elif len(selected) >= final_k:
            reason = "최종 개수 한도"
        else:
            selected.append(doc)
            reason = "선택됨"

        selection_log.append({
            "doc_id": item["doc_id"],
            "reason": reason,
        })

    return {
        "documents": selected,
        "selection_log": selection_log,
    }


def select_context(state: FusionState):
    return select_documents(
        state["fused"],
        document_by_id,
        state["final_k"],
    )
```

**결과 예시**

| 문서 | 처리 |
|---|---|
| `sales:welcome-order-v1` | 폐지 문서 |
| `sales:welcome-order-v2` | 선택됨 |
| `operations:split-shipping` | 선택됨 |

```text
최종 문서:
- sales:welcome-order-v2
- operations:split-shipping
```

핵심은 **검색 순위와 근거 사용 가능 여부를 분리**하는 것이다.

---

## 8. 원질문 기준 답변 - `generate`

답변에는 하위 질문이 아니라 **처음 받은 원질문과 최종 선택 문서**를 전달한다.

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

```python
def generate(state):
    """선택된 근거로 원질문에 답변."""

    if not state["documents"]:
        return {
            "draft": "제공 자료에서 답변 근거를 찾지 못했습니다.",
            "evidence_ids": [],
        }

    allowed_ids = [
        evidence_id(doc)
        for doc in state["documents"]
    ]

    answer = answer_chain.invoke({
        "question": state["question"],
        "allowed_ids": allowed_ids,
        "context": format_documents(state["documents"]),
    })

    return {
        "draft": answer.answer,
        "evidence_ids": answer.evidence_ids,
    }
```

답변 생성 원칙:

- 제공된 근거만 사용
- 사실마다 `[근거 ID]` 표시
- 일반 업무 기준과 특정 주문 상태 구분
- 자료에 없는 가능 여부·가격·일정 확정 금지
- 주문별 상태가 섞이지 않도록 구분

---

## 9. Fusion 그래프 연결

```python
from langgraph.graph import StateGraph, START, END

builder = StateGraph(FusionState)

builder.add_node("expand_queries", expand_queries)
builder.add_node("search_many", search_many)
builder.add_node("fuse", fuse)
builder.add_node("select_context", select_context)
builder.add_node("generate", generate)

builder.add_edge(START, "expand_queries")
builder.add_edge("expand_queries", "search_many")
builder.add_edge("search_many", "fuse")
builder.add_edge("fuse", "select_context")
builder.add_edge("select_context", "generate")
builder.add_edge("generate", END)

fusion_app = builder.compile()
```

그래프 구조:

```text
START
  ↓
expand_queries
  ↓
search_many
  ↓
fuse
  ↓
select_context
  ↓
generate
  ↓
END
```

교안 전체 실행에서는 Jev가 `decomposition`을 선택했고, 다음 문서들이 최종 선택되었다.

```text
operations:split-shipping
sales:welcome-order-v2
operations:partial-shipment
sales:individual-payment
sales:order-policy-history
```

중요한 것은 문서 개수가 아니라 **각 확인 항목에 필요한 근거가 실제로 추가되었는지** 확인하는 것이다.

---

## 10. Adaptive RAG에 Fusion 모듈 연결

교안 01의 Adaptive RAG 전체 구조는 유지하고, **업무 문서 검색 모듈만 Fusion으로 교체**한다.

```text
사용자 질문
   ↓
route_query
   ├─ clarify ───────────────→ respond → END
   ├─ knowledge ─────────────→ search_knowledge
   ├─ orders ─→ lookup_order ─────────→ generate
   └─ both ───→ lookup_order → search_knowledge
                                   ↓
                                generate
                                   ↓
                                  END
```

### 유지하는 부분 / 교체하는 부분

| 유지 | 교체 |
|---|---|
| Adaptive State | `search_knowledge` 내부 검색 |
| `route_query` | 단일 `search_documents` 호출 |
| `lookup_order` | `expand → search → fuse → select` |
| `generate` |  |
| 조건부 엣지 |  |

특정 주문 질문에서 주문 기록은 RRF에 넣지 않는다.

```text
주문 DB 조회 → 주문 근거
업무 문서 검색 → Fusion 근거
                    ↓
            두 근거를 함께 generate
```

### Adaptive State

```python
class RAGState(TypedDict):
    question: str
    top_k: int

    route: Literal["knowledge", "orders", "both", "clarify"]
    reason: str
    search_query: str
    order_ids: list[str]
    clarification: str

    order_notice: str

    documents: list[Document]
    search_log: list[dict]

    draft: str
    evidence_ids: list[str]
```

### 경로 판단

```text
일반 업무 기준만 필요      → knowledge
특정 주문 기록만 필요      → orders
주문 상태 + 일반 조건 필요 → both
질문/주문번호가 불명확     → clarify
```

예시:

```text
MG-20260928-001 주문의 현재 미완료 항목과
제작 시작일 확정 절차를 알려 주세요.
```

특정 주문 상태와 일반 업무 절차가 모두 필요하므로 `both` 경로를 사용한다.

---

## 11. Fusion을 사용하는 `search_knowledge`

주문이 먼저 조회된 경우 상품명·수량을 기존 검색어에 결합한다.

```text
주문 문서
  ├─ product
  └─ quantity
       ↓
"{상품} {수량}개 / {search_query}"
       ↓
Fusion 검색
```

같은 검색어는 한 번만 처리하고, 같은 문서는 최종 `documents`에 한 번만 남긴다.

### 교정한 완성 코드

```python
def search_knowledge(state: RAGState):
    """업무 조건을 Fusion 검색으로 조회."""

    documents = list(state["documents"])
    search_log = list(state["search_log"])

    # 주문 조회 결과가 있으면 상품·수량으로 검색어 보강
    queries = {}

    for doc in documents:
        query = (
            f"{doc.metadata['product']} "
            f"{doc.metadata['quantity']}개 / "
            f"{state['search_query']}"
        )
        queries.setdefault(query, []).append(doc.metadata["order_id"])

    # 일반 knowledge 질문
    if not queries:
        queries[state["search_query"]] = []

    for query, order_ids in queries.items():
        working = make_fusion_state(
            query,
            per_query_k=state["top_k"],
            final_k=state["top_k"],
        )

        working.update(expand_queries(working))
        working.update(search_many(working))
        working.update(fuse(working))
        working.update(select_context(working))

        documents.extend(working["documents"])

        for entry in working["search_log"]:
            search_log.append({
                **entry,
                "order_ids": order_ids,
                "query_mode": working["query_mode"],
            })

    unique_documents = {
        evidence_id(doc): doc
        for doc in documents
    }

    return {
        "documents": list(unique_documents.values()),
        "search_log": search_log,
    }
```

> **교정:** 원본 작성 셀은 `fuse()` 다음에 `expand_queries()`를 다시 호출하고 `select_context()`가 빠져 있으며, 이후 코드가 `...`로 남아 있다. 교안의 작성 요구사항대로 `expand_queries → search_many → fuse → select_context` 순서로 완성한다.

---

## 12. Adaptive 그래프 연결

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

교안 실행 질문:

```text
MG-20260928-001과 MG-20260929-005를 제작 시작해도 되나요?
주문별 현재 상태와 다음 조치를 확인해 주세요.
```

경로 판단 결과:

```text
route: both
```

즉,

```text
두 주문 조회
   ↓
각 주문의 상품·수량으로 검색어 보강
   ↓
Fusion 업무 문서 검색
   ↓
주문 상태 + 업무 조건을 함께 근거로 답변
```

원본 노트북에서는 `search_knowledge`가 미완성 상태라 실행 출력에 주문 조회 로그까지만 나타난다. 위 코드는 교안의 작성 요구사항에 맞춘 완성 형태다.

---

## 13. 핵심 정리

### 전체 구조

```text
                ┌─ single ─────────────┐
질문 → Jev ─────┼─ rewrite ────────────┼→ 질의별 Hybrid Search
                └─ decomposition ──────┘
                              ↓
                       질의 간 RRF
                              ↓
                    현행·존재 여부 확인
                              ↓
                       최종 원문 선택
                              ↓
                     원질문 기준 답변
```

### 기억할 내용

- **Adaptive RAG**: 질문에 따라 어떤 경로를 실행할지 선택.
- **Modular RAG**: 같은 입출력을 가진 검색 모듈을 교체·조합.
- **RAG-Fusion**: 여러 검색 질의의 결과 순위를 다시 RRF로 합침.
- `rewrite`는 **같은 정보의 표현 확장**.
- `decomposition`은 **서로 다른 확인 항목 분리**.
- RRF는 **순위 점수**일 뿐, 문서의 정확성이나 현행 여부를 보장하지 않음.
- `contributions`로 어떤 질의가 문서를 찾는 데 기여했는지 추적.
- 폐지 문서는 점수가 높아도 `select_context`에서 제외.
- 주문 DB 조회 결과는 Fusion RRF에 넣지 않고, 최종 답변 단계에서 업무 문서 근거와 결합.
- 질의를 늘렸는데 필요한 근거가 늘지 않는다면 Fusion보다 단일 질의 검색이 효율적일 수 있음.

### 한 줄 흐름

```text
검색 전략 선택 → 질의 생성 → 개별 검색 → RRF 융합 → 근거 검증 → 답변
```
