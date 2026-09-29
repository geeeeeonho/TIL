# LangGraph 도구 선택 · 검색 라우팅 핵심 정리

> 질문에 따라 **Hybrid 검색 / Graph 검색 / 두 검색 결합** 중 필요한 경로만 실행하는 LangGraph 구조.

---

## 1. 전체 구조

```text
사용자 질문
    ↓
① classify
   └─ Jev가 필요한 검색 경로 판단
      ├─ hybrid ───────────────→ ③ search_hybrid ──┐
      ├─ graph ────────────────→ ④ search_graph ───┤
      └─ combined → ② split_query → ③ search_hybrid
                                      ↓
                                  ④ search_graph
                                      ↓
                               ⑤ collect
                                      ↓
                                ⑥ answer
                                      ↓
                                     END
```

- **실선**: 항상 실행되는 고정 연결
- **조건부 연결**: State의 값에 따라 다음 노드 선택
- 같은 노드를 경로마다 새로 만드는 것이 아니라 **공통 노드를 재사용**함.

### 검색 경로 기준

| 경로 | 필요한 근거 | 실행 도구 |
|---|---|---|
| `hybrid` | 사건, 상황, 줄거리 원문 | 전문 검색 + 벡터 검색 |
| `graph` | 출연 관계, 공유 배우, 개봉연도 등 | Neo4j 관계·속성 조회 |
| `combined` | 줄거리 + 그래프 조건 모두 | 질문 분리 → Hybrid → Graph |

> 영화 제목이 포함됐다는 이유만으로 `graph`를 선택하지 않음. **질문에 필요한 근거 종류**를 기준으로 경로를 선택함.

---

## 2. State: 노드 사이의 공유 데이터

```python
from typing import TypedDict

class RoutingState(TypedDict):
    question: str
    route: str

    semantic_query: str
    graph_request: str

    documents: list[Document]
    graph_rows: list[dict]
    cypher: str

    source_ids: list[str]
    evidence: list[dict]

    answer: str
    evidence_ids: list[str]
```

### 역할별 구분

```text
입력
├─ question
└─ route

검색 입력
├─ semantic_query   → Hybrid 검색용
└─ graph_request    → Graph 검색용

검색 결과
├─ documents        → Hybrid 결과
├─ graph_rows       → Neo4j 조회 결과
└─ cypher           → 생성된 Cypher 확인용

답변 근거
├─ source_ids
└─ evidence

최종 출력
├─ answer
└─ evidence_ids
```

노드는 State 전체를 다시 반환하지 않고 **변경할 필드만 반환**함.

```python
def node(state: RoutingState):
    ...
    return {"route": result}
```

반환하지 않은 State 필드는 기존 값이 유지됨.

### 초기 State

```python
initial_state: RoutingState = {
    "question": "",
    "route": "",
    "semantic_query": "",
    "graph_request": "",
    "documents": [],
    "graph_rows": [],
    "cypher": "",
    "source_ids": [],
    "evidence": [],
    "answer": "",
    "evidence_ids": [],
}
```

새 질문은 이전 결과를 재사용하지 않고 초기 State에서 시작함.

```python
input_state = {
    **initial_state,
    "question": new_question,
}
```

---

# 3. 검색 도구 준비

## 3-1. Hybrid 검색

교안의 Hybrid 검색은 다음 두 검색 결과를 합침.

```text
질문
 ├─ 전문 검색 Full-text
 │    └─ 한글 질문이면 영어 핵심어로 변환
 │
 └─ Dense Vector 검색
      └─ 질문 임베딩 → 유사 청크 검색

          ↓
       RRF 결합
          ↓
   ensemble_retriever
```

### EnsembleRetriever

```python
ensemble_retriever = EnsembleRetriever(
    retrievers=[fulltext_retriever, dense_retriever],
    weights=[0.4, 0.6],
    c=60,
    id_key="source_id",
)
```

핵심:

- Full-text와 Dense 결과를 **RRF**로 결합
- `weights=[0.4, 0.6]`: 전문 검색 40%, Dense 60%
- `id_key="source_id"`: 같은 원문 결과를 하나의 문서로 판단

