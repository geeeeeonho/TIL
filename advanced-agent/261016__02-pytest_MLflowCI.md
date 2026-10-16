# pytest 기초 · MLflow 기준선 · CI 회귀 게이트

> **통합 대상:** `부록_01_pytest_기초.ipynb` + `교안_02_기준선과_pytest_CI_회귀게이트.ipynb`  
> **정리 기준:** 핵심 개념과 코드 문법 위주. 중복된 pytest 설명·실습 출력·화면 이미지는 제외. MLflow의 기본 평가·인용 검증 구현은 교안 01에서 다룬 것으로 간주.

## 1. 전체 구조와 핵심 개념

**목적:** RAG의 검색 개수·프롬프트·모델 등을 변경했을 때, 기존보다 답변 품질이 떨어지는 **회귀(Regression)**를 자동으로 탐지하는 것.

```text
코드/설정 변경 (Pull Request)
    │
    ▼
골든셋으로 RAG 평가 실행
mlflow.genai.evaluate()
    │
    ├── 예측 함수(predict_fn) : 질문 → 검색 → 답변
    └── 채점 함수(scorers)    : correctness / citation_valid
    │
    ▼
평가 결과 저장
reports/results.json  ←→  baselines/baseline.json
   (이번 평가)                (승인된 기준선)
    │
    ▼
pytest 회귀 테스트
    ├── 평가 완전성
    ├── 절대 하한
    ├── 허용 하락폭
    └── 사례별 회귀
    │
    ├── 모두 통과 → 종료 코드 0 → CI 성공
    └── 하나라도 실패 → 종료 코드 1 → CI 실패
                                     │
                                     └── 필수 검사로 지정한 경우 병합 차단
```

| 개념 | 역할 |
|---|---|
| **단위 테스트(Unit Test)** | 함수처럼 작은 코드 단위에 입력을 넣고 예상한 결과가 나오는지 검사 |
| **pytest** | `test_` 함수와 `assert`를 실행하고 성공·실패를 판정하는 테스트 도구 |
| **골든셋(Golden Set)** | 평가 질문, 정답 답변, 사례 ID 등을 포함한 기준 데이터 |
| **MLflow Run** | 한 번의 평가와 실행 조건, 지표, 사례별 결과를 기록하는 단위 |
| **기준선(Baseline)** | 사람이 검토하고 승인한 평가 결과. 변경의 비교 대상 |
| **회귀 게이트(Regression Gate)** | 기준선 대비 품질 하락 여부를 검사해 변경의 통과·실패를 결정하는 규칙 |
| **CI(Continuous Integration)** | 변경 요청이 들어오면 정해진 평가·테스트를 자동 실행하는 과정 |

**역할 분리:** MLflow는 *평가를 실행하고 기록*하며, pytest는 *저장된 평가 결과를 규칙으로 판정*한다. CI는 이를 자동으로 연결한다.

---

## 2. pytest 기초 문법

### 2-1. 테스트 작성·실행

pytest는 기본적으로 `test_`로 시작하는 파일과 함수를 찾아 테스트한다. `assert`의 조건이 거짓이면 해당 테스트가 실패한다.

```python
# tests/test_citation_check.py
from citation_check import normalize

def test_line_break_becomes_space():
    assert normalize("일반 도서를\n14일 동안") == "일반 도서를 14일 동안"

def test_many_spaces_become_one():
    assert normalize("1인   7권까지") == "1인 7권까지"
```

```text
tests/
├── test_citation_check.py   # test_로 시작하는 테스트 파일
├── test_fixture_db.py
└── test_followalong.py
```

