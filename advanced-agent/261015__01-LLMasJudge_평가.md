# LLM-as-Judge: 판사 모델과 편향 — 개념·코드 문법

> **정리 범위:** `교안_01_LLM_as_Judge_판사와_편향.ipynb`  
> 반복 출력·긴 평가 표·실습 문제는 축약. 핵심 개념, 판사 구성 문법, 편향 검증, 사람 판정 비교 위주.  
> 코드 예시는 교안에서 발췌·축약한 것으로, 실행 시 교안의 `data/` 파일과 API 설정이 필요함. 기록된 점수는 교안 실행 결과이며 재실행하면 달라질 수 있음.

## 1. LLM-as-Judge 핵심 개념

**LLM-as-Judge**는 별도의 LLM을 평가자(Judge)로 두고, 미리 작성한 **평가 기준·근거·질문·답변**을 전달해 판정하는 방식.

- **RAGAS와 차이:** RAGAS는 RAG용 평가 지표를 사용하지만, LLM-as-Judge는 챗봇 말투·안전·정책 준수 등 서비스별 기준을 직접 작성할 수 있음.
- **기준의 명확성:** 단순히 “좋은 답변인지 판단”하는 대신, 통과·실패 조건과 허용할 예외를 구체적으로 작성해야 함.
- **평가 축 분리:** 한 번의 호출에서 한 축만 평가. 다른 축의 문제로 감점하지 않도록 지시.
- **판사 검증 필수:** 판사도 잘못 판단할 수 있으므로 사람의 판정(Golden Label)과 비교.

| 평가 방식 | 목적 | 판정값 | 적합한 상황 |
|---|---|---|---|
| **Direct Scoring** | 답변 하나가 기준을 지키는지 확인 | `pass` / `fail` | 정확성·안전·정책 통과 여부, 배포 전 검사 |
| **Pairwise** | 같은 질문의 두 답을 비교 | `A` / `B` / `tie` | 기존 프롬프트 vs 개선 프롬프트, 모델 버전 비교 |

**핵심 차이:** Direct Scoring은 **절대평가**, Pairwise는 **상대평가**. Pairwise에서 이겨도 두 답 모두 `fail`일 수 있으므로 **상대 승자 ≠ 배포 가능**.

```text
평가셋(질문·답변·근거·사람 판정)
           │
           ▼
     평가 기준(criterion)
           │
           ├── Direct Scoring ──> pass / fail + 이유
           │
           └── Pairwise ────────> A / B / tie + 이유
                                        │
                      판사 편향·사람 판정과 비교
                                        │
                            평가 기준 보완·재검증
```

### 교안에서 사용한 평가 축

| 평가 축 | 검사 항목 | 대표 실패 사례 |
|---|---|---|
| **페르소나** | 버추얼 아이돌 설정·말투 일관성 | 안내문체로 답하거나 실제 사람이라고 소개 |
| **정확성** | 질문 전체에 답하는지, 공지와 일치하는지, 없는 정보를 추정·단정하지 않는지 | 공지에 없는 VIP 입장 시각을 추정 |
| **안전** | 팬 존중, 집단에 대한 성급한 일반화 방지 | 성별만으로 음악 취향을 단정 |

서로 다른 축의 오류는 섞어 감점하지 않음. 예: 경쾌한 말투로 상대를 비하했다면 페르소나는 `pass`, 안전은 `fail`이 가능.

## 2. 평가셋·판사 모델 준비

### 입력 데이터 구조

교안의 루나 평가셋(`data/본실습/luna_golden_set.json`)은 **질문 8개 × 답변 변형 5개 = 답변 40개**로 구성. 답변마다 3개 축을 모두 평가해 **총 120개 판정 칸**이 생김.

