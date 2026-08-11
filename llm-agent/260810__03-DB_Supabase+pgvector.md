# Supabase + pgvector 핵심 정리

> 전체 흐름  
> **PostgreSQL/Supabase 준비 → 테이블 CRUD → 임베딩 저장 → 벡터 검색 → 조건 + 의미 결합 검색**

---

# 1. 전체 구조

기존 SQLite의 정형 데이터 처리에 **벡터 검색**을 추가하는 과정.

```text
CSV
↓
pandas DataFrame
↓
임베딩 생성
↓
Supabase PostgreSQL
  ├─ faq_category : 분류·담당팀
  └─ faq_docs     : 질문·답변·임베딩
↓
pgvector로 유사도 검색
↓
RPC 함수로 Python에서 호출
```

핵심 목적:

```text
일반 SQL 조건 검색
+
임베딩 의미 검색
=
분류를 먼저 좁힌 뒤 의미가 가까운 문서 검색
```

---

# 2. SQLite → PostgreSQL

PostgreSQL을 사용하는 핵심 이유는 **pgvector 확장을 이용해 벡터를 DB 안에 저장·검색할 수 있기 때문**.

| 구분 | SQLite | PostgreSQL |
|---|---|---|
| 위치 | 로컬 파일 | 서버·클라우드 |
| 동시 사용 | 쓰기 제한 큼 | 여러 사용자 동시 처리 |
| 타입 검사 | `STRICT` 필요 | 기본 적용 |
| 벡터 | 기본 지원 없음 | `pgvector` 사용 |
| 날짜 | 주로 문자열 | `date`, `timestamptz` |
| 대소문자 무시 검색 | `LIKE` | `ILIKE` |

기존 SQL 대부분은 그대로 사용.

```text
SELECT
WHERE
GROUP BY
HAVING
JOIN
INSERT
UPDATE
DELETE
```

---

# 3. Supabase 역할

Supabase = **클라우드 PostgreSQL을 쉽게 사용하는 서비스**

주요 사용 위치:

| 작업 | 위치 |
|---|---|
| 테이블·인덱스·DB 함수 생성 | SQL Editor |
| 테이블 데이터 확인 | Table Editor |
| Python에서 행 CRUD | `supabase.table()` |
| DB 함수 호출 | `supabase.rpc()` |

연결:

```python
from supabase import create_client

supabase = create_client(project_url, anon_key)
```

연결 정보:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
```

`.env`에 저장.

> `anon key`는 공개용 키. 실제 접근 권한은 RLS 정책으로 제한.  
> `service_role` 같은 관리자 키는 브라우저·공개 저장소에 두지 않음.

---

# 4. DB 구조 만들기

## pgvector 활성화

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

`vector` 타입과 벡터 거리 연산자를 사용할 수 있게 됨.

---

## 분류 테이블

```sql
CREATE TABLE faq_category (
    category  varchar(20) PRIMARY KEY,
    team_name varchar(20) NOT NULL,
    phone     varchar(20)
);
```

역할:

```text
카테고리
→ 담당팀
→ 전화번호
```

---

## FAQ + 임베딩 테이블

```sql
CREATE TABLE faq_docs (
    faq_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category  varchar(20) NOT NULL REFERENCES faq_category(category),
    question  text NOT NULL,
    answer    text NOT NULL,
    embedding vector(768)
);
```

핵심:

```text
질문
답변
분류
임베딩
```

을 **같은 행에 저장**.

따라서 SQL 조건과 벡터 검색을 함께 사용할 수 있음.

---

# 5. 벡터 인덱스

```sql
CREATE INDEX faq_docs_embedding_idx
ON faq_docs
USING hnsw (embedding vector_cosine_ops);
```

`HNSW` = 벡터 검색용 인덱스.

```text
데이터가 적음
→ 전체 벡터 비교도 가능

데이터가 많음
→ HNSW로 빠르게 가까운 후보 검색
```

근사 최근접 검색이므로 속도를 얻는 대신 가까운 벡터 일부를 놓칠 가능성 존재.

---

# 6. supabase-py 기본 사용법

SQL 문자열 대신 **메서드를 연결해서 사용**.

| SQL | supabase-py |
|---|---|
| `SELECT *` | `.select("*")` |
| `WHERE a = 1` | `.eq("a", 1)` |
| `WHERE a >= 1` | `.gte("a", 1)` |
| `ORDER BY a` | `.order("a")` |
| `LIMIT 3` | `.limit(3)` |
| `INSERT` | `.insert({...})` |
| `UPDATE` | `.update({...}).eq(...)` |
| `DELETE` | `.delete().eq(...)` |

마지막에는 반드시:

```python
.execute()
```

실제 요청은 `.execute()`에서 실행됨.

---

## 조회

```python
response = (
    supabase.table("faq_category")
    .select("*")
    .execute()
)
```

결과:

```python
response.data
```

`response.data`는 **딕셔너리 목록**.

```python
[
    {"category": "...", "team_name": "..."},
    ...
]
```

DataFrame으로 변환:

```python
def to_df(response):
    return pd.DataFrame(response.data)
