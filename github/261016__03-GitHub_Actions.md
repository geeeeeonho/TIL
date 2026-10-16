# GitHub Actions 사용방법

> 출처: `부록_02_GitHub_Actions_기초.ipynb`  
> 핵심: **워크플로 YAML 작성 → GitHub에 push → 자동 실행 → 로그 확인 → 필요시 PR 병합 차단**  
> 예시는 원본 교안의 `pytest_ci_practice/` 프로젝트와 `uv`·`pytest` 기준.

## 1. 사용 구조와 준비

GitHub Actions는 GitHub 저장소에 설정한 이벤트가 발생하면, **러너(가상 컴퓨터)**에서 명령을 실행하는 자동화 기능.

```text
코드 수정 → git push / Pull Request 생성
                ↓
        이벤트(on) 감지
                ↓
 .github/workflows/tests.yml 실행
                ↓
         작업(job): pytest
                ↓
   단계(steps)를 위에서부터 실행
   ├─ 저장소 코드 내려받기 (uses)
   ├─ uv 설치             (uses)
   ├─ 라이브러리 설치     (run)
   └─ pytest 실행         (run)
                ↓
    Actions 탭에 성공/실패 및 로그 기록
```

| 구분 | 작성 위치·역할 |
|---|---|
| `on` | 언제 실행할지 설정. 예: `push`, `pull_request`, `workflow_dispatch` |
| `jobs` | 실행할 작업 목록. 작업마다 새 러너 사용 |
| `runs-on` | 실행할 운영체제. 예: `ubuntu-latest` |
| `steps` | 한 작업에서 순서대로 실행할 단계 |
| `uses` | 이미 만들어진 액션을 사용. 예: `actions/checkout` |
| `run` | 터미널 명령 실행. 예: `uv run pytest -v tests` |

**파일 위치가 중요함.** 워크플로는 저장소의 `.github/workflows/` 안에 있는 `.yml` 또는 `.yaml` 파일로 작성.

```text
pytest_ci_practice/             ← GitHub 저장소 최상위 폴더
├─ .github/
│  └─ workflows/
│     └─ tests.yml             ← GitHub Actions 설정
├─ tests/                      ← pytest 테스트 파일
├─ pyproject.toml
└─ uv.lock
```

> **준비 조건:** GitHub 저장소, Git, 실행할 Python 프로젝트 및 테스트 파일 필요. 원본 노트북에서 사용하는 `pytest_ci_practice/` 폴더는 별도의 연습 프로젝트이므로, 해당 파일이 없으면 자신의 프로젝트 구조와 테스트 명령에 맞게 수정해야 함.

## 2. 기본 워크플로 작성부터 실행까지

### 2-1. `tests.yml` 작성

`.github/workflows/tests.yml` 파일을 만든 뒤 다음 내용 작성.

```yaml
name: tests

on:
  push:
    branches: [main]   # main 브랜치에 push할 때
  pull_request:        # Pull Request 생성·갱신 시
  workflow_dispatch:   # GitHub 화면에서 직접 실행

jobs:
  pytest:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: 저장소 받기
        uses: actions/checkout@v7

      - name: uv 설치
        uses: astral-sh/setup-uv@v10.2.0
        with:
          python-version: "3.12"

      - name: 라이브러리 설치
        run: uv sync --locked

      - name: 테스트
        run: uv run pytest -v tests
```

**핵심 해석**

- `push.branches: [main]`: main에 push했을 때만 해당 push 이벤트로 실행.
- `pull_request`: PR에서 수정 사항을 검사.
- `workflow_dispatch`: Actions 탭의 **Run workflow** 버튼 사용 가능.
- `actions/checkout`: 빈 러너에 저장소 코드 내려받기.
- `setup-uv`: `uv` 설치. `with`는 액션에 전달하는 옵션.
- `uv sync --locked`: 잠금 파일(`uv.lock`)에 맞게 라이브러리 설치.
- `uv run pytest -v tests`: `tests/` 폴더의 pytest 테스트 실행. 실패 시 작업 실패로 기록.

