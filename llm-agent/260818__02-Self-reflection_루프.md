# Self-reflection 루프 핵심 정리

> 실제 코딩 흐름 기준 핵심 압축 정리  
> 주제: **생성 → 비평 → 수정 → 반복 → 자동 리포트 연결**

---

# 0. 전체 개발 흐름

```text
1. OpenAI API Key 준비
   ↓
2. ChatOpenAI 모델 생성
   ↓
3. 분석용 수치 요약 준비
   ↓
4. generate()로 초안 생성
   ↓
5. Critique 스키마 정의
   ↓
6. critique()로 점수·개선점 평가
   ↓
7. revise()로 개선점 반영
   ↓
8. reflect()로 반복 루프 구성
   ↓
9. 임계 점수 또는 최대 반복에서 종료
   ↓
10. 최종 리포트 + 점수 이력 반환
   ↓
11. 분석·성찰·저장 도구와 Agent에 결합
```

핵심:

```text
Generate
→ Critique
→ Revise
→ 다시 Critique
→ 기준 충족 시 종료
```

---

# 1. Self-reflection이 필요한 이유

한 번 생성한 답은 다음 문제가 생길 수 있음.

```text
구체적 수치 부족
해석 부족
실행 제안 부족
```

따라서 초안을 바로 최종 결과로 사용하지 않고:

```text
초안 생성
→ 평가
→ 문제점 확인
→ 수정
```

과정을 반복.

## 기본 구조

```text
수치 요약
   ↓
generate()
   ↓
초안
   ↓
critique()
   ↓
점수 + 개선점
   ↓
revise()
   ↓
수정본
```

---

# 2. 모델 준비

## API Key

```python
import os
from dotenv import load_dotenv

load_dotenv(".env")
load_dotenv("../.env")
load_dotenv("../../.env")

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY를 찾지 못했습니다.")
```

목적:

```text
.env
→ OPENAI_API_KEY 로드
→ 모델 생성 전에 키 존재 여부 확인
```

## ChatOpenAI

```python
from langchain_openai import ChatOpenAI

model = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
)
```

`temperature=0`

```text
수업·평가 환경에서 출력 변동을 줄이기 위한 설정
```

---

# 3. 분석 재료 준비

예시:

```python
summary = (
    "카테고리별 평균 완료율: "
    "파이썬 70.5%, 웹개발 69.8%, 데이터분석 61.7%, "
    "디자인 56.9%, AI머신러닝 54.8%. "
    "전체 평균 만족도 4.1/5.0."
)
```

현재 상태:

```text
summary
= 분석용 숫자 요약

아직
해석 X
제안 X
리포트 형태 X
```

이 값을 모델에게 넘겨 리포트 초안을 생성.

---

# 4. 1단계: 초안 생성 `generate()`

## 시스템 프롬프트

```python
GEN_SYSTEM = (
    "너는 데이터 분석 리포트 작성자다. "
    "주어진 수치 요약을 바탕으로 "
    "핵심 인사이트를 한국어 세 문장으로 써라."
)
```

## 생성 함수

```python
def generate(summary):
    r = model.invoke([
        {
            "role": "system",
            "content": GEN_SYSTEM,
        },
        {
            "role": "user",
            "content": summary,
        },
    ])

    return r.text
```

흐름:

```text
summary
→ model.invoke()
→ AI 응답 객체
→ .text
→ 초안 문자열
```

`.text`를 반환하는 이유:

```text
다음 critique() 단계가
응답 객체 전체가 아니라
리포트 본문 문자열을 그대로 받기 때문
```

사용:

```python
draft = generate(summary)
```

---

# 5. 초안 평가 기준

초안에서 확인할 핵심 3가지:

```text
1. 구체적인 수치를 인용했는가
2. 숫자의 의미를 해석했는가
3. 실행 가능한 제안이 있는가
```

사람이 매번 직접 판정하지 않고 모델에게 같은 기준으로 평가시켜 자동화.

문제:

```text
자유 문장 비평
→ 프로그램이 종료 조건으로 사용하기 어려움
```

따라서 **구조화된 출력** 사용.

---

# 6. 2단계: 비평 구조 정의 `Critique`

```python
from pydantic import BaseModel, Field

class Critique(BaseModel):

    score: int = Field(
        ge=1,
        le=10,
        description="1~10 종합 점수",
    )

    issues: list[str] = Field(
        description="개선점 목록(짧게)",
    )
```

결과 구조:

```text
Critique
├─ score  : 1~10 정수
└─ issues : 개선점 목록
```

## 구조화가 필요한 이유

자유 문장:

```text
"조금 부족하며 수치를 더 활용하면 좋다..."
```

구조화:

```python
result.score
result.issues
```

