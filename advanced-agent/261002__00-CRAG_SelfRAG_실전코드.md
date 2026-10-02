# CRAG + Self-RAG 통합 실전 코드

> **기준:** `과제_02_게임소개_숏폼_검수`를 메인으로 사용하고,  
> `과제_01_팝업전시_나들이_플래너`의 **웹 검색 보완 단계**를 추가한 통합 학습 예시.
>
> 두 과제를 따로 반복하지 않고 아래 핵심을 하나의 그래프에서 사용함.
>
> - **CRAG:** 검색 → 근거 평가 → 검색어 재작성 → 재검색 → 웹 보완
> - **Self-RAG:** 답변 생성 → 근거성·유용성 검토 → 수정 → 재검토

---

## 0. 전체 흐름

```text
START
  ↓
retrieve
  ↓
grade
  ├─ 충분 ─────────────────────────────→ generate
  │                                       ↓
  ├─ 부족 + 재검색 가능 → rewrite ─→ retrieve
  │
  └─ 재검색 한도 소진 → web_search → grade
                                          │
                         ┌────────────────┘
                         ↓
                      generate
                         ↓
                       review
                    ↙     ↓      ↘
                accept   revise   hold
                  ↓        │       ↓
                 END       └→ review

근거 없음 → abstain → END
```

핵심은 **검색 실패와 답변 실패를 별도로 교정**하는 것.

```text
검색 근거 문제 → grade / rewrite / web_search
생성 답변 문제 → review / revise
```

---

# 1. 기본 설정과 문서 준비

```python
import os
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal

import requests
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.retrievers import BM25Retriever

from kiwipiepy import Kiwi
from langgraph.graph import StateGraph, START, END


# 경로
material_dir = Path(".")
data_dir = material_dir / "data"

load_dotenv(find_dotenv(usecwd=True))
load_dotenv(material_dir.resolve().parent / ".env")

model_name = os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-luna")
llm = ChatOpenAI(model=model_name, use_responses_api=True)


def read_json(name):
    return json.loads(
        (data_dir / name).read_text(encoding="utf-8")
    )


def make_documents(records):
    return [
        Document(
            id=row["doc_id"],
            page_content=row["text"],
            metadata={
                "source_id": row["doc_id"],
                "title": row["title"],
                "url": row.get("url", ""),
                "source": row["source"],
                **row.get("metadata", {}),
            },
        )
        for row in records
    ]


# 게임 숏폼 과제 자료 사용
documents = make_documents(
    read_json("assignment02_docs.json")
)
cases = read_json("assignment02_cases.json")
```

### 결과

```text
documents
→ 검색에 사용할 공식 자료 Document 목록

cases
→ review_only / full / partial 등의 실행 사례
```

---

# 2. State 구성

검색 교정과 답변 검토에 필요한 상태를 하나로 관리함.

```python
class RAGState(TypedDict):
    # 원질문
    question: str

    # 검색
    search_query: str
    documents: list[Document]

    decision: Literal[
        "",
        "correct",
        "ambiguous",
        "incorrect",
    ]

    feedback: str
    missing_info: str

    search_history: list[dict]

    # 검색 재작성
    rewrite_count: int
    max_rewrites: int

    # 웹 보완
    web_searched: bool
    web_notice: str

    # 생성 답변
    draft: str
    evidence_ids: list[str]

    status: Literal[
        "running",
        "generated",
        "partial",
        "accepted",
        "insufficient",
        "review_failed",
    ]

    # 답변 검토
    support: Literal[
        "",
        "fully",
        "partially",
        "unsupported",
    ]

    useful: bool
    review_count: int
    max_reviews: int
    review_history: list[dict]


def make_initial_state(question):
    return {
        "question": question,
        "search_query": question,
        "documents": [],

        "decision": "",
        "feedback": "",
        "missing_info": "",
        "search_history": [],

        "rewrite_count": 0,
        "max_rewrites": 1,

        "web_searched": False,
        "web_notice": "",

        "draft": "",
        "evidence_ids": [],
        "status": "running",

        "support": "",
        "useful": False,
        "review_count": 0,
        "max_reviews": 2,
        "review_history": [],
    }
```

### 결과

```python
state = make_initial_state("게임 소개 대본을 작성해줘.")

print(state["rewrite_count"])
print(state["review_count"])
print(state["status"])
```

