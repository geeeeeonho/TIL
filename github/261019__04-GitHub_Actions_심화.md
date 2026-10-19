# GitHub Actions 심화 사용방법

> 출처: `부록_02_GitHub_Actions_심화.ipynb`  
> 목적: 기존 `ci.yml`에 **Ruff 검사**와 **PR AI 코드 리뷰**를 추가하는 방법 정리  
> 기준: 기초편의 `pytest_ci_practice/` 저장소, `uv`·`pytest`, `main` 브랜치 사용

## 1. 전체 사용 흐름

기초편에서 작성한 테스트용 CI를 그대로 사용하고, **Ruff는 `unit-tests`의 단계로**, **AI 리뷰는 별도 `ai-review` 작업으로** 추가함.

```text
코드 수정 → Pull Request 생성
                 │
                 ├─ unit-tests (Ubuntu / Windows)
                 │   ├─ pytest 실행          [정상 동작 확인]
                 │   ├─ ruff check .        [린트 검사]
                 │   └─ ruff format --check . [포맷 검사]
                 │              │
                 │              └─ 테스트 통과 시 gate-rules 실행
                 │
                 └─ ai-review (PR일 때만)
                     ├─ git diff로 변경 코드 수집
                     ├─ LLM 리뷰 → review.md 생성
                     └─ gh pr comment로 PR 댓글 등록
```

| 기능 | 사용하는 명령·파일 | 결과 |
|---|---|---|
| 테스트 | `uv run pytest ...` | 실행 결과가 올바른지 판정 |
| 린트 | `uv run ruff check .` | import·변수·문법·스타일 규칙 위반 검사 |
| 포맷 | `uv run ruff format --check .` | 코드 모양이 통일됐는지 검사 |
| AI 리뷰 | `tools/ai_reviewer.py` | 바뀐 코드를 읽고 **참고 의견**을 PR 댓글로 남김 |

**핵심 구분:** pytest·Ruff는 성공/실패를 판정하는 검사. AI 리뷰는 잘못된 지적도 가능하므로 필수 병합 검사로 사용하지 않음. AI 리뷰는 OpenAI API 호출 비용이 발생함.

## 2. Ruff 설정 및 로컬 사용

### 2-1. 설정하고 설치하기

모든 명령은 `pytest_ci_practice/` 저장소 최상위 폴더에서 실행. 기존 `pyproject.toml`에 다음 설정이 있는지 확인하고, 없으면 관련 부분을 추가함.

`pyproject.toml`

```toml
[dependency-groups]
dev = [
    "ruff==0.17.1",
]

[tool.ruff]
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "I"]
```

- `dev`: 개발용 도구 목록. 기존 `dev` 의존성이 있다면 지우지 말고 Ruff를 추가.
- `line-length = 120`: 한 줄 길이 기준.
- `select`: 검사할 규칙 묶음. `E`(스타일), `F`(Pyflakes·안 쓰는 코드 등), `I`(import 순서).
- 교안에는 `W`·`B`·`UP` 규칙도 소개되지만, 위 설정에서는 **선택되지 않아 검사하지 않음**.

```bash
uv sync
uv run ruff --version
```

교안에 고정한 Ruff 버전은 `0.17.1`. 실제 버전은 프로젝트 설정과 잠금 파일에 따름.

### 2-2. 확인 명령과 수정 명령 구분

| 명령 | 역할 | 파일 변경 |
|---|---|---|
| `uv run ruff check .` | 린트 규칙 위반 확인 | X |
| `uv run ruff format --check .` | 포맷 위반 확인 | X |
| `uv run ruff format --diff .` | 포맷했을 때 바뀔 부분 미리 보기 | X |
| `uv run ruff check --fix .` | 안전하게 고칠 수 있는 린트 오류 수정 | O |
| `uv run ruff check --fix --unsafe-fixes .` | 동작이 바뀔 수 있는 수정까지 적용 | O |
| `uv run ruff format .` | 공백·따옴표·줄 나누기 등 실제 정리 | O |