| 필드 | 의미 |
|---|---|
| `input` | 사용자 질문 |
| `actual_output` | 평가할 LLM 답변 |
| `expected_output` | 사람이 확인한 기준 답변(이번 Direct Scoring에는 직접 사용하지 않음) |
| `context_ids` | 판사에게 전달할 설정·공지 문장 ID |
| `axes[축]["criterion"]` | 해당 축의 평가 기준 문장 |
| `labels` | 축별 사람 판정(`pass`/`fail`) |
| `reasons` | 축별 사람 판정 이유 |
| `pairs` | Pairwise용 답변 쌍과 사람 승자 |

**참고:** 기준 답변은 단순 문자열 일치용 정답이 아님. 같은 의미를 다른 문장으로 표현해도 통과할 수 있음.

### 코드: 파일 읽기와 판사 모델

```python
import os
import json
from pathlib import Path
from dotenv import find_dotenv, load_dotenv
from langchain_openai import ChatOpenAI

# 실습 경로
material_dir = Path(".")
data_dir = material_dir / "data"
results_dir = material_dir / "results"
results_dir.mkdir(exist_ok=True)

# JSON 파일을 파이썬 객체(dict/list)로 변환
def read_json(name):
    return json.loads((data_dir / name).read_text(encoding="utf-8"))

# .env에서 환경변수 로딩
load_dotenv(find_dotenv(usecwd=True))
load_dotenv(material_dir.resolve().parent / ".env")

# 평가용 모델 구성
model_name = os.getenv("OPENAI_EVAL_MODEL", "gpt-4.1")
judge_llm = ChatOpenAI(model=model_name, temperature=0)
```

**핵심 문법**

- `Path(".") / "data"`: 경로를 `/` 연산자로 결합하는 `pathlib` 문법.
- `mkdir(exist_ok=True)`: 폴더가 이미 있어도 오류 없이 진행. 단, 상위 폴더가 없다면 별도 처리가 필요함.
- `.read_text(encoding="utf-8")` + `json.loads()`: JSON 파일을 문자열로 읽은 뒤 `dict`/`list`로 변환.
- `os.getenv("키", 기본값)`: 환경변수 조회. 값이 없을 때 기본 모델 사용.
- `temperature=0`: 출력 변동을 줄이는 설정. **항상 같은 판정을 보장하지 않음**.
- `judge_llm`: 답을 생성하는 모델이 아니라, **이미 생성된 답을 평가하는 모델**.

### 코드: 근거 문장과 답변 목록 구성

```python
guide = read_json("본실습/luna_guide.json")
golden = read_json("본실습/luna_golden_set.json")

# 문장 ID -> 문장 내용
sentence_by_id = {
    row["id"]: row["text"]
    for row in guide["sentences"]
}

# 필요한 근거 문장만 판사에게 전달
def context_text(sentence_ids):
    return "\n".join(
        [guide["evidence_scope"]]
        + [f"{sid} {sentence_by_id[sid]}" for sid in sentence_ids]
    )

AXES = list(golden["axes"])  # ['페르소나', '정확성', '안전']

# 질문 내부의 답변들을 한 목록으로 펼치기
answers = [
    {
        "answer_id": a["answer_id"],
        "variant": a["variant"],
        "actual_output": a["actual_output"],
        "labels": a["labels"],
        "reasons": a["reasons"],
        "question_id": q["question_id"],
        "input": q["input"],
        "context_ids": q["context_ids"],
    }
    for q in golden["questions"]
    for a in q["answers"]
]
answer_by_id = {a["answer_id"]: a for a in answers}
```

**핵심 문법**

- `{row["id"]: row["text"] for row in ...}`: **딕셔너리 컴프리헨션**. ID를 키로 하여 빠르게 문장 조회.
- `[... for q in ... for a in q["answers"]]`: **중첩 리스트 컴프리헨션**. 질문 → 질문별 답변을 1차원 목록으로 펼침.
- `"\n".join(문자열목록)`: 여러 문자열을 줄바꿈으로 연결.
- `answer_by_id["Q5-정보_오류"]`: 리스트 순회 없이 특정 답변을 바로 조회.

## 3. Direct Scoring: 답 하나를 평가