```text
0
0
running
```

검색 재작성과 답변 검토 횟수는 **서로 따로 관리**함.

---

# 3. 문서 ID와 검색 결과 병합

재검색할 때 기존에 찾은 근거를 버리지 않고 새 결과와 합침.

```python
def evidence_id(doc):
    chunk_id = doc.metadata.get("chunk_id")

    if chunk_id:
        return chunk_id.rsplit(":", 1)[0]

    return doc.metadata["source_id"]


def merge_documents(kept, found):
    merged = {
        evidence_id(doc): doc
        for doc in kept
    }

    merged.update({
        evidence_id(doc): doc
        for doc in found
    })

    return list(merged.values())


def format_documents(docs):
    return "\n\n".join(
        f"[{evidence_id(doc)}] {doc.metadata['title']}\n"
        f"출처: {doc.metadata['source']} "
        f"{doc.metadata.get('url', '')}\n"
        f"{doc.page_content}"
        for doc in docs
    )
```

### 결과

```text
기존 근거: [A, B]
새 검색:   [B, C]

merge_documents(...)
→ [A, B, C]
```

같은 ID의 문서는 중복되지 않음.

---

# 4. 내부 문서 검색

한국어 문서는 Kiwi로 핵심 토큰을 추출하고 BM25로 검색함.

```python
kiwi = Kiwi()


def kiwi_tokenize(text):
    return [
        token.form.lower()
        for token in kiwi.tokenize(
            text.replace("･", "·")
        )
        if token.tag.startswith("N")
        or token.tag in {"SL", "SN"}
    ]


retriever = BM25Retriever.from_documents(
    documents,
    preprocess_func=kiwi_tokenize,
    k=4,
)


def search_documents(search_query, top_k=4):
    return retriever.invoke(search_query)[:top_k]


def retrieve(state: RAGState):
    found = search_documents(
        state["search_query"]
    )

    return {
        "documents": merge_documents(
            state["documents"],
            found,
        )
    }
```

### 결과 구조

```text
search_query
   ↓
BM25 검색
   ↓
새 후보 문서
   ↓
기존 근거 + 새 후보
```

재검색 결과에 기존 문서가 나오지 않아도 이전 근거는 유지됨.

---

# 5. 검색 근거 평가

검색 결과에서 다음 두 가지를 구분함.

```text
관련 문서가 있는가?
질문의 모든 조건을 답하기에 충분한가?
```

```python
class RetrievalReview(BaseModel):
    feedback: str = Field(
        description="확인된 내용과 아직 부족한 정보"
    )

    useful_ids: list[str] = Field(
        description="실제로 도움이 되는 문서 ID"
    )

    sufficient: bool = Field(
        description="선택 문서만으로 질문 전체를 답할 수 있는지"
    )


grade_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
검색 문서를 평가하세요.

- 일부 요청에 도움이 되는 문서는 useful_ids에 남깁니다.
- 질문의 모든 필수 사실과 조건을 확인할 수 있을 때만
  sufficient=true입니다.
- 문서에 없는 사실은 외부 지식으로 채우지 않습니다.
- 답변은 작성하지 말고 근거만 평가합니다.
""",
    ),
    (
        "human",
        "원질문: {question}\n\n검색 문서:\n{context}",
    ),
])

grade_chain = (
    grade_prompt
    | llm.with_structured_output(
        RetrievalReview,
        strict=True,
    )
)


def grade_documents(question, docs):
    if not docs:
        return (
            [],
            "incorrect",
            "검색된 문서가 없습니다.",
        )

    review = grade_chain.invoke({
        "question": question,
        "context": format_documents(docs),
    })

    known_ids = {
        evidence_id(doc)
        for doc in docs
    }

    selected_ids = {
        value.strip("[] \t\r\n")
        for value in review.useful_ids
    }

    valid_selection = (
        selected_ids.issubset(known_ids)
    )

    kept = [
        doc
        for doc in docs
        if evidence_id(doc) in selected_ids
    ]

    if not kept:
        decision = "incorrect"

    elif review.sufficient and valid_selection:
        decision = "correct"

    else:
        decision = "ambiguous"

    feedback = review.feedback

    if not valid_selection:
        feedback = (
            "후보에 없는 문서 ID가 포함됨. "
            + feedback
        )

    return kept, decision, feedback
```