```

---

## 조건 조회

```python
response = (
    supabase.table("faq_category")
    .select("category, team_name, phone")
    .eq("team_name", "집행지원팀")
    .order("category")
    .limit(2)
    .execute()
)
```

SQL로 보면:

```sql
SELECT category, team_name, phone
FROM faq_category
WHERE team_name = '집행지원팀'
ORDER BY category
LIMIT 2;
```

---

# 7. INSERT / UPDATE / DELETE

## INSERT

```python
supabase.table("faq_category").insert({
    "category": "임시분야",
    "team_name": "임시팀",
    "phone": "042-000-0000"
}).execute()
```

## UPDATE

```python
supabase.table("faq_category") \
    .update({"phone": "042-999-9999"}) \
    .eq("category", "임시분야") \
    .execute()
```

## DELETE

```python
supabase.table("faq_category") \
    .delete() \
    .eq("category", "임시분야") \
    .execute()
```

### 주의

```text
UPDATE / DELETE
→ 조건 필수
```

조건 없는 수정·삭제는 전체 데이터에 영향을 줄 수 있음.

안전한 순서:

```text
같은 조건으로 SELECT
→ 대상 확인
→ UPDATE / DELETE
```

---

# 8. 벡터 데이터 구축

사용 모델:

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(
    "jhgan/ko-sroberta-multitask"
)
```

문장을 768차원 벡터로 변환:

```python
def embed(text):
    return model.encode(
        [text],
        normalize_embeddings=True
    )[0].tolist()
```

```text
"연구비 카드 결제는 언제 빠져나가나요?"
↓
[0.021, -0.154, ..., 0.084]
      768개 숫자
```

---

## CSV 읽기

```python
faq_source = pd.read_csv(
    ROOT / "data" / "research_faq.csv"
)
```

---

## 질문 전체 임베딩

```python
vectors = model.encode(
    faq_source["question"].tolist(),
    normalize_embeddings=True
)

faq_source["embedding"] = [
    vector.tolist()
    for vector in vectors
]
```

---

## DataFrame → DB 전송 형태

Supabase `.insert()`에는 DataFrame을 그대로 넣지 않음.

```python
records = faq_source.to_dict("records")
```

변환:

```text
DataFrame
↓
list[dict]
↓
Supabase
```

반대 방향:

```text
response.data
↓
list[dict]
↓
to_df()
↓
DataFrame
```

---

# 9. 여러 행 적재

한 번에 너무 많은 데이터를 보내지 않고 나누어 전송.

```python
for start in range(0, len(records), 20):
    supabase.table("faq_docs") \
        .insert(records[start:start + 20]) \
        .execute()
```

즉:

```text
0~19
20~39
40~59
...
```

처럼 batch 처리.

적재 후 반드시 원본과 비교해 검산.

```python
loaded["category"].value_counts()
```

확인할 것:

```text
전체 행 수
분류별 행 수
원본과 DB의 건수 일치 여부
```

---

# 10. 벡터 검색 원리

질문 벡터와 저장된 문서 벡터의 거리를 계산.

```sql
SELECT question,
       1 - (embedding <=> query_embedding) AS similarity
FROM faq_docs
ORDER BY embedding <=> query_embedding
LIMIT 3;
```

### `<=>`

코사인 거리.

```text
거리 ↓
→ 더 가까움
→ 의미가 더 비슷함
```

유사도는:

```sql
1 - 거리
```

로 표현.

### Top-K

```sql
ORDER BY embedding <=> query_embedding
LIMIT 3
```

의미:

```text
질문과 가까운 순으로 정렬
→ 상위 3개 선택
```

---

# 11. 왜 `rpc()`가 필요한가

일반 조건 검색은 메서드로 가능.

```python
.eq()
.order()
.limit()
```

하지만 다음 계산은 단순한 열 정렬이 아님.

```sql
embedding <=> query_embedding
```

질문 벡터라는 **값을 넣어서 계산해야 하는 식**.

따라서 복잡한 SQL을 DB 함수로 미리 만들고 Python에서 호출.

```text
Python
→ RPC 호출
→ PostgreSQL 함수
→ 벡터 거리 계산
→ 결과 반환
```

---

# 12. DB 검색 함수 `match_faq`

구조:

```sql
CREATE OR REPLACE FUNCTION match_faq (
    query_embedding vector(768),
    match_count int DEFAULT 3,
    filter_category text DEFAULT NULL
)
```

주요 인자:

| 인자 | 의미 |
|---|---|
| `query_embedding` | 검색 질문 벡터 |
| `match_count` | 가져올 결과 수 |
| `filter_category` | 검색할 카테고리 |

`filter_category = NULL`

```text
전체 카테고리 검색
```

값 지정:

```text
해당 카테고리 안에서만 검색
```

---

# 13. RPC 호출