> 원본 교안의 첫 번째 예제에는 Secret 값을 출력하는 확인용 단계가 포함됨. 실제 프로젝트에서는 비밀 정보 출력이 위험하므로 **기본 템플릿에서는 제외**함.

### 2-2. GitHub 저장소에 올리기

GitHub에서 **빈 저장소**를 생성한 뒤, 터미널에서 프로젝트 최상위 폴더로 이동. 아래 `<계정>`과 `<저장소>`는 실제 값으로 변경.

```bash
cd pytest_ci_practice

git init -b main
git add .
git commit -m "Add pytest workflow"
git remote add origin https://github.com/<계정>/<저장소>.git
git push -u origin main
```

`tests.yml`이 올라가면 `push` 이벤트에 의해 첫 실행이 자동 시작됨. 이미 Git 저장소가 연결돼 있다면 `git init`·`git remote add`는 반복하지 않고 `add → commit → push`만 사용.

### 2-3. 실행 결과 확인

GitHub 저장소에서 다음 순서로 확인.

```text
GitHub 저장소
└─ Actions 탭
   └─ tests 워크플로의 실행 목록
      └─ 실행 항목 선택
         └─ pytest 작업 선택
            └─ 테스트 단계 펼치기
               ├─ pytest 로그
               ├─ PASSED / FAILED
               └─ 실패 원인 출력
```

- **초록 체크:** 실행 성공.
- **빨간 X:** 실행 실패.
- `FAILED` 및 `short test summary info`: 실패한 테스트 확인.
- 로그의 `E` 줄: 기대값과 실제값 등의 오류 내용 확인.

접속: `https://github.com/<계정>/<저장소>/actions`

## 3. 자주 사용하는 실행 방식

### 3-1. 화면에서 수동 실행

워크플로에 `workflow_dispatch:`가 있으면 코드를 다시 push하지 않고 실행할 수 있음.

**Actions → 왼쪽 `tests` 선택 → Run workflow → 브랜치 선택 → Run workflow**

```yaml
on:
  workflow_dispatch:
```

### 3-2. Pull Request에서 자동 테스트

```yaml
on:
  pull_request:
```

1. 새 브랜치에서 코드 수정.
2. 브랜치를 GitHub에 push.
3. **Compare & pull request**로 PR 생성.
4. PR 하단 **Checks / 검사 영역**에서 통과 여부 확인.
5. 실패 시 **Details**를 눌러 테스트 로그 확인.

```bash
git switch -c test/change
git add .
git commit -m "Change code"
git push -u origin test/change
```

> **주의:** 테스트 실패 자체가 PR 병합을 자동으로 차단하지는 않음. 병합 제한은 5절의 Rulesets에서 별도로 설정.

### 3-3. 정해진 시간에 자동 실행

```yaml
on:
  schedule:
    - cron: "0 0 * * 1"  # 매주 월요일 00:00 UTC = 한국 오전 09:00
```

- `schedule`: 정해진 일정에 실행.
- `cron`은 **UTC 기준**이므로 한국 시간과 구분.
- 비용이 큰 전체 평가 등을 정기 실행할 때 활용.

## 4. API 키와 비밀 변수(Secrets) 사용

API 키는 YAML에 직접 적지 않고 GitHub Secrets에 저장.

**등록 경로**

```text
저장소 Settings
  → Secrets and variables
  → Actions
  → New repository secret
  → Name / Secret 값 입력
  → Add secret
```

예: `OPENAI_API_KEY`라는 이름으로 등록하고, 필요한 단계에서만 환경변수로 전달.

```yaml
- name: LLM 평가
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  run: uv run python run_eval.py
```

- `${{ secrets.OPENAI_API_KEY }}`: 저장소에 등록한 Secret 참조.
- `env`: 해당 단계에서 사용할 환경변수 지정.
- **Secret 값은 로그에 출력하지 않음.** GitHub가 일부 출력을 `***`로 가려도 변형된 값은 노출될 수 있음.
- 원본 교안 기준, 외부 저장소에서 fork한 PR에는 저장소 Secrets가 전달되지 않음.