평가 결과를 State에 저장함.

```python
def grade(state: RAGState):
    candidates = state["documents"]

    selected_docs, decision, feedback = (
        grade_documents(
            state["question"],
            candidates,
        )
    )

    missing_info = (
        ""
        if decision == "correct"
        else feedback
    )

    entry = {
        "search_query": state["search_query"],
        "web_searched": state["web_searched"],
        "candidate_ids": [
            evidence_id(doc)
            for doc in candidates
        ],
        "kept_ids": [
            evidence_id(doc)
            for doc in selected_docs
        ],
        "decision": decision,
        "feedback": feedback,
    }

    return {
        "documents": selected_docs,
        "decision": decision,
        "feedback": feedback,
        "missing_info": missing_info,
        "search_history":
            state["search_history"] + [entry],
    }
```

### 결과

```text
correct
→ 필요한 근거가 충분함

ambiguous
→ 관련 근거는 있지만 일부 조건 부족

incorrect
→ 사용할 수 있는 근거가 없음
```

예:

```text
decision: ambiguous
feedback: PC 온라인 이용 조건을 확인할 근거가 부족함
```

---

# 6. 부족한 조건으로 검색어 재작성

원질문은 변경하지 않고 **검색어만 변경**함.

```python
search_language = "한국어"

rewrite_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
원질문의 대상은 유지하고,
현재 부족한 정보를 찾기 위한 짧은 검색어만 작성하세요.

이미 확인된 내용이나 출력 형식은 반복하지 않습니다.
""",
    ),
    (
        "human",
        """
원질문: {question}
현재 검색어: {search_query}
부족한 정보: {feedback}
언어: {search_language}
""",
    ),
])

rewrite_chain = rewrite_prompt | llm


def rewrite_query(
    question,
    search_query,
    feedback,
    search_language="한국어",
):
    response = rewrite_chain.invoke({
        "question": question,
        "search_query": search_query,
        "feedback": feedback,
        "search_language": search_language,
    })

    return response.text.strip()


def rewrite(state: RAGState):
    query = rewrite_query(
        state["question"],
        state["search_query"],
        state["feedback"],
        search_language,
    )

    return {
        "search_query": query,
        "rewrite_count":
            state["rewrite_count"] + 1,
    }
```

### 결과 구조

```text
원질문
"게임 소개와 PC 플레이 조건을 알려줘"
        ↓

첫 검색
"게임 소개와 PC 플레이 조건 ..."
        ↓
grade → 일부 조건 부족
        ↓

rewrite
"게임명 PC 온라인 계정 조건"
```

`question`은 그대로이고 `search_query`만 변경됨.

---

# 7. 내부 검색으로 부족하면 웹 검색 보완

이 단계는 **팝업·전시 플래너의 CRAG 구조에서 가져온 개념**.

실제 사용 시 신뢰할 수 있는 공식 도메인으로 제한하는 것이 좋음.

```python
def search_web(
    search_query,
    official_domains=None,
):
    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        return [], (
            "TAVILY_API_KEY 설정을 "
            "확인해 주세요."
        )

    payload = {
        "query": search_query,
        "search_depth": "basic",
        "max_results": 3,
        "include_answer": False,
    }

    if official_domains:
        payload["include_domains"] = (
            official_domains
        )

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization":
                    f"Bearer {api_key}"
            },
            json=payload,
            timeout=30,
        )

        response.raise_for_status()
        results = response.json()["results"]

    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
    ):
        return [], (
            "웹 검색 결과를 "
            "가져오지 못했습니다."
        )

    docs = [
        Document(
            page_content=item["content"],
            metadata={
                "source_id": item["url"],
                "url": item["url"],
                "title": item["title"],
                "source": item["url"],
                "collected_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
            },
        )
        for item in results
        if item.get("content", "").strip()
    ]

    return (
        docs,
        ""
        if docs
        else "사용 가능한 웹 결과가 없습니다.",
    )


def web_search(state: RAGState):
    found, notice = search_web(
        state["search_query"]
    )

    return {
        "documents": merge_documents(
            state["documents"],
            found,
        ),
        "web_searched": True,
        "web_notice": notice,
    }
```

### 결과 구조