- `.`: 현재 폴더 아래의 대상 파일 검사. 한 파일만 검사하려면 `.` 대신 `try_ruff.py` 같은 파일명 사용.
- **로컬:** `--fix`, `ruff format`으로 수정한 뒤 다시 검사.
- **GitHub CI:** `ruff check`, `ruff format --check`처럼 **확인만 하는 명령** 사용.
- `--unsafe-fixes`는 코드 의미가 바뀔 수 있으므로 수정 내용을 확인할 때만 사용.

### 2-3. 코드 검사 → 수정 → 재검사

연습용 `try_ruff.py`를 만든 뒤 다음 코드 입력.

```python
from gate_rules import metric_drop
import json

def drop_text(baseline_value,current_value):
    drop=metric_drop(baseline_value,current_value)
    if drop == None:
        return "하락폭 없음"
    return f'하락폭 {drop}'
```

**① 문제 확인**

```bash
uv run ruff check --output-format concise try_ruff.py
```

```text
try_ruff.py:1:1: I001 [*] Import block is un-sorted or un-formatted
try_ruff.py:2:8: F401 [*] `json` imported but unused
try_ruff.py:5:16: E711 Comparison to `None` should be `cond is None`
Found 3 errors.
[*] 2 fixable with `--fix` (1 unsafe fix available with `--fix --unsafe-fixes`).
```

출력 형식은 `파일:줄:칸: 규칙코드 [*] 문제`. `[*]`는 `--fix`로 자동 수정 가능하다는 뜻.

| 규칙 | 의미 | 처리 |
|---|---|---|
| `I001` | import 순서 잘못됨 | `--fix` |
| `F401` | 사용하지 않는 import | `--fix` |
| `E711` | `None`을 `==`로 비교 | 직접 `is None`으로 수정하거나 검토 후 unsafe fix |
| `F821` | 정의되지 않은 이름 | 직접 수정 |
| `E501` | 설정한 한 줄 길이 초과 | 직접 줄 나누기 등 검토 |

규칙 설명을 자세히 확인할 때:

```bash
uv run ruff rule F401
```

**② 안전한 자동 수정**

```bash
uv run ruff check --fix try_ruff.py
```

`I001`·`F401`이 수정되고 `E711`은 남음. `if drop == None:`을 `if drop is None:`으로 직접 변경.

**③ 포맷 적용**

```bash
uv run ruff format try_ruff.py
```

**④ 두 검사 다시 실행**

```bash
uv run ruff check try_ruff.py
uv run ruff format --check try_ruff.py
```

정상 결과 예시:

```text
All checks passed!
1 file already formatted
```

최종 코드는 다음과 같음.

```python
from gate_rules import metric_drop


def drop_text(baseline_value, current_value):
    drop = metric_drop(baseline_value, current_value)
    if drop is None:
        return "하락폭 없음"
    return f"하락폭 {drop}"
```

**권장 순서:** `ruff check` → `ruff check --fix` → 남은 문제 직접 수정 → `ruff format` → 두 검사 재확인. 실습 후 `try_ruff.py`는 삭제해 CI에 잘못 포함되지 않도록 함.

### 2-4. 의도적인 규칙 위반은 예외 지정

규칙 위반으로 표시되지만 의도한 코드라면 필요한 규칙만 제외. 가능한 한 **좁은 범위**로 지정.

| 적용 범위 | 작성 예시 |
|---|---|
| 해당 줄 | `from shop.greet import greet  # noqa: F401` |
| 파일 전체 | 파일 맨 위에 `# ruff: noqa: E501` |
| 여러 파일 | `pyproject.toml`의 `per-file-ignores` |

`pyproject.toml` 예시:

```toml
[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]
"shop/messages.py" = ["E501"]
```

`# noqa`만 적으면 그 줄의 다른 위반까지 모두 가릴 수 있음. `# noqa: F401`처럼 **규칙 코드를 명시**하고 이유를 주석으로 남기는 편이 안전함. 재내보내기(re-export)가 목적이면 `from shop.greet import greet as greet`도 사용 가능.

## 3. 기존 GitHub Actions에 Ruff 검사 추가

### 3-1. `ci.yml`에 단계 두 개 추가

기초편의 `.github/workflows/ci.yml`에서 `jobs → unit-tests → steps`의 **기존 pytest 테스트 단계 바로 뒤**에 아래 코드를 추가. `- name: 테스트`와 같은 깊이로 들여쓰기.

