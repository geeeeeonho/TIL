# Microsoft GraphRAG — 색인과 검색 핵심 정리

> **기준:** 교안 `Microsoft GraphRAG 색인과 네 가지 검색` (`graphrag` 3.1.0).  
> **정리 방향:** 개념·데이터 흐름 우선 → 주요 설정과 API 문법 → 근거 평가·갱신.  
> 아래 코드는 **원본 교안의 핵심 부분을 발췌·축약한 학습용 코드**. 일부 보조 함수(`make_settings`, `read_tables`, `run_search`)는 원본에서 정의한 것을 사용한다.

## 1. Microsoft GraphRAG의 구조와 특징

### 핵심 개념

**Microsoft GraphRAG**는 문서에서 LLM으로 **개체(Entity)와 관계(Relationship)** 를 추출하고, 연결이 촘촘한 개체를 **커뮤니티(Community)** 로 묶어 요약한 뒤 검색에 활용하는 RAG 방식.

- **색인(Indexing):** 질문이 들어오기 전, 개체·관계·커뮤니티·커뮤니티 보고서·임베딩을 생성.
- **검색(Query/Search):** 질문 유형에 맞춰 원문, 그래프 주변 정보, 커뮤니티 보고서를 골라 LLM에 전달.
- **핵심 이점:** 문서 한 편의 사실뿐 아니라, 여러 문서에 흩어진 관계와 자료 전체의 주제까지 탐색.

```text
[색인: 질문 이전]
원본 문서
   ↓ 청크 분할
청크 → LLM 개체·관계 추출
   ↓ 같은 개체 합치기 + 설명 요약
개체·관계 그래프
   ↓ Leiden 커뮤니티 탐지
계층 커뮤니티(레벨 0: 가장 큰 묶음)
   ↓ LLM 요약
커뮤니티 보고서(제목·요약·발견)
   ↓
Parquet 테이블 + LanceDB 임베딩 저장

[검색: 질문 이후]
질문 → 검색 방식 선택(Basic / Local / Global / DRIFT)
     → 관련 근거 수집 → 답변 LLM → 답변
```

### Neo4j·LightRAG와 비교

| 구분 | Neo4j 스키마 그래프 | Microsoft GraphRAG | LightRAG |
|---|---|---|---|
| 그래프 구성 | 사람이 노드·관계 유형 정의 | LLM이 개체·관계 추출 | LLM이 개체·관계 추출 |
| 관계 표현 | `[:CONNECTED_TO]` 등 명시적 유형 | 양 끝 개체 + 설명 + `weight` | 양 끝 개체 + 설명·키워드 + `weight` |
| 추가 색인 | 설계에 따라 다름 | **계층 커뮤니티 + 보고서** | **관계 키워드**(커뮤니티 보고서 없음) |
| 주력 검색 | Cypher로 조건·관계 정확 조회 | 개체 주변·전역 요약·멀티홉 | 관계 키워드·개체 검색 |
| 저장 | Neo4j DB | 로컬 Parquet + LanceDB | 로컬 저장소 |

- **Neo4j:** `MATCH`로 관계 종류를 정확히 필터링하거나 집계하는 데 적합.
- **Microsoft GraphRAG:** 사전 정의한 관계 유형 없이도 문서를 그래프로 구성하고, 커뮤니티 보고서로 넓은 질문을 처리.
- **LightRAG:** 커뮤니티 보고서 대신 관계 키워드를 이용해 관련 개체·관계를 찾음.
- **주의:** Microsoft GraphRAG의 `relationships`에는 `LOCATED_IN` 같은 별도 관계 유형 열이 없음. 관계 의미는 `description`에 담김. 또한 `노고단`과 `지리산 노고단`을 다른 개체로 추출할 수 있음.

## 2. 색인(Indexing): 생성물과 저장 구조

### 색인 4단계

1. **추출:** 청크마다 개체 이름·유형·설명, 개체 간 관계 설명을 LLM이 생성.
2. **병합·요약:** 같은 이름의 개체를 통합하고 여러 설명을 LLM이 요약.
3. **계층 커뮤니티:** Leiden 알고리즘으로 서로 강하게 연결된 개체를 계층적으로 묶음.
4. **커뮤니티 보고서:** 각 묶음을 LLM이 `title`, `summary`, `findings` 등으로 요약.

