# RAG Fusion 예시 코드 정리

질문을 그대로 한 번 검색하는 대신, 질문 유형에 따라 **single / rewrite / decomposition** 방식으로 검색 질의를 구성하고 여러 검색 결과를 **RRF(Reciprocal Rank Fusion)** 로 합쳐 최종 근거를 선택하는 구조.

- 코드 → 결과 구조 유지.
- 긴 DataFrame과 반복 출력은 핵심 행만 남기고 축약.
- 그래프 이미지는 노드 역할까지 포함한 텍스트 도식으로 변환.
- `llm`, `query_classifier`, `search_documents()`, `chroma_dir`, `embedding_model` 등은 제공 문서 안에 정의가 없으므로 준비되어 있다고 전제.

## 전체 흐름

```text
[START]
   ↓
┌────────────────────────────────┐
│ 검색 질의 구성                 │
│ expand_queries                 │
│ - 질문 유형 판단              │
│ - single / rewrite /           │
│   decomposition 선택           │
│ - 검색 질의 목록 생성          │
└────────────────────────────────┘
   ↓
┌────────────────────────────────┐
│ 질의별 검색                    │
│ search_many                    │
│ - 각 질의를 독립적으로 검색    │
│ - 질의별 top-k 후보 확보        │
│ - 후보 evidence_id 순위 기록   │
└────────────────────────────────┘
   ↓
┌────────────────────────────────┐
│ RRF 순위 융합                  │
│ fuse                           │
│ - 질의별 검색 순위 결합         │
│ - 1 / (60 + rank) 점수 누적    │
│ - 문서별 최종 순위 계산         │
└────────────────────────────────┘
   ↓
┌────────────────────────────────┐
│ 현행 원문 선택                 │
│ select_context                 │
│ - 문서 ID로 실제 원문 조회      │
│ - 폐지/누락 문서 제외           │
│ - final_k까지 최종 근거 선택    │
└────────────────────────────────┘
   ↓
┌────────────────────────────────┐
│ 답변 생성                      │
│ generate                       │
│ - 선택 근거만 LLM에 제공        │
│ - 근거 ID를 붙여 답변 생성      │
│ - evidence_ids 저장            │
└────────────────────────────────┘
   ↓
 [END]
```

### 질의 모드

```text
single
└─ 원질문 그대로 1회 검색

rewrite
├─ 원질문
└─ 같은 의미의 재작성 질의 여러 개

decomposition
├─ 하위 질문 1
├─ 하위 질문 2
└─ ... 독립적인 정보 요구별 검색
```

---

# 0. 기본 조회 근거 준비

Chroma에 저장된 문서를 다시 임베딩하지 않고 읽어와 검색 대상 원문 목록을 준비.

```python
def evidence_id(doc):
    """문서나 상품 조회 결과에 부여한 근거 ID를 반환합니다."""
    return doc.metadata["source_id"]


vector_store = Chroma(
    collection_name="day54_shop_documents",
    persist_directory=str(chroma_dir),
    embedding_function=embedding_model,
    create_collection_if_not_exists=False,
)

# 저장된 본문·메타데이터를 읽음. 다시 임베딩하지 않음.
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

print(
    "검색 문서:", len(documents),
    "/ 검색 대상:", sum(doc.metadata["active"] for doc in documents)
)

display(pd.DataFrame([
    {
        "ID": evidence_id(doc),
        "제목": doc.metadata["title"],
        "검색 사용": doc.metadata["active"],
    }
    for doc in documents[:6]
]))
```

### 결과

```text
검색 문서: 120 / 검색 대상: 108

ID                         제목                                  검색 사용
manual:keyboard-pairing    키보드 사용 안내: Bluetooth 기기 등록     True
manual:keyboard-switch     키보드 사용 안내: 기기 전환과 동시 입력     True
manual:keyboard-osmode     키보드 사용 안내: Windows와 Mac 모드       True
...
```

---

# 1. Fusion State 설계

검색 질의, 질의별 검색 기록, RRF 결과, 최종 선택 근거, 답변까지 하나의 State에서 관리.

```python
class SearchQuery(TypedDict):
    kind: Literal["original", "rewrite", "subquestion"]
    query: str


class FusionState(TypedDict):
    # 입력
    question: str
    per_query_k: int
    final_k: int

    # 질의 구성
    query_mode: str
    mode_probabilities: dict[str, float]
    queries: list[SearchQuery]

    # 검색·융합
    search_log: list[dict]
    fused: list[dict]
    contributions: list[dict]

    # 최종 근거 선택
    documents: list[Document]
    selection_log: list[dict]

    # 답변
    draft: str
    evidence_ids: list[str]
```

