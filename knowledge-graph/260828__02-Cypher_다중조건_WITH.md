# Cypher 다중 조건 · OPTIONAL MATCH · WITH 문법 정리

> 여러 조건으로 결과를 거르고, 관계의 존재 여부를 검사하고,  
> `WITH`로 중간 결과를 가공한 뒤 정렬·페이징하는 문법 중심 정리.

---

## 1. `WHERE` 조건 확장: 목록 · 문자열 · 정규식

기본 비교 연산자 외에도 `WHERE`에서 목록과 문자열을 직접 검사할 수 있다.

### 목록과 문자열 조건

| 문법 | 의미 | 예시 |
|---|---|---|
| `IN [...]` | 목록 중 하나와 일치 | `c.name IN ['일식', '양식']` |
| `CONTAINS` | 문자열 일부 포함 | `r.name CONTAINS '홍'` |
| `STARTS WITH` | 특정 문자열로 시작 | `r.name STARTS WITH '스'` |
| `ENDS WITH` | 특정 문자열로 끝 | `r.name ENDS WITH '각'` |

예:

```cypher
MATCH (r:Restaurant)-[:SERVES]->(c:Cuisine)
WHERE c.name IN ['일식', '양식']
RETURN r.name AS 식당, c.name AS 요리
ORDER BY 식당
```

`IN`은 여러 개의 `OR`를 짧게 표현하는 형태로 볼 수 있다.

```cypher
c.name IN ['일식', '양식']
```

```cypher
c.name = '일식' OR c.name = '양식'
```

문자열 검색:

```cypher
WHERE r.name CONTAINS '홍'
WHERE r.name STARTS WITH '스'
WHERE r.name ENDS WITH '각'
```

`CONTAINS`, `STARTS WITH`, `ENDS WITH`는 문자열 전용이며 대소문자를 구분한다.

### 여러 조건 조합

새로운 연산자도 기존 `AND`, `OR`, `NOT`과 그대로 조합한다.

```cypher
MATCH (r:Restaurant)-[:SERVES]->(c:Cuisine)
WHERE c.name IN ['일식', '양식']
  AND r.price <= 15000
RETURN r.name AS 식당
```

조건이 복잡해지면 괄호로 우선순위를 명확하게 하는 편이 안전하다.

```cypher
WHERE (A OR B) AND C
```

### 정규식 `=~`

여러 문자열 패턴을 한 번에 표현하거나 대소문자를 무시해야 할 때 사용한다.

```cypher
WHERE r.name =~ '.*(효|홍)'
```

의미:

```text
.*      → 앞에 어떤 문자열이 와도 됨
(효|홍) → 효 또는 홍
```

즉 이름이 `효` 또는 `홍`으로 끝나는 값을 찾는다.

자주 쓰는 형태:

| 문법 | 의미 |
|---|---|
| `r.name =~ '스.*'` | `스`로 시작 |
| `r.name =~ '.*각'` | `각`으로 끝 |
| `r.name =~ '.*(효\|홍)'` | `효` 또는 `홍`으로 끝 |
| `s =~ '(?i)bistro.*'` | 대소문자 무시하고 `bistro`로 시작 |

```cypher
RETURN 'BistroHong' =~ '(?i)bistro.*' AS result
```

간단한 접두·접미·포함 조건은 정규식보다 `STARTS WITH`, `ENDS WITH`, `CONTAINS`가 읽기 쉽다.

### 파라미터 목록: `IN $names`

목록이 파이썬 코드나 사용자 입력에서 정해진다면 쿼리에 직접 문자열을 조립하지 않고 파라미터로 넘긴다.

```cypher
MATCH (r:Restaurant)
WHERE r.name IN $names
RETURN r.name AS 식당
ORDER BY 식당
```

파이썬:

```python
picked = ['스시효', '딤섬각', '없는집']

rows = run_cypher(
    """
    MATCH (r:Restaurant)
    WHERE r.name IN $names
    RETURN r.name AS 식당
    ORDER BY 식당
    """,
    names=picked
)
```

핵심:

```text
쿼리 구조 → 고정
실제 값   → 파라미터로 전달
```

다음처럼 문자열을 직접 이어 붙이는 방식은 피한다.

```python
# 권장하지 않음
"... IN ['" + "','".join(names) + "']"
```

값에 따옴표 등이 들어가면 쿼리가 깨질 수 있고, 외부 입력을 직접 조립하면 Cypher 주입 위험도 생긴다.

---

## 2. 관계를 조건으로 사용하기

