# MCP 도구 기반 Plan-and-Execute 에이전트

> 실제 코딩 흐름 기준 핵심 압축 정리  
> 주제: **MCP Tool → Agent → Middleware → TodoListMiddleware → Plan-and-Execute**

---

# 0. 전체 개발 흐름

```text
1. 환경·경로 준비
   ↓
2. MCP 서버 설정
   ↓
3. 서버에서 Tool 불러오기
   ↓
4. Agent에 허용할 Tool만 필터링
   ↓
5. 기본 Agent 구성
   ↓
6. 복합 요청 실행 → 계획 없는 Agent의 한계 확인
   ↓
7. Middleware / Hook 구조 이해
   ↓
8. TodoListMiddleware 추가
   ↓
9. Plan-and-Execute Agent 구성
   ↓
10. 복합 요청 실행
   ↓
11. Tool 궤적 + todos 진행 상태 검증
```

핵심:

```text
MCP Tool = Agent가 실제로 수행할 수 있는 행동
Middleware = Agent 실행 루프에 기능을 추가하는 장치
TodoListMiddleware = 계획을 만들고 진행 상태를 추적
Plan-and-Execute = 계획 → 단계별 실행
```

---

# 1. 환경 준비

## 핵심 import

```python
from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    TodoListMiddleware,
)
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
```

프로젝트 보조 함수:

```python
from utils import (
    child_env,
    chinook_db_path,
    load_api_key,
    print_trajectory,
    quiet_stdio_logs,
    tool_names,
)
```

준비 목적:

```text
API Key 확인
DB 경로 준비
MCP 자식 프로세스 환경 준비
output 폴더 준비
```

---

# 2. MCP 서버 설정

이번 실습은 3개 MCP 서버 사용.

| 서버 | 역할 |
|---|---|
| SQLite | DB 조회·집계 |
| Code Runner | 계산·그래프 생성 |
| Filesystem | Markdown·텍스트 저장 |

```python
SQLITE = {...}
CODE_RUNNER = {...}
FILESYSTEM = {...}
```

## 출력 경로 통일

```python
OUTPUT_DIR = DAY_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
```

Code Runner와 Filesystem의 기준 폴더를 같은 `output`으로 맞춤.

```text
code_run-code → output에서 코드 실행
files_write_file → output에 파일 저장
```

따라서 Agent에는 긴 절대경로 대신 **파일명만 전달**하면 됨.

---

# 3. MCP Tool 불러오기 + 권한 제한

## 서버 연결

```python
client = MultiServerMCPClient(
    {
        "db": SQLITE,
        "code": CODE_RUNNER,
        "files": FILESYSTEM,
    },
    tool_name_prefix=True,
)

mcp_tools = await client.get_tools()
```

`tool_name_prefix=True`

```text
db_...
code_...
files_...
```

서버별 접두사를 붙여 Tool 이름 충돌 방지.

## 필요한 Tool만 허용

```python
ALLOWED = {
    "db_read_query",
    "db_list_tables",
    "db_describe_table",
    "code_run-code",
    "files_write_file",
}

TOOLS = [
    t for t in mcp_tools
    if t.name in ALLOWED
]
```

핵심:

```text
Agent는 전달받은 Tool만 사용할 수 있음.
Tool 필터링 = 기능 제한 + 권한 설계
```

쓰기·수정 도구를 전부 넘기지 않고 필요한 기능만 허용.

---

# 4. Agent 공통 규칙 작성

```python
SYSTEM_BASE = (
    "너는 데이터 분석 비서다. ..."
)
```

주요 규칙:

```text
DB 조회·집계
→ db_read_query

계산·그래프
→ code_run-code

표·열 이름이 불확실
→ db_list_tables / db_describe_table

텍스트 저장
→ files_write_file

이미지 저장
→ code_run-code + matplotlib.savefig()
```

추가 안전 규칙:

- 숫자를 임의로 계산하거나 생성하지 않음
- 코드 결과는 `print()`로 명시적 출력
- 같은 코드를 반복 호출하지 않음
- `code_run-code`는 한 번에 하나씩 호출
- 그래프 저장 후 파일 크기 확인
- 저장 경로 대신 파일명만 사용

---

# 5. 기본 Agent 구성

## 모델

```python
model = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    timeout=60,
)
```

## 모델 호출 상한

```python
LIMIT = ModelCallLimitMiddleware(
    run_limit=20,
    exit_behavior="end",
)
```

반복 호출에 빠졌을 때 무한 실행 방지.

## 계획 기능 없는 Agent

```python
plain_agent = create_agent(
    model,
    TOOLS,
    system_prompt=SYSTEM_BASE,
    middleware=[LIMIT],
)
```