따라서 프로그램에서 바로 사용 가능.

```python
if result.score >= 8:
    ...
```

핵심:

```text
점수
→ 종료 조건 판단

개선점
→ revise() 입력
```

---

# 7. 3단계: 비평 `critique()`

## 평가 프롬프트

```python
CRITIC_SYSTEM = (
    "너는 깐깐한 리포트 편집자다. "
    "아래 리포트를 평가하라. "
    "구체적 수치 인용·해석의 명확성·실행 제안 유무를 "
    "기준으로 1~10점을 매기고, "
    "개선점을 항목으로 지적하라."
)
```

## 구조화 모델 생성

```python
critic_model = model.with_structured_output(Critique)
```

원래 `model`을 변경하는 것이 아니라:

```text
기존 model
→ Critique 구조로 응답하는 모델 래퍼 생성
```

## 비평 함수

```python
def critique(report):

    critic_model = model.with_structured_output(Critique)

    return critic_model.invoke([
        {
            "role": "system",
            "content": CRITIC_SYSTEM,
        },
        {
            "role": "user",
            "content": report,
        },
    ])
```

사용:

```python
critique_result = critique(draft)

print(critique_result.score)
print(critique_result.issues)
```

---

# 8. 4단계: 수정 `revise()`

비평 결과의 `issues`를 받아 기존 리포트를 고쳐 씀.

## 수정 프롬프트

```python
REVISE_SYSTEM = (
    "너는 리포트 작성자다. "
    "아래 [리포트]를 [개선점]을 모두 반영해 다시 써라. "
    "한국어 세 문장을 유지하라."
)
```

핵심:

```text
새 리포트를 처음부터 생성
X

기존 리포트의 장점을 유지하면서 수정
O
```

## 수정 함수

```python
def revise(report, issues):

    user = (
        f"[리포트]\n{report}\n\n"
        "[개선점]\n"
        + "\n".join(f"- {x}" for x in issues)
    )

    r = model.invoke([
        {
            "role": "system",
            "content": REVISE_SYSTEM,
        },
        {
            "role": "user",
            "content": user,
        },
    ])

    return r.text
```

`issues`는 리스트 그대로 넣지 않고 문자열 목록으로 변환.

```python
"\n".join(f"- {x}" for x in issues)
```

변환:

```text
[
    "수치 인용 부족",
    "실행 제안 부족",
]

↓

- 수치 인용 부족
- 실행 제안 부족
```

---

# 9. 생성 → 비평 → 수정 반복

개별 함수:

```text
generate()
critique()
revise()
```

이제 하나의 반복 함수로 묶음.

```text
generate
   ↓
critique
   ↓
score 확인
   ↓
기준 미달
   ↓
revise
   ↓
다시 critique
```

---

# 10. 종료 조건

Self-reflection 루프에는 **2개의 종료 조건** 필요.

## 1. 임계 점수

```python
score >= threshold
```

목표 품질에 도달하면 즉시 종료.

예:

```python
threshold = 8
```

```text
8점 이상
→ 수정하지 않고 종료
```

## 2. 최대 반복

```python
max_iter = 3
```

점수가 계속 기준에 도달하지 못해도 정해진 횟수에서 종료.

목적:

```text
무한 반복 방지
모델 호출 횟수 제한
```

따라서:

```text
성공 종료
→ threshold

강제 종료
→ max_iter
```

둘 다 필요.

---

# 11. 5단계: Self-reflection 루프 `reflect()`

```python
def reflect(summary, threshold=8, max_iter=3):

    report = generate(summary)
    score_history = []

    for _ in range(max_iter):

        result = critique(report)

        score_history.append(
            result.score
        )

        if result.score >= threshold:
            break

        report = revise(
            report,
            result.issues,
        )

    return report, score_history
```

---

# 12. `reflect()` 내부 흐름

## ① 최초 생성

```python
report = generate(summary)
```

초안 생성은 처음 한 번.

이후에는:

```text
새로 생성
X

현재 리포트를 계속 수정
O
```

---

## ② 점수 기록

```python
score_history = []
```

반복마다:

```python
score_history.append(result.score)
```

예:

```python
[4, 6, 8]
```

의미:

```text
초안      → 4점
1차 수정  → 6점
2차 수정  → 8점
```

점수가 어떻게 변했는지 확인하는 실행 로그.

---

## ③ 반복

```python
for _ in range(max_iter):
```

반복 횟수가 정해져 있으므로 `for` 사용.

---

## ④ 비평

```python
result = critique(report)
```

현재 버전을 계속 재평가.

---

## ⑤ 기준 충족 여부 판단

```python
if result.score >= threshold:
    break
```

충분한 품질이면 더 수정하지 않음.