새 질문마다 초기 State 생성.

```python
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

---

# 2. 검색 질의 구성

`expand_queries`가 원질문을 보고 어떤 방식으로 검색할지 결정한 뒤 실제 검색 질의 목록을 만듦.

## 2.1 검색 모드 판단 기준

```python
mode_question = Choice(
    instructions=(
        "질문에 필요한 검색 질의 구성을 하나 고르세요. "
        "독립적인 정보 요구가 여러 개이면 decomposition을 우선합니다. "
        "하나의 정보 요구이면 표현을 정리할 필요가 있는지 보고 rewrite 또는 single을 고르세요. "
        "수량·시점·대상 같은 조건이 여러 개라는 이유만으로 질문을 분해하지 마세요. "
        "검색 결과를 보지 않은 단계이므로 문서 존재 여부나 검색 성공을 추측하지 마세요."
    ),
    criteria={
        "single": (
            "하나의 정보 요구이며 대상과 검색할 내용이 구체적이어서 "
            "원질문을 그대로 검색하면 되는 질문"
        ),
        "rewrite": (
            "하나의 정보 요구이지만 구어적·장황한 표현을 "
            "핵심 검색어로 정리하면 도움이 되는 질문"
        ),
        "decomposition": (
            "서로 독립적으로 확인할 정보 요구가 둘 이상이어서 "
            "각각 검색한 근거를 함께 모아야 하는 질문"
        ),
    },
)
```

## 2.2 생성 질의 구조

```python
class QueryVariants(BaseModel):
    queries: list[str] = Field(
        max_length=5,
        description=(
            "선택된 모드에 맞게 만든 검색 질의 목록입니다. "
            "rewrite이면 같은 정보 요구를 다른 용어로 표현하고, "
            "decomposition이면 서로 다른 확인 항목을 하위 질문으로 나눕니다. "
            "각 질의에 필요한 대상·수량·시점·조건을 남기고, "
            "중복 없이 최대 5개 안에서 필요한 만큼 작성합니다."
        ),
    )
```

```python
query_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "검색 모드는 {mode}입니다. 결과는 queries에 넣으세요. "
        "rewrite이면 원질문의 전체 의미를 유지한 다른 검색 표현들을 만드세요. "
        "원질문 자체는 다시 넣지 마세요. "
        "decomposition이면 원질문에 직접 요청된 확인 항목만 분리하고, "
        "각 질문을 독립적으로 검색할 수 있게 작성하세요. "
        "하나의 확인 항목을 비슷한 질문 여러 개로 반복하지 마세요. "
        "도움이 될 것 같은 추가 확인이나 후속 업무는 새 질의로 만들지 마세요. "
        "질문에 없는 서류명·준비물·담당자·기한 등을 예상 답처럼 질의에 넣지 마세요. "
        "질의는 최대 5개이며, 5개를 억지로 채우지 마세요. "
        "어순만 바꾸거나 같은 항목을 반복해 개수를 늘리지 마세요. "
        "원질문에 명시된 조건과 선후 관계를 보존하고, "
        "없는 요구나 추측한 답변은 추가하지 마세요."
    ),
    ("human", "{question}"),
])

query_chain = query_prompt | llm.with_structured_output(QueryVariants)
```

## 2.3 `expand_queries` 노드

```python
def expand_queries(state: FusionState):
    """모드에 맞는 검색 질의와 Jev의 판단 결과를 반환합니다."""

    question = state["question"]

    # 1. 검색 모드 판단
    result = query_classifier.invoke({
        "state": question,
        "questions": {
            "query_mode": mode_question
        }
    })

    mode_result = result.choices["query_mode"]
    mode = mode_result.choice
    probabilities = mode_result.probabilities

    # 2. single: 원질문 그대로 사용
    if mode == "single":
        queries = [
            {
                "kind": "original",
                "query": question,
            }
        ]

    # 3. rewrite / decomposition: LLM으로 질의 생성
    else:
        generated = query_chain.invoke({
            "question": question,
            "mode": mode,
        })
        generated_queries = generated.queries

        if mode == "rewrite":
            # 원질문 + 재작성 질의
            queries = [
                {
                    "kind": "original",
                    "query": question,
                }
            ]

            for query in generated_queries:
                queries.append({
                    "kind": "rewrite",
                    "query": query,
                })

        elif mode == "decomposition":
            # 하위 질문들만 사용
            queries = []

            for query in generated_queries:
                queries.append({
                    "kind": "subquestion",
                    "query": query,
                })

    return {
        "query_mode": mode,
        "mode_probabilities": probabilities,
        "queries": queries,
    }
