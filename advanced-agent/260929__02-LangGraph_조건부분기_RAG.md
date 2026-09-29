# LangGraph 조건부 분기 RAG 그래프 핵심 정리

> **핵심 주제:** `State → Node → Router → Conditional Edge` 구조로 질문에 따라 검색 경로를 나누고, **BM25 + Dense + RRF** 검색 결과를 근거로 답변하는 LangGraph 구성

---

## 1. 전체 구조

이 실습은 **질문 분류 → 검색어 생성 → 하이브리드 검색 → 근거 기반 답변**을 하나의 그래프로 연결한다.

### 텍스트 도식

```text
START
  ↓
① classify_question
  │
  ├─ route = "search"
  │      ↓
  │   ② prepare_search
  │      ↓
  │   ③ retrieve
  │      │
  │      ├─ documents 있음 → "answer"
  │      │                      ↓
  │      │                 ④ generate
  │      │                      ↓
  │      │                     END
  │      │
  │      └─ documents 없음 → "empty"
  │                             ↓
  │                        ⑥ no_evidence
  │                             ↓
  │                            END
  │
  └─ route = "clarify"
         ↓
      ⑤ clarify
         ↓
        END
```

각 노드는 같은 **State**를 공유하며 필요한 필드만 읽고 갱신한다.

```text
Shared State
├─ question
├─ top_k
├─ search_query
├─ route
├─ route_probabilities
├─ documents
├─ context
├─ source_urls
└─ answer
```

---

# 2. State

## 개념

`State`는 그래프의 노드 사이에서 전달되는 **공유 데이터 구조**다.

- 노드는 필요한 State 값을 읽음
- 처리 결과 중 변경할 필드만 `dict`로 반환
- LangGraph가 반환값을 기존 State에 반영

## 핵심 문법

```python
from typing import TypedDict
from langchain_core.documents import Document

class MovieSearchState(TypedDict):
    question: str
    top_k: int
    search_query: str
    route: str
    route_probabilities: dict[str, float]
    documents: list[Document]
    context: str
    source_urls: list[str]
    answer: str
```

초기 State도 같은 구조로 만든다.

```python
initial_state: MovieSearchState = {
    "question": "해커가 자신이 사는 세계가 가상 현실임을 알게 되는 영화는 무엇인가요?",
    "top_k": 3,
    "search_query": "",
    "route": "",
    "route_probabilities": {},
    "documents": [],
    "context": "",
    "source_urls": [],
    "answer": "",
}
```

### 주요 필드

| 필드 | 역할 |
|---|---|
| `question` | 사용자의 원 질문 |
| `search_query` | 검색용으로 변환한 영어 검색어 |
| `top_k` | 최종 답변에 사용할 최대 청크 수 |
| `route` | 다음 실행 경로 |
| `route_probabilities` | 분류 결과의 선택지별 확률 |
| `documents` | 검색된 문서 청크 |
| `context` | LLM에 전달할 근거 문자열 |
| `source_urls` | 검색 문서의 원문 출처 |
| `answer` | 최종 답변 또는 안내 문구 |

---

# 3. Node

## 개념

Node는 실제 작업을 수행하는 함수다.

기본 형태는 다음과 같다.

```python
def node_name(state: MovieSearchState):
    value = ...
    return {"state_field": value}
```

즉, **전체 State를 다시 반환하지 않고 갱신할 값만 반환**한다.

---

## 3-1. 질문 분류 노드 `classify_question`

### 역할

```text
question
  ↓
Jev 분류
  ↓
route + route_probabilities
```

질문에 검색 가능한 구체적 단서가 있는지 판단한다.

- `search`: 영화 제목·사건·줄거리·주제 등 검색 단서가 있음
- `clarify`: 검색 조건이 부족하거나 영화 검색과 관계없는 요청

### 분류 기준 정의

```python
from langchain_typesafe import Choice

route_question = Choice(
    instructions="영화 질문의 실행 경로를 고르세요.",
    criteria={
        "search": "구체적인 영화 제목·줄거리·사건·주제 단서가 있는 질문",
        "clarify": "검색할 구체적인 단서가 없는 질문",
    },
)
```

### Node

```python
def classify_question(state: MovieSearchState):
    decision = question_classifier.invoke({
        "state": state["question"],
        "questions": {"route": route_question},
    })

    selected = decision.choices["route"]

    return {
        "route": selected.choice,
        "route_probabilities": selected.probabilities,
    }
```