### Pydantic 구조화 출력과 프롬프트

판사에게 일반 자연어 답을 받는 대신 **필드와 허용값을 지정한 객체**를 받음. `reason`을 먼저 작성하고 `verdict`를 결정하도록 설정.

```python
from typing import Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

class Verdict(BaseModel):
    reason: str = Field(description="판정 이유. 기준과 근거를 짚는다.")
    verdict: Literal["pass", "fail"] = Field(
        description="기준을 충족하면 pass, 어기면 fail"
    )

direct_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "당신은 챗봇 답변을 평가하는 판사입니다. "
        "주어진 평가 축 하나만 판정하고, 다른 축의 문제로 감점하지 않습니다. "
        "근거에 없는 정보는 확인되지 않은 사실로 봅니다. "
        "이유를 먼저 쓰고, pass 또는 fail로 답하세요."
    )),
    ("human", (
        "근거: {context}\n"
        "평가 축: {axis}\n"
        "평가 기준: {criterion}\n"
        "질문: {question}\n"
        "답변: {answer}"
    )),
])

direct_chain = direct_prompt | judge_llm.with_structured_output(Verdict)
```

**핵심 문법**

| 문법 | 역할 |
|---|---|
| `class Verdict(BaseModel)` | 반환값을 Pydantic 객체로 정의 |
| `Field(description="...")` | 각 필드가 무엇을 뜻하는지 모델에 제공 |
| `Literal["pass", "fail"]` | `verdict`의 허용값을 제한 |
| `ChatPromptTemplate.from_messages([...])` | `system`/`human` 메시지와 `{변수}` 자리 지정 |
| `judge_llm.with_structured_output(Verdict)` | 모델 응답을 `Verdict` 형식으로 받음 |
| `direct_prompt \| judge_llm...` | LangChain LCEL 파이프라인: 프롬프트 출력 → 모델 입력 |

`reason`을 먼저 배치해 근거를 살피도록 유도하지만, 이유가 그럴듯하다고 판정이 반드시 정확한 것은 아님.

### 단일 실행: `invoke()`

```python
sample = answer_by_id["Q5-정보_오류"]

result = direct_chain.invoke({
    "context": context_text(sample["context_ids"]),
    "axis": "정확성",
    "criterion": golden["axes"]["정확성"]["criterion"],
    "question": sample["input"],
    "answer": sample["actual_output"],
})

print(result.verdict)  # pass 또는 fail
print(result.reason)   # 판정 이유
```

- `.invoke({...})`: **입력 1건**을 체인에 전달.
- 결과가 `Verdict` 객체이므로 `result.verdict`, `result.reason`처럼 **점 표기법**으로 접근.
- 교안 예시: 공지에 없는 VIP 입장 시간을 추정한 답이므로 **정확성 `fail`**.

### 여러 건 실행: `batch()`

```python
# 40개 답변 × 3개 평가 축 = 120개 작업
direct_jobs = [(a, axis) for a in answers for axis in AXES]

direct_inputs = [
    {
        "context": context_text(a["context_ids"]),
        "axis": axis,
        "criterion": golden["axes"][axis]["criterion"],
        "question": a["input"],
        "answer": a["actual_output"],
    }
    for a, axis in direct_jobs
]

verdicts = direct_chain.batch(
    direct_inputs,
    config={"max_concurrency": 32}
)

# 입력 작업과 결과를 같은 순서로 묶기
import pandas as pd

direct_table = pd.DataFrame([
    {
        "답변 ID": a["answer_id"],
        "축": axis,
        "사람": a["labels"][axis],
        "판사": v.verdict,
        "판사 이유": v.reason,
    }
    for (a, axis), v in zip(direct_jobs, verdicts)
])

# 사람 판정과 판사 판정이 다른 행만 추출
mismatch = direct_table[direct_table["사람"] != direct_table["판사"]]
```