```text
내부 재검색 후에도 부족
        ↓
web_search
        ↓
기존 근거 + 웹 근거
        ↓
grade에서 다시 평가
```

웹 검색이 실패해도 **기존 근거는 삭제하지 않음**.

---

# 8. 근거 기반 답변 생성

답변과 사용한 근거 ID를 구조화 출력으로 함께 받음.

```python
class GroundedAnswer(BaseModel):
    answer: str = Field(
        description=(
            "근거 기반 한국어 초안. "
            "사실 뒤에 [근거ID] 표시"
        )
    )

    evidence_ids: list[str] = Field(
        description=(
            "실제로 답변에서 사용한 "
            "근거 ID 목록"
        )
    )


generate_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
제공된 근거만 사용해 답변하세요.

- 사실 뒤에 [근거ID]를 표시합니다.
- evidence_ids에는 실제 사용한 ID만 넣습니다.
- 근거 없는 사실은 만들지 않습니다.
- 확인되지 않은 요청은 추측하지 않습니다.
- 미확인 사항은 추가 확인이 필요하다고 안내합니다.
- 수정 요청이면 이전 답변과 검토 의견을 반영합니다.
""",
    ),
    (
        "human",
        """
원질문:
{question}

근거:
{context}

이전 답변:
{draft}

검토 또는 미확인 사항:
{feedback}
""",
    ),
])

generate_chain = (
    generate_prompt
    | llm.with_structured_output(
        GroundedAnswer,
        strict=True,
    )
)


def generate_answer(
    question,
    docs,
    draft="",
    feedback="",
):
    return generate_chain.invoke({
        "question": question,
        "context": format_documents(docs),
        "draft": draft,
        "feedback": feedback,
    })


def generate(state: RAGState):
    answer = generate_answer(
        state["question"],
        state["documents"],
        feedback=state["missing_info"],
    )

    status = (
        "generated"
        if state["decision"] == "correct"
        else "partial"
    )

    return {
        "draft": answer.answer,
        "evidence_ids": answer.evidence_ids,
        "status": status,
    }
```

### 결과 구조

```text
draft:
"게임의 핵심 플레이는 ... [doc-01]"

evidence_ids:
["doc-01"]

status:
generated
```

근거 일부가 부족하면:

```text
status:
partial
```

---

# 9. 답변의 근거성과 유용성 검토

검색 근거가 충분해도 **생성 답변이 정확하다는 보장은 없음**.

따라서 답변 자체를 다시 검토함.

```python
class AnswerReview(BaseModel):
    feedback: str = Field(
        description="오류·누락·수정 방향"
    )

    support: Literal[
        "fully",
        "partially",
        "unsupported",
    ] = Field(
        description="답변의 근거성"
    )

    useful: bool = Field(
        description="사용자 요청 충족 여부"
    )


review_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
답변을 근거와 대조해 검토하세요.

support:
- fully: 모든 사실·조건·인용이 근거와 일치
- partially: 일부 오류 또는 필수 조건 누락
- unsupported: 핵심 오류 또는 잘못된 인용

useful:
- 사용자의 요청을 충족하는지 판단
- 미확인 내용의 한계와 확인 방법도 확인

외부 지식으로 오류를 보완하지 않습니다.
""",
    ),
    (
        "human",
        """
원질문:
{question}

근거:
{context}

검토할 답변:
{draft}

미확인 사항:
{missing_info}
""",
    ),
])

review_chain = (
    review_prompt
    | llm.with_structured_output(
        AnswerReview,
        strict=True,
    )
)


def review_answer(
    question,
    docs,
    draft,
    missing_info="",
):
    return review_chain.invoke({
        "question": question,
        "context": format_documents(docs),
        "draft": draft,
        "missing_info": missing_info,
    })
```

인용 ID도 코드에서 별도로 검사함.