```

---

# 3. 질의별 검색

`search_many`가 각 질의를 독립적으로 검색하고, 문서 전체가 아닌 **순위가 유지된 evidence ID 목록**을 저장.

```python
def search_many(state: FusionState):
    search_log = []

    for item in state["queries"]:
        docs = search_documents(
            item["query"],
            top_k=state["per_query_k"],
        )

        candidate_ids = [
            evidence_id(doc)
            for doc in docs
        ]

        search_log.append({
            "source": "knowledge",
            "kind": item["kind"],
            "query": item["query"],
            "candidate_ids": candidate_ids,
        })

    return {
        "search_log": search_log
    }
```

### 결과 확인

```python
test_state = make_fusion_state("테스트 질문", per_query_k=2)

test_state["queries"] = [
    {"kind": "subquestion", "query": "기기 등록"},
    {"kind": "subquestion", "query": "단축키 설정"},
]

result = search_many(test_state)
print(result["search_log"])
```

```text
[
  {
    'kind': 'subquestion',
    'query': '기기 등록',
    'candidate_ids': [
      'manual:keyboard-pairing',
      'guide:KB-102-pairing'
    ]
  },
  {
    'kind': 'subquestion',
    'query': '단축키 설정',
    'candidate_ids': [
      'faq:keyboard-shortcuts',
      'guide:KB-102-shortcuts'
    ]
  }
]
```

---

# 4. RRF로 검색 순위 융합

여러 질의에서 반복해서 높은 순위에 등장한 문서가 더 높은 점수를 받도록 검색 결과를 합침.

```text
RRF 기여 점수 = 1 / (60 + rank)

rank 1 → 1 / 61
rank 2 → 1 / 62
rank 3 → 1 / 63
...

같은 문서가 여러 질의에 등장하면 기여 점수를 모두 합산.
```

## `fuse` 노드

```python
def fuse(state: FusionState):
    scores = {}
    contributions = []

    for log in state["search_log"]:
        # 한 검색 결과 내부의 중복 ID 제거
        seen = set()
        unique_ids = []

        for doc_id in log["candidate_ids"]:
            if doc_id not in seen:
                seen.add(doc_id)
                unique_ids.append(doc_id)

        # 순위별 RRF 점수 누적
        for rank, doc_id in enumerate(unique_ids, start=1):
            contribution = 1 / (60 + rank)

            scores[doc_id] = scores.get(doc_id, 0) + contribution

            contributions.append({
                "doc_id": doc_id,
                "source": log["source"],
                "kind": log["kind"],
                "query": log["query"],
                "rank": rank,
                "contribution": contribution,
            })

    # 점수 내림차순 → 동점이면 ID 오름차순
    fused = [
        {
            "doc_id": doc_id,
            "score": score,
        }
        for doc_id, score in scores.items()
    ]

    fused.sort(
        key=lambda item: (-item["score"], item["doc_id"])
    )

    return {
        "fused": fused,
        "contributions": contributions,
    }
```

### 결과 확인

```python
test_state = make_fusion_state("테스트 질문")

test_state["search_log"] = [
    {
        "source": "knowledge",
        "kind": "subquestion",
        "query": "기기 등록",
        "candidate_ids": ["A", "B"],
    },
    {
        "source": "knowledge",
        "kind": "subquestion",
        "query": "단축키 설정",
        "candidate_ids": ["B"],
    },
]

result = fuse(test_state)
print(result["fused"])
print(result["contributions"])
```

```text
fused:
[
  {'doc_id': 'B', 'score': 0.03252...},
  {'doc_id': 'A', 'score': 0.01639...}
]