**핵심:** 이 노드는 다음 노드로 직접 이동시키지 않는다. 먼저 `route` 값을 **State에 저장**한다.

---

## 3-2. 검색어 생성 노드 `prepare_search`

원문이 영어이고 BM25가 단어 일치를 사용하므로 질문을 **영어 핵심어**로 변환한다.

### 구조화 출력 모델

```python
from pydantic import BaseModel, Field

class EnglishKeywords(BaseModel):
    keywords: list[str] = Field(
        description="중복 없는 영어 단어 4~8개"
    )
```

### Prompt + Structured Output

```python
from langchain_core.prompts import ChatPromptTemplate

lexical_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "영화 줄거리 질문을 영어 원문 검색용 핵심어 4~8개로 바꾸세요."
    ),
    ("human", "{question}"),
])

lexical_chain = (
    lexical_prompt
    | llm.with_structured_output(EnglishKeywords)
)
```

### Node

```python
def prepare_search(state: MovieSearchState):
    terms = lexical_chain.invoke({
        "question": state["question"]
    })

    return {
        "search_query": " ".join(terms.keywords)
    }
```

예시:

```text
원 질문
"해커가 자신이 사는 세계가 가상 현실임을 알게 되는 영화는?"

        ↓

search_query
"hacker discovers world virtual reality"
```

---

# 4. Hybrid Retrieval

실습에서는 **BM25 + Dense + RRF**를 사용한다.

```text
search_query
   ├─ BM25 ──┐
   │          │
   └─ Dense ──┤
              ↓
             RRF
              ↓
         상위 documents
```

| 검색 | 역할 |
|---|---|
| BM25 | 검색어와 단어가 일치하는 문서 탐색 |
| Dense | 질문 벡터와 의미적으로 가까운 문서 탐색 |
| RRF | 두 검색 결과의 순위를 결합 |

실습 설정:

```text
BM25 후보: 6개
Dense 후보: 6개
가중치: BM25 0.3 / Dense 0.7
RRF c: 60
중복 식별 키: chunk_id
```

---

## 4-1. BM25 토큰화

```python
import re

stop_words = {
    "a", "an", "the", "is", "are", "was", "were",
    "of", "to", "in", "on", "and", "or"
}


def tokenize(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [word for word in words if word not in stop_words]
```

---

## 4-2. BM25 + Dense 구성

```python
from langchain_community.retrievers import BM25Retriever

bm25 = BM25Retriever.from_documents(
    movie_documents,
    preprocess_func=tokenize,
    bm25_params={"k1": 1.5, "b": 0.75},
    k=6,
)

# Chroma 기반 Dense Retriever
dense = vector_store.as_retriever(
    search_kwargs={"k": 6}
)
```

---

## 4-3. RRF 결합

```python
from langchain_classic.retrievers import EnsembleRetriever

hybrid = EnsembleRetriever(
    retrievers=[bm25, dense],
    weights=[0.3, 0.7],
    c=60,
    id_key="chunk_id",
)
```

RRF는 각 검색기의 순위 기여를 합친다.

```text
score ≈ weight / (c + rank)
```

`id_key="chunk_id"`를 지정하면 같은 청크가 BM25와 Dense 양쪽에서 검색되어도 하나의 문서로 합쳐서 계산할 수 있다.

---

# 5. 검색 Node `retrieve`

## Context 생성

LLM이 인용할 수 있도록 **청크 ID + 본문** 형태로 합친다.

```python
def format_context(documents):
    parts = []

    for document in documents:
        parts.append(
            f"[{document.metadata['chunk_id']}] "
            f"{document.page_content}"
        )

    return "\n\n".join(parts)
```

## 검색 Node

```python
def retrieve(state: MovieSearchState):
    candidates = hybrid.invoke(
        state["search_query"]
    )

    found = candidates[:state["top_k"]]

    return {
        "documents": found,
        "context": format_context(found),
        "source_urls": [
            doc.metadata["source"]
            for doc in found
        ],
    }
```

### 흐름

```text
search_query
    ↓
hybrid.invoke()
    ↓
BM25 + Dense + RRF
    ↓
상위 top_k개
    ↓
documents / context / source_urls
```

---

# 6. 답변 생성 Node `generate`

검색된 문서만 근거로 답하고, 사용한 **청크 ID를 인용**하도록 한다.