```python
def review(state: RAGState):
    result = review_answer(
        state["question"],
        state["documents"],
        state["draft"],
        state["missing_info"],
    )

    known_ids = {
        evidence_id(doc)
        for doc in state["documents"]
    }

    valid_ids = (
        bool(state["evidence_ids"])
        and set(
            state["evidence_ids"]
        ).issubset(known_ids)
    )

    support = (
        result.support
        if valid_ids
        else "unsupported"
    )

    feedback = result.feedback

    if not valid_ids:
        feedback = (
            "인용 ID가 선택 근거와 "
            "일치하지 않습니다. "
            + feedback
        )

    entry = {
        "draft": state["draft"],
        "evidence_ids":
            list(state["evidence_ids"]),
        "support": support,
        "useful": result.useful,
        "feedback": feedback,
    }

    return {
        "support": support,
        "useful": result.useful,
        "feedback": feedback,
        "review_count":
            state["review_count"] + 1,
        "review_history":
            state["review_history"] + [entry],
    }
```

### 결과

```text
support = fully
useful = True
→ 통과 가능
```

또는:

```text
support = partially
useful = False
feedback = 필수 플레이 조건이 빠져 있음
→ revise 필요
```

근거 목록에 없는 ID를 인용하면 모델 판정과 관계없이:

```text
support = unsupported
```

---

# 10. 검토 의견을 이용해 답변 수정

검토 결과를 단순 기록하지 않고 **다음 생성 입력으로 다시 사용**함.

```python
def revise(state: RAGState):
    feedback = state["feedback"]

    if state["missing_info"]:
        feedback += (
            "\n미확인 사항: "
            + state["missing_info"]
        )

    answer = generate_answer(
        state["question"],
        state["documents"],
        draft=state["draft"],
        feedback=feedback,
    )

    return {
        "draft": answer.answer,
        "evidence_ids": answer.evidence_ids,
    }
```

### 결과 구조

```text
첫 초안
  ↓
review
  ↓
"필수 조건 누락"
  ↓
revise
  ↓
수정된 초안
  ↓
review
```

즉:

```text
review → feedback → revise → review
```

---

# 11. 종료 상태와 조건 분기

## 검색 평가 후 분기

```python
def route_after_grade(state: RAGState):
    # 충분하면 바로 생성
    if state["decision"] == "correct":
        return "generate"

    # 웹 검색까지 수행한 뒤에는
    # 남은 근거로 종료 판단
    if state["web_searched"]:
        return (
            "generate"
            if state["documents"]
            else "abstain"
        )

    # 내부 재검색 가능
    if (
        state["rewrite_count"]
        < state["max_rewrites"]
    ):
        return "rewrite"

    # 재검색 한도 소진
    return "web_search"
```

### 결과

```text
correct
→ generate

ambiguous + rewrite 여유
→ rewrite

ambiguous + rewrite 한도 소진
→ web_search

웹 검색 이후 근거 있음
→ generate

웹 검색 이후 근거 없음
→ abstain
```

---

## 답변 검토 후 분기

```python
def route_after_review(state: RAGState):
    # 마지막 검토에서도 통과 여부를 먼저 확인
    if (
        state["support"] == "fully"
        and state["useful"]
    ):
        return "accept"

    if (
        state["review_count"]
        >= state["max_reviews"]
    ):
        return "hold"

    return "revise"
```

### 결과

```text
fully + useful
→ accept

미통과 + 검토 횟수 남음
→ revise

미통과 + 검토 한도 도달
→ hold
```

---

## 종료 노드

```python
def accept(state: RAGState):
    return {
        "status": (
            "partial"
            if state["missing_info"]
            else "accepted"
        )
    }


def hold(state: RAGState):
    return {
        "status": "review_failed"
    }


def abstain(state: RAGState):
    return {
        "draft": (
            "제공 자료에서 답할 근거를 "
            "찾지 못했습니다. "
            + state["missing_info"]
            + "\n추가 공식 자료 확인이 필요합니다."
        ),
        "evidence_ids": [],
        "status": "insufficient",
    }
```

### 상태 구분

| 상태 | 의미 |
|---|---|
| `accepted` | 근거와 답변 모두 검토 통과 |
| `partial` | 확인 가능한 부분만 답변 |
| `insufficient` | 사용할 근거 자체가 없음 |
| `review_failed` | 근거는 있으나 답변 검토를 통과하지 못함 |

---

# 12. 전체 LangGraph 연결