| 문법·명령 | 의미 |
|---|---|
| `def test_name():` | pytest가 자동으로 발견할 테스트 함수 |
| `assert actual == expected` | 실제 값과 기대값 비교 |
| `assert condition, "메시지"` | 실패할 때 표시할 설명 추가 |
| `uv run pytest` | 현재 uv 환경에서 테스트 실행 |
| `uv run pytest tests` | `tests` 폴더 전체 실행 |
| `uv run pytest tests/test_x.py` | 파일 하나 실행 |
| `uv run pytest tests/test_x.py::test_name` | 특정 테스트 함수만 실행 |
| `-v` | 테스트별 이름과 `PASSED`·`FAILED` 자세히 출력 |
| `-q` | 짧게 출력 |
| `-k "문자열"` | 이름에 해당 문자열이 포함된 테스트만 실행 |
| `-s` | `print()` 출력 표시 |
| `--tb=short` / `--tb=no` | 실패 위치 표시를 줄이거나 생략 |

```bash
uv run pytest -v tests/test_citation_check.py
uv run pytest -v -k middle_dot tests/test_citation_check.py
```

테스트 출력에서 `.`은 성공, `F`는 실패. 실패 시 `FAILURES` 구역의 실패 줄과 실제값·기대값 차이, 마지막 `short test summary info`를 확인한다.

### 2-2. `parametrize`: 여러 입력을 한 테스트로 처리

같은 함수를 여러 입력·기대값으로 검사할 때 사용한다. **데이터 한 줄이 독립적인 테스트 하나**가 된다.

```python
import pytest
from citation_check import check_citation

@pytest.mark.parametrize(
    "evidence_id, quote, expected",
    [
        ("loan-basic", "14일 동안", "확인"),
        ("loan-weekend", "주말 3일", "없는 근거 ID"),
        ("loan-basic", "30일 동안", "원문에 없는 문구"),
    ],
    ids=["ok", "unknown_id", "wrong_quote"],
)
def test_check_citation(source_texts, evidence_id, quote, expected):
    citation = {"evidence_id": evidence_id, "quote": quote}
    result = check_citation(citation, source_texts, ["loan-basic"])
    assert result == expected
```

- `@pytest.mark.parametrize("a, b", [(값1, 값2), ...])`: 매 실행마다 인자 값을 바꿈
- `ids=[...]`: 각 테스트에 읽기 쉬운 이름 부여 (`test_check_citation[unknown_id]`)
- `source_texts`: 여기서는 아래에서 설명할 **fixture**가 제공하는 값
- 하나의 입력에서 실패해도 나머지 입력은 개별적으로 판정됨

### 2-3. `fixture`: 테스트 준비물을 주입

공통 데이터·객체·DB 연결을 테스트 전에 준비해 함수 인자로 넘긴다. pytest는 **인자 이름과 동일한 fixture**를 찾아 실행한다.

```python
@pytest.fixture
def source_texts():
    return {
        "loan-basic": "회원은 일반 도서를 14일 동안 빌릴 수 있습니다.",
        "reading-room": "열람실 좌석은 4시간 단위로 예약합니다.",
    }

def test_original_quote(source_texts):
    assert "14일 동안" in source_texts["loan-basic"]
```

**`parametrize` vs `fixture`**

| 구분 | `parametrize` | `fixture` |
|---|---|---|
| 목적 | 테스트할 입력·기대값 조합 제공 | 테스트에 필요한 준비물 제공 |
| 효과 | 데이터 개수만큼 테스트 실행 | 테스트 함수에 준비된 값 주입 |
| 주요 문법 | `@pytest.mark.parametrize(...)` | `@pytest.fixture` |
| 활용 | 여러 인용 상태 검사 | 공통 원문 사전, 문서, DB 연결 |

가변 객체(`dict`, `list`)를 테스트 간 직접 공유하면 한 테스트의 수정이 다른 테스트를 오염시킬 수 있다. 기본 fixture(`scope="function"`)는 테스트마다 새 객체를 만든다.

**`yield`로 준비·정리 구분**

```python
import sqlite3
import pytest

@pytest.fixture
def library_db():
    conn = sqlite3.connect("library.db")  # 준비
    yield conn                            # 테스트에 전달
    conn.close()                         # 테스트 종료 후 정리

def test_rule_count(library_db):
    count = library_db.execute(
        "SELECT COUNT(*) FROM loan_rules"
    ).fetchone()[0]
    assert count == 3
```