```python
answer_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "제공된 영화 원문만 근거로 한국어로 짧게 답하세요. "
        "사용한 청크 ID 전체를 대괄호로 인용하세요. "
        "근거가 부족하면 확인할 수 없다고 말하세요."
    ),
    (
        "human",
        "질문: {question}\n\n근거:\n{context}"
    ),
])

answer_chain = answer_prompt | llm
```

```python
def generate(state: MovieSearchState):
    response = answer_chain.invoke({
        "question": state["question"],
        "context": state["context"],
    })

    return {"answer": response.text}
```

**중요:** 검색 결과가 존재한다고 해서 질문에 답할 충분한 근거가 있다는 뜻은 아니다. 따라서 생성 단계에서도 **검색 원문 안에 실제 근거가 있는지 확인**하도록 Prompt를 구성한다.

---

# 7. 안내 Node

검색을 수행하지 않아도 되는 경우에는 고정 문구를 반환한다.

## `clarify`

검색 단서가 부족할 때 실행한다.

```python
def clarify(state: MovieSearchState):
    return {
        "answer": (
            "찾는 영화의 제목이나 기억나는 장면, "
            "사건, 주제를 구체적으로 적어 주세요."
        )
    }
```

## `no_evidence`

검색된 문서 자체가 없을 때 실행한다.

```python
def no_evidence(state: MovieSearchState):
    return {
        "answer": (
            "답변에 전달할 검색 자료가 없습니다. "
            "자료 범위와 검색 설정을 확인해 주세요."
        )
    }
```

---

# 8. Router와 조건부 Edge

## 핵심 개념

**Node와 Router는 역할이 다르다.**

```text
Node
→ State를 읽음
→ 작업 수행
→ State 갱신값 반환

Router
→ State를 읽음
→ 다음 경로 이름 반환
```

라우터는 이 실습에서 모델을 다시 호출하지 않는다.

---

## 8-1. 질문 분류 결과에 따른 Router

```python
def choose_route(state: MovieSearchState):
    return state["route"]
```

```text
route = "search"  → prepare_search
route = "clarify" → clarify
```

---

## 8-2. 검색 결과 유무에 따른 Router

```python
def route_evidence(state: MovieSearchState):
    if state["documents"]:
        return "answer"

    return "empty"
```

```text
documents 있음 → "answer" → generate
documents 없음 → "empty"  → no_evidence
```

---

# 9. `add_conditional_edges()`

조건부 분기의 핵심 문법이다.

```python
builder.add_conditional_edges(
    "출발_노드",
    routing_function,
    {
        "라우터_반환값1": "이동할_노드1",
        "라우터_반환값2": "이동할_노드2",
    },
)
```

### 예시 1: 질문 분류

```python
builder.add_conditional_edges(
    "classify_question",
    choose_route,
    {
        "search": "prepare_search",
        "clarify": "clarify",
    },
)
```

### 예시 2: 검색 결과 확인

```python
builder.add_conditional_edges(
    "retrieve",
    route_evidence,
    {
        "answer": "generate",
        "empty": "no_evidence",
    },
)
```

### 중요한 문법 포인트

```text
라우터 반환값 ≠ 반드시 Node 이름
```

예를 들어

```python
return "answer"
```

를 반환하더라도 매핑이

```python
{"answer": "generate"}
```

이면 실제 실행되는 노드는 `generate`다.

---

# 10. 전체 그래프 조립

```python
from langgraph.graph import START, END, StateGraph

builder = StateGraph(MovieSearchState)

# Node 등록
builder.add_node("classify_question", classify_question)
builder.add_node("prepare_search", prepare_search)
builder.add_node("retrieve", retrieve)
builder.add_node("generate", generate)
builder.add_node("clarify", clarify)
builder.add_node("no_evidence", no_evidence)

# 시작
builder.add_edge(START, "classify_question")

# 조건 분기 A
builder.add_conditional_edges(
    "classify_question",
    choose_route,
    {
        "search": "prepare_search",
        "clarify": "clarify",
    },
)

# 검색
builder.add_edge("prepare_search", "retrieve")

# 조건 분기 B
builder.add_conditional_edges(
    "retrieve",
    route_evidence,
    {
        "answer": "generate",
        "empty": "no_evidence",
    },
)

# 종료
builder.add_edge("generate", END)
builder.add_edge("clarify", END)
builder.add_edge("no_evidence", END)

movie_graph = builder.compile()
```