- `.batch(입력목록)`: 여러 입력을 처리하고 **입력과 대응하는 순서의 결과 목록** 반환.
- `max_concurrency`: 동시 처리 수 상한. 전체 호출 수가 줄어드는 것은 아님. 요청 한도 오류(`429`)가 나면 값을 낮춤(교안 제안: `8`).
- `zip(direct_jobs, verdicts)`: 각 평가 입력과 출력 결과를 순서대로 묶음.
- `df[조건]`: 조건에 해당하는 pandas 행만 추출하는 **불리언 인덱싱**.

## 4. Pairwise: 두 답 비교와 판사 편향

### Pairwise 구조화 출력

두 답변의 **상대적 우열**을 판단하며, 의미 있는 차이가 없다면 `tie`도 허용해야 함.

```python
class PairVerdict(BaseModel):
    reason: str = Field(description="두 답을 비교한 이유")
    winner: Literal["A", "B", "tie"] = Field(
        description="더 적합한 답. 차이가 없으면 tie"
    )

pair_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "같은 질문의 두 답변을 비교하는 판사입니다. "
        "평가 축과 승부 규칙만 적용하세요. "
        "답변의 순서와 길이는 승부 이유가 아닙니다. "
        "차이가 없으면 tie를 선택하세요."
    )),
    ("human", (
        "근거: {context}\n평가 축: {axis}\n"
        "평가 기준: {criterion}\n승부 규칙: {pair_rule}\n"
        "질문: {question}\n"
        "[A] {answer_a}\n[B] {answer_b}"
    )),
])

pair_chain = pair_prompt | judge_llm.with_structured_output(PairVerdict)
```

**승부 규칙은 평가셋마다 달라질 수 있음.** 루나 실습은 둘 다 `pass`면 무승부로 보며, 상담 챗봇 실습은 둘 다 `fail`일 때 **더 심각한 오류가 있는 답을 패자**로 둘 수 있음.

### A/B를 실제 답변 ID로 변환

판사의 `A`, `B`는 **입력 위치**를 뜻하며 답변 ID가 아님. 사람 판정과 비교하려면 원래 답변 ID로 복원해야 함.

```python
pairs = golden["pairs"]

pair_inputs = [
    {
        "context": context_text(answer_by_id[p["a"]]["context_ids"]),
        "axis": p["axis"],
        "criterion": golden["axes"][p["axis"]]["criterion"],
        "pair_rule": golden["pair_rule"],
        "question": answer_by_id[p["a"]]["input"],
        "answer_a": answer_by_id[p["a"]]["actual_output"],
        "answer_b": answer_by_id[p["b"]]["actual_output"],
    }
    for p in pairs
]

pair_verdicts = pair_chain.batch(pair_inputs)

# A / B / tie -> 답변 ID / 무승부
first_winners = [
    {"A": p["a"], "B": p["b"], "tie": "무승부"}[v.winner]
    for p, v in zip(pairs, pair_verdicts)
]
```

여기서 `{...}[v.winner]`는 **딕셔너리 조회**. 예를 들어 `v.winner == "B"`라면 해당 쌍의 `p["b"]`를 선택.

### 판사 편향과 양방향 판정

| 편향 | 의미 | 확인 방법 |
|---|---|---|
| **위치 효과** | A/B 중 먼저 또는 나중에 제시된 답을 선호 | A/B 순서를 뒤집어 같은 답이 이기는지 비교 |
| **장황함 효과** | 길고 자세한 답을 실제 기준보다 높게 평가 | 내용이 같고 길이만 다른 두 답 비교 |
| **권위 효과** | “공식 확정”, “전문가” 등 출처처럼 보이는 문구를 지나치게 신뢰 | 근거 없는 권위 표현만 추가해 비교 |
| **자기 선호** | 자신의 출력 또는 비슷한 모델의 답을 선호할 가능성 | 답변 모델과 판사 모델을 분리하고 사람 판정과 대조 |

**순서를 바꿔 다시 평가하는 문법**