- `return`: 준비물을 넘기고 함수 종료
- `yield`: 준비물을 넘긴 후 테스트가 끝나면 **아래 정리 코드** 수행
- DB 연결이나 임시 파일처럼 사용 후 정리가 필요한 자원에 적합

| `scope` | fixture 생성 빈도 | 활용 |
|---|---|---|
| `function` (기본) | 테스트 함수마다 | 테스트가 수정할 데이터 |
| `class` | 테스트 클래스마다 | 같은 클래스의 공유 준비물 |
| `module` | 테스트 파일마다 | 읽기 전용 DB 연결·모델 |
| `package` | 테스트 패키지마다 | 패키지 공통 자원 |
| `session` | pytest 실행마다 | 실행 전체의 공통 자원 |

`scope`가 넓을수록 같은 객체를 공유하므로, 테스트 간 상태 오염에 주의한다.

### 2-4. LLM 대신 가짜 모델로 주변 코드 검사

**LLM이 생성한 답변의 품질**은 골든셋 기반 평가로 다루고, **LLM 호출 전후의 결정적 코드**는 단위 테스트로 확인한다.

교안의 예시는 LangChain `FakeListChatModel`을 사용한다.

```python
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from rag_answer import ABSTAIN, answer_question

def test_unknown_citation_is_blocked(docs):
    fake_llm = FakeListChatModel(
        responses=["주말에는 3일 더 빌릴 수 있습니다. [loan-weekend]"]
    )
    result = answer_question(
        "일반 도서는 몇 권까지 빌리나요?",
        docs,
        fake_llm,
    )
    assert result == ABSTAIN
```

- `FakeListChatModel(responses=[...])`: 모델이 돌려줄 응답을 미리 지정
- `answer_question(question, docs, llm)`: 가짜 모델을 주입해 앱의 후처리 검사
- 이 예시는 `docs`가 검색 문서 fixture이고 `loan-weekend`가 검색되지 않았다는 **교안의 테스트 조건**을 전제로 함
- 문서 문맥 생성(`format_documents`), 검색되지 않은 인용 차단, 빈 검색 결과 처리 등에 유용

### 2-5. 종료 코드와 설정 파일

| 종료 코드 | 의미 |
|---|---|
| `0` | 모든 테스트 통과 |
| `1` | 한 개 이상 실패 |
| `2` | 테스트 수집 등 실행 중 오류 |
| `5` | 실행할 테스트 없음 |

CI는 성공 메시지의 문장을 읽는 대신 **종료 코드 0인지** 확인한다.

```python
import subprocess
import sys

completed = subprocess.run(
    [sys.executable, "-m", "pytest", "-q", "tests"],
    capture_output=True,
    text=True,
)
print(completed.returncode)
```

`pytest.ini` 예시(부록에서 사용):

```ini
[pytest]
testpaths = tests
pythonpath = .
addopts = -p no:deepeval
```

- `testpaths`: 기본 테스트 탐색 폴더
- `pythonpath`: 프로젝트 루트의 모듈을 import할 경로
- `-p no:deepeval`: 이 실습에서 불필요한 DeepEval pytest 플러그인 로드 방지

> 교안에는 실패 출력 확인용으로 **일부러 틀리게 작성한** `test_failure_demo.py`가 있다. 실제 CI의 전체 테스트에 포함하면 종료 코드 1이 되므로 실무용 테스트에서는 제외한다.

---

## 3. MLflow 기준선 만들기

### 3-1. Run에 평가 조건과 결과 기록

교안 01에서 만든 `library_records`, `answer_with_citations`, `correctness`, `citation_valid`를 재사용한다.