```yaml
      - name: 문법·스타일·import 순서 검사
        if: always()
        run: uv run ruff check .

      - name: 포맷 검사
        if: always()
        run: uv run ruff format --check .
```

**작업의 내부 순서**

```text
unit-tests (ubuntu-latest / windows-latest)
├─ checkout: 저장소 받기
├─ setup-uv: uv 준비
├─ uv sync --locked: 라이브러리와 Ruff 설치
├─ pytest: 단위 테스트
├─ ruff check .: 린트 검사
└─ ruff format --check .: 포맷 검사
```

- `if: always()`: 앞의 pytest 단계가 실패해도 Ruff 단계의 실행을 시도하여 문제를 함께 확인.
- `uv sync --locked`: `pyproject.toml`·`uv.lock`에 맞게 Ruff까지 설치되어 있어야 함.
- CI에서 `--fix`나 `ruff format .`은 쓰지 않음. 러너에서 수정된 파일은 저장소에 자동 반영되지 않기 때문.
- 같은 권한·설치 환경을 쓰므로 Ruff를 새 작업으로 분리하지 않고 기존 작업에 포함.

### 3-2. PR에서 실패 및 통과 확인

**① 규칙 위반을 담은 PR 생성**

```bash
git switch main
git pull
git switch -c try/ruff-check
# 앞의 잘못된 try_ruff.py 예제를 저장
git add try_ruff.py
git commit -m "Ruff 검사 확인용 파일 추가"
git push -u origin try/ruff-check
```

GitHub에서 `main`을 대상으로 PR 생성 → **Checks**에서 아래 결과 확인.

```text
unit-tests (ubuntu-latest)    FAILED
unit-tests (windows-latest)   FAILED
 └─ 문법·스타일·import 순서 검사
     ├─ I001
     ├─ F401
     └─ E711
gate-rules                   SKIPPED (needs: unit-tests)
```

기초편에서 두 `unit-tests` 작업을 필수 검사로 등록해 두었다면, 실패한 PR은 병합이 차단됨. (필수 검사 설정을 하지 않았다면 실패 표시만으로 병합이 반드시 차단되지는 않음.)

**② 로컬에서 수정 후 다시 push**

```bash
uv run ruff check --fix try_ruff.py
# try_ruff.py의 if drop == None: 을 if drop is None: 으로 직접 수정
uv run ruff format try_ruff.py
git commit -am "Ruff 규칙에 맞게 고침"
git push
```

같은 PR에 검사 실행이 새로 생성됨. 단위 테스트와 Ruff 검사 모두 통과하는지 확인. 이 PR은 실습용이므로 **병합하지 않고 닫기**.

## 4. Pull Request에 AI 코드 리뷰 자동화

### 4-1. 전체 동작과 준비 파일

```text
Pull Request 열기/갱신
        ↓
변경분 가져오기: git diff origin/main...HEAD
        ↓
ChatOpenAI로 변경 코드 리뷰
        ↓
review.md 저장
        ↓
gh pr comment로 PR 댓글 등록
```

추가할 파일·설정:

```text
pytest_ci_practice/
├─ .github/workflows/ci.yml   ← ai-review 작업 추가
├─ tools/ai_reviewer.py        ← diff 추출 및 LLM 리뷰 스크립트
├─ .env                        ← 로컬 키(커밋 금지)
└─ .gitignore                  ← .env, review.md 제외 여부 확인

GitHub Settings → Secrets and variables → Actions
└─ OPENAI_API_KEY              ← CI용 비밀 변수
```

- `langchain-core`, `langchain-openai`, `python-dotenv` 필요. 원본 연습 프로젝트에는 기본 의존성으로 포함됨.
- PR마다 LLM을 호출하므로 API 비용 발생. 변경 코드가 없으면 API 호출을 생략함.
- AI 리뷰는 판정이 아닌 **참고 댓글**. Required status checks에는 넣지 않음.

### 4-2. AI 리뷰 스크립트 작성

`tools/ai_reviewer.py`를 생성.