### 질문 언어 분류

전문 검색은 영어 원문을 대상으로 하므로 한글 질문은 영어 핵심어로 변환함.

```python
language_classifier = TypeSafeClassifier(...)

decision = language_classifier.invoke({
    "state": query,
    "questions": {"language": language_question},
})

language = decision.choices["language"].choice
```

```text
질문
 ↓
Jev 언어 판단
 ├─ en → 질문 그대로 전문 검색
 └─ ko → LLM으로 영어 핵심어 추출
             ↓
        "word1" OR "word2" ...
```

> **언어 판단 Choice**와 뒤에서 사용하는 **검색 경로 판단 Choice**는 서로 다른 분류 작업임.

---

# 4. Node 구성

## 4-1. `classify`: 필요한 검색 도구 선택

```text
읽기: question
쓰기: route, semantic_query, graph_request
```

Jev `TypeSafeClassifier`로 세 경로 중 하나를 선택함.

```python
route_classifier = TypeSafeClassifier(
    model=os.getenv("TYPESAFE_MODEL", "jev-1.13.0")
)

route_question = Choice(
    instructions="영화 질문에 필요한 검색 경로를 선택하세요.",
    criteria={
        "hybrid": "줄거리·사건·분위기 검색",
        "graph": "관계·속성 조회",
        "combined": "두 조건을 모두 만족해야 하는 질문",
    },
)
```

### 분류 호출 문법

```python
decision = route_classifier.invoke({
    "state": question,
    "questions": {"route": route_question},
})

route = decision.choices["route"].choice
```

### Node

```python
def classify(state: RoutingState):
    question = state["question"].strip()

    decision = route_classifier.invoke({
        "state": question,
        "questions": {"route": route_question},
    })

    return {
        "route": decision.choices["route"].choice,
        "semantic_query": question,
        "graph_request": question,
    }
```

처음에는 두 검색 입력 모두 원 질문으로 초기화함.

---

## 4-2. `split_query`: 복합 질문 분리

`combined` 경로에서만 실행함.

```text
원 질문
 ├─ semantic_query → 줄거리·사건·상황
 └─ graph_request  → 관계·속성·숫자·범위 조건
```

### 구조화 출력

```python
class SearchQueries(BaseModel):
    semantic_query: str
    graph_request: str
```

```python
query_split_chain = (
    query_split_prompt
    | llm.with_structured_output(SearchQueries)
)
```

### Node

```python
def split_query(state: RoutingState):
    queries = query_split_chain.invoke({
        "question": state["question"]
    })

    return {
        "semantic_query": queries.semantic_query,
        "graph_request": queries.graph_request,
    }
```

중요:

- 숫자와 범위 조건 유지
- `이상 / 초과 / 이전 / 이후 / 제외` 등을 임의로 변경하지 않음
- 줄거리 조건은 Graph 검색에 섞지 않음

### 예시

```text
원 질문
"Sleepless in Seattle과 배우를 최소 2명 공유하고
1993년 이후 개봉한 영화 중 경쟁하는 서점 주인들이
익명 이메일로 사랑하게 되는 작품"

↓

semantic_query
"서로 경쟁하는 서점 주인들이 익명 이메일로 사랑하게 되는 이야기"

graph_request
"Sleepless in Seattle과 배우를 최소 2명 공유하고
1993년 이후 개봉한 다른 영화를 조회"
```

---

## 4-3. `search_hybrid`: 전문 + 벡터 검색

```text
읽기: semantic_query
쓰기: documents
```

```python
def search_hybrid(state: RoutingState):
    docs = ensemble_retriever.invoke(
        state["semantic_query"]
    )

    return {"documents": docs}
```

- `hybrid`: 원 질문이 `semantic_query`
- `combined`: `split_query`가 분리한 줄거리 질문이 `semantic_query`

---

## 4-4. `search_graph`: Neo4j 관계 검색

```text
읽기: graph_request, route
쓰기: graph_rows, cypher
```