## 5. 테스트 실패 시 PR 병합 차단

GitHub의 **Rulesets**에서 필요한 테스트를 필수 검사로 지정.

1. **Settings → Rules → Rulesets → New ruleset → New branch ruleset**.
2. 규칙 이름 설정, **Enforcement status: Active**.
3. **Target branches → Add target → Include default branch**.
4. **Require status checks to pass** 활성화.
5. **Add checks**에서 `pytest` 검색 후 GitHub Actions 검사 선택.
6. **Create**로 저장.

이후 `pytest` 검사가 실패하면 규칙이 적용되는 저장소에서는 main 병합이 차단됨.

**설정 시 주의**

- 필수 검사 이름은 워크플로 이름(`tests`)이 아닌 **작업 이름(`pytest`)** 기준.
- 검색 결과가 없으면 워크플로를 먼저 실행한 뒤 다시 검색.
- 원본 교안 기준, GitHub Free의 비공개 저장소에서는 Rulesets가 적용되지 않을 수 있음.
- 필수 검사로 지정한 워크플로가 `paths`·`paths-ignore` 조건으로 **실행되지 않으면 검사 대기 상태**가 되어 병합이 막힐 수 있음.

## 6. 실전 확장: 여러 운영체제 테스트 + 결과 저장

테스트 종류가 늘어나면 하나의 작업 대신 **단위 테스트 → 후속 검사**로 나누는 방식 사용.

```text
main push / PR / 수동 실행
              ↓
     unit-tests (matrix)
       ├─ Ubuntu ─┐
       └─ Windows ┤  두 환경 모두 성공
                  ↓
             gate-rules
                  ↓
        reports/ 산출물 보관
```

### 6-1. 완성된 `ci.yml`

원본 교안의 `design/ci.yml`에 있는 TODO 5개를 채운 형태. `tests/test_normalize.py`, `tests/test_check_citation.py`, `tests/test_gate_rules.py`가 있다는 전제.

`.github/workflows/ci.yml`

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  unit-tests:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    timeout-minutes: 10
    steps:
      - name: 저장소 받기
        uses: actions/checkout@v7
      - name: uv 설치
        uses: astral-sh/setup-uv@v10.2.0
        with:
          python-version: "3.12"
          enable-cache: true
      - name: 라이브러리 설치
        run: uv sync --locked
      - name: 단위 테스트
        run: uv run pytest -v tests/test_normalize.py tests/test_check_citation.py

  gate-rules:
    needs: unit-tests
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: 저장소 받기
        uses: actions/checkout@v7
      - name: uv 설치
        uses: astral-sh/setup-uv@v10.2.0
        with:
          python-version: "3.12"
          enable-cache: true
      - name: 라이브러리 설치
        run: uv sync --locked
      - name: 게이트 규칙 테스트
        run: uv run pytest -v tests/test_gate_rules.py --junitxml=reports/junit.xml
      - name: 결과 저장
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: gate-reports
          path: reports/
          retention-days: 7