contributions:
A ← 기기 등록 1위 : 0.01639...
B ← 기기 등록 2위 : 0.01612...
B ← 단축키 설정 1위 : 0.01639...
```

`B`는 두 질의에 모두 등장했기 때문에 누적 점수가 더 높아짐.

---

# 5. 실제 사용할 원문 선택

RRF 결과는 문서 ID와 점수만 가지고 있으므로, ID를 실제 `Document`로 다시 연결하고 사용할 수 있는 문서만 선택.

```python
# ID → 실제 원문 조회용 사전
document_by_id = {
    evidence_id(doc): doc
    for doc in documents
}
```

## 5.1 원문 선택 보조 함수

선택 우선순위:

```text
원문 없음      → 제외
active=False   → 폐지 문서로 제외
final_k 초과   → 제외
그 외          → 최종 근거로 선택
```

```python
def select_documents(fused, document_index, final_k):
    selected = []
    selection_log = []

    for item in fused:
        doc_id = item["doc_id"]
        doc = document_index.get(doc_id)

        if doc is None:
            reason = "원문 없음"

        elif not doc.metadata["active"]:
            reason = "폐지 문서"

        elif len(selected) >= final_k:
            reason = "최종 개수 한도"

        else:
            reason = "선택"
            selected.append(doc)

        selection_log.append({
            "doc_id": doc_id,
            "reason": reason,
        })

    return {
        "documents": selected,
        "selection_log": selection_log,
    }
```

## 5.2 `select_context` 노드

```python
def select_context(state: FusionState):
    return select_documents(
        state["fused"],
        document_by_id,
        state["final_k"],
    )
```

### 결과 확인

```python
test_fused = [
    {"doc_id": "A", "score": 0.03},
    {"doc_id": "B", "score": 0.02},
]

test_index = {
    "A": Document(page_content="문서 A", metadata={"active": True}),
    "B": Document(page_content="문서 B", metadata={"active": True}),
}

result = select_documents(test_fused, test_index, final_k=1)

print(result["documents"])
print(result["selection_log"])
```

```text
선택 문서:
[Document(... page_content='문서 A')]

selection_log:
[
  {'doc_id': 'A', 'reason': '선택'},
  {'doc_id': 'B', 'reason': '최종 개수 한도'}
]
```

---

# 6. 선택 근거로 답변 생성

최종 선택한 문서만 LLM에 전달하고, 실제 사용한 근거 ID를 함께 반환.

## 6.1 구조화 답변 모델

```python
class GroundedAnswer(BaseModel):
    answer: str = Field(
        description=(
            "원질문에 대한 답변입니다. "
            "확인된 사실마다 [근거 ID]를 붙이고 확인되지 않은 항목을 구분합니다."
        )
    )
    evidence_ids: list[str] = Field(
        description=(
            "답변에서 실제로 인용한 제공 근거 ID 목록입니다. "
            "없는 ID를 만들지 않습니다."
        )
    )
```

```python
def format_documents(docs):
    return "\n\n".join(
        f"[{evidence_id(doc)}] {doc.metadata['title']}\n"
        f"출처: {doc.metadata['source']}\n"
        f"{doc.page_content}"
        for doc in docs
    )
```

프롬프트의 핵심 규칙:

- 제공된 근거만 사용.
- 사실마다 `[근거 ID]` 표시.
- 다른 상품의 사양·설정 정보를 섞지 않음.
- 근거가 없는 내용은 확인 불가로 표시.
- 자료에 없는 가격·입고일·버튼 조합 등을 생성하지 않음.

```python
answer_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "제공된 근거로만 원질문에 답하세요. 사실에는 [근거 ID]를 붙이고 "
        "실제 사용한 ID를 evidence_ids에 넣으세요. "
        "상품번호별 가격·재고·기능을 섞지 마세요. "
        "다른 상품의 설정키나 지원 기능을 문의한 상품에 적용하지 마세요. "
        "원질문에 요청된 항목을 빠뜨리지 말고 근거가 없는 항목은 확인 불가로 밝혀 주세요. "
        "간결하게 답하며 자료에 없는 가격·도착일·입고일·버튼 조합을 만들지 마세요."
    ),
    (
        "human",
        "질문: {question}\n"
        "인용 가능한 ID: {allowed_ids}\n"
        "근거:\n{context}"
    ),
])

answer_chain = answer_prompt | llm.with_structured_output(GroundedAnswer)
```

> 원문의 긴 시스템 프롬프트는 핵심 규칙이 유지되도록 축약 표시.

## 6.2 `generate` 노드

```python
def generate(state):
    # 근거가 없으면 LLM을 호출하지 않음
    if not state["documents"]:
        return {
            "draft": "제공 자료에서 답변 근거를 찾지 못했습니다.",
            "evidence_ids": [],
        }

    # 실제 제공 문서만 인용 가능
    allowed_ids = [
        evidence_id(doc)
        for doc in state["documents"]
    ]

    answer = answer_chain.invoke({
        "question": state["question"],
        "allowed_ids": allowed_ids,
        "context": (
            format_documents(state["documents"])
            + "\n조회 안내: "
            + state.get("product_notice", "")
        ),
    })

    return {
        "draft": answer.answer,
        "evidence_ids": answer.evidence_ids,
    }
