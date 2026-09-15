# 검색 도구를 선택하는 GraphRAG Agent 압축 정리

## 0. 핵심

교안 01에서는 `Text2Cypher`와 `Vector Search`를 각각 실행했다.

교안 02에서는 두 검색 방식을 **하나의 Agent에 Tool로 연결**하고, 질문에 따라 Agent가 필요한 Tool을 선택한다.

```text
사용자 질문
↓
GraphRAG Agent
├─ 이름 확인 필요 → select_names
├─ 그래프 관계 질문 → search_graph
├─ 원문 설명 질문 → search_documents
└─ 둘 다 필요 → 두 Tool 모두 호출
↓
검색 결과 확인
↓
answer + evidence_ids 반환
```

> 핵심 변화  
> **검색 Tool을 직접 선택하는 단계 → Agent가 질문을 보고 Tool을 선택하는 단계**

---

## 1. 전체 구조

Agent에 다음 세 Tool을 연결한다.

| Tool | 역할 | 실제 검색 |
|---|---|---|
| `select_names` | 이름·별칭 확인 | Neo4j 등록 이름 조회 |
| `search_graph` | 저장된 관계·경로 조회 | Text2Cypher |
| `search_documents` | 원문 설명 검색 | Vector Search |

예:

```text
"Keanu Reeves가 출연한 영화의 감독은?"
→ search_graph

"인간이 인공지능의 가상현실 속에서 사는 영화는?"
→ search_documents

"Carbidopa 치료 관계와 Laquinimod 연구 단계를 알려줘"
→ search_graph + search_documents
```

`select_names`는 이름 표기가 불확실할 때만 보조적으로 사용한다.

---

## 2. 기존 검색 기능 준비

교안 01의 기능을 그대로 재사용한다.

```text
스키마
Cypher 작성 규칙
read_query()
VectorRetriever
```

### Text2Cypher 측

```text
질문
→ Agent가 Cypher 작성
→ search_graph
→ read_query
→ Neo4j 관계 조회
```

`read_query()`는 먼저 `EXPLAIN`으로 실행 계획을 확인하고 **조회 전용 쿼리만 실행**한다.

주요 규칙:

- `MATCH`, `WHERE`, `WITH`, `RETURN`, `ORDER BY`, `LIMIT` 중심
- 쓰기 쿼리 사용 금지
- 현재 `dataset` 조건 유지
- 스키마의 관계 의미·방향 준수
- 답변 값과 근거 ID를 같은 조회 결과에서 확보

### Vector Search 측

```text
질문
→ search_documents
→ 질문 임베딩
→ VectorRetriever
→ 관련 Chunk 검색
```

교안 기준:

```text
Embedding : text-embedding-3-large
Dimension : 768
top_k     : 3
```

문서 벡터는 저장된 값을 사용하고 질문만 새로 임베딩한다.

---

## 3. Tool 정의

### `select_names`

질문의 이름을 Neo4j의 등록 이름·별칭과 연결한다.

```text
질문의 이름
→ name / aliases 확인
→ standard_id 후보 반환
```

- 최대 20개 후보
- 이름 확인용
- 관계나 원문 근거로 사용하지 않음

---

### `search_graph`

Agent가 작성한 Cypher를 실행한다.

```python
@tool
def search_graph(cypher: str) -> dict:
    return {
        "cypher": cypher,
        "rows": read_query(cypher)
    }
```

역할:

```text
저장된 관계
경로
연결된 개체
관계 종류
```

를 조회한다.

---

### `search_documents`

원문에 적힌 설명을 의미 기반으로 검색한다.

```python
@tool
def search_documents(dataset: str, query: str) -> dict:
    result = vector_retrievers[dataset].search(
        query_text=query,
        top_k=3
    )
    return {
        "chunks": [
            {**item.metadata, "text": item.content}
            for item in result.items
        ]
    }
```

사용 기준:

```text
원문에 적힌 설명·문구 → search_documents
저장된 관계·경로 → search_graph
```

벡터 유사도가 높아도 바로 정답으로 판단하지 않고 **검색된 원문을 직접 읽어야 한다.**

---

## 4. 하나의 Agent에 Tool 연결

핵심은 `create_agent()`에 세 Tool을 같이 넣는 것.

```python
paper_agent = create_agent(
    model=llm,
    tools=[
        select_names,
        search_graph,
        search_documents,
    ],
    system_prompt=paper_system,
    response_format=ProviderStrategy(
        GroundedAnswer,
        strict=True
    ),
)
```

이제 사용자가 검색 방식을 직접 지정하지 않아도 Agent가 질문을 보고 결정한다.