`weight`는 관계 연결 강도. 이 교안의 Microsoft GraphRAG에서는 LLM이 관계 점수를 부여하고, 같은 개체 쌍의 관계가 중복되면 강도를 합산함. 커뮤니티 탐지에서 간선 가중치로 사용.

### 생성 파일과 검색에서의 역할

```text
프로젝트/
├─ input/                    # 색인할 .txt 문서
├─ output/
│  ├─ documents.parquet
│  ├─ text_units.parquet
│  ├─ entities.parquet
│  ├─ relationships.parquet
│  ├─ communities.parquet
│  ├─ community_reports.parquet
│  └─ lancedb/              # 임베딩 저장
└─ cache/, logs/, update_output/  # 설정한 경우
```

| 데이터 | 의미 | 주요 사용처 |
|---|---|---|
| `documents` | 원본 문서와 식별자 | 청크가 속한 문서 확인 |
| `text_units` | 청크·문서 연결 정보 | Basic의 원문, Local의 근거 |
| `entities` | 개체의 이름·유형·설명 | Local의 검색 출발점 |
| `relationships` | `source`, `target`, `description`, `weight` | Local에서 개체와 연결된 관계 수집 |
| `communities` | 커뮤니티 레벨·소속 개체 | 개체와 보고서 연결 |
| `community_reports` | 커뮤니티별 제목·요약·주요 발견 | Global, Local, DRIFT |

**LanceDB에 임베딩하는 항목은 세 가지.**

| 벡터 테이블 | 임베딩 대상 | 사용 검색 |
|---|---|---|
| `text_unit_text` | 청크 원문 | **Basic** |
| `entity_description` | 개체 설명 | **Local**, DRIFT의 후속 Local |
| `community_full_content` | 커뮤니티 보고서 본문 | **DRIFT** 첫 단계 |

**`relationships` 자체는 벡터 검색하지 않음.** Local은 벡터 검색으로 *개체*를 찾은 뒤, 개체와 연결된 관계를 테이블에서 가져옴. Global은 임베딩 검색 없이 지정한 레벨의 보고서를 읽음.

## 3. 네 가지 검색 방식 — 가장 중요한 부분

| 방식 | 검색 시작점 | LLM에 전달하는 근거 | 적합한 질문 |
|---|---|---|---|
| **Basic** | 청크 임베딩 유사도 | 가까운 원문 청크 | 단일 사실·수치 |
| **Local** | 개체 설명 임베딩 유사도 | 개체·관계·원문·관련 커뮤니티 보고서 | 특정 개체 주변 정보 |
| **Global** | 지정 레벨의 보고서 전체 | 보고서마다 뽑은 요점(Map) → 통합(Reduce) | 자료 전체의 주제·목록·경향 |
| **DRIFT** | 가상 답변과 보고서 임베딩 유사도 | 보고서 기반 초기 답 + 후속 질문별 Local 검색 결과 | 다단계 관계·멀티홉 |

```text
Basic   질문 ──(청크 벡터 검색)──> 원문 청크 ──> 답변

Local   질문 ──(개체 벡터 검색)──> 개체
                                    ├─ 연결된 관계
                                    ├─ 관련 원문 청크 ──> 답변
                                    └─ 소속 커뮤니티 보고서

Global  커뮤니티 보고서 전체 ──> 묶음별 Map(LLM)
                                     └──> Reduce(LLM) ──> 답변

DRIFT   질문 ──> 가상 답변(HyDE) ──(보고서 벡터 검색)──> 관련 보고서
                                                   ↓
                                           초기 답 + 후속 질문
                                                   ↓
                                         후속 질문별 Local 검색
                                                   ↓
                                               답변 통합
```

### Basic · Local

- **Basic:** 질문 임베딩과 유사한 청크 `k`개를 가져와 1회 LLM 호출로 답함. 그래프는 사용하지 않음. 문서 여러 개를 이어 읽어야 하면 근거 누락 가능.
- **Local:** 가까운 개체를 찾고, 연결된 관계·원문 청크·커뮤니티 보고서를 함께 수집. 1회 LLM 호출로 답함. 첫 개체를 잘못 찾거나 토큰 예산이 부족하면 필요한 근거가 빠질 수 있음.
- Local의 컨텍스트는 기본 최대 **12,000토큰**. 이 교안은 `community_prop=0.25`(커뮤니티 보고서 약 25%)를 설정하고, `text_unit_prop`로 원문 청크 예산을 조절.