```

---

# 7. LangGraph 연결

다섯 노드는 조건 분기 없이 순차 실행. 검색 방식의 차이는 `expand_queries` 내부에서 처리.

```python
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

display(Image(fusion_app.get_graph().draw_mermaid_png()))
```

### 그래프 구조

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

---

# 8. 전체 실행 테스트

복합 질문을 넣어 자동으로 질의 분해 → 검색 → RRF → 근거 선택 → 답변까지 수행.

```python
question = (
    "KB-102를 Windows 노트북과 iPad에 번갈아 쓰려고 합니다. "
    "두 기기를 어떻게 등록하고 전환하나요? "
    "iPad에서 일부 단축키가 다르게 동작하면 무엇을 확인해야 하나요?"
)

fusion_result = fusion_app.invoke(
    make_fusion_state(question)
)

print("Jev 선택:", fusion_result["query_mode"])
display(pd.DataFrame(fusion_result["queries"]))
display(pd.DataFrame(fusion_result["contributions"]))
display(pd.DataFrame(fusion_result["selection_log"]))
display(Markdown(fusion_result["draft"]))
```

### 결과 - 질의 구성

```text
Jev 선택: decomposition

1. KB-102를 Windows 노트북에 등록하는 방법은 무엇인가요?
2. KB-102를 iPad에 등록하는 방법은 무엇인가요?
3. Windows 노트북과 iPad에 등록된 KB-102를 번갈아 전환해 사용하는 방법은 무엇인가요?
4. iPad에서 KB-102의 일부 단축키가 Windows와 다르게 동작할 때 확인할 사항은 무엇인가요?
```

### 결과 - 최종 근거 선택

```text
guide:KB-102-shortcuts    → 선택
guide:KB-102-pairing      → 선택
guide:KB-103-channels     → 선택
faq:keyboard-shortcuts    → 선택
guide:KB-105-app          → 선택
```

> 질의별 `contributions` 전체 표는 행이 많아 생략. 각 하위 질문의 검색 순위에 따라 RRF 기여 점수가 누적되는 구조.

### 결과 - 답변

```text
KB-102는 Bluetooth 기기 3대를 Fn+1, Fn+2, Fn+3에 각각 등록할 수 있음.
예를 들어 Windows 노트북은 Fn+1, iPad는 Fn+2에 등록 가능.
등록할 채널 키를 3초간 눌러 페어링한 뒤, 채널 키를 짧게 눌러 기기 사이를 전환함.
[guide:KB-102-pairing]

Windows에서는 Fn+W, iPad에서는 Fn+M으로 OS 모드를 선택함.
iPad에서 일부 단축키가 다르면 OS 모드와 하드웨어 키보드 설정,
입력 언어 및 앱의 단축키 지원 여부를 확인함.
[guide:KB-102-shortcuts] [faq:keyboard-shortcuts]
```

---

# 9. 원질문 단일 검색과 Fusion 검색 비교

같은 `final_k` 범위에서 원질문 1회 검색과 자동 질의 구성 검색이 어떤 근거를 선택하는지 비교.

```python
single_result = make_fusion_state(question)
single_result["queries"] = [
    {
        "kind": "original",
        "query": question,
    }
]

single_result.update(search_many(single_result))
single_result.update(fuse(single_result))
single_result.update(select_context(single_result))

single_ids = {
    evidence_id(doc)
    for doc in single_result["documents"]
}

fusion_ids = {
    evidence_id(doc)
    for doc in fusion_result["documents"]
}

display(pd.DataFrame([
    {
        "ID": doc_id,
        "제목": document_by_id[doc_id].metadata["title"],
        "원질문 검색": doc_id in single_ids,
        "자동 선택 검색": doc_id in fusion_ids,
    }
    for doc_id in sorted(single_ids | fusion_ids)
]))

print(
    "검색 횟수:",
    len(single_result["search_log"]),
    "→",
    len(fusion_result["search_log"]),
)
```

### 결과

```text
                         원질문 검색   자동 선택 검색
faq:keyboard-shortcuts       True          True
guide:KB-102-pairing         True          True
guide:KB-102-shortcuts       True          True
guide:KB-103-channels        False         True
guide:KB-105-app             False         True

검색 횟수: 1 → 4
```

Fusion 검색은 검색 횟수를 늘리는 대신, 복합 질문을 여러 검색 관점으로 나눠 후보 근거를 더 넓게 확보하는 구조.