교안에서는 `GraphCypherQAChain`으로 자연어 질문을 Cypher로 변환함.

```python
graph_chain = GraphCypherQAChain.from_llm(
    llm=llm,
    graph=graph,
    cypher_prompt=cypher_prompt,
    return_direct=True,
    return_intermediate_steps=True,
    top_k=100,
    allow_dangerous_requests=True,
)
```

### 주요 옵션

| 옵션 | 역할 |
|---|---|
| `return_direct=True` | DB 조회 결과를 직접 반환 |
| `return_intermediate_steps=True` | 생성한 Cypher까지 확인 |
| `top_k=100` | 최대 조회 결과 수 |
| `allow_dangerous_requests=True` | 생성 Cypher 실행 동의 |

> `allow_dangerous_requests=True`는 DB 쓰기 권한을 제한하는 보안 설정이 아님. 실제 DB 권한은 별도로 제한해야 함.

### Node

```python
def search_graph(state: RoutingState):
    result = graph_chain.invoke({
        "query": state["graph_request"],
        "search_mode": state["route"],
    })

    return {
        "graph_rows": result["result"],
        "cypher": result["intermediate_steps"][0]["query"],
    }
```

생성 Cypher를 State에 저장하는 이유:

```text
원 질문 조건
    ↓ 비교
생성된 Cypher
```

숫자·범위·제외 조건이 빠지지 않았는지 확인 가능함.

---

## 4-5. `collect`: 검색 결과를 답변 근거로 통합

```text
읽기: route, documents, graph_rows
쓰기: source_ids, evidence
```

경로별 동작이 다름.

```text
hybrid
→ Hybrid 상위 문서 사용

graph
→ Graph의 facts + 관계 근거 사용

combined
→ Hybrid 순위 ∩ Graph 조건 통과 문서
→ Graph 후보 중 Hybrid에 없던 문서는 뒤에 보완
→ 최대 3개 원문 사용
```

핵심 구조:

```python
def collect(state: RoutingState):
    if state["route"] == "graph":
        return {
            "source_ids": [],
            "evidence": collect_evidence(state["graph_rows"]),
        }

    source_ids = [
        doc.metadata["source_id"]
        for doc in state["documents"]
    ]

    if state["route"] == "combined":
        allowed = {
            row["source_id"]
            for row in state["graph_rows"]
        }

        source_ids = [
            source_id
            for source_id in source_ids
            if source_id in allowed
        ]

    top_ids = source_ids[:3]
    ...
```

### Combined의 핵심

```text
Hybrid 검색 결과
[영화 A, 영화 B, 영화 C, 영화 D]

Graph 조건 통과
{영화 B, 영화 D, 영화 E}

          ↓ 교집합 + 보완

최종 후보
[영화 B, 영화 D, 영화 E]
```

> Graph 조건을 통과했다는 것은 **줄거리까지 일치한다는 의미가 아님**. 최종 답변에서는 원문 근거를 다시 확인해야 함.

---

## 4-6. `answer`: 근거 기반 최종 답변

```text
읽기: question, evidence
쓰기: answer, evidence_ids
```

### 구조화 출력

```python
class SearchAnswer(BaseModel):
    answer: str
    evidence_ids: list[str]
```

```python
search_answer_chain = (
    search_answer_prompt
    | llm.with_structured_output(SearchAnswer, strict=True)
)
```

### Node

```python
def answer(state: RoutingState):
    result = search_answer_chain.invoke({
        "question": state["question"],
        "context": json.dumps(
            state["evidence"],
            ensure_ascii=False,
        ),
    })

    return {
        "answer": result.answer,
        "evidence_ids": result.evidence_ids,
    }
```

원 질문과 `evidence`만 전달해 **검색 근거 밖 내용을 생성하지 않도록 제한**함.

---

# 5. Router와 Conditional Edge

## 5-1. Router는 State를 변경하지 않음

Router는 이미 State에 저장된 값을 읽고 **다음 경로 이름만 반환**함.

