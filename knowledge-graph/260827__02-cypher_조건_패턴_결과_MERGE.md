# Cypher 조건 · 패턴 · 결과 정리 · MERGE 문법

> 앞의 기본 문법(`CREATE`, `MATCH`, `RETURN`, `SET`, `DELETE`)에서 이어지는 내용.  
> 이번 단계는 **조건 검색 → 관계 탐색 → 결과 정리 → 중복 없는 적재** 흐름으로 보면 됨.

---

## 1. WHERE로 조건 검색

기본 구조:

```cypher
MATCH (변수:레이블)
WHERE 조건
RETURN 반환값
```

동작 순서:

```text
MATCH  → 찾을 노드·패턴 지정
WHERE  → 조건에 맞는 것만 남김
RETURN → 필요한 값 반환
```

### 비교 연산자

| 문법 | 의미 |
|---|---|
| `=` | 같다 |
| `<>` | 같지 않다 |
| `>` | 초과 |
| `<` | 미만 |
| `>=` | 이상 |
| `<=` | 이하 |

예:

```cypher
MATCH (e:Employee)
WHERE e.years >= 3
RETURN e.name AS name
```

결과:

```text
김서준
박도윤
이하은
```

같지 않음:

```cypher
MATCH (e:Employee)
WHERE e.role <> '백엔드'
RETURN e.name AS name
```

> Cypher에서는 같지 않음을 `<>`로 표현.

### 날짜 비교

날짜 속성도 비교 연산자 사용 가능.

```cypher
MATCH (p:Project)
WHERE p.deadline >= date('2026-07-01')
RETURN p.name AS name,
       p.deadline AS deadline
```

`date(...)`와 일반 문자열은 같은 자료형이 아님.

```text
date('2026-12-31')   → Date
'2026-12-31'         → String
```

날짜 비교가 목적이면 처음 저장할 때부터 `date()`로 저장하는 것이 중요.

---

### AND · OR

여러 조건을 조합할 때 사용.

```cypher
MATCH (e:Employee)
WHERE e.role = '백엔드'
  AND e.years <= 3
RETURN e.name AS name
```

```text
AND → 모든 조건 만족
OR  → 하나 이상의 조건 만족
```

예:

```cypher
MATCH (e:Employee)
WHERE e.role = '백엔드'
   OR e.years <= 3
RETURN e.name AS name
```

조건이 복잡하면 괄호로 우선순위를 명시.

```cypher
WHERE e.role = '백엔드'
  AND (e.years >= 3 OR e.level = '시니어')
```

---

### NOT · IS NULL

조건을 반대로 만들 때:

```cypher
MATCH (e:Employee)
WHERE NOT e.role = '백엔드'
RETURN e.name AS name
```

속성이 존재하지 않는 노드를 찾을 때:

```cypher
MATCH (e:Employee)
WHERE e.role IS NULL
RETURN e.name AS name
```

속성이 있는 노드:

```cypher
MATCH (e:Employee)
WHERE e.role IS NOT NULL
RETURN e.name AS name
```

중요한 구분:

```text
role = '백엔드'
→ 값이 실제로 '백엔드'

NOT role = '백엔드'
→ role 값이 존재하면서 백엔드가 아님

role IS NULL
→ role 속성 자체가 없음
```

따라서 속성이 없는 노드는 다음 조건에 자동으로 포함된다고 생각하면 안 됨.

```cypher
WHERE NOT e.role = '백엔드'
```

원본 실습에서도 `role`이 없는 직원은 `IS NULL`로 따로 조회됨.

### 조건 문법 압축

```cypher
MATCH (n:Label)
WHERE n.age >= 20
  AND n.status <> '종료'
RETURN n
```

```text
조건 비교     : =, <>, >, <, >=, <=
조건 결합     : AND, OR
조건 반전     : NOT
속성 없음     : IS NULL
속성 존재     : IS NOT NULL
```

---

## 2. 여러 노드를 잇는 관계 패턴

Cypher의 핵심은 관계를 따라가며 그래프의 모양 자체를 `MATCH`에 적는 것.

### 체인 패턴

기본 형태:

```text
(a)-[:REL1]->(b)-[:REL2]->(c)
```

예:

```cypher
MATCH
(e:Employee {name: '김서준'})
-[:WORKS_IN]->
(t:Team)
-[:OWNS]->
(p:Project)

RETURN p.name AS name
```

