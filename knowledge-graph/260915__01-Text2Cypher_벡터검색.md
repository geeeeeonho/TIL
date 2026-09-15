# Text2Cypher와 Vector Search 압축 정리

## 0. 핵심

이 교안의 목적은 **그래프 관계 조회**와 **원문 의미 검색**을 분리해서 익히는 것.

| 방식 | 무엇을 찾는가 | 핵심 도구 | 근거 |
|---|---|---|---|
| Text2Cypher | 그래프에 저장된 관계·경로 | `select_names`, `search_graph` | `claim_id` |
| Vector Search | 원문 청크의 설명·문구 | `search_documents` | `chunk_id` |

둘 다 흐름은 같다.

```text
사용자 질문
→ 검색 도구 실행
→ 검색 결과 확보
→ LLM이 결과만 사용해 답변
→ answer + evidence_ids 반환
→ 실제 원문과 인용 확인
```

> 기억 기준  
> **관계가 그래프에 이미 저장되어 있으면 Text2Cypher, 원문 설명을 찾아야 하면 Vector Search**

---

## 1. 데이터 구조

그래프 데이터와 원문 데이터를 같은 Neo4j 안에서 함께 사용한다.

### 영화 데이터

```text
Chunk
  └─ FROM_DOCUMENT → Document
                         └─ ABOUT_MOVIE → Movie

Person ─ ACTED_IN / DIRECTED 등 → Movie
```

- 영화·인물과 6종 관계 저장
- 영화별 위키백과 문서와 청크 저장
- 관계 조회와 원문 검색을 모두 수행 가능

### 의료 데이터

```text
Entity ─ FROM_CHUNK → Chunk
                         └─ FROM_DOCUMENT → Document
```

- 약물·질환·증상 관계 저장
- 관계의 근거 청크와 PMC 논문 원문 연결
- 관계 자체와 해당 관계의 실제 원문을 함께 확인 가능

교안에서는 문서 임베딩을 다시 생성하지 않고 **저장된 벡터를 재사용**한다.

---

## 2. Text2Cypher

### 목적

자연어 질문을 그래프 구조에 맞는 Cypher로 바꿔 **저장된 관계를 조회**한다.

예:

```text
"키아누 리브스가 출연한 영화의 감독은?"
→ Person - ACTED_IN → Movie ← DIRECTED - Person
```

### 필요한 정보

에이전트에 JSON 스키마를 전달한다.

| 스키마 | 역할 |
|---|---|
| `node_types` | 노드 종류·속성 |
| `relationship_types` | 관계 의미 |
| `patterns` | 주어-관계-목적어 방향 |

관계 방향과 속성을 임의로 추측하지 않고 스키마를 기준으로 Cypher를 작성한다.

### 주요 도구

#### `select_names`

질문의 이름을 DB에 등록된 이름과 맞추는 도구.

```text
질문의 이름
→ name / aliases 비교
→ standard_id 확인
```

- 이름·별칭 확인용
- 최대 20개 후보 반환
- **후보 자체는 답변 근거가 아님**

#### `search_graph`

LLM이 작성한 Cypher를 실행해 실제 관계를 조회하는 도구.

```python
@tool
def search_graph(cypher: str):
    return {
        "cypher": cypher,
        "rows": read_query(cypher)
    }
```

### 조회 안전장치

`read_query()`에서 먼저 `EXPLAIN`을 실행한다.

```text
Cypher 작성
→ EXPLAIN
→ query_type == "r" 확인
→ 실제 조회 실행
```

즉, `MATCH`, `WHERE`, `RETURN` 중심의 **조회 전용 Cypher**만 허용한다.

### 핵심 Cypher 규칙

- 현재 `dataset` 조건 유지
- 관계 방향은 `patterns` 기준
- 불확실한 이름만 `select_names`로 확인
- 쓰기 쿼리 사용 금지
- 관계 타입은 `type(r)` 사용
- 답변 값과 근거를 같은 행에서 반환
- 여러 홉이면 경로의 모든 관계 근거 유지

대표 반환 구조:

```text
answer_value
evidence_ids
evidence_texts
source_doc_ids
source_kinds
relation_types
```

### Text2Cypher 흐름

```text
질문
↓
스키마 확인
↓
필요하면 select_names
↓
LLM이 Cypher 작성
↓
search_graph
↓
관계 결과 + claim_id
↓
최종 답변
```

---

## 3. Vector Search

### 목적

그래프 관계가 아니라 **문서 원문에 적힌 설명이나 문구**를 의미 기반으로 찾는다.

예:

```text
"인간이 인공지능이 만든 가상현실 속에서 사는 영화는?"
→ 질문 임베딩
→ 영화 줄거리 Chunk 검색
→ 관련 원문을 읽고 영화 판단
```

### 벡터 인덱스

청크의 다음 속성을 사용한다.

```text
Chunk.text
Chunk.embedding
```

교안 기준:

```text
Embedding: text-embedding-3-large
Dimension: 768
Similarity: cosine
```

영화와 의료 자료는 **별도 인덱스**로 구성해 서로 섞이지 않게 한다.

### 검색 방식

문서 벡터는 저장된 값을 그대로 사용하고 **질문만 새로 임베딩**한다.