```python
import mlflow

gate_scorers = [correctness, citation_valid]
JUDGED_SCORERS = ["correctness", "citation_valid"]

def evaluate_run(run_name, dataset, predict_fn, scorers, params):
    with mlflow.start_run(run_name=run_name):
        for key, value in params.items():
            mlflow.log_param(key, value)

        result = mlflow.genai.evaluate(
            data=dataset,
            predict_fn=predict_fn,
            scorers=scorers,
        )
        mlflow.log_metric("case_count", len(result.result_df))
    return result
```

| 문법 | 역할 |
|---|---|
| `with mlflow.start_run(run_name=...)` | 하나의 평가 Run 시작·종료 |
| `mlflow.log_param(key, value)` | 모델·프롬프트 버전·`top_k` 등 실행 조건 기록 |
| `mlflow.log_metric(key, value)` | 사례 수처럼 수치 지표 기록 |
| `mlflow.genai.evaluate(data=..., predict_fn=..., scorers=...)` | 질문별 답변 생성 및 채점 |
| `result.metrics` | 집계 평가 지표 |
| `result.result_df` | 사례별 입력·출력·채점 결과 DataFrame |
| `result.run_id` | 해당 평가 Run 식별자 |

회귀 평가에서는 비용을 줄이기 위해 교안 01의 `faithfulness`를 제외하고 **`correctness`(정답 판정), `citation_valid`(인용 검증)** 두 항목을 사용한다.

### 3-2. 반복 평가와 흔들림(Noise)

동일한 설정이어도 답변 모델과 판사 모델의 결과가 달라질 수 있으므로 **현재 설정을 여러 번 평가**한다.

```python
top3_params = {
    "prompt_version": "v1",
    "app_model": model_name,
    "judge_model": eval_model_name,
    "top_k": 3,
}

top3_results = [
    evaluate_run(name, library_records, answer_with_citations,
                 gate_scorers, top3_params)
    for name in ["top3-a", "top3-b", "top3-c"]
]
```

교안은 전체 골든셋 **16건을 3회** 평가한다. 각 Run의 결과를 아래처럼 정리한다.

```text
make_report(result, split)
    └── {
          "split": "full" 또는 "smoke",
          "run_id": 평가 Run ID,
          "errors": 채점 실패/누락 칸 수,
          "metrics": {
              "correctness": 통과 비율,
              "citation_valid": 통과 비율
          },
          "cases": {
              "lib-01": {
                  "correctness": True/False/None,
                  "citation_valid": True/False/None
              },
              ...
          }
        }
```

`make_report`에서 중요한 판정 처리:

```python
value = row[f"{name}/value"]

if pd.isna(value):
    errors += 1
    case[name] = None
else:
    case[name] = bool(value == True)
```

- `pd.isna(value)`: 판정이 비어 있으면 채점 오류로 기록
- `case_id`로 판정을 보관해 Run마다 같은 질문끼리 비교
- **통과 비율 = `True`인 사례 수 / 평가 대상 사례 수**
- 채점 오류(`None`)를 통과로 처리하지 않음

**반복 평가로 계산할 값**

1. **늘 통과한 사례(Stable Cases):** 모든 Run에서 두 채점 함수가 모두 `True`인 사례. 사례별 회귀 검사에 사용.
2. **지표 흔들림(Noise):** 같은 범위에서 각 Run 통과 비율의 `최댓값 - 최솟값`.
3. **평가 범위(Split):** `full`(전체 16건)과 `smoke`(대표 6건)를 분리.

예를 들어 3회 판정이 `3/3`이면 안정 통과 후보, `1/3`·`2/3`이면 흔들린 사례, `0/3`이면 기존에도 실패하던 개선 과제로 본다. **3회만으로 실제 흔들림이 없다고 단정할 수는 없다.**

### 3-3. 기준선의 네 가지 판정 규칙

**기준선(Baseline)**은 점수가 가장 높은 Run이 아니라 **사람이 검토하고 승인한 Run**. 교안에서는 `top3-a`를 기준선으로 사용한다.