의미:

```text
김서준
  ↓ WORKS_IN
소속 팀
  ↓ OWNS
팀이 맡은 프로젝트
```

중간 노드는 경로를 연결하는 용도로만 사용할 수도 있음.

```cypher
(t:Team)
```

`t`를 `RETURN`하지 않아도 패턴 탐색에는 사용됨.

---

### 역방향 탐색

관계의 실제 방향은 그대로 두고 반대쪽 노드에서 시작할 수 있음.

관계가 다음과 같다면:

```text
Employee -[:ASSIGNED_TO]-> Project
```

프로젝트에서 직원 쪽으로 찾기:

```cypher
MATCH
(p:Project {name: '결제시스템'})
<-[:ASSIGNED_TO]-
(e:Employee)

RETURN e.name AS name
```

아래 문법과 같은 관계를 찾음.

```cypher
MATCH
(e:Employee)
-[:ASSIGNED_TO]->
(p:Project {name: '결제시스템'})

RETURN e.name AS name
```

즉:

```text
->  관계 방향으로 탐색
<-  관계를 거슬러 탐색
```

관계 자체의 저장 방향이 바뀌는 것은 아님.

---

### 여러 관계를 연속으로 역탐색

```cypher
MATCH
(p:Project {name: '결제시스템'})
<-[:OWNS]-
(t:Team)
<-[:WORKS_IN]-
(e:Employee)

RETURN e.name AS name
```

구조:

```text
Employee → Team → Project
                      ↑
               여기서 시작
```

결과는 결제시스템을 **직접 배정받은 사람**이 아니라,
결제시스템을 맡은 **팀에 속한 직원**을 찾는 것.

그래프에서는 어떤 관계를 따라갔는지가 검색 의미를 결정함.

---

### 가운데 노드에서 양쪽으로 연결

```cypher
MATCH
(:Team {name: '개발팀'})
<-[:WORKS_IN]-
(e:Employee)
-[:ASSIGNED_TO]->
(:Project {name: '앱개편'})

RETURN e.name AS name
```

의미:

```text
개발팀 소속
AND
앱개편 프로젝트 배정
```

공통 변수 `e`를 중심으로 두 관계 조건을 동시에 만족하는 노드를 찾음.

---

### 공유 노드 패턴

같은 프로젝트를 공유하는 직원:

```cypher
MATCH
(a:Employee {name: '김서준'})
-[:ASSIGNED_TO]->
(p:Project)
<-[:ASSIGNED_TO]-
(b:Employee)

RETURN b.name AS name
```

구조:

```text
김서준 ──ASSIGNED_TO──> 프로젝트 <──ASSIGNED_TO── 동료
```

`p`를 양쪽 관계가 공유하기 때문에 **같은 프로젝트를 가진 사람**이라는 조건이 만들어짐.

같은 방식으로:

```text
학생 → 동아리 ← 다른 학생
사람 → 영화 ← 다른 사람
상품 → 카테고리 ← 다른 상품
```

처럼 사용할 수 있음.

### 한 MATCH 패턴과 여러 MATCH 절

원본 실습에서는 다음 두 형태의 차이도 확인함.

한 패턴으로 연결:

```cypher
MATCH
(a:Employee {name: '김서준'})
-[:ASSIGNED_TO]->
(p)
<-[:ASSIGNED_TO]-
(b:Employee)

RETURN b.name AS name
```

MATCH를 나눠서 작성:

```cypher
MATCH
(a:Employee {name: '김서준'})
-[:ASSIGNED_TO]->
(p)

MATCH
(p)
<-[:ASSIGNED_TO]-
(b:Employee)

RETURN b.name AS name
```

원본 데이터에서는 첫 번째 형태에서 김서준 자신이 빠지고,
두 번째 형태에서는 김서준도 결과에 포함됨.

학습 핵심은 다음 정도로 보면 됨.

```text
같은 MATCH 안의 연결 패턴
→ 하나의 연결된 그래프 패턴으로 매칭

MATCH를 나눔
→ 앞에서 찾은 변수를 다음 MATCH에서 다시 사용
```

자기 자신을 확실히 제외하려면 패턴 구조에만 기대지 않고 조건을 명시하는 편이 명확함.

