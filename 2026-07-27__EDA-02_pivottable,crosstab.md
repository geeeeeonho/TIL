# Pivot Table·교차표·데이터 병합

## 1. `groupby`와 `pivot_table`

`groupby`와 `pivot_table`은 **그룹 기준·집계 대상·집계 함수가 같다면 같은 계산**을 수행함.

차이는 계산 결과를 배치하는 방법임.

```python
# 요일 × 시간대별 식사 금액 평균
df.groupby(['day', 'time'])['total_bill'].mean()

df.pivot_table(
    index='day',
    columns='time',
    values='total_bill',
    aggfunc='mean'
)
```

| 구분    | `groupby`     | `pivot_table`       |
| ----- | ------------- | ------------------- |
| 결과 배치 | 모든 조합을 행으로 쌓음 | 첫 기준은 행, 두 번째 기준은 열 |
| 결과 형태 | 다중 인덱스 Series | 격자 형태 DataFrame     |
| 없는 조합 | 행 자체가 없음      | `NaN` 빈칸으로 표시       |
| 주요 용도 | 계산·필터·정렬·병합   | 비교표·보고서·히트맵         |

### 결과 형태 비교

```python
by_group = (
    df.groupby(['day', 'time'])['total_bill']
      .mean()
)

by_pivot = df.pivot_table(
    index='day',
    columns='time',
    values='total_bill',
    aggfunc='mean'
)
```

`groupby` 결과:

```text
day   time
Fri   Dinner    19.66
      Lunch     12.85
Sat   Dinner    20.44
Sun   Dinner    21.41
Thur  Dinner    18.78
      Lunch     17.66
```

`pivot_table` 결과:

| day  | Dinner | Lunch |
| ---- | -----: | ----: |
| Fri  |  19.66 | 12.85 |
| Sat  |  20.44 |   NaN |
| Sun  |  21.41 |   NaN |
| Thur |  18.78 | 17.66 |

주말 점심 데이터가 없을 때:

* `groupby`: 해당 조합의 행이 없음
* `pivot_table`: 해당 위치가 `NaN`으로 표시됨

따라서 존재하지 않는 조합을 확인할 때는 `pivot_table`이 편함.

---

## 2. `unstack`

`unstack()`은 다중 인덱스의 한 단계를 열 방향으로 펼침.

```python
by_group.unstack()
```

동일한 조건으로 계산했다면 다음 두 결과가 같음.

```python
by_group.unstack().equals(by_pivot)
```

```text
groupby + unstack ≈ pivot_table
```

반대로 격자형 결과를 세로로 쌓으려면 `stack()`을 사용함.

```python
by_pivot.stack()
```

---

# `pivot_table` 사용법

## 3. 기본 문법

```python
df.pivot_table(
    index='행에 놓을 열',
    columns='열에 놓을 열',
    values='집계할 값',
    aggfunc='집계 함수'
)
```

주요 입력값:

* `index`: 행 방향 그룹 기준
* `columns`: 열 방향 그룹 기준
* `values`: 계산할 값
* `aggfunc`: 집계 방법, 기본값은 평균
* `fill_value`: `NaN` 대신 넣을 값
* `margins`: 전체 집계 행·열 추가
* `margins_name`: 전체 행·열 이름 지정

```python
df.pivot_table(
    index='day',
    columns='time',
    values='total_bill',
    aggfunc='mean',
    fill_value=0
)
```

`fill_value=0`을 사용하면 없는 조합의 `NaN`을 `0`으로 표시함.

단, 데이터 없음과 실제 값 `0`은 의미가 다를 수 있으므로 구분해서 사용해야 함.

---

## 4. 사용자 정의 집계

`aggfunc`에는 문자열뿐 아니라 `lambda`와 일반 함수도 사용할 수 있음.

```python
df.pivot_table(
    index='day',
    columns='time',
    values='tip',
    aggfunc=lambda s: s.max() - s.min()
)
```