```

**실전에서 알아둘 설정**

| 설정 | 사용 목적 |
|---|---|
| `matrix.os` | 같은 작업을 Ubuntu와 Windows에서 각각 실행 |
| `fail-fast: false` | 한 운영체제가 실패해도 다른 운영체제 테스트 계속 실행 |
| `needs: unit-tests` | 단위 테스트가 모두 성공한 후 `gate-rules` 실행 |
| `if: always()` | 테스트가 실패해도 결과 저장 단계 실행 |
| `upload-artifact` | `reports/` 파일을 Actions 실행 결과에 첨부 |
| `retention-days: 7` | 결과 파일을 7일 보관 |
| `concurrency` | 같은 그룹의 새 실행이 시작되면 이전 실행 취소 |
| `permissions: contents: read` | 저장소 내용을 읽을 권한만 부여 |
| `timeout-minutes` | 작업 실행 최대 시간 제한 |
| `enable-cache: true` | `uv` 캐시를 사용해 재설치 시간 줄이기 |

> 작업(`job`)은 서로 다른 러너에서 실행되므로 **각 작업에서 저장소 받기와 라이브러리 설치가 다시 필요**함. `needs`는 실행 순서만 설정하며 작업 사이의 파일을 자동 공유하지 않음.

### 6-2. 기존 워크플로 교체

원본 실습처럼 `tests.yml`에서 새 `ci.yml`로 바꾸는 경우:

```bash
git switch main
cp design/ci.yml .github/workflows/ci.yml
git rm .github/workflows/tests.yml
git add .
git commit -m "Split CI into unit tests and gate rules"
git push
```

위 명령은 **완성한 파일이 `design/ci.yml`에 있고, 기존 `tests.yml`이 존재할 때** 사용. 직접 `.github/workflows/ci.yml`을 작성했다면 복사 단계 생략.

**확인 위치:** Actions → `ci` 실행 항목 → Summary.

- `unit-tests (ubuntu-latest)`와 `unit-tests (windows-latest)`가 실행됐는지 확인.
- 둘 다 성공한 다음 `gate-rules`가 실행됐는지 확인.
- 하단 **Artifacts → gate-reports**에서 결과 파일 다운로드.

### 6-3. 필수 검사도 변경

`tests.yml`을 삭제했다면 기존 필수 검사 `pytest`를 제거하고 다음 **세 작업**을 모두 지정.

```text
Required status checks
├─ unit-tests (ubuntu-latest)
├─ unit-tests (windows-latest)
└─ gate-rules
```

`gate-rules`만 필수로 넣으면 `unit-tests` 실패로 인해 후속 작업이 **건너뛰어진 경우**까지 제대로 막지 못할 수 있음. 원본 교안은 세 작업을 모두 필수 검사로 등록하도록 설명함.

## 7. 자주 발생하는 문제와 확인 항목

| 현상 | 확인할 부분 |
|---|---|
| Actions가 실행되지 않음 | `.github/workflows/` 경로, YAML 들여쓰기, `on` 이벤트와 브랜치 조건 |
| 직접 실행 버튼이 없음 | `workflow_dispatch:` 설정 여부 |
| `pytest`가 실패함 | Actions의 `pytest` 작업 → 테스트 단계 → `FAILED` / `E` 줄 |
| 코드나 라이브러리를 못 찾음 | `checkout`, `setup-uv`, `uv sync` 단계 존재 여부 |
| Secrets를 읽지 못함 | Secret 이름, Settings 등록 여부, `env` 연결 여부, fork PR인지 확인 |
| 필수 검사를 검색할 수 없음 | 해당 작업을 실제로 한 번 실행했는지 확인 |
| CI를 교체한 뒤 PR이 계속 대기함 | 삭제한 워크플로의 검사(`pytest`)가 Rulesets에 남았는지 확인 |
| 테스트 실패 뒤 결과 파일이 안 남음 | `if: always()`와 `upload-artifact`, `path` 확인 |

### 핵심 사용 순서

1. **실행 명령 정리:** 로컬에서 실행되는 `uv run pytest ...`부터 확인.
2. **YAML 작성:** `.github/workflows/`에서 `on`, `jobs`, `steps` 설정.
3. **GitHub에 push:** 실행 이벤트를 발생시킴.
4. **로그 확인:** Actions → 실행 → 작업 → 단계.
5. **확장:** 필요할 때 `Secrets`, `matrix`, `needs`, `artifact`, `Rulesets` 추가.

> 참고: 액션의 `@버전`과 GitHub의 요금·저장소 규칙 적용 조건은 변경될 수 있음. YAML에 적은 액션 버전은 **원본 교안 기준**이며, 실제 적용 전 공식 액션 문서에서 지원 버전을 확인하는 것이 좋음.