```cypher
WHERE b <> a
```

---

## 3. DISTINCT · ORDER BY · LIMIT으로 결과 정리

Cypher 결과의 행 수는 **노드 종류의 개수**가 아니라
`MATCH` 패턴이 실제로 성립한 횟수를 기준으로 만들어짐.

예:

```cypher
MATCH
(p:Project)
<-[:ASSIGNED_TO]-
(e:Employee)

RETURN p.name AS name
```

직원 5명이 프로젝트에 배정되어 있다면 프로젝트가 2개뿐이어도 결과는 5행이 될 수 있음.

```text
결제시스템
결제시스템
결제시스템
앱개편
앱개편
```

즉:

```text
MATCH된 관계/조합 하나
→ 결과 한 행
```

---

### 독립된 패턴을 쉼표로 나열

```cypher
MATCH (t:Team), (p:Project)
RETURN t.name AS team,
       p.name AS project
```

두 패턴 사이에 관계가 없기 때문에 가능한 모든 조합이 생성됨.

예:

```text
팀 2개 × 프로젝트 2개 = 4행
```

관계를 의도한다면 실제 관계 패턴을 적어야 함.

```cypher
MATCH (t:Team)-[:OWNS]->(p:Project)
RETURN t.name, p.name
```

---

### DISTINCT

중복 행 제거:

```cypher
MATCH
(p:Project)
<-[:ASSIGNED_TO]-
(e:Employee)

RETURN DISTINCT p.name AS name
```

결과:

```text
결제시스템
앱개편
```

기본 구조:

```text
RETURN DISTINCT 반환값
```

주의할 점은 `DISTINCT`가 특정 열 하나가 아니라 **RETURN으로 만든 행 전체**를 기준으로 본다는 것.

```cypher
RETURN DISTINCT
       p.name AS project,
       e.name AS employee
```

프로젝트 이름이 같아도 직원 이름이 다르면 서로 다른 행이므로 제거되지 않음.

```text
DISTINCT p.name
→ 프로젝트 이름 기준의 서로 다른 결과

DISTINCT p.name, e.name
→ (프로젝트, 직원) 조합 기준
```

---

### ORDER BY

정렬:

```cypher
MATCH (e:Employee)
RETURN e.name AS name,
       e.years AS years
ORDER BY e.years DESC
```

```text
ASC  → 오름차순
DESC → 내림차순
```

`ASC`는 기본값이라 생략 가능.

```cypher
ORDER BY e.years
```

여러 정렬 기준도 지정 가능.

```cypher
ORDER BY e.years, e.name
```

의미:

```text
1차 정렬: years
2차 정렬: years가 같으면 name
```

동점 결과의 순서를 안정적으로 만들고 싶으면 보조 정렬 기준을 두는 것이 좋음.

---

### LIMIT

위에서 지정한 개수만 반환.

```cypher
MATCH (e:Employee)
RETURN e.name AS name,
       e.years AS years
ORDER BY e.years DESC
LIMIT 3
```

결과:

```text
김서준 5
박도윤 4
이하은 3
```

일반적으로:

```text
MATCH
→ WHERE
→ RETURN
→ ORDER BY
→ LIMIT
```

흐름으로 읽으면 됨.

예:

```cypher
MATCH (e:Employee)
WHERE e.years >= 2
RETURN e.name AS name,
       e.years AS years
ORDER BY e.years DESC, e.name
LIMIT 3
```

---

## 4. MERGE로 중복 없이 적재

`CREATE`는 실행할 때마다 새 데이터를 생성.

```cypher
CREATE (:Team {name: '인프라팀'})
```

같은 문장을 두 번 실행하면 같은 속성을 가진 노드가 두 개 생길 수 있음.

`MERGE`는 먼저 해당 패턴이 존재하는지 찾음.

```cypher
MERGE (:Team {name: '인프라팀'})
```

동작:

```text
이미 있음 → 기존 것 사용
없음      → 새로 생성
```

따라서 같은 쿼리를 반복해도 결과 상태가 같도록 만드는 **멱등 적재**에 사용.

```cypher
MERGE (:Team {name: '인프라팀'})
MERGE (:Team {name: '인프라팀'})
```

원본 실습 결과:

```text
인프라팀 노드 수: 1
```

반대로 `CREATE` 두 번:

```cypher
CREATE (:Team {name: '중복팀'})
CREATE (:Team {name: '중복팀'})
```

결과:

```text
중복팀 노드 수: 2
```

---

### 관계 MERGE

기존 노드를 찾은 뒤 관계만 중복 없이 생성.

```cypher
MATCH
(e:Employee {name: '김서준'}),
(t:Team {name: '인프라팀'})

MERGE (e)-[:WORKS_IN]->(t)
```

같은 쿼리를 여러 번 실행해도 해당 관계는 하나로 유지됨.

기본 패턴:

```text
MATCH 양쪽 노드
MERGE (a)-[:REL]->(b)
```

---

### MERGE가 같은 것으로 판단하는 기준

중요한 부분.

```cypher
MERGE (:Team {name: '보안팀'})
```

과

```cypher
MERGE (:Team {
    name: '보안팀',
    floor: 7
})
```

은 같은 `name`을 가졌지만 MERGE에 적은 전체 패턴이 다름.

원본 실습에서는 결과가 노드 2개가 됨.

따라서 MERGE 패턴에는 보통 **식별에 필요한 속성만** 넣음.

```cypher
MERGE (t:Team {name: '보안팀'})
SET t.floor = 7
```

권장 구조:

```text
MERGE → 어떤 개체인지 식별
SET   → 나머지 속성 저장·수정
```

---

### 관계 속성도 MERGE 기준에 포함

기존 관계:

```text
(e)-[:ASSIGNED_TO]->(p)
```

가 있을 때:

```cypher
MERGE
(e)-[:ASSIGNED_TO {hours: 10}]->(p)
```

를 실행하면 기존 관계에 `hours`가 자동으로 붙는 것이 아님.

```text
기존 관계:
ASSIGNED_TO

MERGE가 찾는 관계:
ASSIGNED_TO {hours: 10}
```

패턴이 다르기 때문에 새 관계가 생성될 수 있음.

따라서 관계도 다음 형태가 안전함.

```cypher
MERGE (e)-[r:ASSIGNED_TO]->(p)
SET r.hours = 10
```

---

### ON CREATE SET · ON MATCH SET

처음 생성될 때와 이미 존재할 때의 동작을 구분.

```cypher
MERGE (t:Team {name: '리서치팀'})

ON CREATE SET
    t.created_at = 2026

ON MATCH SET
    t.seen = 1
```

첫 실행:

```text
리서치팀 없음
→ 노드 생성
→ ON CREATE SET 실행
```

결과:

```python
{
    'created_at': 2026,
    'seen': None
}
```

두 번째 실행:

```text
리서치팀 이미 있음
→ 기존 노드 매칭
→ ON MATCH SET 실행
```

결과:

```python
{
    'created_at': 2026,
    'seen': 1
}
```

구조:

```text
MERGE (식별 패턴)
ON CREATE SET 처음 생성할 때의 값
ON MATCH SET  이미 있을 때의 값
```

---

## 5. Python 값을 `$파라미터`로 넘기기

Cypher 문자열 안에 Python 값을 직접 이어 붙이기보다 파라미터 사용.

쿼리:

```cypher
MERGE (:Team {name: $team})
```

Python:

```python
run_cypher(
    "MERGE (:Team {name: $team})",
    team="데이터팀"
)
```

`$team`은 Cypher 안의 자리표시자이고,
실제 값은 `run_cypher()`의 키워드 인자로 전달.

여러 값:

```python
run_cypher(
    """
    MATCH (e:Employee)
    WHERE e.years >= $min_years
    RETURN e.name AS name
    LIMIT $limit
    """,
    min_years=3,
    limit=5
)
```

기본 관계:

```text
Cypher                Python
$team       ←→        team=value
$name       ←→        name=value
$min_years  ←→        min_years=value
```

반복 적재에도 같은 쿼리를 재사용 가능.

```python
new_teams = [
    '인프라팀',
    '보안팀',
    '데이터팀'
]

for team in new_teams:
    run_cypher(
        "MERGE (:Team {name: $team})",
        team=team
    )
```

장점:

```text
쿼리 구조와 데이터 분리
문자열 따옴표 처리 단순화
같은 쿼리 재사용
입력값을 문자열로 직접 조립하지 않음
```

---

## 핵심 문법 압축