```text
질문 분석
↓
필요한 Tool 선택
↓
Tool 실행
↓
결과 확인
↓
필요하면 추가 검색
↓
최종 답변
```

호출 순서와 재검색 횟수는 질문과 모델 판단에 따라 달라질 수 있다.

---

## 5. Tool 선택 규칙

시스템 프롬프트에서 선택 기준을 명확하게 준다.

### 관계 질문

```text
누가 출연했는가?
어떤 증상을 완화하는가?
A와 B의 관계는?
어떤 경로로 연결되는가?
```

→ `search_graph`

---

### 원문 설명 질문

```text
논문에서 어떤 단계라고 설명했는가?
영화 줄거리에 어떤 내용이 있는가?
원문에서 해당 개념을 어떻게 표현하는가?
```

→ `search_documents`

---

### 복합 질문

```text
저장된 관계를 조회하고,
관련 원문 설명도 찾아줘.
```

→ `search_graph` + `search_documents`

즉, Agent는 하나지만 검색 방식은 하나로 합쳐진 것이 아니다.

```text
GraphRAG Agent
├─ Graph Search Tool
└─ Vector Search Tool
```

필요한 Tool을 **선택·조합**하는 구조다.

---

## 6. Agent 프롬프트에서 중요한 규칙

교안의 핵심 규칙을 압축하면 다음과 같다.

```text
1. 이름이 불확실하면 select_names
2. 저장 관계는 search_graph
3. 원문 설명은 search_documents
4. 둘 다 필요하면 두 Tool 사용
5. 질문에서 지정한 관계 의미를 임의로 확대하지 않음
6. 원문 검색 시 질문의 개체 이름을 유지
7. 실제 검색 결과만 답변 근거로 사용
8. 여러 홉이면 경로의 모든 관계 ID 유지
9. 수치·단계는 원문에 직접 명시된 경우만 사용
10. 근거가 없으면 답변을 보류
```

특히 관계 의미를 임의로 확장하면 안 된다.

예:

```text
치료 관계 질문
≠ 완화 관계까지 자동 포함
```

질문에서 지정한 관계의 의미를 그대로 유지한다.

---

## 7. 구조화된 답변

최종 출력은 `GroundedAnswer`로 제한한다.

```python
class GroundedAnswer(BaseModel):
    answer: str
    evidence_ids: list[str]
```

| 필드 | 내용 |
|---|---|
| `answer` | 검색 근거로 작성한 최종 답변 |
| `evidence_ids` | 실제 사용한 관계·청크 ID |

근거 종류:

```text
Graph Search  → claim_id
Vector Search → chunk_id
```

`ProviderStrategy(..., strict=True)`는 출력 형식을 지키게 하지만, **인용 내용 자체가 올바른지는 별도로 확인해야 한다.**

---

## 8. 근거가 없을 때

검색 결과가 없으면 추측해서 답하지 않는다.

```text
근거 없음
→ 확인할 수 없다고 답변
→ evidence_ids = []
```

중요한 점:

```text
검색 결과 없음
≠ 현실에 해당 사실이 없음
```

다음도 확인해야 한다.

```text
Tool을 제대로 호출했는가?
Cypher 조건이 맞는가?
검색 대상 이름이 맞는가?
근거를 모델이 놓치지는 않았는가?
```

---

## 9. 실습 흐름

### 관계 질문

```text
Gabapentin이 완화할 수 있는 증상은?
↓
search_graph
↓
Neo4j 관계 조회
↓
claim_id 근거
```

---

### 원문 질문

```text
Laquinimod 임상시험 중
원문에 연구 단계가 명시된 시험과 단계는?
↓
search_documents
↓
관련 논문 Chunk 검색
↓
chunk_id 근거
```

---

### 복합 질문

```text
Carbidopa의 치료 관계를 조회하고,
Laquinimod 임상시험의 연구 단계를 찾아줘.
↓
search_graph
+
search_documents
↓
관계 근거 + 원문 근거
```

이 실습이 교안 02의 핵심이다.

---

## 10. 검색 결과와 인용 검증

답변을 받은 뒤 실제 근거를 다시 확인한다.

### 관계 근거

```text
evidence_ids의 claim_id
↓
원래 관계 조회
↓
부분 그래프로 시각화
```

`draw_evidence()`를 사용해 **실제로 답변에 인용한 관계만** 표시한다.

---

### 원문 근거

```text
evidence_ids의 chunk_id
↓
검색 결과의 Chunk 확인
↓
원문 + 문서 출처 확인
```

청크는 원문 근거이지 새로운 그래프 관계가 아니다.

```text
관계 근거 → 그래프로 표현 가능
원문 Chunk → 원문으로 확인
```