---

## ⑥ 기준 미달이면 수정

```python
report = revise(
    report,
    result.issues,
)
```

비평에서 나온 개선점을 다음 수정 단계에 직접 전달.

---

# 13. 실행

```python
final_report, score_history = reflect(summary)
```

결과:

```text
final_report
→ 최종 수정된 리포트

score_history
→ 반복별 평가 점수
```

확인:

```python
print("점수 이력:", score_history)
print("최종 리포트:")
print(final_report)
```

---

# 14. 전체 코드 관계

```text
summary
   │
   ▼
generate(summary)
   │
   ▼
report
   │
   ▼
critique(report)
   │
   ├───────────────┐
   ▼               ▼
score           issues
   │               │
   │               ▼
   │        revise(report, issues)
   │               │
   │               ▼
   │          수정된 report
   │               │
   └──── 다시 critique()
```

---

# 15. 핵심 코드만 압축

```python
from pydantic import BaseModel, Field


class Critique(BaseModel):
    score: int = Field(ge=1, le=10)
    issues: list[str]


def generate(summary):

    r = model.invoke([
        {"role": "system", "content": GEN_SYSTEM},
        {"role": "user", "content": summary},
    ])

    return r.text


def critique(report):

    critic_model = model.with_structured_output(Critique)

    return critic_model.invoke([
        {"role": "system", "content": CRITIC_SYSTEM},
        {"role": "user", "content": report},
    ])


def revise(report, issues):

    user = (
        f"[리포트]\n{report}\n\n"
        "[개선점]\n"
        + "\n".join(f"- {x}" for x in issues)
    )

    r = model.invoke([
        {"role": "system", "content": REVISE_SYSTEM},
        {"role": "user", "content": user},
    ])

    return r.text


def reflect(summary, threshold=8, max_iter=3):

    report = generate(summary)
    score_history = []

    for _ in range(max_iter):

        result = critique(report)
        score_history.append(result.score)

        if result.score >= threshold:
            break

        report = revise(
            report,
            result.issues,
        )

    return report, score_history
```

---

# 16. 분석 도구와 결합

앞 단계까지는 사람이 직접:

```python
reflect(summary)
```

를 호출.

다음 단계에서는 이 성찰 루프 자체를 **Tool**로 감싸 Agent에 연결.

원본 교안의 4절 구조:

```text
데이터 요약 Tool
+
Self-reflection Tool
+
파일 저장 Tool
        ↓
      Agent
```

최종 목표:

```text
사용자 요청
→ 데이터 분석
→ 수치 요약
→ Self-reflection 리포트 생성
→ 파일 저장
```

즉:

```text
내가 만든 Python 함수
→ Tool화
→ Agent의 행동으로 사용
```

> 해당 Agent 결합 실습은 원본에서 별도 `01_자동_리포트.py` 파일로 진행됨.

---

# 17. Self-reflection의 한계

비평 루프가 확인하는 것:

```text
수치를 구체적으로 인용했는가
해석이 명확한가
실행 제안이 있는가
```

하지만 확인하지 못하는 것:

```text
그 수치 자체가 실제로 정확한가
```

따라서:

```text
점수 상승
≠
데이터 정확성 보장
```

최종 리포트의 숫자는 원본 수치 요약과 대조 필요.

---

# 18. 최종 정리

| 단계 | 역할 | 핵심 코드 |
|---|---|---|
| 생성 | 수치로 초안 작성 | `generate(summary)` |
| 구조 정의 | 비평 결과 형식 고정 | `Critique(BaseModel)` |
| 비평 | 점수·개선점 생성 | `critique(report)` |
| 수정 | 개선점 반영 | `revise(report, issues)` |
| 반복 | 품질 기준까지 재평가 | `reflect(...)` |
| 종료 | 품질 또는 반복 횟수 제한 | `threshold`, `max_iter` |
| 기록 | 개선 과정 추적 | `score_history` |
| 확장 | 루프 자체를 Tool화 | Agent 연결 |

## 핵심 개념

```text
generate
= 초안을 만든다

critique
= 현재 결과의 문제를 구조화해서 찾는다

revise
= 문제를 반영해 기존 결과를 고친다

reflect
= 위 과정을 반복하고 종료 조건을 관리한다
```

## 한 줄 구조

```text
수치 요약
→ 초안 생성
→ 구조화 비평
→ 점수 확인
→ 개선점 반영
→ 재평가
→ 기준 충족 시 최종 리포트 반환
```

## 가장 중요한 기준

```text
생성 = 결과 만들기
비평 = 문제 찾기
수정 = 문제 반영하기
루프 = 품질을 반복해서 끌어올리기
종료 조건 = 무한 반복 막기
```