구조:

```text
질문
→ 모델 판단
→ Tool 호출
→ Tool 결과
→ 다시 모델 판단
→ 최종 답변
```

기본적으로 ReAct형 실행은 가능하지만 **전체 작업 계획은 따로 기록하지 않음**.

---

# 6. 복합 요청으로 한계 확인

예시 요청:

```text
연도별 매출 집계
+ 국가별 매출 TOP 5
+ 전년 대비 증감률 계산
+ 그래프 저장
```

실행:

```python
result_plain = await plain_agent.ainvoke({
    "messages": complex_q
})

print_trajectory(result_plain)
print(tool_names(result_plain))
```

확인할 것:

```text
어떤 Tool을 호출했는가?
필요한 단계를 모두 처리했는가?
그래프 저장까지 완료했는가?
```

계획 Middleware가 없으면:

```python
"todos" in result_plain
```

과 같은 명시적 작업 목록이 없음.

즉:

```text
ReAct
= 현재 상황을 보고 다음 행동을 반복 결정

하지만
= 전체 작업 목록을 먼저 만들어 추적하지는 않음
```

---

# 7. Middleware 핵심

`create_agent()`의 실행 구조:

```text
모델 호출
→ Tool 실행
→ 다시 모델 호출
→ ...
```

**Middleware**는 이 루프를 직접 수정하지 않고 정해진 위치에 기능을 끼워 넣는 장치.

```python
create_agent(
    ...,
    middleware=[...],
)
```

---

# 8. Middleware의 6개 Hook

| Hook | 시점 | 대표 용도 |
|---|---|---|
| `before_agent` | Agent 시작 전 1회 | 초기 상태·사용자 정보 준비 |
| `before_model` | 모델 호출 전 매번 | 요약·호출 제한 검사 |
| `wrap_model_call` | 모델 호출 자체를 감쌈 | 재시도·모델 교체·요청 수정 |
| `after_model` | 모델 응답 후 매번 | 응답 검사·승인·후처리 |
| `wrap_tool_call` | Tool 호출 자체를 감쌈 | 재시도·차단·결과 수정 |
| `after_agent` | Agent 종료 후 1회 | 로그·통계·최종 저장 |

## 핵심 구분

### `before_` / `after_`

```text
현재 state를 읽거나 수정
```

호출 자체를 직접 제어하지는 못함.

### `wrap_`

```text
handler를 직접 호출
```

따라서:

```text
재시도
차단
대체 호출
요청·응답 수정
```

같은 처리가 가능.

암기:

```text
상태를 다룸 → before / after
호출을 다룸 → wrap
```

---

# 9. Middleware 여러 개의 실행 순서

```python
middleware=[A(), B()]
```

A가 바깥쪽, B가 안쪽.

```text
before → A → B
after  → B → A
wrap   → A가 B를 감쌈
```

개념적으로:

```text
A 시작
 └─ B 시작
     └─ 실제 호출
 └─ B 종료
A 종료
```

---

# 10. 주요 Middleware 선택 기준

| 문제 | Middleware |
|---|---|
| 복합 작업 계획 필요 | `TodoListMiddleware` |
| 긴 대화 정리 | `SummarizationMiddleware` |
| 개인정보 제어 | `PIIMiddleware` |
| 위험한 Tool 승인 | `HumanInTheLoopMiddleware` |
| 모델 호출 폭주 | `ModelCallLimitMiddleware` |
| Tool 호출 폭주 | `ToolCallLimitMiddleware` |
| 일시적 실패 재시도 | `ModelRetryMiddleware`, `ToolRetryMiddleware` |
| 모델 장애 시 대체 | `ModelFallbackMiddleware` |

판단 기준:

```text
판단 문제 → 계획
긴 컨텍스트 → 대화 관리
위험 작업 → 승인·안전
무한 반복 → 호출 제한
일시적 실패 → Retry
```

---

# 11. TodoListMiddleware로 계획 기능 추가

## Plan-and-Execute

```text
Plan
→ 전체 작업을 먼저 목록으로 작성

Execute
→ 목록을 따라 단계별 실행
```

ReAct와 비교:

| 방식 | 실행 특징 |
|---|---|
| ReAct | 상황을 보고 다음 행동을 계속 결정 |
| Plan-and-Execute | 전체 할 일을 먼저 만들고 진행 상태 추적 |

`TodoListMiddleware`는:

```text
1. write_todos Tool 추가
2. state에 todos 값 추가
3. 모델에게 계획 작성·갱신 기능 제공
```

---

# 12. 계획 Agent 구성

시스템 규칙에 계획 지시 추가.