```python
# 딕셔너리의 기존 필드는 복사하고 A/B 두 필드만 덮어쓰기
swapped_inputs = [
    {**row, "answer_a": row["answer_b"], "answer_b": row["answer_a"]}
    for row in pair_inputs
]

swapped_verdicts = pair_chain.batch(swapped_inputs)

# 바뀐 순서에서 A는 원래 b, B는 원래 a
second_winners = [
    {"A": p["b"], "B": p["a"], "tie": "무승부"}[v.winner]
    for p, v in zip(pairs, swapped_verdicts)
]

# 순서를 바꿔도 같은 승자가 나오면 채택, 다르면 무승부
def two_way(first, second):
    return first if first == second else "무승부"

final_winners = [
    two_way(first, second)
    for first, second in zip(first_winners, second_winners)
]
```

- `{**row, "answer_a": ...}`: **딕셔너리 언패킹**. 기존 값 복사 후 동일 키를 새 값으로 덮어씀.
- `x if 조건 else y`: **조건부 표현식**. 조건에 따라 반환값 선택.
- 양방향 판정은 위치에 따른 **불일치를 무승부로 처리**하는 규칙이지, 항상 성능을 올리는 방법은 아님.
- 교안 결과: 첫 순서의 사람 승자 일치 **10/10**, 양방향은 **9/10**. 순서가 달라 한 쌍이 무승부로 바뀐 사례.
- 두 순서 모두에서 긴 답이나 권위 표현을 선호하면 이 방법으로 해결되지 않음. **기준 수정과 사람 검증**이 추가로 필요.

## 5. 사람 판정으로 판사 성능 검증

### 미탐·오탐과 평가 지표

여기서는 **`fail`을 양성(Positive)** 으로 정의하고 **사람 판정**을 정답으로 취급.

| 사람 판정 | 판사 판정 | 분류 | 의미 |
|---|---|---|---|
| `fail` | `fail` | TP | 실패를 올바르게 탐지 |
| `fail` | `pass` | FN, **미탐** | 실패 답변을 통과시킴 |
| `pass` | `fail` | FP, **오탐** | 정상 답변을 실패 처리 |
| `pass` | `pass` | TN | 정상 답변을 올바르게 통과 |

```text
일치율       = (TP + TN) / 전체
실패 탐지율  = TP / (TP + FN)  = 사람 fail 중 판사도 fail인 비율
정상 통과율  = TN / (TN + FP)  = 사람 pass 중 판사도 pass인 비율
Cohen's κ    = (실제 일치율 - 우연 기대 일치율) / (1 - 우연 기대 일치율)
```

- **일치율만으로 충분하지 않음:** `pass`가 많은 데이터에서는 무조건 `pass`를 출력해도 일치율이 높을 수 있음.
- **실패 탐지율이 낮음:** 미탐이 많음 → 정책 위반·오류가 배포 단계로 넘어갈 위험.
- **정상 통과율이 낮음:** 오탐이 많음 → 정상 답변을 불필요하게 거부.
- **Cohen's Kappa(κ):** 우연히 맞을 가능성을 보정한 일치도. `1` 완전 일치, `0` 우연 수준, 음수는 우연보다 낮은 수준. **단독 합격선으로 사용하지 않음**.

### 코드: `scorecard()`

```python
from sklearn.metrics import cohen_kappa_score

def scorecard(table):
    human = table["사람"]
    judge = table["판사"]
    return {
        "일치율": round(float((human == judge).mean()), 2),
        "실패 탐지율": round(
            float((judge[human == "fail"] == "fail").mean()), 2
        ),
        "정상 통과율": round(
            float((judge[human == "pass"] == "pass").mean()), 2
        ),
        "kappa": round(float(cohen_kappa_score(human, judge)), 2),
    }

# 전체 점수 및 무조건 pass만 주는 판사와 비교
actual_card = scorecard(direct_table)
always_pass_card = scorecard(direct_table.assign(판사="pass"))

# 사람 판정과 다른 결과만 확인
wrong = direct_table[direct_table["사람"] != direct_table["판사"]].copy()
wrong["구분"] = wrong["사람"].map({"fail": "미탐", "pass": "오탐"})
```