```python
def route_search(state: RoutingState):
    return state["route"]
```

```text
classify에서 Jev 호출
        ↓
State.route에 결과 저장
        ↓
route_search는 저장된 route만 읽음
```

즉, Router에서 Jev를 다시 호출하지 않음.

---

## 5-2. Hybrid 검색 이후 두 번째 분기

```python
def after_hybrid(state: RoutingState):
    if state["route"] == "combined":
        return "graph"
    return "collect"
```

```text
search_hybrid
     ↓
route == combined ?
 ├─ Yes → search_graph
 └─ No  → collect
```

`combined`만 Graph 검색을 추가 실행함.

---

# 6. StateGraph 조립

## 6-1. 노드 등록

```python
from langgraph.graph import START, END, StateGraph

builder = StateGraph(RoutingState)

builder.add_node("classify", classify)
builder.add_node("split_query", split_query)
builder.add_node("search_hybrid", search_hybrid)
builder.add_node("search_graph", search_graph)
builder.add_node("collect", collect)
builder.add_node("answer", answer)
```

형식:

```python
builder.add_node("노드 이름", 실행 함수)
```

---

## 6-2. 고정 Edge

```python
builder.add_edge(START, "classify")
builder.add_edge("split_query", "search_hybrid")
builder.add_edge("search_graph", "collect")
builder.add_edge("collect", "answer")
builder.add_edge("answer", END)
```

형식:

```python
builder.add_edge("현재 노드", "다음 노드")
```

---

## 6-3. Conditional Edge

### 첫 번째 분기

```python
builder.add_conditional_edges(
    "classify",
    route_search,
    {
        "hybrid": "search_hybrid",
        "graph": "search_graph",
        "combined": "split_query",
    },
)
```

```text
route_search() 반환값     실제 이동 노드
------------------------------------------------
hybrid                 → search_hybrid
graph                  → search_graph
combined               → split_query
```

### 두 번째 분기

```python
builder.add_conditional_edges(
    "search_hybrid",
    after_hybrid,
    {
        "graph": "search_graph",
        "collect": "collect",
    },
)
```

형식:

```python
builder.add_conditional_edges(
    "분기 시작 노드",
    라우팅_함수,
    {
        "라우터 반환값": "실제 다음 노드",
    },
)
```

> 조건부 분기 위치에 고정 `add_edge()`까지 같이 연결하면 원하지 않는 노드가 함께 실행될 수 있음.

---

## 6-4. Compile

```python
routing_graph = builder.compile()
```

```text
StateGraph 설계도(builder)
        ↓ compile()
실행 가능한 그래프(routing_graph)
```

---

# 7. 최종 그래프를 텍스트로 표현

교안의 그래프 이미지를 텍스트로 바꾸면 다음 구조임.

```text
                         ┌────────────── hybrid ──────────────┐
                         │                                    ↓
START → ① classify ── A ┼────────────→ ③ search_hybrid ── B ─┼─→ ⑤ collect
                         │                                    │
                         │                                    └─ graph → ④ search_graph
                         │
                         ├─ graph ───────────────────────────────→ ④ search_graph
                         │
                         └─ combined → ② split_query
                                            ↓
                                     ③ search_hybrid
                                            ↓
                                     ④ search_graph
                                            ↓
                                      ⑤ collect
                                            ↓
                                       ⑥ answer
                                            ↓
                                           END
```

더 단순화하면:

```text
hybrid
START → classify → search_hybrid → collect → answer → END

graph
START → classify → search_graph → collect → answer → END

combined
START → classify → split_query
      → search_hybrid → search_graph
      → collect → answer → END
```

---

# 8. 실행

```python
new_result = routing_graph.invoke({
    **initial_state,
    "question": new_question,
})
```

실행 후 최종 State에 각 노드 결과가 누적되어 있음.

```python
new_result["route"]
new_result["semantic_query"]
new_result["graph_request"]
new_result["documents"]
new_result["cypher"]
new_result["source_ids"]
new_result["answer"]
new_result["evidence_ids"]
```

---

# 9. 교안 실행 예시