```python
SYSTEM_PLAN = SYSTEM_BASE + (
    " 여러 단계가 필요한 복합 요청은 "
    "먼저 계획을 세우고 단계별로 처리하라."
)
```

Agent:

```python
analyst = create_agent(
    model,
    TOOLS,
    middleware=[
        TodoListMiddleware(),
        LIMIT,
    ],
    system_prompt=SYSTEM_PLAN,
)
```

핵심 변화:

```text
Tool 자체는 동일
+
TodoListMiddleware 추가
+
복합 요청은 먼저 계획하도록 지시
```

---

# 13. 계획 Agent 실행

예시 요청 구조:

```text
1. 아티스트별 앨범 수 조회
2. 앨범별 곡 수 조회
3. TOP 3 아티스트 비중 계산
4. TOP 10 그래프 생성·저장
```

실행:

```python
result = await analyst.ainvoke({
    "messages": plan_q
})
```

궤적 확인:

```python
print_trajectory(result)
```

계획 확인:

```python
for item in result.get("todos", []):
    print(
        f"- [{item['status']}] "
        f"{item['content']}"
    )
```

실행 흐름:

```text
복합 질문
→ write_todos로 계획 작성
→ 1단계 Tool 실행
→ todos 상태 갱신
→ 2단계 Tool 실행
→ ...
→ 전체 완료
→ 최종 답변
```

---

# 14. 실제 디버깅·검증 포인트

Agent가 답을 냈다는 사실만 확인하면 부족함.

확인 대상:

```text
1. 어떤 Tool을 골랐는가
2. Tool 호출 순서가 맞는가
3. 필요한 단계가 빠지지 않았는가
4. 그래프·파일이 실제 저장됐는가
5. todos가 생성됐는가
6. todos 상태가 단계별로 갱신됐는가
```

대표 확인 코드:

```python
print_trajectory(result)
tool_names(result)
result.get("todos", [])
```

---

# 15. 핵심 코드만 압축

```python
# 1. MCP Tool 가져오기
client = MultiServerMCPClient(
    {
        "db": SQLITE,
        "code": CODE_RUNNER,
        "files": FILESYSTEM,
    },
    tool_name_prefix=True,
)

mcp_tools = await client.get_tools()


# 2. 허용 Tool 제한
TOOLS = [
    t for t in mcp_tools
    if t.name in ALLOWED
]


# 3. 모델 준비
model = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
)


# 4. 호출 상한
LIMIT = ModelCallLimitMiddleware(
    run_limit=20,
    exit_behavior="end",
)


# 5. 계획 Agent
analyst = create_agent(
    model,
    TOOLS,
    system_prompt=SYSTEM_PLAN,
    middleware=[
        TodoListMiddleware(),
        LIMIT,
    ],
)


# 6. 실행
result = await analyst.ainvoke({
    "messages": plan_q
})


# 7. 실행 궤적 확인
print_trajectory(result)


# 8. 계획 상태 확인
for item in result.get("todos", []):
    print(item["status"], item["content"])
```

---

# 16. 최종 정리

| 개념 | 핵심 |
|---|---|
| MCP | 외부 서버의 Tool을 Agent에 연결 |
| Tool 제한 | Agent 권한 범위를 결정 |
| Agent | 모델이 상황에 따라 Tool을 선택·실행 |
| Middleware | Agent 실행 루프에 기능 추가 |
| Hook | Middleware가 개입할 수 있는 정해진 위치 |
| `before/after` | state 중심 처리 |
| `wrap` | 실제 호출 제어 |
| `ModelCallLimitMiddleware` | 무한 반복·과도한 모델 호출 제한 |
| `TodoListMiddleware` | 계획 생성 + 진행 상태 추적 |
| `write_todos` | Agent가 계획을 작성·갱신하는 Tool |
| `todos` | 최종 state에 남는 작업 목록 |
| ReAct | 현재 상황을 보고 다음 행동 결정 |
| Plan-and-Execute | 전체 계획 작성 후 단계별 실행 |

## 한 줄 구조

```text
MCP Tool 준비
→ 필요한 Tool만 허용
→ Agent 생성
→ Middleware로 실행 방식 확장
→ TodoList로 계획 생성
→ 단계별 Tool 실행
→ trajectory + todos로 검증
```

## 가장 중요한 기준

```text
Tool = 무엇을 할 수 있는가
Middleware = 어떻게 실행할 것인가
TodoList = 무엇을 어떤 순서로 할 것인가
```

---

> 참고: 원본 노트북에는 실행 결과가 저장되어 있지 않아, 위 정리는 코드와 설명 셀의 실행 구조를 기준으로 재배치·압축함.