| 목적 | 문법 |
|---|---|
| 조건 지정 | `WHERE 조건` |
| 같지 않음 | `<>` |
| 조건 조합 | `AND`, `OR` |
| 조건 반전 | `NOT` |
| 속성 없음 | `IS NULL` |
| 속성 존재 | `IS NOT NULL` |
| 연속 관계 | `(a)-[:R1]->(b)-[:R2]->(c)` |
| 역방향 탐색 | `(a)<-[:REL]-(b)` |
| 공유 노드 | `(a)-[:REL]->(x)<-[:REL]-(b)` |
| 중복 행 제거 | `RETURN DISTINCT ...` |
| 오름차순 | `ORDER BY x ASC` |
| 내림차순 | `ORDER BY x DESC` |
| 결과 제한 | `LIMIT n` |
| 중복 없는 생성 | `MERGE 패턴` |
| 처음 생성 시 수정 | `ON CREATE SET ...` |
| 기존 데이터 매칭 시 수정 | `ON MATCH SET ...` |
| Python 값 전달 | `$name` |

### 전체 작성 흐름

```cypher
MATCH (n:Label)
WHERE 조건
RETURN DISTINCT
       n.property AS value
ORDER BY value DESC
LIMIT 5
```

적재:

```cypher
MERGE (n:Label {id: $id})
ON CREATE SET n.created_at = $created_at
ON MATCH SET n.updated_at = $updated_at
```

관계 적재:

```cypher
MATCH (a:LabelA {id: $a_id}),
      (b:LabelB {id: $b_id})

MERGE (a)-[r:REL]->(b)
SET r.value = $value
```

---

## 이번 단계 핵심

```text
WHERE
→ MATCH로 찾은 결과에 조건 적용

관계 체인
→ 노드 사이의 경로 자체를 검색 조건으로 사용

DISTINCT
→ 같은 RETURN 행 제거

ORDER BY + LIMIT
→ 정렬 후 필요한 상위 결과만 반환

MERGE
→ 같은 패턴이 있으면 재사용, 없으면 생성

$파라미터
→ Python 값과 Cypher 쿼리를 분리
```

### CREATE와 MERGE 구분

```text
CREATE
→ 항상 새로 생성

MERGE
→ 먼저 찾고 없을 때만 생성
```

MERGE를 안정적으로 쓰는 핵심:

```text
1. MERGE에는 식별 속성 위주로 작성
2. 나머지 값은 SET으로 관리
3. 관계 속성도 MERGE 패턴에 무작정 넣지 않음
4. 처음/기존 동작을 나누려면 ON CREATE / ON MATCH 사용
```

---

## 원본 실습에서 정리·교정한 부분

원본의 핵심 문법과 실행 결과는 유지하되, 학습용 문서에서는 몇 가지 실습 코드를 정돈함.

### 관계 방향 표기 통일

원본 따라하기 예제에는:

```cypher
(c:Club)-[:HOSTS]-(e:Event)
```

처럼 방향을 생략한 부분이 있음.

초기 그래프가 `Club -[:HOSTS]-> Event`로 정의되어 있으므로 문법 학습에서는 다음처럼 방향을 명시.

```cypher
(c:Club)-[:HOSTS]->(e:Event)
```

방향을 생략한 패턴 자체가 잘못된 것은 아니지만,
이번 단계에서는 **관계 방향 학습**을 위해 명시하는 형태로 정리함.

### 응용 코드의 관계명 오타

초기 데이터의 직원-팀 관계는:

```text
WORKS_IN
```

인데 응용 셀에서는:

```text
WORK_IN
```

으로 작성된 부분이 있음.

정리본에서는 기존 모델에 맞춰:

```cypher
(e)-[:WORKS_IN]->(t)
```

로 통일.

### MERGE와 속성 업데이트 분리

관계 속성을 다음처럼 MERGE 패턴 안에 바로 넣으면:

```cypher
MERGE (e)-[:ASSIGNED_TO {hours: 10}]->(p)
```

속성이 없는 기존 관계와 다른 패턴으로 판단되어 관계가 추가될 수 있음.

학습용 권장 형태:

```cypher
MERGE (e)-[r:ASSIGNED_TO]->(p)
SET r.hours = 10
```

즉 **식별은 MERGE, 값 갱신은 SET**으로 분리해 이해하면 됨.