| 규칙 | 실패 조건 | 확인 목적 |
|---|---|---|
| **평가 완전성** | 사례 목록 불일치 또는 채점 오류 발생 | 일부만 평가하고 통과하는 문제 방지 |
| **절대 하한** | 현재 통과 비율이 정해진 최소값 미만 | 서비스 품질의 최저선 유지 |
| **허용 하락폭** | 기준선보다 허용량을 초과해 하락 | 평균 지표의 큰 회귀 탐지 |
| **사례별 회귀** | 원래 늘 통과하던 사례가 하나라도 실패 | 평균에 가려진 개별 실패 탐지 |

교안의 허용 하락폭 계산 규칙:

\[
\text{Noise} = \max(\text{반복 Run 통과율})-\min(\text{반복 Run 통과율})
\]

\[
\text{Allowed Drop} = \text{Noise}+\frac{1}{N}
\]

- `N`: 해당 평가 범위의 사례 수 (`full=16`, `smoke=6`)
- `1/N`: 사례 1건만큼 더 허용하는 **교안의 팀 정책**. 일반적으로 정해진 공식은 아님.
- 정답 판정 절대 하한 **0.6**, 인용 검증 절대 하한 **0.8**도 이 실습에서 팀이 정한 값.
- 허용 하락폭에 여유가 있어도 *안정적으로 통과하던 사례*가 실패하면 별도의 사례별 회귀 규칙에서 차단 가능.

```python
noise[name] = round(max(values) - min(values), 4)
allowed_drop[name] = round(
    noise[name] + 1 / len(case_ids), 4
)
```

**기준선 자료의 구조**

```text
baseline.json
├── run_id                  # 승인한 Run
├── params                  # prompt_version, app_model, judge_model, top_k
├── stable_cases            # 반복 평가에서 모두 통과한 case_id
└── splits
    ├── full
    │   ├── case_ids
    │   ├── metrics         # 기준선 통과 비율
    │   ├── noise
    │   ├── allowed_drop
    │   └── absolute_floor
    └── smoke               # 동일한 키 구조
```

### 3-4. 기준선 등록·저장·변경 비교

두 곳에 기준선을 남긴다.

- **MLflow:** 기준선 Run에 `baseline_role=champion` 태그 (사람이 화면에서 확인)
- **Git 저장소:** `baselines/baseline.json` (CI가 직접 읽어 판정)

```python
import json
from pathlib import Path
from mlflow import MlflowClient

client = MlflowClient()

# 이미 종료된 Run에도 태그 지정 가능
client.set_tag(library_baseline["run_id"], "baseline_role", "champion")

baseline_path = Path("baselines/baseline.json")
baseline_path.parent.mkdir(parents=True, exist_ok=True)
baseline_path.write_text(
    json.dumps(library_baseline, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
```

실제 노트북에서는 **기존 champion을 `retired`로 변경한 뒤** 새 champion을 등록한다. 기준선 갱신은 새 설정의 반복 평가 → 기존 대비 사례 확인 → 검토·승인 → 파일과 태그 갱신 순서.

설정을 바꿔 비교할 때는 **변경 대상 외 조건을 고정**한다. 교안에서는 `top_k=3 → 1`만 변경한다.

```python
def answer_top1(question):
    return answer_with_citations(question, top_k=1)

top1_result = evaluate_run(
    "top1", library_records, answer_top1,
    gate_scorers, {**top3_params, "top_k": 1},
)
```

`evaluate`가 넘겨주는 `question`에 추가 인자 `top_k`를 고정하려면 위와 같이 **래퍼 함수**를 사용한다.

Run 조회·조건별 비교:

```python
runs = mlflow.search_runs(
    experiment_names=["library-rag-eval"],
    filter_string="tags.baseline_role = 'champion'",
)
```

`mlflow.search_runs()`는 DataFrame을 반환. `tags.mlflow.runName`, `params.top_k`, `metrics.correctness/mean` 등의 열을 통해 조건과 지표를 비교할 수 있다. 사례별 상세 비교는 `result.result_df`의 `case_id/value`를 기준으로 맞춘다.