예제 질문은 다음 조건을 동시에 요구함.

```text
1. Sleepless in Seattle과 배우 최소 2명 공유
2. 1993년 이후 개봉
3. 경쟁하는 서점 주인
4. 익명 이메일로 사랑하게 되는 줄거리
```

따라서 분류 결과:

```text
route = combined
```

질문 분리 결과:

```text
semantic_query
→ 경쟁하는 서점 주인들이 익명 이메일로 사랑하게 되는 영화

graph_request
→ Sleepless in Seattle과 배우를 최소 2명 공유하고
  1993년 이후 개봉한 다른 영화 조회
```

실행 구조:

```text
Hybrid 검색
→ 줄거리 후보 탐색

Graph 검색
→ 배우 공유 수 + 개봉연도 조건 검사

collect
→ 두 조건을 모두 만족하는 근거 통합

answer
→ 근거 ID를 인용한 답변 생성
```

교안 실행에서는 `You've Got Mail`이 후보로 선택되고, `Meg Ryan`, `Tom Hanks`의 출연 관계가 Graph 근거로 연결됨.

---

# 10. 결과 검증 포인트

## 경로가 잘못 선택된 경우

```text
확인 → classify의 Choice 기준
```

## Combined인데 조건이 빠진 경우

```text
확인 순서
split_query
    ↓
graph_request
    ↓
생성 Cypher
```

## 검색 결과는 맞는데 답변이 근거 밖으로 나간 경우

```text
확인 → evidence + answer 프롬프트
```

## Graph 경로에서 `documents`가 빈 이유

Graph 경로에는 `search_hybrid`가 연결되지 않음.

```text
classify
   ↓ graph
search_graph
   ↓
collect
```

따라서 `documents`는 초기값 `[]` 그대로 유지됨.

## Combined에서 Hybrid 뒤 바로 답하면 안 되는 이유

Hybrid 검색은 줄거리 조건만 확인함.

```text
Hybrid만 사용
→ "익명 이메일 / 서점 경쟁"은 확인 가능
→ "배우 2명 공유 / 1993년 이후"는 확인 불가
```

그래서 `combined`에서는 반드시 Graph 검색까지 실행해야 함.

---

# 11. 핵심 문법만 모아보기

```python
# 1. State
class RoutingState(TypedDict):
    question: str
    route: str
    ...


# 2. Node

def node(state: RoutingState):
    value = state["question"]
    ...
    return {"field": result}


# 3. Router

def router(state: RoutingState):
    return state["route"]


# 4. Graph 생성
builder = StateGraph(RoutingState)


# 5. Node 등록
builder.add_node("classify", classify)


# 6. 고정 Edge
builder.add_edge(START, "classify")


# 7. 조건부 Edge
builder.add_conditional_edges(
    "classify",
    route_search,
    {
        "hybrid": "search_hybrid",
        "graph": "search_graph",
        "combined": "split_query",
    },
)


# 8. Compile
routing_graph = builder.compile()


# 9. 실행
result = routing_graph.invoke({
    **initial_state,
    "question": new_question,
})
```

---

# 핵심 정리

```text
State
→ 각 노드가 공유할 데이터

Node
→ State를 읽고 필요한 필드만 갱신

Classifier
→ 질문에 필요한 검색 종류 판단

Router
→ 저장된 분류 결과를 읽어 다음 노드 이름 반환

Conditional Edge
→ Router 반환값을 실제 다음 노드와 연결

Hybrid Search
→ Full-text + Dense 검색을 RRF로 결합

Graph Search
→ 관계·속성 조건을 Cypher로 조회

Combined
→ 질문 분리 → Hybrid → Graph → 근거 통합

Collect
→ 검색 결과를 최종 답변용 evidence로 정리

Answer
→ evidence만 사용해 인용 답변 생성
```

**전체 핵심 흐름**

```text
질문
→ 필요한 검색 판단
→ 검색별 입력 분리
→ 필요한 검색 도구만 실행
→ 근거 통합
→ 근거 기반 답변
```