```python
builder = StateGraph(RAGState)

# 검색 교정
builder.add_node("retrieve", retrieve)
builder.add_node("grade", grade)
builder.add_node("rewrite", rewrite)
builder.add_node("web_search", web_search)

# 생성
builder.add_node("generate", generate)
builder.add_node("abstain", abstain)

# 답변 검토
builder.add_node("review", review)
builder.add_node("revise", revise)
builder.add_node("accept", accept)
builder.add_node("hold", hold)


builder.add_edge(
    START,
    "retrieve",
)

builder.add_edge(
    "retrieve",
    "grade",
)


builder.add_conditional_edges(
    "grade",
    route_after_grade,
    {
        "generate": "generate",
        "rewrite": "rewrite",
        "web_search": "web_search",
        "abstain": "abstain",
    },
)

builder.add_edge(
    "rewrite",
    "retrieve",
)

builder.add_edge(
    "web_search",
    "grade",
)


builder.add_edge(
    "generate",
    "review",
)

builder.add_conditional_edges(
    "review",
    route_after_review,
    {
        "accept": "accept",
        "revise": "revise",
        "hold": "hold",
    },
)

builder.add_edge(
    "revise",
    "review",
)


builder.add_edge(
    "accept",
    END,
)

builder.add_edge(
    "hold",
    END,
)

builder.add_edge(
    "abstain",
    END,
)


self_rag_app = builder.compile()
```

### 결과 구조

```text
                    ┌──────── rewrite ────────┐
                    │                         │
START → retrieve → grade ───── correct ─────┐│
                    │                       ││
                    └→ web_search → grade ─┘│
                                            ↓
                                         generate
                                            ↓
                                          review
                                      ┌─────┼─────┐
                                      ↓     ↓     ↓
                                   accept revise hold
                                      ↓     │     ↓
                                     END ───┘    END

근거 없음 → abstain → END
```

---

# 13. 실제 실행

```python
case = cases["full"]

initial_state = make_initial_state(
    case["question"]
)

result = self_rag_app.invoke(
    initial_state,
    config={
        "recursion_limit": 30
    },
)
```

필요한 결과만 확인함.

```python
print("상태:", result["status"])
print("검색 재작성:", result["rewrite_count"])
print("웹 검색:", result["web_searched"])
print("답변 검토:", result["review_count"])

print("\n검색 판정:", result["decision"])
print("근거성:", result["support"])
print("유용성:", result["useful"])

print("\n미확인 사항:")
print(result["missing_info"] or "없음")

print("\n최종 답변:")
print(result["draft"])

print("\n사용 근거:")
print(result["evidence_ids"])
```

### 결과 형태

정상적으로 근거와 답변이 모두 통과한 경우:

```text
상태: accepted
검색 재작성: 0 또는 1
웹 검색: False 또는 True
답변 검토: 1 또는 2

검색 판정: correct
근거성: fully
유용성: True

미확인 사항:
없음

최종 답변:
...

사용 근거:
['문서ID', ...]
```

일부 정보만 확인된 경우:

```text
상태: partial
검색 판정: ambiguous
근거성: fully
유용성: True

미확인 사항:
추가 공식 자료가 필요한 조건 ...
```

검색 근거 자체가 없는 경우:

```text
상태: insufficient
답변 검토: 0
사용 근거: []
```

답변 수정 후에도 검토를 통과하지 못한 경우:

```text
상태: review_failed
답변 검토: 2
```

---

# 14. 핵심 정리

## CRAG 영역

```text
retrieve
→ grade
→ rewrite
→ retrieve
→ grade
→ web_search
→ grade
```

검색 결과의 **관련성·충분성**을 평가하고 부족하면 검색 자체를 보완함.

## Self-RAG 영역

```text
generate
→ review
→ revise
→ review
```

생성된 답변의 **근거성·유용성**을 평가하고 부족하면 답변을 수정함.

## 가장 중요한 구분

```text
decision
→ 검색 근거의 상태

support
→ 생성 답변의 근거성

useful
→ 생성 답변이 사용자 요구를 충족하는지

rewrite_count
→ 검색 수정 횟수

review_count
→ 답변 검토 횟수
```

따라서 최종 구조는 다음처럼 이해하면 됨.

```text
질문
 ↓
검색
 ↓
검색 평가 ── 부족 → 검색 교정
 ↓
근거 확보
 ↓
답변 생성
 ↓
답변 평가 ── 부족 → 답변 수정
 ↓
최종 답변
```

> **핵심:**  
> `CRAG`는 **검색 근거를 고치고**,  
> `Self-RAG`는 **생성 답변을 고친다.**