```text
질문
↓
질문 임베딩
↓
VectorRetriever
↓
유사한 Chunk 검색
↓
원문 + 출처 + score 반환
```

`search_documents`는 최대 3개의 청크를 반환한다.

```python
result = retriever.search(
    query_text=query,
    top_k=3
)
```

검색 결과에는 다음 정보가 포함된다.

```text
chunk_id
source_doc_id
title
url
score
text
```

### 중요한 점

**유사도가 높다고 정답인 것은 아님.**

벡터 검색은 가까운 원문을 찾는 단계다.  
최종 답변의 사실 여부는 검색된 문장을 직접 읽고 판단해야 한다.

### Vector Search 흐름

```text
질문
↓
search_documents
↓
유사한 원문 Chunk
↓
LLM이 실제 원문 확인
↓
답변 + chunk_id
```

---

## 4. 답변과 근거 관리

두 검색 방식은 같은 출력 구조를 사용한다.

```python
class GroundedAnswer(BaseModel):
    answer: str
    evidence_ids: list[str]
```

### 근거 ID

```text
Text2Cypher → claim_id
Vector Search → chunk_id
```

### 답변 규칙

- 실제 검색된 근거만 사용
- 근거 ID를 새로 만들지 않음
- 여러 홉이면 모든 관계 ID 유지
- 근거가 없으면 확인할 수 없다고 답변
- 원문의 조건·수치·단계를 임의로 확대하지 않음
- 최종적으로 인용 ID와 실제 원문을 대조

즉,

```text
검색 성공 ≠ 답변 검증 완료
```

검색 결과가 실제 답변 내용을 뒷받침하는지 마지막에 확인해야 한다.

---

## 5. 두 방식 비교

| 구분 | Text2Cypher | Vector Search |
|---|---|---|
| 검색 대상 | 노드·관계 | 원문 청크 |
| 검색 기준 | 그래프 구조 | 의미 유사도 |
| 질문 예 | 누가 감독했는가 | 원문에서 어떻게 설명하는가 |
| 주요 입력 | 스키마 + 질문 | 질문 임베딩 |
| 도구 | `select_names`, `search_graph` | `search_documents` |
| 근거 ID | `claim_id` | `chunk_id` |
| 강점 | 정확한 관계·경로 조회 | 서술형 원문 탐색 |
| 주의 | 관계 방향·스키마 준수 | 높은 score가 정답을 의미하지 않음 |

둘은 상하 관계가 아니라 **서로 다른 검색 Tool**이다.

---

## 6. 질문에 따른 선택

### Text2Cypher가 적합

```text
A와 B는 어떤 관계인가?
누가 이 영화에 출연했는가?
이 약물이 완화한다고 저장된 증상은?
특정 개체와 연결된 노드는?
```

→ **그래프에 구조화된 관계를 직접 조회**

### Vector Search가 적합

```text
논문에서 어떤 단계라고 설명했는가?
영화 줄거리가 어떤 내용인가?
원문에서 해당 개념을 어떻게 설명하는가?
특정 문구나 설명이 포함된 문서는?
```

→ **원문 청크를 의미 기반으로 검색**

---

## 7. 교안 실습 예시

### Text2Cypher

```text
키아누 리브스 출연 영화 → 감독 조회
Gabapentin → PALLIATES_CS → 증상 조회
```

Gabapentin 실습의 확인 근거:

```text
P04
P05
P06
```

### Vector Search

```text
가상현실 줄거리 → 영화 찾기
Laquinimod 임상시험 → 원문에 명시된 연구 단계 확인
```

Laquinimod 실습에서는 `PMC13494208`의 실제 문장을 확인한다.

---

## 8. 전체 코드 구조만 압축

```text
1. Neo4j 연결
2. 그래프·문서·Chunk·Embedding 적재

3. Text2Cypher
   ├─ read_schema()
   ├─ select_names()
   ├─ search_graph()
   ├─ graph_template
   └─ graph_agent

4. Vector Search
   ├─ Vector Index
   ├─ VectorRetriever
   ├─ search_documents()
   ├─ vector_template
   └─ vector_agent

5. 공통
   ├─ GroundedAnswer
   ├─ ask()
   ├─ show_response()
   └─ show_citations()
```

---

## 9. 이름 검색 개선 아이디어

교안 메모의 방향은 **MVP 우선 → 이후 이름 정규화 개선**.

```text
질문의 이름
↓
정확 일치
↓
aliases 확인
↓
한국어 ↔ 영어 이름 변환
↓
부분 일치 / 오타 후보
↓
standard_id 결정
```

별도 CSV 등을 두고 다음 형태로 관리 가능하다.

| standard_name | aliases |
|---|---|
| Keanu Reeves | 키아누 리브스, Keanu Reaves 등 |

핵심은 이름 변환 자체가 아니라 **그래프에 저장된 개체와 안정적으로 연결하는 것**.

---

## 최종 요약

```text
Text2Cypher
= 자연어 질문 → Cypher → 그래프 관계 조회
= 구조화된 사실 검색
= claim_id 근거

Vector Search
= 질문 → 임베딩 → 원문 Chunk 검색
= 비정형 설명 검색
= chunk_id 근거

공통
= 검색 결과만 사용해 답변
= answer + evidence_ids 반환
= 마지막에 실제 원문과 반드시 대조
```