그래프에서는 노드 속성뿐 아니라 **어떤 관계로 연결되어 있는가** 자체가 중요한 조건이 된다.

### 서로 다른 관계를 이어 붙이기

관계 종류가 달라도 하나의 패턴으로 연속해서 연결할 수 있다.

```cypher
MATCH (d:Diner)
      -[:VISITED]->
      (r:Restaurant)
      -[:LOCATED_IN]->
      (:Area {name:'강남'})
RETURN d.name AS 손님,
       r.name AS 식당
```

구조:

```text
Diner
  │ VISITED
  ▼
Restaurant
  │ LOCATED_IN
  ▼
Area
```

중간 노드를 같은 변수로 계속 사용하면 여러 `MATCH`로 나눌 수도 있다.

```cypher
MATCH (cp:Camper)-[:STAYED]->(c:Campsite)
MATCH (c)-[:HAS_FACILITY]->(f:Facility)
MATCH (m:Manager)-[:MANAGES]->(c)
RETURN cp.name, c.name, f.name, m.name
```

### `[:A|B]`: 한 칸에서 여러 관계 종류 허용

다음 두 문법은 의미가 다르다.

```cypher
(a)-[:A]->(b)-[:B]->(c)
```

```text
A 관계 한 칸
→ B 관계 한 칸
→ 총 두 단계
```

반면:

```cypher
(a)-[:A|B]->(x)
```

```text
한 칸만 이동
→ 그 한 칸의 관계가 A 또는 B
```

예:

```cypher
MATCH (r:Restaurant {name:'스시효'})
      -[x:SERVES|LOCATED_IN]->
      (t)
RETURN type(x) AS 관계종류,
       t.name AS 닿는곳
```

`type(x)`는 실제로 어떤 관계를 타고 온 행인지 확인할 때 사용한다.

> `[:A|B]`는 **여러 관계를 연속으로 타는 문법이 아니다.**

### 관계 존재 여부 자체를 조건으로 사용

특정 관계가 존재하는지만 보고 싶다면 패턴 자체를 조건으로 사용할 수 있다.

```cypher
MATCH (r:Restaurant)
WHERE (r)<-[:WORKS_AT]-(:Chef)
RETURN r.name AS 식당
```

반대는 `NOT`을 붙인다.

```cypher
MATCH (r:Restaurant)
WHERE NOT (r)<-[:WORKS_AT]-(:Chef)
RETURN r.name AS 식당
```

속성까지 포함할 수 있다.

```cypher
MATCH (r:Restaurant)
WHERE (r)-[:LOCATED_IN]->(:Area {name:'강남'})
RETURN r.name AS 식당
```

이 방식은 관계가 존재하는지만 검사하므로, 연결된 상대 노드를 결과에 출력할 필요가 없을 때 편하다.

### `EXISTS { }`: 관계 상대에도 조건 걸기

짧은 패턴 조건보다 더 복잡한 조건이 필요하면 `EXISTS { }`를 사용한다.

```cypher
MATCH (r:Restaurant)
WHERE EXISTS {
    (r)<-[:VISITED]-(d:Diner)
    WHERE d.name STARTS WITH '지'
}
RETURN r.name AS 식당
```

흐름:

```text
바깥에서 r 확보
    ↓
EXISTS 내부에서 d 생성
    ↓
d에 추가 WHERE 조건
    ↓
하나라도 만족하면 True
```

비교:

```cypher
# 단순히 관계 존재 여부만 확인
WHERE (r)<-[:WORKS_AT]-(:Chef)
```

```cypher
# 연결된 상대 노드에 별도 조건까지 적용
WHERE EXISTS {
    (r)<-[:VISITED]-(d:Diner)
    WHERE d.name STARTS WITH '지'
}
```

없는 경우를 찾으려면:

```cypher
WHERE NOT EXISTS {
    ...
}
```

`EXISTS { }` 안에서 만든 변수는 바깥 결과에 직접 사용할 수 없다.  
조건 검사에만 사용하는 지역 변수라고 보면 된다.

---

## 3. `OPTIONAL MATCH`: 연결이 없어도 행 유지

일반 `MATCH`는 패턴이 맞지 않으면 해당 행 자체가 사라진다.

```cypher
MATCH (r:Restaurant)
MATCH (ch:Chef)-[:WORKS_AT]->(r)
RETURN r.name, ch.name
```

셰프가 없는 식당은 결과에 나오지 않는다.

모든 식당을 유지하면서 셰프가 있을 때만 붙이려면:

```cypher
MATCH (r:Restaurant)
OPTIONAL MATCH (ch:Chef)-[:WORKS_AT]->(r)
RETURN r.name AS 식당,
       ch.name AS 셰프
```

결과 개념:

```text
식당          셰프
-----------------------
스시효        사토
국밥천국      null
라멘야마      null
```

즉:

```text
MATCH
→ 관계가 없으면 행 삭제

OPTIONAL MATCH
→ 관계가 없어도 행 유지
→ 못 찾은 값만 null
```

관계형 DB의 `LEFT JOIN`과 비슷한 생각으로 볼 수 있다.

### `OPTIONAL MATCH` 뒤의 `WHERE` 주의

다음처럼 바로 조건을 붙이면:

```cypher
MATCH (r:Restaurant)
OPTIONAL MATCH (ch:Chef)-[:WORKS_AT]->(r)
WHERE ch IS NULL
RETURN r.name, ch.name
```

이 `WHERE`는 **최종 결과를 거르는 조건**이 아니라 `OPTIONAL MATCH`가 어떤 패턴을 찾을지 결정하는 조건으로 붙는다.

`OPTIONAL MATCH`는 못 찾더라도 행을 남기므로, 기대한 방식으로 "셰프가 없는 식당만" 걸러지지 않는다.

이미 만들어진 결과를 대상으로 필터링하려면 `WITH`로 단계를 끊는다.

```cypher
MATCH (r:Restaurant)
OPTIONAL MATCH (ch:Chef)-[:WORKS_AT]->(r)

WITH r, ch
WHERE ch IS NULL

RETURN r.name AS 식당
```

흐름:

```text
모든 식당 확보
    ↓
셰프가 있으면 연결
    ↓
WITH로 현재 결과 확정
    ↓
ch IS NULL인 행만 필터링
```

단순히 "셰프가 없는 식당"만 찾는 목적이라면 더 짧게:

```cypher
WHERE NOT (r)<-[:WORKS_AT]-(:Chef)
```

라고 쓸 수 있다.

### 연결 여부를 `True / False`로 판별

경로가 없을 때도 한 행을 남기고 싶다면 `shortestPath()`를 `OPTIONAL MATCH`로 감쌀 수 있다.

```cypher
MATCH (a:Diner {name:'지민'}),
      (b:Diner {name:'서연'})

OPTIONAL MATCH p = shortestPath(
    (a)-[:VISITED*]-(b)
)

RETURN p IS NOT NULL AS connected
```

```text
경로 있음
→ p에 경로 저장
→ p IS NOT NULL = True

경로 없음
→ p = null
→ p IS NOT NULL = False
```

일반 `MATCH p = shortestPath(...)`라면 경로가 없을 때 행 자체가 반환되지 않는다.

### 관계 방향은 질문의 의미를 바꾼다

```cypher
(a)-[:VISITED*]-(b)
```

관계 방향을 무시하고 양쪽으로 이동한다.

```cypher
(a)-[:VISITED*]->(b)
```

관계가 저장된 방향으로만 이동한다.

예를 들어:

```text
Diner -[:VISITED]-> Restaurant
```

에서 두 손님이 같은 식당을 방문했는지 연결성을 보고 싶다면 식당에서 다른 손님 쪽으로 다시 이동해야 하므로 방향을 무시하는 패턴이 필요할 수 있다.

반대로 송금·배송·선수과목처럼 방향 자체가 의미를 가지면 화살표를 지켜야 한다.

---

## 4. `WITH`: 중간 결과를 다음 단계로 넘기기

`RETURN`이 최종 결과를 내고 쿼리를 끝낸다면, `WITH`는 값을 선택해서 **다음 쿼리 단계로 넘긴다.**

```text
MATCH
  ↓
WHERE
  ↓
WITH
  ↓
WHERE / MATCH / ORDER BY / LIMIT
  ↓
RETURN
```

### 값 그대로 넘기기

```cypher
MATCH (r:Restaurant)
WHERE r.rating >= 4.5

WITH r
WHERE r.price <= 50000

RETURN r.name AS 식당,
       r.rating AS 평점
ORDER BY 평점 DESC
```

단순히 조건 두 개를 나란히 적용하는 것뿐이라면:

```cypher
WHERE r.rating >= 4.5
  AND r.price <= 50000
```

처럼 한 번에 적는 것이 더 간단하다.

`WITH`는 **중간 결과를 따로 가공할 이유가 있을 때** 의미가 커진다.

### `WITH DISTINCT`

중간 단계에서 중복을 제거한 뒤 다음 처리를 이어 갈 수 있다.