### Global · DRIFT

- **Global:** `community_level=1`이면 레벨 0·1 커뮤니티 보고서를 모두 읽음(`dynamic_community_selection=False`). 각 묶음을 LLM이 요약(Map)하고 결과를 합쳐 최종 답을 생성(Reduce). 원문 청크를 직접 넘기지 않음.
  - 커뮤니티 보고서가 많을수록 Map 호출·비용 증가.
  - `dynamic_community_selection=True`이면 LLM이 관련 보고서를 선별한 후 Map에 사용. **벡터 검색 방식은 아님.**
- **DRIFT:** LLM이 질문에 대한 **가상 답변(HyDE)** 을 만든 뒤, 그 임베딩과 비슷한 커뮤니티 보고서를 선택. 보고서로 초기 답과 후속 질문을 생성하고, **각 후속 질문에 Local 검색을 반복**한 후 답을 합침.
  - Global처럼 전체 보고서를 읽지 않음.
  - 멀티홉 질문에 유리하지만 호출 수가 많고 무작위 선택 요소 때문에 검색 결과가 달라질 수 있음.

**교안 설정에 따른 LLM 호출 예시** (실측·설정에 따라 변동)

| Basic | Local | Global | DRIFT |
|---:|---:|---:|---:|
| 1회 | 1회 | 약 15회(14 Map + 1 Reduce) | 6회(확장 1 + 초기 1 + Local 3 + 최종 1) |

DRIFT 핵심 설정: `primer_folds=1`(초기 보고서 묶음), `drift_k_followups=3`(보고서·후속 질문 수), `n_depth=1`(후속 Local 탐색 깊이). **호출 수는 선택·생성된 질문 수에 따라 달라짐.**

### 검색 방식 선택 기준

- **단일 사실:** Basic → 예: 출렁다리 길이.
- **특정 개체를 중심으로 한 주변 정보:** Local → 예: 노고단 주변 볼거리.
- **자료 전체에서 빠짐없이 분류·요약:** Global → 예: 모든 장애의 반복 원인.
- **A에서 B를 거쳐 C로 연결해야 하는 질문:** DRIFT → 예: 장애 원인 서비스 → 관련 캐시 → 운영 팀 담당자.

## 4. 주요 코드 문법

> 아래 예시는 개념 이해를 위해 일부 초기화·모델·프롬프트 설정을 생략. **완전한 독립 실행 코드가 아니라 핵심 API 사용법**이며, 교안의 `make_settings`, 경로·환경변수·테이블 준비를 선행해야 함.

### 4-1. 설정 생성 → 색인 실행

```python
import graphrag.api as api
from graphrag.config.models.graph_rag_config import GraphRagConfig

# 교안에 정의된 make_settings()로 설정 dict 생성
settings = make_settings(project_dir, ["장소", "인물", "단체", "행사"])
config = GraphRagConfig(**settings)   # dict를 키워드 인자로 풀어 설정 객체 생성

# 색인: 청크·개체·관계·커뮤니티·보고서·임베딩 생성
index_results = await api.build_index(config=config, method="standard")

for result in index_results:
    print(result.workflow, result.error)  # 단계별 성공·실패 확인
```

`make_settings()`에서 알아둘 주요 설정 키(원본의 일부):

```python
settings = {
    "extract_graph": {
        "entity_types": ["장소", "인물", "단체", "행사"],
        "prompt": str(prompt_paths["extract_graph"]),
        "max_gleanings": 0,
    },
    "basic_search": {"k": 5},
    "local_search": {"text_unit_prop": text_unit_prop, "community_prop": 0.25},
    "drift_search": {"primer_folds": 1, "drift_k_followups": 3, "n_depth": 1},
    # 나머지: completion_models, embedding_models, input/output_storage,
    #         vector_store, community_reports 등 (원본 make_settings 참조)
}
```

