# 지식 그래프 · 온톨로지 · RDF · SPARQL 압축 정리

> 전체 흐름  
> **Wikidata에서 사실 수집 → 온톨로지로 범위 정의·검증 → RDF 트리플로 저장 → SPARQL로 탐색**

```mermaid
flowchart LR
    A["Wikidata<br/>공개 지식 그래프"] --> B["사실 수집<br/>주어·술어·목적어"]
    B --> C["Ontology<br/>타입·관계 규칙"]
    C --> D["RDF Graph<br/>표준 트리플"]
    D --> E["SPARQL<br/>검색·조인·경로·수정"]
```

---

# 1. 지식 그래프와 온톨로지

## 지식 그래프 = 사실을 연결로 쌓은 그래프

이름 하나만 있는 것은 지식이 아니다.

```text
아인슈타인
```

다른 개체와 관계가 붙을 때 하나의 사실이 된다.

```text
아인슈타인 ──국적──> 독일
아인슈타인 ──직업──> 물리학자
```

지식 그래프는 이런 사실을 **주어·술어·목적어의 연결**로 계속 쌓은 구조다.

```python
[
    ["레오나르도 다 빈치", "국적", "피렌체 공화국"],
    ["조선 세종", "국적", "조선"],
    ["조선 세종", "직업", "군주"],
]
```

한 줄을 읽으면 그대로 문장이 된다.

```text
주어        술어      목적어
조선 세종   직업  →   군주

= "조선 세종의 직업은 군주다."
```

원본 실습에서는 Wikidata에서 인물 11명의 `국적(P27)`과 `직업(P106)`을 받아 약 100개의 트리플을 만들었다.

### Wikidata의 특징

Wikidata는 공개 지식 그래프다.

- 개체는 이름 대신 `Q-id`로 식별
- 관계·속성은 `P-id`로 식별
- 같은 대상에 여러 사실이 붙을 수 있음
- 사람이 편집하므로 누락·세분화·언어 차이가 존재할 수 있음

예:

```text
Q937  = 알베르트 아인슈타인
P27   = 국적
P106  = 직업
```

따라서 검색 결과가 없다고 바로 사실이 틀렸다고 보면 안 된다.

```text
질의 결과 없음
→ 실제로 사실이 없음
또는
→ Wikidata에 해당 사실이 등록되지 않음
```

---

## 온톨로지 = 그래프에 담을 의미의 규격

Wikidata의 값을 그대로 가져오면 지나치게 세분화된 값이 섞인다.

원본 실습에서는 11명의 직업만 조회했는데도 약 **56종의 직업 값**이 나왔다.

```text
과학자
교수
대학 교수
물리학자
이론물리학자
화가
...
```

따라서 우리가 만들 그래프의 범위를 먼저 정한다.  
이 규격이 **온톨로지(Ontology)**다.

온톨로지는 크게 두 가지를 정한다.

| 규칙 | 의미 | 예 |
|---|---|---|
| 관계 규칙 | 어떤 타입끼리 연결 가능한가 | `국적: 인물 → 국가` |
| 타입 사전 | 각 타입에 어떤 값이 들어가는가 | 직업은 지정한 8종만 허용 |

```python
RELATION_RULES = {
    "국적": ("인물", "국가"),
    "직업": ("인물", "직업"),
}

VALID_JOBS = {
    "물리학자", "수학자", "화학자", "화가",
    "작곡가", "극작가", "생물학자", "군주",
}

TYPE_DICT = {
    "인물": VALID_PEOPLE,
    "국가": VALID_COUNTRIES,
    "직업": VALID_JOBS,
}
```

트리플 검증은 **술어뿐 아니라 주어와 목적어의 타입도 모두 확인**해야 한다.

```python
def is_valid(triple):
    subj, pred, obj = triple

    # 허용하지 않은 관계
    if pred not in RELATION_RULES:
        return False

    subj_type, obj_type = RELATION_RULES[pred]

    return (
        subj in TYPE_DICT[subj_type]
        and obj in TYPE_DICT[obj_type]
    )
```

예:

```python
is_valid(["알베르트 아인슈타인", "직업", "물리학자"])
# True

is_valid(["알베르트 아인슈타인", "취미", "바이올린"])
# False
```

원본 실습에서는 약 100개 사실 중 **38개 정도만 정의한 온톨로지를 통과**했다.

중요한 점:

> 걸러졌다고 틀린 사실은 아니다.  
> **현재 그래프가 다루기로 한 범위 밖이라는 뜻**이다.

```text
지식 그래프 = 실제 사실
온톨로지    = 어떤 사실을 어떤 구조로 담을지 정한 규칙
```

---

# 2. RDF: 사실을 표현하는 표준

## RDF 트리플