* `s`: 각 요일×시간대 그룹의 `tip` Series
* 결과: 그룹별 팁 최댓값과 최솟값의 차이

재사용할 계산은 `def` 함수로 만드는 것이 좋음.

```python
def tip_range(s):
    return s.max() - s.min()
```

```python
df.pivot_table(
    index='day',
    columns='time',
    values='tip',
    aggfunc=tip_range
).round(2)
```

`lambda`는 결과 이름이 `<lambda>`로 표시될 수 있지만, `def` 함수는 함수 이름이 결과 라벨로 사용됨.

---

## 5. 여러 집계 함수 적용

집계 함수를 리스트로 전달하면 여러 결과를 한 번에 계산함.

```python
df.pivot_table(
    index='day',
    values='tip',
    aggfunc=['mean', tip_range]
).round(2)
```

요일별로 다음 값을 함께 계산함.

* 팁 평균
* 팁 범위

결과 열은 여러 단계의 다중 인덱스가 될 수 있음.

---

## 6. 열마다 다른 집계 적용

`aggfunc`에 딕셔너리를 전달하면 열마다 다른 함수를 적용할 수 있음.

```python
df.pivot_table(
    index='day',
    values=['tip', 'total_bill'],
    aggfunc={
        'tip': tip_range,
        'total_bill': 'mean'
    }
).round(2)
```

* `tip`: 최댓값−최솟값
* `total_bill`: 평균

### 결과 열 이름 변경

`groupby().agg()`의 Named Aggregation처럼 결과 이름을 직접 붙이는 기능은 `pivot_table`에 없음.

결과를 만든 뒤 `rename()`으로 변경함.

```python
tip_summary = df.pivot_table(
    index='day',
    values='tip',
    aggfunc=tip_range
)

tip_summary = tip_summary.rename(
    columns={'tip': '팁범위'}
)
```

---

# `margins`

## 7. 전체 집계 추가

`margins=True`를 사용하면 오른쪽과 아래에 전체 집계가 추가됨.

```python
day_slot = gym.pivot_table(
    index='요일',
    columns='시간대',
    values='운동시간',
    aggfunc='mean',
    margins=True,
    margins_name='전체'
)
```

* 오른쪽 `전체`: 해당 요일 전체 시간대의 평균
* 아래 `전체`: 해당 시간대 전체 요일의 평균
* 오른쪽 아래 `전체`: 전체 데이터의 평균

### 주의

`margins`는 항상 `aggfunc`에 지정한 함수를 그대로 사용함.

```python
# 평균을 사용했으므로 전체 칸도 평균
aggfunc='mean'
```

```python
# 범위를 사용했으므로 전체 칸도 최댓값-최솟값
aggfunc=lambda s: s.max() - s.min()
```

따라서 다음 코드의 오른쪽 아래 `All`은 전체 평균이 아니라 **전체 운동시간 범위**임.

```python
gym.pivot_table(
    index='요일',
    columns='시간대',
    values='운동시간',
    aggfunc=lambda s: s.max() - s.min(),
    margins=True
)
```

---

## 8. 운동 데이터 예시

### 평균 격자표

```python
mean_slot = gym.pivot_table(
    index='요일',
    columns='시간대',
    values='운동시간',
    aggfunc='mean'
).round(1)
```

### 범위 격자표

```python
range_slot = gym.pivot_table(
    index='요일',
    columns='시간대',
    values='운동시간',
    aggfunc=lambda s: s.max() - s.min()
)
```

두 표를 비교하면 다음을 확인할 수 있음.

* 평균이 높은 시간대
* 평균은 비슷하지만 값의 변동이 큰 시간대
* 데이터가 없어 `NaN`으로 표시된 조합

---

# 교차표 `crosstab`

## 9. 빈도 교차표

`pd.crosstab()`은 두 범주형 열의 조합이 몇 번 등장했는지 계산함.