- `GraphRagConfig(**settings)`: 설정 `dict`를 설정 객체로 변환.
- `await`: `build_index` 등 비동기 API 호출을 완료할 때까지 기다림(Jupyter 셀 기준).
- `method="standard"`: 개체·관계 추출, 설명 요약, 보고서 작성에 LLM 사용.
- `prompt`: 교안에서는 기본 추출·요약·보고서 프롬프트에 **한국어 출력 지시를 추가한 텍스트 파일의 경로**를 전달.
- `text_unit_prop`: Local에서 원문 청크가 차지하는 토큰 비율. 교안은 Basic의 `k=5`와 대략 같은 문서 분량으로 계산.

### 4-2. 색인 테이블 확인

```python
import pandas as pd

names = ["documents", "text_units", "entities",
         "relationships", "communities", "community_reports"]

tables = {
    name: pd.read_parquet(project_dir / "output" / f"{name}.parquet", engine="pyarrow")
    for name in names
}

# 관계: 시작 개체·끝 개체·설명·강도
relations = tables["relationships"]
print(relations[["source", "target", "description", "weight"]].head())

# 커뮤니티 보고서: 레벨별 개수
print(tables["community_reports"]["level"].value_counts().sort_index())
```

`read_parquet`은 Parquet 파일을 DataFrame으로 읽음. `value_counts()`는 그룹별 개수, `sort_index()`는 레벨 번호 순 정렬.

### 4-3. 네 검색 API — 다른 인자를 비교

`config`, `query`, `response_type`, `callbacks`는 공통으로 사용. `tables`는 위에서 읽은 결과. `callbacks=[]`는 컨텍스트 수집 콜백을 사용하지 않는 예시이고, 실제 근거를 모으려면 4-4처럼 `callbacks=[collector]`를 전달. 아래 코드는 **교안의 검색 호출 부분만 발췌**한 것.

```python
question = "노고단 주변에 어떤 볼거리가 있나?"
response_type = "한국어로 한두 문장. 근거에 없으면 모른다고 답한다"
community_level = 1

# ① Basic: 청크 기반
basic_answer, basic_ctx = await api.basic_search(
    config=config, query=question, response_type=response_type,
    text_units=tables["text_units"], callbacks=[],
)

# ② Local: 개체 + 그래프 연결 정보
local_answer, local_ctx = await api.local_search(
    config=config, query=question, response_type=response_type,
    entities=tables["entities"], relationships=tables["relationships"],
    text_units=tables["text_units"], communities=tables["communities"],
    community_reports=tables["community_reports"],
    covariates=None, community_level=community_level, callbacks=[],
)

# ③ Global: 커뮤니티 보고서 Map-Reduce
global_answer, global_ctx = await api.global_search(
    config=config, query=question, response_type=response_type,
    entities=tables["entities"], communities=tables["communities"],
    community_reports=tables["community_reports"],
    community_level=community_level, dynamic_community_selection=False,
    callbacks=[],
)

# ④ DRIFT: 보고서 + 후속 질문별 Local 검색
drift_answer, drift_ctx = await api.drift_search(
    config=config, query=question, response_type=response_type,
    entities=tables["entities"], relationships=tables["relationships"],
    text_units=tables["text_units"], communities=tables["communities"],
    community_reports=tables["community_reports"],
    community_level=community_level, callbacks=[],
)
```

**핵심 문법:** `api.<방식>_search(...)`는 `await`로 실행하며 **`(answer, context)` 튜플**을 반환. 전달하는 테이블이 검색마다 달라짐. 실제 검색 방식은 `query` 내용과 별도로 API 선택이 결정.

### 4-4. 콜백으로 검색 근거 수집·평가

DRIFT는 여러 번 Local을 호출하므로 **API 반환 컨텍스트만 보면 마지막 검색 근거만 남을 수 있음.** 교안은 `on_context` 콜백으로 모든 컨텍스트를 수집.

```python
from graphrag.callbacks.query_callbacks import QueryCallbacks

class ContextCollector(QueryCallbacks):
    def __init__(self):
        self.contexts = []

    def on_context(self, context):
        self.contexts.append(context)

collector = ContextCollector()
answer, last_context = await api.basic_search(
    config=config, query=question, response_type=response_type,
    text_units=tables["text_units"], callbacks=[collector],
)
all_contexts = collector.contexts
```