### 그래프 구조

```text
START
  ↓
classify_question
  ├─ search ──→ prepare_search
  │                ↓
  │             retrieve
  │              ├─ answer → generate ──────→ END
  │              └─ empty  → no_evidence ───→ END
  │
  └─ clarify ─→ clarify ─────────────────────→ END
```

> 조건부 분기 출발 노드에 별도의 고정 Edge까지 연결하면 **선택하지 않은 작업도 실행될 수 있으므로 주의**한다.

---

# 11. 실행

컴파일된 그래프는 `invoke()`로 실행한다.

```python
movie_result = movie_graph.invoke(initial_state)
```

결과는 최종 State 형태로 반환된다.

```python
print(movie_result["route"])
print(movie_result["search_query"])
print(movie_result["documents"])
print(movie_result["answer"])
```

---

## 구체적인 질문

```text
질문
↓
classify_question
↓ search
prepare_search
↓
retrieve
↓ answer
generate
↓
END
```

실습 결과에서는 `The Matrix` 관련 청크가 검색된다.

---

## 모호한 질문

```python
clarify_input = {
    **initial_state,
    "question": "그 영화 좀 알려줘",
}

result = movie_graph.invoke(clarify_input)
```

실행 흐름:

```text
질문
↓
classify_question
↓ clarify
clarify
↓
END
```

검색·임베딩·답변 생성 단계를 수행하지 않는다.

---

# 12. 기존 벡터를 Chroma에 넣는 문법

실습에서는 문서 임베딩을 다시 생성하지 않고 **배포된 벡터를 재사용**한다.

```python
import chromadb

chroma_client = chromadb.Client()

collection = chroma_client.get_or_create_collection(
    "day50_lesson02_movies",
    metadata={"hnsw:space": "cosine"},
    embedding_function=None,
)

collection.upsert(
    ids=chunk_ids,
    embeddings=vectors.tolist(),
    documents=[doc.page_content for doc in movie_documents],
    metadatas=[doc.metadata for doc in movie_documents],
)
```

`upsert`:

```text
같은 ID 존재 → 갱신
같은 ID 없음 → 추가
```

이후 Chroma를 LangChain VectorStore로 연결한다.

```python
from langchain_chroma import Chroma

vector_store = Chroma(
    client=chroma_client,
    collection_name="day50_lesson02_movies",
    embedding_function=embedding_model,
)
```

이 구조에서는 문서 벡터를 재사용하고, **Dense 검색 시 질문만 임베딩**한다.

---

# 13. 핵심 문법만 모아보기

## State

```python
class State(TypedDict):
    value: str
```

## Node

```python
def node(state: State):
    return {"value": new_value}
```

## 일반 Edge

```python
builder.add_edge("node_a", "node_b")
```

## Router

```python
def router(state: State):
    return "path_a"
```

## 조건부 Edge

```python
builder.add_conditional_edges(
    "node_a",
    router,
    {
        "path_a": "node_b",
        "path_b": "node_c",
    },
)
```

## 그래프 생성

```python
builder = StateGraph(State)
builder.add_node("node_a", node_a)
builder.add_edge(START, "node_a")
graph = builder.compile()
```

## 실행

```python
result = graph.invoke(initial_state)
```

---

# 14. 핵심 정리

```text
State
= 노드 사이에서 공유하는 데이터

Node
= 실제 작업을 수행하고 State의 일부를 갱신

Router
= State를 읽고 다음 경로 이름을 반환

add_edge
= 항상 같은 다음 노드로 이동

add_conditional_edges
= Router 결과에 따라 다음 노드를 선택

Hybrid Retrieval
= BM25 + Dense 결과를 RRF로 결합

RAG
= 검색된 원문을 context로 만들고 LLM 답변의 근거로 사용
```

### 이번 그래프의 핵심 한 줄

```text
질문을 먼저 분류하고 → 필요한 경우에만 검색하며 →
검색 결과 유무에 따라 답변 생성 또는 안내 노드로 분기한다.
```

---

## 참고 링크

- LangGraph Graph API: https://docs.langchain.com/oss/python/langgraph/graph-api
- LangChain Chroma: https://docs.langchain.com/oss/python/integrations/vectorstores/chroma
- EnsembleRetriever: https://reference.langchain.com/python/langchain-classic/retrievers/ensemble/EnsembleRetriever/