```python
pd.crosstab(
    df['day'],
    df['time']
)
```

* 첫 번째 값: 행에 놓을 범주
* 두 번째 값: 열에 놓을 범주
* 각 칸: 해당 조합의 등장 횟수

```python
program_grade = pd.crosstab(
    gym['프로그램'],
    gym['회원등급']
)
```

| 프로그램 |  일반 | 프리미엄 |
| ---- | --: | ---: |
| 스피닝  |  79 |   46 |
| 요가   |  69 |   59 |
| 웨이트  | 102 |   60 |
| 필라테스 |  63 |   42 |

---

## 10. 비율 교차표

`normalize`를 사용하면 개수가 아니라 비율을 계산함.

```python
pd.crosstab(
    gym['프로그램'],
    gym['회원등급'],
    normalize='index'
).round(2)
```

`normalize='index'`:

* 각 행의 합이 `1`
* 프로그램별 회원등급 구성비 확인

| 프로그램 |   일반 | 프리미엄 |
| ---- | ---: | ---: |
| 스피닝  | 0.63 | 0.37 |
| 요가   | 0.54 | 0.46 |
| 웨이트  | 0.63 | 0.37 |
| 필라테스 | 0.60 | 0.40 |

다른 설정:

```python
normalize='index'    # 행별 비율
normalize='columns'  # 열별 비율
normalize='all'      # 전체 데이터 기준 비율
```

백분율로 표시:

```python
pd.crosstab(
    gym['프로그램'],
    gym['회원등급'],
    normalize='index'
).mul(100).round(1)
```

---

## 11. `crosstab`과 `pivot_table`

| 구분             | `crosstab`    | `pivot_table` |
| -------------- | ------------- | ------------- |
| 주요 목적          | 조합별 빈도 계산     | 값의 평균·합계 등 계산 |
| 집계 대상 `values` | 기본적으로 필요 없음   | 필요함           |
| 기본 결과          | 개수            | 평균            |
| 주요 입력          | 범주형 열 2개      | 그룹 기준과 수치형 값  |
| 예시             | 프로그램별 회원등급 인원 | 요일별 운동시간 평균   |

```python
# 조합별 개수
pd.crosstab(gym['프로그램'], gym['회원등급'])
```

```python
# 조합별 운동시간 평균
gym.pivot_table(
    index='프로그램',
    columns='회원등급',
    values='운동시간',
    aggfunc='mean'
)
```

기억할 내용:

```text
조합의 개수 → crosstab
수치값의 평균·합계 → pivot_table
```

---

# 데이터 병합

## 12. 기본 병합

두 DataFrame을 공통 키를 기준으로 연결할 때 `merge`를 사용함.

```python
result = pd.merge(
    left,
    right,
    on='day',
    how='left'
)
```

* `left`: 기준이 되는 왼쪽 표
* `right`: 붙일 오른쪽 표
* `on`: 공통 키 열
* `how`: 병합 방식

주요 병합 방식:

* `left`: 왼쪽 표의 모든 행 유지
* `inner`: 양쪽에 모두 존재하는 키만 유지
* `right`: 오른쪽 표의 모든 행 유지
* `outer`: 양쪽의 모든 키 유지

---

## 13. 키 이름이 다를 때

같은 의미의 열이지만 이름이 다르면 `left_on`, `right_on`을 사용함.

```python
result = pd.merge(
    left,
    right,
    left_on='day',
    right_on='요일',
    how='left'
)
```

* 왼쪽 병합 키: `day`
* 오른쪽 병합 키: `요일`

병합 후 두 키 열이 모두 남을 수 있으므로 필요 없는 열을 제거할 수 있음.

```python
result = result.drop(columns='요일')
```

---

## 14. 열 이름이 겹칠 때

병합 키가 아닌 열 이름이 양쪽 표에 모두 존재하면 기본적으로 `_x`, `_y`가 붙음.

```text
note_x
note_y
```

`suffixes`로 의미 있는 이름을 지정할 수 있음.