같은 `callbacks=[collector]`를 **Local / Global / DRIFT** 호출에도 전달 가능. 특히 DRIFT에서는 `collector.contexts`를 기준으로 실제 넘긴 청크들을 확인해야 함.

```python
# 원본 교안의 context_doc_ids()는 sources의 청크 ID를
# text_units → documents에 연결해 원본 문서 ID 목록으로 변환
sent_doc_ids = context_doc_ids(all_contexts, tables)
gold_doc_ids = ["정답_근거_문서_ID"]

hit_docs = len(set(sent_doc_ids) & set(gold_doc_ids))
all_hit = int(hit_docs == len(set(gold_doc_ids)))
```

- `docs_given`: 답변 모델에 넘긴 **서로 다른 문서 수**.
- `gold_docs`: 답을 위해 필요한 **정답 근거 문서 수**.
- `hit_docs`: 정답 근거 중 실제로 넘긴 문서 수.
- `all_hit`: 모든 정답 근거 문서가 있으면 `1`, 아니면 `0`.
- **Global은 원문 대신 보고서를 전달**하므로 이 지표의 문서 열을 `None`으로 두고, 답변에 포함된 항목·인용 보고서를 별도로 확인.
- 정답 문서가 포함됐어도 **답변의 정확성이 보장되는 것은 아님**. 검색 간 비교에는 넘긴 문서 수·토큰 예산도 함께 고려.

### 4-5. 증분 색인과 질문 라우팅

```python
# 새 .txt 문서를 설정의 input/ 폴더에 넣은 후
results = await api.build_index(
    config=config, method="standard", is_update_run=True
)
```

- `is_update_run=True`: **이전에 없던 파일 이름**을 기준으로 새 문서를 추가 색인.
- 기존 커뮤니티를 전체 재계산하거나 기존 보고서를 다시 쓰지 않음.
- **기존 파일의 수정·삭제는 반영되지 않음.** 이런 변경이나 누적 불일치가 있으면 전체 재색인 필요.

교안의 따라하기에서는 질문 분류기 **Jev `TypeSafeClassifier`** 를 이용해 검색 방식 선택:

```python
import os
from langchain_typesafe import Choice, TypeSafeClassifier

router = TypeSafeClassifier(model=os.getenv("TYPESAFE_MODEL", "jev-1.13.0"))
route_question = Choice(
    instructions="질문에 적절한 GraphRAG 검색 방식을 골라라.",
    criteria={
        "basic": "한 문서의 단일 사실",
        "local": "특정 개체와 바로 연결된 정보",
        "drift": "둘 이상의 연결 단계를 거치는 멀티홉",
        "global": "자료 전체의 목록·경향·주제",
    },
)

result = router.invoke({"state": question, "questions": {"route": route_question}})
mode = result.choices["route"].choice
# mode에 따라 run_search(mode, 질문_dict, config, tables) 호출
```

`result.choices["route"].probabilities`에는 검색 방식별 선택 확률이 들어 있음. **라우터의 선택은 정답이 아니라 예측**이므로, 골드 질문 유형과 비교해 검토.

## 5. 기억할 내용

1. **색인과 검색은 별개.** `build_index`는 질문 이전에 그래프·보고서를 만들고, 검색 API는 질문 때 근거를 가져옴.
2. **커뮤니티 보고서가 Microsoft GraphRAG의 핵심.** Local에서 개체 주변 정보, Global에서 전체 요약, DRIFT에서 초기 탐색의 근거로 사용.
3. **벡터 검색 대상은 청크·개체 설명·커뮤니티 보고서.** 관계 자체는 임베딩하지 않고 개체 연결로 가져옴.
4. **검색 선택:** 단일 사실=Basic / 개체 주변=Local / 전체 요약=Global / 여러 단계 연결=DRIFT.
5. **품질 판단:** 답변만 보지 말고 `sources`, `reports`, 근거 문서 포함 여부, LLM 호출 수를 함께 확인.
6. **갱신 한계:** 새 파일 추가와 기존 파일 수정·삭제는 다름. 필요하면 전체 재색인.