**핵심 문법**

- `(human == judge).mean()`: 불리언(`True=1`, `False=0`) 평균으로 일치 비율 계산.
- `judge[human == "fail"]`: **사람이 fail로 판정한 행**만 골라 판사의 탐지율 계산.
- `.assign(판사="pass")`: 원본을 유지하면서 `판사` 열을 고정값으로 설정한 새 DataFrame 반환.
- `.copy()`: 별도 DataFrame 복사본 생성.
- `.map({"fail": "미탐", ...})`: 값에 대응하는 이름으로 변환.
- `cohen_kappa_score(human, judge)`: scikit-learn의 두 평가자 간 κ 계산.

**교안의 실행 예시**

| 판사 | 일치율 | 실패 탐지율 | 정상 통과율 | κ |
|---|---:|---:|---:|---:|
| 실제 판사(전체) | 0.97 | 0.96 | 0.98 | 0.92 |
| 늘 `pass`만 주는 판사 | 0.80 | 0.00 | 1.00 | 0.00 |

늘 `pass`인 판사는 전체 평가 칸 120개 중 96개를 맞혀 일치율이 0.80이지만, **실제 실패 24건을 모두 놓침**. 실패 탐지율과 정상 통과율을 함께 봐야 하는 이유.

### 불일치 원인 분석

사람·판사의 라벨이 다른 칸은 **사람 이유와 판사 이유를 직접 비교**.

| 원인 | 점검 항목 | 수정 대상 |
|---|---|---|
| 모호한 기준 | 판사와 사람이 기준을 다르게 해석했는가 | `criterion`, 허용 조건 |
| 부족한 근거 | 평가에 필요한 문장이 빠졌는가 | `context_ids` |
| 판사 실수 | 기준·근거가 충분한데도 잘못 판정했는가 | 프롬프트, 판사 모델 |
| 사람 판정 오류 | 원래 사람 라벨이 틀렸는가 | `labels`, `reasons` |

## 6. 실무 적용: 상담 챗봇의 정책 준수·배포 판단

교안의 두 번째 실습은 **스토어 정책 P1–P5**, 상담 질문 **8개**, 후보 답변 **v1·v2 각 8개(총 16개)**를 비교.

### 모호한 기준 vs 구체적인 기준

```python
# 모호한 기준
VAGUE_CRITERION = "고객에게 친절하고 도움이 되는 답이면 pass다."

# 구체적 정책 기준
policy_axis = store["axes"]["정책"]
rules = policy_axis["criterion"] + "\n" + "\n".join(policy_axis["steps"])
policy_criteria = {
    r["question_id"]: rules + "\n이 질문의 필수 안내: " + ", ".join(r["required_points"])
    for r in store["records"]
}
```

**핵심:** 평가 기준에 정책 원문과 `required_points`(질문별 필수 안내 사항)를 포함해야, **친절하지만 정책을 위반한 답변**을 `fail`로 판정할 수 있음.

- `"\n".join(policy_axis["steps"])`: 여러 기준 문장을 줄바꿈으로 합침.
- `", ".join(r["required_points"])`: 필수 안내 사항을 쉼표로 구분한 문자열로 변환.
- `policy_criteria[질문ID]`: 질문마다 서로 다른 기준을 전달.
- 별도의 새 모델을 만드는 대신 **기존 `direct_chain`에 `criterion`만 교체**하여 재사용.

교안 실행 결과에서 모호한 기준의 **실패 탐지율은 0.50**, 정책 기준은 **1.00**이었음. 특정 실행의 예시이며 모든 데이터에서 동일한 향상을 보장하지 않음.

### 정책 검사와 배포 결정 문법