---

## 11. GraphRAG 평가 기준

교안에서는 평가를 크게 세 단계로 나눈다.

| 평가 대상 | 확인 내용 |
|---|---|
| 검색기 | 필요한 관계·원문을 잘 찾는가 |
| Tool 선택 | 질문에 맞는 Tool을 호출하는가 |
| 답변 생성 | 검색 근거에 맞는 답변을 만드는가 |

### 1. 검색기 평가

예:

```text
Hit
Recall
Precision
MRR
```

골드셋과 비교해서 검색 품질을 확인한다.

### 2. Tool 선택 평가

```text
관계 질문 → search_graph ?
원문 질문 → search_documents ?
복합 질문 → 두 Tool ?
```

시스템 프롬프트와 LLM의 Tool 선택 능력을 평가한다.

### 3. 답변 평가

```text
검색된 근거
↓
최종 답변
```

답변이 근거의 의미를 유지하는지 확인한다.

골드 답변과 LLM 평가 또는 사람이 직접 평가할 수 있다.

---

## 12. Microsoft GraphRAG와 비교

이 교안의 GraphRAG Agent와 Microsoft GraphRAG는 같은 방식이 아니다.

### 현재 교안

```text
Agent
├─ Text2Cypher → 특정 관계·경로
└─ Vector Search → 관련 원문 Chunk
```

특정 개체·관계·원문을 찾는 질문에 적합하다.

---

### Microsoft GraphRAG

그래프의 **커뮤니티와 커뮤니티 보고서**를 활용한다.

| 방식 | 검색 방식 | 적합한 질문 |
|---|---|---|
| Global | 여러 커뮤니티 보고서 종합 | 전체 문서의 주요 주제 |
| Local | 특정 개체 주변의 그래프·원문 수집 | 특정 개체 관련 정보 |
| DRIFT | 보고서 기반 초기 탐색 후 Local 반복 | 전체 주제 + 구체 사례 |

`DRIFT`:

```text
Dynamic Reasoning and Inference
with Flexible Traversal
```

### 주의

```text
Microsoft GraphRAG Local
≠ Text2Cypher
```

- Text2Cypher: 질문을 Cypher로 변환해 직접 관계 조회
- Local Search: 관련 개체를 중심으로 그래프와 원문 맥락 수집

---

## 13. 어떤 검색을 사용할지

### 특정 관계·경로

```text
Gabapentin과 연결된 증상은?
```

→ `search_graph`

---

### 특정 원문 설명

```text
Laquinimod 연구 단계는 원문에 어떻게 적혀 있는가?
```

→ `search_documents`

---

### 관계 + 원문

```text
약물 관계를 조회하고 논문 설명도 확인해줘.
```

→ 두 Tool 조합

---

### 여러 문서 전체의 주제

```text
논문 전체에서 반복되는 주요 연구 주제는?
```

→ 단순 상위 Chunk 몇 개만으로는 부족

→ Microsoft GraphRAG의 `Global` 같은 방식도 비교 대상

---

## 14. 전체 코드 구조 압축

```text
1. Neo4j 연결
2. LLM / Embedding 준비
3. 그래프·원문·벡터 적재

4. 검색 기반 기능
   ├─ read_schema()
   ├─ cypher_rules
   ├─ read_query()
   └─ VectorRetriever

5. Tool
   ├─ select_names()
   ├─ search_graph()
   └─ search_documents()

6. Agent
   ├─ GroundedAnswer
   ├─ agent_template
   ├─ create_agent()
   └─ ask()

7. 실행
   ├─ 관계 질문
   ├─ 원문 질문
   └─ 복합 질문

8. 검증
   ├─ show_response()
   ├─ show_citations()
   └─ draw_evidence()

9. 평가
   ├─ 검색 품질
   ├─ Tool 선택
   └─ 답변 근거성
```

---

## 최종 요약

```text
교안 01
Text2Cypher와 Vector Search를 각각 실행

교안 02
두 검색을 Tool로 등록
↓
create_agent에 연결
↓
Agent가 질문에 따라 Tool 선택

관계 질문
→ search_graph
→ claim_id

원문 설명 질문
→ search_documents
→ chunk_id

복합 질문
→ 두 Tool 모두 사용

이름 불확실
→ select_names

근거 없음
→ 추측하지 않고 답변 보류
→ evidence_ids = []

마지막
→ 답변과 실제 관계·원문을 다시 대조
```

> 한 줄 정리  
> **GraphRAG Agent = 하나의 거대한 검색기가 아니라, 질문에 맞는 Graph Search와 Vector Search Tool을 선택·조합하는 Agent 구조**