**RDF(Resource Description Framework)**는 사실을 다음 세 칸으로 표현하는 웹 표준이다.

```text
Subject     Predicate     Object
주어         술어          목적어
```

예:

```text
알베르트 아인슈타인 ──국적──> 독일
```

RDF에서는 개체를 이름보다 **URI**로 식별한다.

```text
http://www.wikidata.org/entity/Q937
```

이유:

```text
이름 → 동명이인 가능
URI  → 개체를 고유하게 식별
```

목적어에는 두 종류가 올 수 있다.

| 목적어 | 예 | 표현 |
|---|---|---|
| 다른 개체 | 독일, 프랑스 | URI |
| 단순 값 | 이름, 숫자, 날짜 | Literal |

```python
from rdflib import Graph, Literal, Namespace

EX = Namespace("http://example.org/kg/")

g = Graph()
g.add((EX["모나리자"], EX["제작연도"], Literal(1503)))
```

---

## Turtle: RDF를 사람이 읽기 쉽게 적는 형식

RDF 트리플을 그대로 쓰면 URI가 길다.  
**Turtle**은 같은 RDF를 압축해 사람이 읽기 쉽게 표현한다.

```turtle
@prefix ex: <http://example.org/kg/> .

ex:모나리자
    ex:별명 "라 조콘다"@ko ;
    ex:제작연도 1503 .
```

핵심 기호:

```text
;  → 같은 주어를 계속 사용
,  → 같은 주어 + 같은 술어를 계속 사용
```

반대로 `N-Triples(nt)`는 압축하지 않는다.

```text
한 줄 = 트리플 하나
```

---

## RDF와 LPG의 관계

RDF와 LPG는 서로 완전히 다른 데이터가 아니라 **같은 그래프를 표현하는 방식이 다르다.**

| RDF | LPG |
|---|---|
| 주어·술어·목적어 | 노드·관계·속성 |
| 모든 사실을 트리플로 표현 | 속성을 노드·관계 내부에 저장 가능 |
| URI 중심 | 레이블·속성 중심 |
| 표준 데이터 연결에 강함 | 서비스 내부 탐색·운영에 편리 |

```text
RDF
알베르트 아인슈타인 ──국적──> 독일

LPG
(:Person {name:"알베르트 아인슈타인"})
-[:NATIONALITY]->
(:Country {name:"독일"})
```

---

# 3. rdflib으로 RDF 그래프 만들기

파이썬에서는 `rdflib`으로 RDF 그래프를 직접 만들 수 있다.

```python
from rdflib import Graph, Namespace

EX = Namespace("http://example.org/kg/")

graph = Graph()
graph.bind("ex", EX)

for subject, predicate, obj in kg_triples:
    graph.add((
        EX[subject.replace(" ", "_")],
        EX[predicate],
        EX[obj.replace(" ", "_")],
    ))
```

```text
Graph()       → RDF 그래프 생성
Namespace()   → URI 앞부분 정의
graph.add()   → 트리플 추가
graph.query() → SPARQL 실행
serialize()   → Turtle 등으로 출력
```

원본 실습에서는 온톨로지를 통과한 약 38개의 트리플을 RDF 그래프로 옮겼다.

---

## 온톨로지도 RDF로 표현 가능

파이썬의 `dict`로 만든 규칙도 RDF/RDFS 표준 표현으로 옮길 수 있다.

```python
from rdflib import RDF, RDFS

# "마리 퀴리는 인물이다"
graph.add((
    EX["마리_퀴리"],
    RDF.type,
    EX["인물"],
))

# "이론물리학자는 물리학자의 하위 타입이다"
graph.add((
    EX["이론물리학자"],
    RDFS.subClassOf,
    EX["물리학자"],
))

# 국적 관계: 인물 → 국가
graph.add((EX["국적"], RDFS.domain, EX["인물"]))
graph.add((EX["국적"], RDFS.range, EX["국가"]))
```

주요 표현:

| 표현 | 의미 |
|---|---|
| `rdf:type` / `a` | 개체가 어떤 타입인지 |
| `rdfs:Class` | 타입 자체를 선언 |
| `rdfs:subClassOf` | 타입의 상하 관계 |
| `rdfs:domain` | 관계의 주어 타입 |
| `rdfs:range` | 관계의 목적어 타입 |

```text
rdf:type
→ "마리 퀴리는 인물이다"

rdfs:subClassOf
→ "이론물리학자는 물리학자의 하위 개념이다"

domain / range
→ "국적 관계는 인물에서 국가로 이어진다"
```

---

# 4. SPARQL 핵심

**SPARQL**은 RDF 그래프를 조회하는 표준 질의어다.

```text
RDB → SQL
RDF → SPARQL
```

기본 구조:

```sparql
PREFIX ex: <http://example.org/kg/>

SELECT ?person
WHERE {
    ?person ex:직업 ex:물리학자 .
}
```

읽는 법:

```text
?person            → 모르는 값, 즉 변수
ex:직업            → 관계
ex:물리학자        → 알고 있는 값
```

즉:

> "직업이 물리학자인 사람은 누구인가?"

---

## 여러 패턴을 같은 변수로 연결 = 조인

```sparql
SELECT ?person ?country
WHERE {
    ?person ex:직업 ex:물리학자 .
    ?person ex:국적 ?country .
}
```

두 줄에서 같은 `?person`을 사용했기 때문에:

```text
물리학자인 사람
AND
그 사람의 국적
```

을 동시에 만족하는 조합만 남는다.

관계형 DB의 `JOIN`과 비슷한 역할이다.

---

## 자주 쓰는 조건 문법

모든 문법을 따로 외우기보다 역할별로 묶어서 기억하면 된다.

| 문법 | 역할 |
|---|---|
| `FILTER` | 조건에 맞는 결과만 남김 |
| `UNION` | 두 조건 중 하나라도 만족 |
| `OPTIONAL` | 값이 있으면 넣고 없어도 행 유지 |
| `FILTER NOT EXISTS` | 특정 관계가 없는 것만 |
| `DISTINCT` | 중복 제거 |
| `ORDER BY` | 정렬 |
| `LIMIT` | 결과 개수 제한 |
| `COUNT`, `GROUP BY` | 그룹별 집계 |
| `ASK` | 존재 여부를 True/False로 반환 |

### `OPTIONAL`이 중요한 이유

```sparql
SELECT ?person ?country
WHERE {
    ?person ex:직업 ex:작곡가 .
    OPTIONAL {
        ?person ex:국적 ?country .
    }
}
```

국적이 없어도 사람 자체는 결과에 남는다.

```text
OPTIONAL 없음
→ 국적 없는 사람은 행 자체가 사라짐

OPTIONAL 있음
→ 사람은 남고 country만 빈 값
```

### `UNION` + `DISTINCT`

```sparql
SELECT DISTINCT ?person
WHERE {
    { ?person ex:직업 ex:화가 . }
    UNION
    { ?person ex:직업 ex:작곡가 . }
}
```

```text
UNION    → A 또는 B
DISTINCT → 두 조건에 모두 걸려 생긴 중복 제거
```

---

## 속성 경로: 여러 홉을 한 줄로 탐색

미술관 예시:

```mermaid
flowchart LR
    A["모나리자"] -->|창작자| B["레오나르도 다 빈치"]
    B -->|국적| C["피렌체 공화국"]
```

패턴을 두 줄로 쓰면:

```sparql
SELECT ?work ?country
WHERE {
    ?work ex:창작자 ?artist .
    ?artist ex:국적 ?country .
}
```

속성 경로를 사용하면:

```sparql
SELECT ?work ?country
WHERE {
    ?work ex:창작자/ex:국적 ?country .
}
```

```text
ex:창작자/ex:국적
= 창작자 관계 1홉
→ 국적 관계 1홉
= 총 2홉
```

중간 노드인 작가까지 결과로 보고 싶다면 두 줄 형태가 더 적합하다.

---

## SELECT 외의 주요 질의

### ASK: 존재 여부만 확인

```sparql
ASK {
    ex:마리_퀴리 ex:직업 ex:물리학자 .
}
```

결과:

```text
True / False
```

### CONSTRUCT: 검색 결과로 새 그래프 생성

```sparql
CONSTRUCT {
    ?work ex:작가국적 ?country .
}
WHERE {
    ?work ex:창작자/ex:국적 ?country .
}
```

기존의:

```text
작품 → 작가 → 국가
```

를 다음처럼 요약한 새 그래프로 만들 수 있다.

```text
작품 → 작가국적 → 국가
```

### INSERT / DELETE: 그래프 수정

```sparql
INSERT DATA {
    ex:모나리자 ex:제작연도 "1503" .
}
```

```sparql
DELETE DATA {
    ex:모나리자 ex:제작연도 "1503" .
}
```

RDF에는 별도의 `UPDATE` 문장이 있는 것이 아니라 보통:

```text
기존 트리플 DELETE
+
새 트리플 INSERT
```

방식으로 값을 변경한다.

---

# 5. Wikidata에 직접 SPARQL 보내기

Wikidata에서는 항목과 속성을 번호로 사용한다.

```text
wd:Q937       → 아인슈타인
wd:Q7186      → 마리 퀴리
wdt:P106      → 직업
wdt:P27       → 국적
wd:Q169470    → 물리학자
```

표준 SPARQL 예시:

```sparql
PREFIX wd:   <http://www.wikidata.org/entity/>
PREFIX wdt:  <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?person ?name ?countryName
WHERE {
    VALUES ?person {
        wd:Q937
        wd:Q935
        wd:Q7186
    }

    ?person wdt:P106 wd:Q169470 .
    ?person wdt:P27 ?country .

    ?person rdfs:label ?name .
    FILTER(lang(?name) = "ko")

    ?country rdfs:label ?countryName .
    FILTER(lang(?countryName) = "ko")
}
ORDER BY ?name ?countryName
```

핵심 해석:

```text
VALUES
→ 검색 대상을 먼저 제한

?person wdt:P106 wd:Q169470
→ 직업이 물리학자인 사람

?person wdt:P27 ?country
→ 같은 사람의 국적

rdfs:label
→ URI에 사람이 읽을 이름 연결

FILTER(lang(...) = "ko")
→ 한국어 이름만 선택
```

Wikidata 공식 엔드포인트의 `SERVICE wikibase:label`은 편리하지만 **Wikidata 전용 기능**이다.

다른 SPARQL 엔드포인트에서도 동작하는 코드를 만들려면 `rdfs:label`을 직접 사용하는 방식이 더 일반적이다.

---

## 계층까지 포함한 검색

단순 검색:

```sparql
?person wdt:P106 wd:Q169470 .
```

은 직업 값이 **정확히 `물리학자`로 등록된 사람**만 찾는다.

하지만:

```text
이론물리학자 ──상위 개념──> 물리학자
핵물리학자   ──상위 개념──> 물리학자
```

처럼 하위 직업까지 포함하려면 계층을 따라가야 한다.

```sparql
?person wdt:P106/wdt:P279* wd:Q169470 .
```

해석:

```text
P106      → 사람의 직업으로 이동
P279*     → 그 직업의 상위 개념을 0번 이상 따라감
Q169470   → 최종적으로 물리학자에 도달
```

`*`가 **0홉도 허용**하므로 직업이 처음부터 `물리학자`인 사람도 포함한다.

> 원본 노트북의 해당 코드 셀은 설명과 달리 `P279+`를 사용해 직접 `물리학자`인 경우를 제외하는 형태가 되어 있음.  
> 정리본에서는 설명 의도인 **"물리학자 자체 + 모든 하위 직업"**에 맞게 `P279*`로 통일.

---

# 6. 핵심 흐름 정리

```text
1. Wikidata에서 사실을 가져옴
   ↓
2. [주어, 술어, 목적어] 트리플로 표현
   ↓
3. 온톨로지로 타입·관계·허용 범위를 정의
   ↓
4. 규칙에 맞는 사실만 지식 그래프에 저장
   ↓
5. RDF URI·Literal 형태로 표준화
   ↓
6. rdflib Graph에 저장
   ↓
7. SPARQL로 패턴 검색·조인·경로 탐색
   ↓
8. 필요하면 CONSTRUCT / INSERT / DELETE로 그래프 생성·수정
   ↓
9. 같은 SPARQL을 Wikidata 같은 외부 지식 그래프에도 사용
```

## 개념 구분

| 개념 | 핵심 |
|---|---|
| 지식 그래프 | 현실의 사실을 개체와 관계의 연결로 저장 |
| 온톨로지 | 어떤 타입·관계·값을 허용할지 정의 |
| RDF | 사실을 주어·술어·목적어로 표현하는 표준 |
| Turtle | RDF 트리플을 사람이 읽기 좋게 적는 형식 |
| rdflib | 파이썬에서 RDF 그래프를 만들고 다루는 라이브러리 |
| SPARQL | RDF 그래프를 조회·생성·수정하는 질의 언어 |
| Wikidata | SPARQL로 조회 가능한 공개 지식 그래프 |

## SPARQL 최소 치트시트

```sparql
# 기본 검색
SELECT ?x
WHERE {
    ?x ex:관계 ex:값 .
}

# 두 관계 연결
?x ex:관계1 ?middle .
?middle ex:관계2 ?y .

# 2홉 경로
?x ex:관계1/ex:관계2 ?y .

# 선택 정보
OPTIONAL { ?x ex:관계 ?y . }

# OR
{ 패턴1 }
UNION
{ 패턴2 }

# 중복 제거
SELECT DISTINCT ?x

# 집계
SELECT ?job (COUNT(?person) AS ?count)
WHERE {
    ?person ex:직업 ?job .
}
GROUP BY ?job
ORDER BY DESC(?count)
```

### 최종 핵심

> **지식 그래프는 사실의 연결망이고, 온톨로지는 그 연결망의 규칙이다. RDF는 이를 표준 트리플로 표현하며, SPARQL은 그 트리플의 빈칸을 찾아 관계를 탐색하는 언어다.**