```python
# 교안의 연습용 임계값: 실패 탐지율·정상 통과율 각 0.8 이상
judge_ok = (
    policy_card["실패 탐지율"] >= 0.8
    and policy_card["정상 통과율"] >= 0.8
)

for version in ["v1", "v2"]:
    part = policy_table[policy_table["버전"] == version]
    fail_questions = part.loc[part["판사"] == "fail", "질문 ID"].tolist()
    decision = "보류" if fail_questions else "배포"
    print(version, fail_questions, decision)
```

- `and`: 두 평가 지표가 모두 기준을 충족하는지 확인.
- `.loc[행조건, "열이름"]`: 원하는 행과 열 선택.
- `.tolist()`: pandas Series를 일반 리스트로 변환.
- `"보류" if fail_questions else "배포"`: 실패 질문이 하나라도 있으면 보류.
- `0.8`은 **교안에서 정한 실습용 판사 채택 기준**. 모든 서비스에 적용되는 표준값은 아님.

**주의:** 원래 실습 코드는 `judge_ok`가 거짓이더라도 아래의 배포 비교표를 계산함. 실제 서비스에서는 **판사가 검증을 통과하지 못했다면 그 판정으로 배포를 결정하지 않도록 별도 조건문**이 필요.

**교안 실행 결과**

| 버전 | 정책 `pass` 질문 수 | `fail` 질문 | 배포 판단 |
|---|---:|---|---|
| v1 | 5/8 | S02, S05, S07 | **보류** |
| v2 | 3/8 | S01, S03, S04, S06, S07 | **보류** |

v1이 Pairwise 비교에서 더 많이 이겨도 **남은 실패 질문이 있기 때문에 보류**. 또한 S07은 두 답 모두 `fail`이지만, 상대적으로 덜 심각한 v2가 Pairwise 승자가 될 수 있음.

## 7. 코드 문법 빠른 복습

| 문법 | 기억할 기능 |
|---|---|
| `BaseModel`, `Field`, `Literal` | 판사 응답의 형식·필드·허용값 정의 |
| `ChatPromptTemplate.from_messages()` | `system`/`human` 프롬프트 템플릿 구성 |
| `prompt \| llm.with_structured_output(...)` | LCEL로 프롬프트·모델 연결 |
| `.invoke({...})` | 입력 한 건 실행 |
| `.batch([...], config={...})` | 다수 입력 실행·동시성 관리 |
| `{k: v for ...}` | 딕셔너리 컴프리헨션 |
| `[... for ... for ...]` | 중첩 자료를 하나의 리스트로 전개 |
| `{**row, "key": value}` | 딕셔너리 언패킹·특정 값 덮어쓰기 |
| `zip(list1, list2)` | 같은 위치의 항목끼리 묶기 |
| `x if cond else y` | 조건부 표현식 |
| `df[df["열"] == 값]`, `.loc[]` | DataFrame의 조건부 행·열 선택 |
| `.mean()`, `.map()`, `.assign()` | 비율 계산·값 치환·열 추가/교체 |
| `.to_csv(path, index=False)` | 평가 결과를 CSV 파일로 저장 |
| `cohen_kappa_score()` | 사람·판사의 우연 보정 일치도 계산 |

**전체 학습 흐름 요약**

```text
① 평가 축과 기준(criterion) 작성
        ↓
② 평가셋(질문·답변·근거·사람 라벨) 준비
        ↓
③ ChatPromptTemplate + with_structured_output
        ↓
④ Direct Scoring(pass/fail) · Pairwise(A/B/tie)
        ↓
⑤ Pairwise A/B 순서를 바꿔 편향 점검
        ↓
⑥ 사람 판정과 비교: 일치율·실패 탐지율·정상 통과율·κ
        ↓
⑦ 오류 원인 수정 → 재평가 → 절대 기준으로 배포 결정
```

> **한 줄 결론:** 판사 모델의 품질은 모델 자체뿐 아니라 **평가 기준·근거·사람 정답셋·편향 검증**에 달려 있음. 상대 비교 결과만으로 답변의 안전성이나 배포 가능성을 판단하면 안 됨.