---

## 4. pytest로 회귀 게이트 구현

### 4-1. 평가 실행과 판정을 분리하는 이유

RAG 평가(LLM 호출)는 느리고 비용이 들지만, **pytest 규칙 검사는 저장된 JSON만 읽어 실행**할 수 있다.

```text
[평가 단계]                               [판정 단계]
run_eval.py                                pytest
  └── MLflow 평가                           ├── baseline.json
       └── reports/results.json  ──────────┤
                                           └── 통과/실패·종료 코드
```

```text
rag_eval_ci/
├── app.py
├── run_eval.py
├── data/
├── baselines/
│   └── baseline.json
├── reports/
│   └── results.json
├── tests/
│   └── test_rag_regression.py
├── pyproject.toml
└── .github/workflows/rag-eval.yml
```

`reports/results.json`에는 이번 평가의 `split`, `errors`, `metrics`, `cases`가 저장되고, `baselines/baseline.json`에는 승인된 `splits`, `stable_cases` 등이 저장된다.

### 4-2. 회귀 테스트 핵심 코드

`test_rag_regression.py`의 핵심을 한 번에 정리한 코드. **테스트 과정에서 LLM을 호출하지 않는다.**

```python
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

report = json.loads(
    (ROOT / "reports/results.json").read_text(encoding="utf-8")
)
baseline = json.loads(
    (ROOT / "baselines/baseline.json").read_text(encoding="utf-8")
)

# full / smoke에 맞는 기준값 선택
split = baseline["splits"][report["split"]]
JUDGED_SCORERS = list(split["metrics"])

# 안정 통과 사례 중 현재 평가 범위에 포함된 것만 검사
stable_in_scope = [
    case_id for case_id in baseline["stable_cases"]
    if case_id in report["cases"]
]

# 1. 평가 완전성
def test_same_cases():
    assert sorted(report["cases"]) == sorted(split["case_ids"])

def test_no_scoring_errors():
    assert report["errors"] == 0

# 2. 절대 하한
@pytest.mark.parametrize("name", JUDGED_SCORERS)
def test_metric_floor(name):
    assert report["metrics"][name] >= split["absolute_floor"][name]

# 3. 허용 하락폭
@pytest.mark.parametrize("name", JUDGED_SCORERS)
def test_metric_drop(name):
    drop = round(split["metrics"][name] - report["metrics"][name], 4)
    assert drop <= split["allowed_drop"][name]

# 4. 사례별 회귀
@pytest.mark.parametrize("case_id", stable_in_scope)
def test_stable_case_still_passes(case_id):
    for name in JUDGED_SCORERS:
        assert report["cases"][case_id][name] is True
```

**핵심 문법·판정 읽기**

| 코드 | 의미 |
|---|---|
| `Path(__file__).resolve().parents[1]` | 테스트 파일 기준으로 프로젝트 루트 경로 계산 |
| `json.loads(path.read_text(...))` | 저장된 JSON을 Python dict로 변환 |
| `baseline["splits"][report["split"]]` | `full`/`smoke` 중 이번 평가와 동일한 범위 선택 |
| `sorted(a) == sorted(b)` | 사례 순서와 관계없이 목록 일치 비교 |
| `@pytest.mark.parametrize("name", JUDGED_SCORERS)` | 채점 함수별로 동일한 규칙 테스트 |
| `drop = baseline - current` | 기준선에서 현재 값으로의 하락량 |
| `case[name] is True` | 안정 사례는 각 채점 함수에서 명시적으로 통과해야 함 |

```bash
# 평가와 테스트를 순서대로 실행
uv sync
uv run python run_eval.py --split smoke
uv run pytest -q tests
```

**`smoke`와 `full`**

| 평가 범위 | 사례 수(교안) | 실행 시점 |
|---|---:|---|
| `smoke` | 6 | 변경 요청(Pull Request)마다 |
| `full` | 16 | 예약 실행 또는 수동 실행 |