```python
result = pd.merge(
    orders,
    day_info,
    on='day',
    how='left',
    suffixes=('_주문', '_요일정보')
)
```

결과:

```text
note_주문
note_요일정보
```

---

# 병합 키 중복

## 15. 중복 키로 인한 행 증가

병합 키가 중복되어 있으면 행이 예상보다 많이 복제될 수 있음.

예를 들어:

* 왼쪽 표에서 `월요일`이 3행
* 오른쪽 표에서 `월요일`이 2행

병합 결과:

```text
3 × 2 = 6행
```

이를 다대다 병합이라고 함.

거래 데이터처럼 같은 요일이 반복되는 것은 정상일 수 있음.
하지만 요일 설명표처럼 키 하나당 한 행이어야 하는 표에서 중복이 발생하면 문제가 됨.

---

## 16. 중복 키 확인

키가 하나만 존재해야 하는 오른쪽 표를 기준으로 확인함.

```python
day_info['요일'].duplicated().sum()
```

중복된 데이터를 모두 확인:

```python
day_info[
    day_info['요일'].duplicated(keep=False)
]
```

* `duplicated()`: 첫 번째 값을 제외한 중복을 `True`로 표시
* `keep=False`: 중복된 모든 행을 `True`로 표시
* `sum()`: 중복 행 개수 계산

---

## 17. 중복 제거

```python
day_info = day_info.drop_duplicates(
    subset='요일',
    keep='first'
)
```

* `subset='요일'`: 요일 열을 기준으로 중복 판단
* `keep='first'`: 첫 번째 행 유지
* 결과를 다시 저장해야 원본 변수에 적용됨

다음 코드는 결과를 반환할 뿐 원본을 수정하지 않음.

```python
day_info['요일'].drop_duplicates()
```

또한 한 열만 추출해 중복을 제거하면 나머지 열 정보가 사라짐.

따라서 전체 DataFrame에서 키 기준으로 처리하는 것이 좋음.

```python
day_info = day_info.drop_duplicates(subset='요일')
```

중복이 정상 데이터인지 오류인지 먼저 판단해야 함. 거래·방문 기록의 중복 키를 무조건 제거하면 실제 데이터가 손실될 수 있음.

---

## 18. 병합 관계 검증

`validate`를 사용하면 예상하지 못한 중복 키를 오류로 확인할 수 있음.

```python
result = pd.merge(
    orders,
    day_info,
    left_on='day',
    right_on='요일',
    how='left',
    validate='many_to_one'
)
```

`many_to_one` 의미:

* 왼쪽 키: 여러 행 가능
* 오른쪽 키: 하나의 행만 가능

주요 설정:

```python
validate='one_to_one'    # 양쪽 키 모두 고유
validate='one_to_many'   # 왼쪽 고유, 오른쪽 중복 가능
validate='many_to_one'   # 왼쪽 중복 가능, 오른쪽 고유
validate='many_to_many'  # 양쪽 중복 가능
```

요일 정보표처럼 키 하나당 설명 하나만 존재해야 한다면 `many_to_one` 검증이 유용함.

---

# 핵심 정리

```text
groupby
→ 그룹 조합을 세로로 쌓아 계산하기 좋음

pivot_table
→ 그룹 결과를 행×열 격자로 만들어 비교하기 좋음

unstack
→ groupby의 다중 인덱스를 열로 펼침

crosstab
→ 두 범주형 열의 조합별 개수나 비율을 계산함

margins=True
→ 전체 행·열을 추가하며 aggfunc와 같은 함수를 사용함

merge
→ 공통 키를 기준으로 두 표를 연결함

left_on / right_on
→ 양쪽 키 이름이 다를 때 사용함

suffixes
→ 겹치는 열 이름에 구분 이름을 붙임

duplicated
→ 병합 전 중복 키 확인

validate
→ 예상한 병합 관계가 맞는지 검사
```