```python
response = supabase.rpc(
    "match_faq",
    {
        "query_embedding": embed(question),
        "match_count": 5,
        "filter_category": None,
    }
).execute()
```

기본 구조:

```python
supabase.rpc(
    "함수이름",
    {
        "인자이름": 값
    }
).execute()
```

> 딕셔너리 키는 SQL 함수의 매개변수 이름과 정확히 일치해야 함.

---

# 14. 조건 + 의미 결합 검색

단순 벡터 검색:

```text
전체 FAQ
→ 의미가 가까운 순
```

결합 검색:

```text
전체 FAQ
↓
category 조건으로 후보 축소
↓
남은 후보의 벡터 거리 계산
↓
Top-K
```

DB 함수 내부:

```sql
WHERE filter_category IS NULL
   OR d.category = filter_category

JOIN faq_category c
  ON c.category = d.category

ORDER BY d.embedding <=> query_embedding

LIMIT match_count
```

역할:

| 처리 | 목적 |
|---|---|
| `WHERE` | 카테고리 후보 제한 |
| `JOIN` | 담당팀·전화 연결 |
| `<=>` | 의미 거리 계산 |
| `ORDER BY` | 가까운 순 정렬 |
| `LIMIT` | Top-K 선택 |

예:

```python
response = supabase.rpc(
    "match_faq",
    {
        "query_embedding": embed("계좌 등록은 어떻게 하나요?"),
        "match_count": 3,
        "filter_category": "환경설정",
    }
).execute()
```

```text
환경설정 FAQ만 선택
→ 그 안에서 '계좌 등록'과 의미가 가까운 3개 검색
```

---

# 15. 최종 검색 함수

지금까지의 흐름을 하나로 합치면:

```python
def search_faq(question, category=None, k=3):
    response = supabase.rpc(
        "match_faq",
        {
            "query_embedding": embed(question),
            "match_count": k,
            "filter_category": category,
        }
    ).execute()

    return to_df(response)[[
        "question",
        "answer",
        "team_name",
        "phone",
        "similarity"
    ]]
```

사용:

```python
search_faq(
    "연구비 카드로 결제한 금액은 언제 빠져나가나요?"
)
```

조건 추가:

```python
search_faq(
    "계좌 등록은 어떻게 하나요?",
    category="환경설정"
)
```

---

# 16. 핵심 치트시트

## Supabase

```python
supabase.table("t")
```

| 목적 | 코드 |
|---|---|
| 조회 | `.select("*")` |
| 같음 | `.eq("열", 값)` |
| 이상 | `.gte("열", 값)` |
| 정렬 | `.order("열")` |
| 개수 제한 | `.limit(k)` |
| 추가 | `.insert({...})` |
| 수정 | `.update({...}).eq(...)` |
| 삭제 | `.delete().eq(...)` |
| 실행 | `.execute()` |
| 결과 | `.data` |

---

## pgvector

| 목적 | 문법 |
|---|---|
| 확장 | `CREATE EXTENSION ... vector` |
| 벡터 열 | `vector(768)` |
| 코사인 거리 | `<=>` |
| L2 거리 | `<->` |
| 음의 내적 | `<#>` |
| 코사인 유사도 | `1 - 거리` |
| Top-K | `ORDER BY 거리 LIMIT k` |
| 인덱스 | `USING hnsw` |
| DB 함수 호출 | `supabase.rpc()` |

---

# 17. 가장 중요한 구분

```text
SQL Editor
→ DB 구조 생성
→ CREATE TABLE / INDEX / FUNCTION

supabase.table()
→ 일반 행 처리
→ SELECT / INSERT / UPDATE / DELETE

supabase.rpc()
→ DB에 저장한 복잡한 함수 실행
→ 벡터 검색 등
```

```text
DataFrame
→ .to_dict("records")
→ Supabase INSERT

Supabase response.data
→ to_df()
→ DataFrame
```

```text
조건 검색
.eq()

일반 정렬
.order()

의미 검색
embedding <=> query_embedding

복잡한 벡터 검색
.rpc()
```

---

# 18. 전체 흐름 한 번에

```text
1. Supabase PostgreSQL 준비
2. pgvector 확장 활성화
3. category / FAQ 테이블 생성
4. embedding vector(768) 열 생성
5. CSV를 pandas로 읽음
6. question을 임베딩
7. DataFrame → list[dict] 변환
8. Supabase에 저장
9. 사용자 질문도 임베딩
10. category로 후보 제한
11. 벡터 거리로 정렬
12. Top-K 반환
```

## 핵심 한 줄

```text
Supabase + pgvector
= 관계형 DB의 조건·JOIN + 임베딩 의미 검색을 한 DB에서 함께 처리
```

이때 만든 `search_faq()`가 이후 **RAG의 검색(Retrieval) 단계​**가 됨.

```text
사용자 질문
→ search_faq()
→ 관련 문서 검색
→ 검색 결과를 LLM에 전달
→ 근거 기반 답변 생성
```