```python
"""main과 비교한 변경 코드를 AI가 리뷰하고 review.md에 저장."""

import subprocess
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

# 로컬에서는 .env 사용, CI에서는 이미 전달된 환경변수 사용
load_dotenv(find_dotenv(usecwd=True))

diff = subprocess.run(
    ["git", "diff", "origin/main...HEAD"],
    capture_output=True,
    text=True,
    check=True,
).stdout

if diff.strip() == "":
    review = "main 과 비교해 바뀐 코드가 없어 리뷰하지 않았습니다."
else:
    diff = diff[:10000]  # 호출 비용을 줄이기 위해 변경분 앞부분만 사용

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "당신은 시니어 파이썬 개발자입니다. 코드 변경(diff)을 읽고 잠재적인 버그와 스타일 문제를 짚고, "
                "잘한 점도 적어 주세요. 한국어 마크다운으로 간결하게 씁니다.",
            ),
            ("human", "다음 코드 변경을 리뷰해 주세요.\n\n```diff\n{diff}\n```"),
        ]
    )
    llm = ChatOpenAI(model="gpt-4.1")
    review = (prompt | llm).invoke({"diff": diff}).content

Path("review.md").write_text(review, encoding="utf-8")
print(review)
```

**핵심 코드**

- `git diff origin/main...HEAD`: `main`과 갈라진 지점부터 현재 브랜치의 커밋 변경분 수집.
- `diff[:10000]`: 변경 코드 앞부분 최대 10,000자만 모델에 전달.
- `ChatPromptTemplate` + `ChatOpenAI`: 리뷰 요청.
- `Path("review.md").write_text(...)`: 댓글로 올릴 리뷰 내용 저장.
- 변경이 없으면 별도 API 호출 없이 안내문만 파일에 기록.

### 4-3. 로컬에서 직접 테스트

프로젝트 최상위에 `.env` 파일 작성 (`.gitignore`에 `.env`가 포함돼 있어야 함).

```dotenv
OPENAI_API_KEY=본인_API_키
```

변경 내용을 **커밋한 뒤** 실행. `git diff origin/main...HEAD`는 작업 폴더의 커밋하지 않은 수정을 대상으로 삼지 않음.

```bash
uv sync
git switch main
git pull
git switch -c try/ai-review
# 추적 중인 파일 하나 수정 후 저장
git commit -am "AI 리뷰 확인용 변경"
git fetch origin main
uv run python tools/ai_reviewer.py
```

기대 결과:

```text
터미널에 AI 리뷰 출력
        ↓
프로젝트 최상위에 review.md 생성
```

- `.env`가 없거나 이름이 다르면 `Missing credentials` 발생 가능.
- 잘못된 API 키라면 `AuthenticationError`(401) 발생 가능.
- 다른 폴더의 가상환경 활성화로 `VIRTUAL_ENV ... will be ignored`가 나오면 uv가 현재 프로젝트 환경을 선택하는지 확인.
- 확인용 브랜치는 테스트 후 `git switch main`으로 돌아가 정리 가능.

### 4-4. GitHub Secret 등록 및 YAML 추가

**① Secret 등록**

```text
저장소 Settings
└─ Secrets and variables
   └─ Actions
      └─ New repository secret
         ├─ Name: OPENAI_API_KEY
         └─ Secret: 실제 API 키 입력
```

**② `.github/workflows/ci.yml`의 `jobs:` 아래에 별도 `ai-review` 작업 추가**

`gate-rules` 작업이 끝난 다음 위치에 넣되, `ai-review:`는 `unit-tests:`·`gate-rules:`와 동일한 들여쓰기 깊이.

```yaml
  ai-review:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
      pull-requests: write
    steps:
      - name: 저장소 받기
        uses: actions/checkout@v7
        with:
          fetch-depth: 0

      - name: uv 설치
        uses: astral-sh/setup-uv@v10.2.0
        with:
          python-version: "3.12"

      - name: 라이브러리 설치
        run: uv sync --locked

      - name: AI 리뷰 생성
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: uv run python tools/ai_reviewer.py

      - name: pull request 댓글로 올리기
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh pr comment ${{ github.event.pull_request.number }} --body-file review.md
```