```cypher
MATCH (r:Restaurant)-[:LOCATED_IN]->(:Area {name:'강남'})
MATCH (r)-[:SERVES]->(c:Cuisine)

WITH DISTINCT c.name AS 요리

RETURN 요리
ORDER BY 요리
```

차이:

```text
RETURN DISTINCT
→ 중복 제거 후 쿼리 종료

WITH DISTINCT
→ 중복 제거 후 다음 단계 계속
```

### 계산값을 만들어 넘기기

데이터에 없는 값을 계산해서 이름을 붙인 뒤 사용할 수 있다.

```cypher
MATCH (r:Restaurant)

WITH r,
     r.price * 2 AS 둘이서

WHERE 둘이서 <= 60000

RETURN r.name AS 식당,
       둘이서
```

핵심:

```cypher
WITH 기존변수, 계산식 AS 새이름
```

예:

```cypher
WITH c, c.price / 2 AS 인당가격
```

그다음부터:

```cypher
WHERE 인당가격 <= 25000
RETURN c.name, 인당가격
```

처럼 별칭을 사용할 수 있다.

`WITH`에서 다음 단계에 필요한 변수는 모두 함께 넘겨야 한다.

```cypher
WITH r, r.price * 2 AS 둘이서
```

여기서 `r`을 빼면 다음 단계에서 `r.name` 등을 사용할 수 없다.

### 이미 구한 경로를 나중에 필터링

최단 경로를 먼저 계산하고 그 결과의 길이를 검사하려면 `WITH`로 단계를 분리한다.

```cypher
MATCH p = shortestPath(
    (a)-[:VISITED*]-(b)
)

WITH p,
     length(p) AS 홉수

WHERE 홉수 >= $n

RETURN 홉수
```

의미:

```text
1. 먼저 최단 경로 계산
2. length(p)를 홉수로 저장
3. 이미 계산된 결과를 조건으로 필터링
```

### 중간에서 `ORDER BY` + `LIMIT`

`WITH`의 중요한 용도 중 하나는 **다음 관계를 연결하기 전에 일부 결과만 먼저 선택하는 것**이다.

```cypher
MATCH (r:Restaurant)

WITH r
ORDER BY r.rating DESC, r.name
LIMIT 3

MATCH (d:Diner)-[:VISITED]->(r)

RETURN r.name AS 식당,
       d.name AS 손님
```

의미:

```text
전체 식당
  ↓
평점 상위 3곳만 선택
  ↓
그 3곳을 방문한 손님 연결
```

반면 마지막에만 `LIMIT 3`을 두면:

```cypher
MATCH (r:Restaurant)
MATCH (d:Diner)-[:VISITED]->(r)

RETURN r.name AS 식당,
       d.name AS 손님
ORDER BY r.rating DESC, r.name
LIMIT 3
```

이미 방문 관계까지 모두 펼친 뒤 **최종 행 3개만 자른다.**

즉:

```text
WITH ... LIMIT 3
→ 다음 단계에 넘길 대상 3개

RETURN ... LIMIT 3
→ 최종 결과 행 3개
```

자르는 위치가 다르면 질문 자체가 달라진다.

---

## 5. 정렬과 페이지네이션: `ORDER BY` → `SKIP` → `LIMIT`

결과를 페이지 단위로 나누려면 세 절을 함께 사용한다.

```cypher
MATCH (r:Restaurant)
RETURN r.name AS 식당,
       r.rating AS 평점
ORDER BY 평점 DESC, 식당
SKIP 3
LIMIT 3
```

문법 순서:

```text
ORDER BY
   ↓
SKIP
   ↓
LIMIT
```

| 문법 | 의미 |
|---|---|
| `ORDER BY` | 결과 순서 결정 |
| `SKIP N` | 앞에서 N개 건너뜀 |
| `LIMIT N` | 이후 N개만 반환 |

3개씩 페이지를 만든다면:

```text
1페이지 → SKIP 0 LIMIT 3
2페이지 → SKIP 3 LIMIT 3
3페이지 → SKIP 6 LIMIT 3
```

일반식:

```text
skip = (page_no - 1) * page_size
```

파이썬:

```python
def page(page_no, size=3):
    skip = (page_no - 1) * size

    return run_cypher(
        """
        MATCH (r:Restaurant)
        RETURN r.name AS 식당,
               r.rating AS 평점
        ORDER BY 평점 DESC, 식당
        SKIP $skip
        LIMIT $size
        """,
        skip=skip,
        size=size
    )
```

최근 Cypher에서는 `SKIP` 대신 `OFFSET` 표기도 볼 수 있다.