`smoke`가 실패한 경우 실패 이유를 확인하고, 원래 흔들리던 사례가 의심되면 `full` 평가로 재확인한다.

### 4-3. DeepEval `assert_test`와 차이

```python
from deepeval import assert_test

def test_answer_matches_expected_output():
    assert_test(test_case, [correctness_metric])
```

| 방식 | 판정 시점 | 특징 |
|---|---|---|
| **MLflow 결과 파일 + pytest** | 평가 완료 후 | 기존 기준선과 비교. 테스트는 파일만 읽음 |
| **DeepEval `assert_test`** | 테스트 실행 중 | `LLMTestCase`와 `GEval` 등의 지표로 직접 채점 |

`assert_test`는 모델 판정이 통과 기준(`threshold`)에 미달하면 테스트를 실패시킨다. 위 예시는 `test_case`와 `correctness_metric`이 사전에 정의돼 있어야 한다.

---

## 5. GitHub Actions로 자동화

### 5-1. 핵심 구성과 YAML 문법

GitHub Actions는 `.github/workflows/*.yml` 파일을 읽고, 이벤트에 맞춰 가상 컴퓨터(Runner)에서 작업을 실행한다.

```text
Pull Request 생성·갱신
    └── GitHub Actions
        ├── 저장소 받기
        ├── uv + 의존성 설치
        ├── RAG 평가 (smoke 또는 full)
        ├── pytest 회귀 테스트
        └── 결과 요약·산출물 보관
```

| YAML 키 | 역할 |
|---|---|
| `name` | 워크플로 표시 이름 |
| `on` | 실행 이벤트: `pull_request`, `schedule`, `workflow_dispatch` |
| `paths` | 변경 요청 중 특정 경로 변경 시에만 실행 |
| `jobs` | 하나 이상의 작업 |
| `runs-on` | 작업 실행 환경 |
| `steps` | 작업 안에서 순서대로 실행할 단계 |
| `uses` | 외부 GitHub Action 사용 |
| `run` | 셸 명령 실행 |
| `env` | 환경 변수 등록 |
| `if: always()` | 앞 단계가 실패했어도 해당 단계 수행 |
| `secrets.OPENAI_API_KEY` | 저장소의 비밀 변수 참조 |

**교안 워크플로의 핵심 흐름(중복·주석 축약)**

```yaml
name: rag-eval

on:
  pull_request:
    paths:
      - "app.py"
      - "run_eval.py"
      - "data/**"
      - "tests/**"
      - "baselines/**"
      - "pyproject.toml"
      - "uv.lock"
      - ".github/workflows/rag-eval.yml"
  schedule:
    - cron: "0 17 * * *"  # UTC 17:00 = 한국 시간 다음 날 02:00
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: rag-eval-${{ github.ref }}
  cancel-in-progress: true

jobs:
  evaluate:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10.2.0
        with:
          python-version: "3.12"
          enable-cache: true

      - name: 라이브러리 설치
        run: uv sync --locked

      - name: 평가 실행
        run: |
          if [ "${{ github.event_name }}" = "pull_request" ]; then
            uv run python run_eval.py --split smoke
          else
            uv run python run_eval.py --split full
          fi

      - name: 회귀 테스트
        run: uv run pytest -q tests --junitxml=reports/junit.xml

      - name: 결과 요약
        if: always()
        run: |
          if [ -f reports/summary.md ]; then
            cat reports/summary.md >> "$GITHUB_STEP_SUMMARY"
          fi

      - name: 평가 산출물 저장
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: rag-eval-reports
          path: reports/
          retention-days: 14
```

`cron`의 다섯 칸은 `분 시 일 월 요일` 순서이며 UTC를 기준으로 실행된다.