| 설정 | 의미 |
|---|---|
| `if: github.event_name == 'pull_request'` | PR에서만 AI 리뷰 실행. push·수동 실행은 건너뜀 |
| `permissions.pull-requests: write` | PR 댓글 작성 권한 부여 |
| `fetch-depth: 0` | 변경분 비교를 위해 전체 커밋 이력 가져오기 |
| `OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}` | 등록한 OpenAI 키를 스크립트에 환경변수로 전달 |
| `GH_TOKEN: ${{ github.token }}` | GitHub가 제공하는 토큰으로 `gh` 명령 인증. 별도 발급 불필요 |
| `--body-file review.md` | 리뷰 파일 내용을 PR 댓글 본문으로 사용 |

**③ PR을 열어 확인**

```text
GitHub PR → Checks → ai-review 실행 로그
                          ↓
          AI 리뷰 생성 → PR 댓글로 올리기
                          ↓
                  Conversation 탭에서 확인
```

- `ai-review`는 별도 작업이라 `unit-tests` 실패와 관계없이 실행될 수 있음.
- 다른 사람의 **fork에서 보낸 PR**에는 저장소 Secrets가 전달되지 않으므로 이 예시에서는 AI 리뷰 생성 단계가 실패할 수 있음.
- AI 리뷰 작업은 필수 검사에 넣지 않아, 리뷰 호출 실패만으로 병합을 막지 않도록 구성.

> **실무 보안 참고(교안 내용에 추가한 주의사항):** 비밀 변수가 포함된 작업에서 PR의 스크립트와 의존성을 실행하면, 신뢰할 수 없는 기여자의 변경 코드가 비밀 변수에 접근할 위험이 있음. 이 예시는 신뢰하는 저장소·기여자 환경을 전제로 실습하고, 공개 저장소에 적용할 때는 실행 조건과 비밀 변수 전달 방식을 별도 점검할 것.

## 5. 실무 점검표

| 현상 | 확인 사항 |
|---|---|
| 로컬 린트 실패 | `uv run ruff check --output-format concise .`로 규칙 코드·위치 확인 |
| `ruff check`는 통과하지만 포맷 실패 | `uv run ruff format --diff .`로 차이 확인 → `ruff format .` 적용 |
| `--fix`로도 일부 규칙이 남음 | `E711` 등 unsafe fix인지 확인하고 직접 수정 |
| CI의 Ruff 단계에서 실패 | `pyproject.toml` 규칙, 미수정 파일, `uv sync --locked` 설치 여부 확인 |
| PR에서 필수 검사 때문에 병합 불가 | `unit-tests (ubuntu-latest)`·`unit-tests (windows-latest)` 로그 확인 |
| AI 리뷰 스크립트가 리뷰할 변경이 없다고 함 | `main` 대비 변경을 **커밋**했는지, `git fetch origin main` 했는지 확인 |
| `Missing credentials` 또는 401 | 로컬 `.env`/GitHub Secret의 이름과 키 값 확인 |
| PR에 리뷰 댓글이 달리지 않음 | `ai-review` 로그, `pull-requests: write`, `GH_TOKEN`, `gh pr comment` 확인 |
| fork PR에서 AI 리뷰 실패 | 외부 PR에는 `OPENAI_API_KEY` Secret이 전달되지 않는지 확인 |

### 핵심 작업 순서

```text
[로컬 코드 수정]
1. uv run ruff check .
2. uv run ruff check --fix .
3. 남은 문제 직접 수정
4. uv run ruff format .
5. uv run ruff check .
6. uv run ruff format --check .
7. git add → commit → push → PR

[GitHub Actions]
8. unit-tests에서 pytest·Ruff 검사 결과 확인
9. ai-review에서 review.md 생성 및 PR 댓글 확인
10. 검사 실패는 코드 수정 후 재-push, AI 의견은 사람이 검토
```

> 참고: 이 문서는 **원본 심화 교안에서 사용하는 모델(`gpt-4.1`)과 액션 버전**을 유지함. 새로운 프로젝트에 복사할 때는 해당 모델의 사용 가능 여부, API 비용, 액션 버전과 기존 프로젝트 의존성을 별도로 확인해야 함.