### 페이지네이션에서는 보조 정렬키가 중요

다음처럼 평점만 정렬하면:

```cypher
ORDER BY r.rating DESC
```

같은 평점의 행끼리는 순서가 확정되지 않을 수 있다.

따라서:

```cypher
ORDER BY r.rating DESC, r.name
```

처럼 동점을 깨는 보조 정렬키를 둔다.

```text
1차 정렬 → rating
2차 정렬 → name
```

페이지마다 같은 `ORDER BY`를 사용해야 결과가 겹치거나 빠지는 문제를 줄일 수 있다.

---

## 복합 쿼리 조립 예시

지역 목록과 2인 예산을 받아 식당을 고른 뒤, 상위 2곳의 셰프까지 붙이는 흐름:

```cypher
MATCH (r:Restaurant)-[:LOCATED_IN]->(a:Area)
WHERE a.name IN $areas

WITH r,
     r.price * 2 AS 둘이서
WHERE 둘이서 <= $budget

WITH r
ORDER BY r.rating DESC, r.name
LIMIT 2

OPTIONAL MATCH (ch:Chef)-[:WORKS_AT]->(r)

RETURN r.name AS 식당,
       r.rating AS 평점,
       ch.name AS 셰프
ORDER BY 평점 DESC, 식당
```

처리 순서:

```text
지역 조건
   ↓
2인 가격 계산
   ↓
예산 필터
   ↓
평점 상위 2곳 선택
   ↓
셰프가 있으면 연결
   ↓
최종 출력
```

원본 실습의 `-[LOCATED_IN]-` 표기는 학습용으로 다음처럼 정리하는 편이 안전하다.

```cypher
-[:LOCATED_IN]->
```

관계 타입에는 `:`를 붙이고, 실제 저장된 관계 방향까지 표시한다.

---

## 핵심 문법 압축

| 목적 | 문법 |
|---|---|
| 목록 중 하나 | `x IN [a, b, c]` |
| 부분 문자열 | `x CONTAINS '문자'` |
| 시작 문자열 | `x STARTS WITH '문자'` |
| 끝 문자열 | `x ENDS WITH '문자'` |
| 정규식 | `x =~ '패턴'` |
| 대소문자 무시 정규식 | `x =~ '(?i)패턴'` |
| 파라미터 목록 | `x IN $names` |
| 관계 연속 연결 | `(a)-[:A]->(b)-[:B]->(c)` |
| 관계 종류 중 하나 | `(a)-[:A\|B]->(x)` |
| 관계 존재 확인 | `WHERE (a)-[:R]->(:B)` |
| 관계 없음 확인 | `WHERE NOT (a)-[:R]->(:B)` |
| 복잡한 존재 조건 | `WHERE EXISTS { ... }` |
| 연결 없어도 행 유지 | `OPTIONAL MATCH` |
| 연결 여부 판별 | `p IS NOT NULL` |
| 중간 결과 전달 | `WITH x` |
| 중간 중복 제거 | `WITH DISTINCT x` |
| 계산값 전달 | `WITH x, 식 AS 이름` |
| 중간 상위 N개 | `WITH x ORDER BY ... LIMIT N` |
| 페이지 건너뛰기 | `SKIP N` |
| 결과 개수 제한 | `LIMIT N` |

### 전체 작성 흐름

```text
1. MATCH로 시작 노드·관계 선택
            ↓
2. WHERE로 속성 또는 관계 조건 적용
   IN / 문자열 / EXISTS
            ↓
3. 필요하면 OPTIONAL MATCH
   없는 연결도 유지
            ↓
4. WITH로 중간 결과 가공
   계산 / DISTINCT / 필터 / 정렬 / LIMIT
            ↓
5. 다음 MATCH 연결
            ↓
6. RETURN
            ↓
7. ORDER BY → SKIP → LIMIT
```

---

## 참고: 패턴 내부 조건 표기

공식 문서에서는 `WHERE` 조건을 패턴 안에 직접 넣는 표기도 볼 수 있다.

```cypher
MATCH (r:Restaurant WHERE r.rating >= 4.5)
```

기존 방식:

```cypher
MATCH (r:Restaurant)
WHERE r.rating >= 4.5
```

관계에서도 사용할 수 있다.

```cypher
MATCH (a)-[x:ROUTE WHERE x.time < 60]->(b)
```

이 정리에서는 읽기 쉬운 기존 `WHERE` 절 중심으로 사용하고, 공식 문서에서 패턴 내부 조건 표기가 나올 수 있다는 정도로 구분하면 된다.