- `uv sync --locked`: `uv.lock`의 의존성 버전을 유지하고 잠금 파일이 맞지 않으면 실패
- `--junitxml=reports/junit.xml`: pytest 결과를 JUnit XML로 저장
- `$GITHUB_STEP_SUMMARY`: Actions 실행 화면에 Markdown 요약 표시
- `upload-artifact`: `reports/` 결과물을 실행 종료 후에도 확인할 수 있도록 보관
- `concurrency.cancel-in-progress`: 같은 브랜치의 이전 실행을 취소해 중복 평가 비용 완화

### 5-2. CI 실패와 병합 차단은 구분

**pytest가 실패했다고 병합 버튼까지 자동으로 막히는 것은 아니다.** 저장소의 브랜치 보호 규칙/Ruleset에서 해당 검사를 **필수 상태 검사(Required Status Check)**로 지정해야 병합이 차단된다.

실무 주의점:

- `paths` 필터 때문에 필수 검사가 실행되지 않으면 대기 상태로 남아 병합이 막힐 수 있음. 필수 검사 설정과 함께 설계할 것.
- 외부 Fork에서 제출한 PR에는 Secrets가 전달되지 않을 수 있음. 키가 필요한 평가와 키 없는 테스트의 실행 조건을 구분할 것.
- `continue-on-error: true`, `|| true`로 테스트 실패를 성공 처리하지 말 것.
- 답변·판사에 무작위성이 있으므로, 게이트가 실패한 사례와 판정 이유를 읽고 필요하면 반복 평가해 확인할 것.
- 새로운 모델·채점 규칙·골든셋을 적용하면 기존 기준선과 직접 비교하기 어려울 수 있으므로 기준선을 재검토할 것.

### 5-3. 응용: 프롬프트만 변경하는 경우

교안의 HR 상담 챗봇 실습은 검색 문서 수가 아니라 **프롬프트 버전**을 바꿔 동일한 회귀 게이트를 재사용한다.

- 현재 프롬프트 `v1`: 인용 구절을 원문에서 글자 그대로 복사
- 개정 프롬프트 `v2`: 인용 구절을 읽기 쉽게 다듬도록 지시
- 결과적으로 **내용 정답(`correctness`)과 정확한 인용(`citation_valid`)은 별도로 판단해야 함**

서로 다른 챗봇이 같은 테스트 파일을 공유할 때는 채점 결과 이름을 일치시킨다.

```python
from mlflow.genai.scorers import scorer

@scorer(name="citation_valid")
def hr_citation_valid(outputs):
    # HR 문서 원문으로 인용 상태를 판정
    ...
```

실행 조건 dict는 원본을 직접 변경하지 않도록 **복사한 뒤 수정**한다.

```python
hr_v2_params = dict(hr_params)
hr_v2_params["prompt_version"] = "v2"
```

---

## 핵심 문법만 다시 보기

| 용도 | 대표 코드 |
|---|---|
| 테스트 함수 | `def test_example(): assert actual == expected` |
| 여러 입력 검사 | `@pytest.mark.parametrize("x, expected", [...])` |
| 테스트 준비물 | `@pytest.fixture` |
| 준비·정리 | `yield resource` |
| 가짜 LLM | `FakeListChatModel(responses=[...])` |
| MLflow Run 생성 | `with mlflow.start_run(run_name=...)` |
| Run 실행 조건 | `mlflow.log_param("top_k", 3)` |
| 평가 실행 | `mlflow.genai.evaluate(data=..., predict_fn=..., scorers=...)` |
| Run 조회 | `mlflow.search_runs(experiment_names=[...])` |
| 종료된 Run 태그 | `MlflowClient().set_tag(run_id, "baseline_role", "champion")` |
| JSON 저장 | `path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")` |
| JSON 불러오기 | `json.loads(path.read_text(encoding="utf-8"))` |
| 전체 테스트 실행 | `uv run pytest -q tests` |
| CI 평가 실행 | `uv run python run_eval.py --split smoke` |

**최종 흐름:** `pytest 문법 이해 → 반복 평가 → 흔들림 계산 → 기준선 승인 → 변경 평가 → JSON 비교 테스트 → GitHub Actions 자동 실행`.
