# Jev 평가와 Prompt Optimization — 개념·코드 문법 정리

> **학습 목표:** RAG 챗봇의 답변을 골든셋과 Jev로 평가하고, 평가 결과를 이용해 시스템 프롬프트를 자동 개선하는 구조 이해.
>
> **기준:** `부록_Jev_평가와_Prompt_Optimization.ipynb`. 원본의 흐름·설정값을 유지하되 반복 코드와 긴 표 출력을 축약함. 아래 코드는 **위에서 아래로 실행하는 연결 예시**이며, 중간에 쓰이는 변수는 앞선 코드에서 정의된 것으로 가정함. 원본 노트북에는 저장된 실행 출력이 없으므로, 결과 수치는 교안에 *서술된 시험 실행 관찰값*으로만 표시함.

## 1. 전체 구조와 핵심 개념

이 실습의 대상은 가상 헬스장 **핏플러스**의 RAG 안내 챗봇. 안내 문서에 없는 질문에 대해 다른 헬스장의 일반적인 정보를 지어내는 문제가 있음. 이를 평가 지표로 탐지하고 프롬프트를 수정하는 과정.

```text
[안내 문서: 9개 유형 · 54문장]
          │
          ▼
 [Chroma 검색기: top-k=4] ──→ [검색된 문장: retrieval_context]
          │                              │
          ▼                              │
[시스템 프롬프트 + 질문]                  │
          │                              │
          ▼                              │
    [RAG 답변 생성] ────────────┐        │
                                ▼        ▼
                         [Jev 판사: 품질 평가]
                                  │
                                  ▼
                       [GEPA: 프롬프트 수정]
                                  │
                                  ▼
                        [새 프롬프트로 재실행]
                                  │
                                  ▼
                      [별도 확인용 골든으로 비교]
```

| 개념 | 의미 | 실습에서의 역할 |
|---|---|---|
| **Golden(골든)** | 질문과 기대 정답 등을 포함한 평가용 사례 | 챗봇이 어떤 질문에 어떻게 답해야 하는지 정의 |
| **Golden Set(골든셋)** | 여러 골든의 모음 | 최적화·검증에 쓰는 평가 데이터 |
| **Synthesizer** | 문서를 이용해 골든을 자동 생성하는 도구 | 안내 문서로 답할 수 있는 질문과 정답 생성 |
| **JevEval** | 참·거짓 형태의 판정 문장을 평가하는 지표 | 답변의 누락과 환각 여부 판정 |
| **Noul** | Jev가 판단할 판정 문장 | `retrieval_context`에 근거한 세부 평가 기준 |
| **PromptOptimizer** | 평가 결과를 이용해 프롬프트를 개선하는 도구 | 시스템 프롬프트를 자동 재작성 |
| **GEPA** | 피드백 기반 수정 + 파레토 후보 유지 알고리즘 | 여러 프롬프트를 만들어 비교·선택 |

**중요한 구분:** `Golden`은 *정답이 무엇인지 정해 둔 데이터*이고, `LLMTestCase`는 *실제 답변을 넣어 판정하는 입력*임.

## 2. RAG 챗봇 구성과 핵심 문법

### 환경 및 검색기

원본은 생성 모델(`gpt-4.1`), 골든 검사·프롬프트 수정 모델(`gpt-5.6-luna`), Jev 판정 모델(`jev-1.13.0`, 환경 변수로 변경 가능)을 별도로 사용. `.env`에 `OPENAI_API_KEY`, `TYPESAFE_API_KEY`가 필요함.

```python
import os
from pathlib import Path
from dotenv import find_dotenv, load_dotenv

# DeepEval 임포트보다 먼저 환경 변수를 설정
os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
os.environ["DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS_OVERRIDE"] = "30"
os.environ["DEEPEVAL_RETRY_MAX_ATTEMPTS"] = "4"

load_dotenv(find_dotenv(usecwd=True))

material_dir = Path(".")
data_dir = material_dir / "data"
generation_model_name = "gpt-4.1"
judgment_model_name = "gpt-5.6-luna"
jev_model_name = os.getenv("TYPESAFE_MODEL", "jev-1.13.0")
```

- `os.environ["KEY"] = "값"`: 프로세스 환경 변수 설정.
- `os.getenv("KEY", "기본값")`: 환경 변수가 없으면 기본값 사용.
- `Path(...) / "하위폴더"`: 운영체제에 맞는 경로 연결.
- `load_dotenv(...)`: `.env` 파일의 값을 환경 변수로 로드.

원본은 **기존 Chroma 저장소를 다시 불러오는 방식**. 문서를 새로 임베딩하는 과정은 생략함.

```python
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

embedding_model = OpenAIEmbeddings(
    model="text-embedding-3-large",
    dimensions=768,
    check_embedding_ctx_length=False,
)

vector_store = Chroma(
    collection_name="fitplus_guide",
    embedding_function=embedding_model,
    persist_directory=str(data_dir / "부록" / "chroma_fitplus"),
)

retriever = vector_store.as_retriever(search_kwargs={"k": 4})

for doc in retriever.invoke("주말에도 문 열어요?"):
    print(doc.page_content)
```

- `embedding_function`: 질의를 임베딩할 모델. **저장소를 만들 때와 같은 모델·차원 설정**이 필요.
- `persist_directory`: 로컬 Chroma 저장 경로.
- `.as_retriever(search_kwargs={"k": 4})`: 가장 관련성 높은 문서 4개 반환하는 검색기 구성.
- `.invoke(question)`: 질문 1개로 검색기 실행. 반환값은 `Document` 목록이며, 텍스트는 `.page_content`에 있음.

### LCEL로 RAG 체인 연결

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

answer_llm = ChatOpenAI(model=generation_model_name, use_responses_api=True)

def format_docs(docs):
    return "\n".join(doc.page_content for doc in docs)

# 고쳐야 할 초기 시스템 프롬프트: 문서 밖의 내용도 추측하라고 지시함
initial_system_prompt = (
    "너는 헬스장 '핏플러스'의 회원 안내 챗봇이야. 친절하고 짧게 답해.\n"
    "회원이 실망하지 않게, 안내 문서에 없는 내용을 물으면 "
    "다른 헬스장에서 흔한 내용으로 구체적으로 답해."
)

answer_prompt = ChatPromptTemplate.from_messages([
    ("system", initial_system_prompt),
    ("human", "[안내 문서]\n{context}\n\n[회원 질문]\n{input}"),
])

rag_chain = (
    {"context": retriever | format_docs, "input": RunnablePassthrough()}
    | answer_prompt
    | answer_llm
    | StrOutputParser()
)

reply = rag_chain.invoke("PT 체험 수업은 무료예요?")
print(reply)
```

```text
사용자 질문 ─────────────────────────────┐
    │                                   │
    ▼                                   ▼
retriever → format_docs → {context}   {input} (그대로 전달)
    │                                   │
    └─────────────────┬─────────────────┘
                      ▼
          ChatPromptTemplate
                      ▼
                  ChatOpenAI
                      ▼
               StrOutputParser
                      ▼
                  답변 문자열
```

| 문법 | 의미 |
|---|---|
| `ChatPromptTemplate.from_messages([...])` | 시스템·사용자 메시지를 포함한 템플릿 생성 |
| `{context}`, `{input}` | 실행 시 채워지는 템플릿 변수 |
| `A \| B` | LCEL의 파이프라인: A의 출력을 B에 전달 |
| `RunnablePassthrough()` | 입력을 변형하지 않고 그대로 전달 |
| `StrOutputParser()` | 모델 응답을 문자열로 반환 |
| `rag_chain.invoke(question)` | 질문 1개에 대한 체인 실행 |

**문제 상황:** 검색 문서에 없는 PT 체험 가격을 답하면, 응답이 자연스러워도 *근거 없는 생성*이므로 실패로 봐야 함.

## 3. 골든셋 생성 — Synthesizer와 Golden

### 골든 데이터 구조

```python
from deepeval.dataset import Golden

golden = Golden(
    input="일일 이용권 있어요?",
    expected_output="안내 문서에 없는 내용이라 정확히 안내드리기 어려워요. 프런트에 문의해 주세요.",
    context=["안내 문서에 이 질문에 대한 내용이 없음"],
    source_file="data/부록/fitplus_guide.md",
)
```

| 필드 | 의미 |
|---|---|
| `input` | 평가 질문 |
| `expected_output` | 기대하는 정답 답변 |
| `context` | 골든 정답을 만들 때 사용한 근거. **정답 근거** |
| `source_file` | 근거 문서 경로 |
| `retrieval_context` | RAG 검색기가 실제로 찾아낸 문장. **판사가 보는 근거** |

`context`와 `retrieval_context`는 같지 않을 수 있음. 검색기가 엉뚱한 문장을 찾았다면 골든의 정답 근거가 정확하더라도, 챗봇은 그 정보를 보지 못함.

### 문서에서 합성 골든 생성

```python
from deepeval.synthesizer import Synthesizer
from deepeval.synthesizer.config import (
    StylingConfig, EvolutionConfig,
    FiltrationConfig, ContextConstructionConfig,
)

synthesizer = Synthesizer(
    model=generation_model_name,
    async_mode=True,
    max_concurrent=32,
    styling_config=StylingConfig(
        scenario="헬스장 '핏플러스 강남점' 회원이 앱 채팅으로 이용 안내를 묻는다.",
        task="헬스장 회원 안내 챗봇",
        input_format="회원이 쓰는 짧은 한국어 질문 한 문장",
        expected_output_format="안내 문서를 근거로 한 짧은 한국어 답변",
    ),
    evolution_config=EvolutionConfig(num_evolutions=0),
    filtration_config=FiltrationConfig(
        critic_model=judgment_model_name,
        max_quality_retries=1,
    ),
)

synthetic_goldens = await synthesizer.a_generate_goldens_from_docs(
    document_paths=[str(data_dir / "부록" / "fitplus_guide.md")],
    max_goldens_per_context=1,
    include_expected_output=True,
    context_construction_config=ContextConstructionConfig(
        embedder="text-embedding-3-small",
        critic_model=judgment_model_name,
        chunk_size=100,
        chunk_overlap=0,
        max_contexts_per_document=9,
        max_context_length=1,
        max_retries=1,
    ),
)
```

**Synthesizer의 처리 과정**

```text
문서 파일
  → 토큰 단위로 청크 분할
  → 골든 생성용 근거 묶음 선정·품질 검사
  → 질문(input)과 정답(expected_output) 생성
  → 질문 품질 검사·필요 시 수정
  → Golden 목록 반환
```

| 설정 | 핵심 역할 | 교안 설정 |
|---|---|---|
| `model` | 질문·정답을 생성할 LLM | `gpt-4.1` |
| `StylingConfig` | 상황·질문 형식·답변 말투 지정 | 한국어 헬스장 안내 |
| `num_evolutions` | 질문을 복잡하게 다시 쓰는 횟수 | `0` = 재작성하지 않음 |
| `critic_model` | 근거/질문의 품질 검사 모델 | `gpt-5.6-luna` |
| `max_quality_retries` | 품질 미달 질문의 수정 시도 횟수 | `1` |
| `chunk_size`, `chunk_overlap` | 청크 토큰 길이, 겹침 길이 | `100`, `0` |
| `max_contexts_per_document` | 문서당 선택할 근거 묶음 수 | `9` |
| `max_context_length` | 근거 묶음 하나에 들어갈 청크 수 | `1` |
| `max_goldens_per_context` | 근거 묶음당 생성 골든 수 | `1` |
| `include_expected_output` | 정답 답변도 자동 생성할지 여부 | `True` |
| `max_retries` | 근거 후보 청크 선정·품질 검사의 재시도 관련 설정 | `1` |

교안 설정에서는 **합성 골든 9개**를 생성. 단, 청크를 100토큰씩 잘라 중간에서 문장이 끊길 수 있고, 생성되는 골든의 내용은 실행마다 달라짐. *합성 정답도 사람 검토가 필요함*.

**비동기 문법:** `async def`는 비동기 함수를 정의, `await`는 비동기 작업의 결과를 기다리는 표현. 주피터에서는 `await synthesizer.a_generate_goldens_from_docs(...)`로 실행하며, 코드가 동기 함수와 섞여 있을 때 API 이름의 `a_`는 비동기 버전임을 나타내는 경우가 많음.

### 저장·불러오기와 문서 밖 질문 추가

```python
from deepeval.dataset import EvaluationDataset, Golden

# 생성 비용을 반복 지불하지 않도록 JSON으로 보관
EvaluationDataset(goldens=synthetic_goldens).save_as(
    file_type="json",
    directory=str(data_dir / "부록"),
    file_name="synthetic_goldens",
)

# 이후 실행에서는 저장된 JSON을 읽어 사용 가능
saved_dataset = EvaluationDataset()
saved_dataset.add_goldens_from_json_file(
    str(data_dir / "부록" / "synthetic_goldens.json")
)
doc_goldens = saved_dataset.goldens

out_of_doc_questions = [
    "다른 지점에서도 운동할 수 있어요?",
    "일일 이용권 있어요?",
    "인바디 측정은 얼마예요?",
    "반려견을 데려가도 되나요?",
]

out_of_doc_goldens = [
    Golden(
        input=q,
        expected_output="안내 문서에 없는 내용이라 정확히 안내드리기 어려워요. 프런트에 문의해 주세요.",
        context=["안내 문서에 이 질문에 대한 내용이 없음"],
        source_file="data/부록/fitplus_guide.md",
    )
    for q in out_of_doc_questions
]

golden_set = doc_goldens + out_of_doc_goldens
```

- `EvaluationDataset(goldens=...)`: 골든 목록으로 평가 데이터셋 생성.
- `.save_as(file_type="json", ...)`: JSON 파일 저장.
- `.add_goldens_from_json_file(path)`: 저장된 골든 데이터 불러오기.
- `[표현식 for 항목 in 목록]`: 리스트 컴프리헨션. 반복하여 `Golden` 객체 4개 생성.
- `+`: 두 리스트를 이어 붙여 총 **13개(합성 9 + 직접 추가 4)**의 골든셋 구성.

**합성 데이터의 한계:** Synthesizer는 문서 근거로 *답할 수 있는 질문*을 주로 만들기 때문에, **문서에 없는 질문**은 별도로 설계해야 함.

## 4. Jev 판사 — Noul과 평가 테스트 케이스

### 평가 기준 정의

원본은 두 가지 판정 기준을 사용.

1. **답변 충실성:** 검색 결과에 답이 있으면 누락 없이 말하고, 없을 때만 없다고 안내했는가?
2. **근거 충실성:** 검색 결과에 없는 시각·가격·계획·약속 등을 지어내지 않았는가?

```python
from deepeval.metrics import JevEval
from deepeval.metrics.jev_eval import Noul
from deepeval.test_case import SingleTurnParams

accuracy_judge = JevEval(
    name="안내 정확성",
    evaluation_params=[
        SingleTurnParams.INPUT,
        SingleTurnParams.ACTUAL_OUTPUT,
        SingleTurnParams.RETRIEVAL_CONTEXT,
    ],
    questions=[
        Noul(
            "retrieval_context에 input의 답이 있으면 actual_output은 "
            "그 답을 빠뜨리지 않고 말한다. "
            "retrieval_context에 답이 없을 때만 없다고 안내한다."
        ),
        Noul(
            "actual_output은 retrieval_context에 있는 내용만 말하고, "
            "retrieval_context에 없는 시각·계획·약속·공식 확정을 지어내지 않는다."
        ),
    ],
    system_one_model=jev_model_name,
    strict_mode=True,
    async_mode=True,
)
```

- `SingleTurnParams`: 판정에 사용할 `LLMTestCase`의 필드 선택.
- `Noul("참이어야 하는 문장")`: Jev가 참일 확률을 평가할 조건. **한 문장에 한 판단 항목**으로 설계.
- `questions=[...]`: 여러 판정 조건을 함께 평가.
- `strict_mode=True`: 교안 기준 각 문장의 `P(yes)`가 **0.5 이상이어야** 최종 통과.
- `system_one_model`: Jev 판정 모델 버전 지정.

**주의:** “질문에 반드시 답한다”만 평가하면 문서에 없는 정보에 대해 적절히 거절한 답변까지 fail 처리할 수 있음. **거절해야 하는 조건도 평가 문장에 포함**해야 함.

### 단건 평가와 일괄 평가

```python
from deepeval.test_case import LLMTestCase

question = "PT 체험 수업은 무료예요?"
found = [doc.page_content for doc in retriever.invoke(question)]

case = LLMTestCase(
    input=question,
    actual_output=reply,
    retrieval_context=found,
)

await accuracy_judge.a_measure(case)
print(accuracy_judge.score, accuracy_judge.success)
print(accuracy_judge.reason)
```

- `LLMTestCase(...)`: *질문 + 생성된 답변 + 검색된 근거*로 판정 사례 생성.
- `.a_measure(case)`: 비동기로 단일 사례 평가.
- `.score`: 지표의 산출 점수, `.success`: 통과 여부, `.reason`: 판정 근거·조건별 결과.
- `P(yes)`: 각 Noul 문장이 참이라고 본 확률. 근거 없는 내용이 포함되면 해당 조건은 fail 가능성이 커짐.

여러 건은 `evaluate()`에 전달. 먼저 골든별로 실제 검색 결과를 붙이는 단계가 중요함.

```python
from deepeval import evaluate
from deepeval.evaluate import AsyncConfig, DisplayConfig

# 골든이 아니라 검색기가 찾은 문장을 판사의 근거로 전달
for golden in golden_set:
    golden.retrieval_context = [
        doc.page_content for doc in retriever.invoke(golden.input)
    ]

# 먼저 골든의 정답이 판사에게 통과하는지 시험
reference_cases = [
    LLMTestCase(
        input=g.input,
        actual_output=g.expected_output,
        retrieval_context=g.retrieval_context,
        name=str(i),
    )
    for i, g in enumerate(golden_set)
]

result = evaluate(
    test_cases=reference_cases,
    metrics=[accuracy_judge],
    async_config=AsyncConfig(max_concurrent=32),
    display_config=DisplayConfig(print_results=False, show_indicator=False),
)

for test_result in result.test_results:
    metric = test_result.metrics_data[0]
    print(test_result.name, metric.success, metric.reason)
```

- `evaluate(test_cases=..., metrics=...)`: 여러 테스트 케이스와 지표를 일괄 평가.
- `AsyncConfig(max_concurrent=32)`: 동시 평가 요청 수 제한.
- `DisplayConfig(...)`: 기본 상세 출력 축소.
- `result.test_results`: 테스트별 결과 모음. 반환 순서가 입력 순서와 다를 수 있으므로 `name`으로 연결.
- `test_result.metrics_data[0].success`: 첫 번째 지표의 성공 여부.

**골든 정답의 fail을 해석할 때** `context`와 `retrieval_context`를 함께 확인해야 함.

- **골든 오류:** 청크 경계 때문에 정답이 일부 정보만 포함하거나 실제 안내 문서와 다름 → 골든 수정.
- **검색 오류:** 골든 정답은 맞지만 `top-k=4` 검색에 필요한 근거가 빠짐 → 검색기/청크 구성 검토.
- **판정 오류:** 근거도 있고 정답도 맞는데 fail → Noul 기준과 판사 결과 재검토.

교안은 정답 답변 13개를 시험했을 때 **9~11개 pass**가 관찰됐다고 설명하며, fail 다수가 잘못 생성된 합성 골든이었다고 기술함. **13개 모두를 맹신하거나, fail을 무조건 판사 오류로 간주하면 안 됨.**

## 5. Prompt Optimization — GEPA로 시스템 프롬프트 개선

### GEPA 원리와 데이터 분할

```text
[초기 시스템 프롬프트]
          │
          ▼
 [골든 질문으로 답변 생성]
          │
          ▼
    [Jev 평가 + 이유]
          │
          ▼
[수정 LLM: 오류 원인 분석]
          │
          ▼
   [새 프롬프트 후보]
          │
          ├─ 점수 개선 없음 → skipped
          └─ 점수 개선됨 ─→ 후보 비교
                               ├─ 기존 후보에 밀림 → rejected
                               └─ 파레토 후보로 남음 → accepted
                                            │
                                            ▼
                                  [최종 프롬프트 선정]
```

- **Genetic:** 부모 프롬프트를 수정해 자식 프롬프트 생성.
- **Pareto:** 일부 유형에서 강점이 다른 후보를 함께 남기고, 다른 후보에게 모든 면에서 밀리는 후보만 제거.
- **고칠 점 찾기용:** 실패 사례로 프롬프트를 수정하는 데이터.
- **후보 비교용:** 수정한 후보가 기존 후보보다 좋은지 비교하는 데이터(최적화용 내부 분할).
- **확인용:** 최적화에 사용하지 않는 별도 테스트 데이터. 과적합 확인에 사용.

```python
# 4개 최적화용: 문서 밖 2 + 문서 안 2
train_goldens = [
    out_of_doc_goldens[0],
    doc_goldens[0],
    doc_goldens[1],
    out_of_doc_goldens[1],
]

# 9개 확인용: 문서 안 7 + 문서 밖 2
check_goldens = doc_goldens[2:] + out_of_doc_goldens[2:]
```

| GEPA 파라미터 | 의미 | 교안 설정 |
|---|---|---|
| `iterations` | 후보 프롬프트를 고쳐보는 회차 수 | `2` |
| `pareto_size` | 최적화용 안에서 후보 비교용으로 떼어 둘 골든 수 | `2` |
| `minibatch_size` | 회차마다 고칠 점 찾기에 사용하는 골든 수 | `2` |
| `random_seed` | 데이터 분할·샘플링 난수 고정 | `42` |

교안의 주어진 골든 순서와 시드에서는 **문서 밖 질문 2개가 수정용**, **문서 안 질문 2개가 후보 비교용**으로 사용됨. 전체 확인용 9개는 최적화에 사용하지 않음.

### PromptOptimizer 실행 코드

```python
from deepeval.optimizer import PromptOptimizer
from deepeval.optimizer.algorithms import GEPA
from deepeval.prompt import Prompt

async def answer_with_prompt(prompt, golden):
    """현재 후보 프롬프트를 적용해 골든 질문에 대한 RAG 답변 생성."""
    candidate_prompt = ChatPromptTemplate.from_messages([
        ("system", prompt.text_template),
        ("human", "[안내 문서]\n{context}\n\n[회원 질문]\n{input}"),
    ])
    candidate_chain = (
        {"context": retriever | format_docs, "input": RunnablePassthrough()}
        | candidate_prompt
        | answer_llm
        | StrOutputParser()
    )
    return await candidate_chain.ainvoke(golden.input)

initial_prompt = Prompt(text_template=initial_system_prompt)

optimizer = PromptOptimizer(
    model_callback=answer_with_prompt,
    metrics=[accuracy_judge],
    optimizer_model=judgment_model_name,
    algorithm=GEPA(
        iterations=2,
        pareto_size=2,
        minibatch_size=2,
        random_seed=42,
    ),
)

optimized_prompt = await optimizer.a_optimize(
    prompt=initial_prompt,
    goldens=train_goldens,
)

print(optimized_prompt.text_template)
```

| 문법 | 의미 |
|---|---|
| `Prompt(text_template=...)` | 최적화 대상인 프롬프트 문자열을 래핑 |
| `model_callback=함수명` | 각 후보 프롬프트를 실제 챗봇에 적용해 답변을 만드는 함수 전달 |
| `async def answer_with_prompt(...)` | 동시 호출 가능한 비동기 콜백 정의 |
| `await candidate_chain.ainvoke(...)` | 비동기 RAG 실행 |
| `optimizer_model` | 실패 이유를 읽고 시스템 프롬프트를 다시 쓰는 LLM |
| `metrics=[accuracy_judge]` | 후보 평가에 사용할 판사 지정 |
| `.a_optimize(prompt=..., goldens=...)` | 평가→수정→비교 반복 및 최종 프롬프트 반환 |
| `.text_template` | `Prompt`에 저장된 프롬프트 문자열 |

**개선 목표:** “문서 밖 질문에 다른 헬스장의 일반적인 정보를 덧붙여라”는 잘못된 규칙을 **“문서에 근거가 없으면 추측하지 말고 문의를 안내하라”**는 규칙으로 바꾸는 것.

**교안의 버전별 주의 사항:** 원본에는 *DeepEval 4.2.5~4.2.9에서* `Scorer` / `Rewriter`의 `_accrue_tokens` 누락으로 발생한 오류를 우회하는 아래 임시 코드가 있음. **해당 오류가 실제로 발생하는 버전에서만 사용**하며, 내부 메서드를 덮어쓰므로 일반적인 해결책으로 권장하지 않음.

```python
# 특정 교안 환경에서만 사용한 임시 우회
from deepeval.optimizer.rewriter import Rewriter
from deepeval.optimizer.scorer import Scorer

def skip_token_count(self, input_tokens, output_tokens):
    pass

Scorer._accrue_tokens = skip_token_count
Rewriter._accrue_tokens = skip_token_count
```

### 최적화 과정 확인

```python
report = optimizer.optimization_report

# 비교용 골든의 점수와, 최종까지 살아남은 후보 확인
for config_id, scores in report.pareto_scores.items():
    config = report.prompt_configurations[config_id]
    for kept_prompt in config.prompts.values():
        print(scores, kept_prompt.text_template)
```

- `optimizer.optimization_report`: 최적화 과정에 대한 리포트.
- `pareto_scores`: 파레토 후보의 비교용 골든 점수. 예시 `[1.0, 0.0]`은 두 골든 중 하나 pass·하나 fail이라는 의미.
- `prompt_configurations`: 해당 후보가 어떤 프롬프트인지 확인하는 설정 모음.
- `accepted`: 후보 채택 / `skipped`: 수정 점수 개선 없음 / `rejected`: 다른 후보에 밀림.

최종 선택된 프롬프트가 항상 모든 질문에 좋은 것은 아님. 확인용 데이터로 별도 검증 필요.

## 6. 최적화 전후 비교 및 지표 계산

같은 **확인용 골든 9개**를 초기 프롬프트와 최적화 프롬프트에 입력하고, 답변을 Jev로 평가. 두 프롬프트 간 검색기·질문·판사는 동일하게 둠.

```python
import pandas as pd

optimized_prompt_template = ChatPromptTemplate.from_messages([
    ("system", optimized_prompt.text_template),
    ("human", "[안내 문서]\n{context}\n\n[회원 질문]\n{input}"),
])
optimized_chain = (
    {"context": retriever | format_docs, "input": RunnablePassthrough()}
    | optimized_prompt_template
    | answer_llm
    | StrOutputParser()
)

check_questions = [golden.input for golden in check_goldens]

# 다건 답변 생성: 입력한 순서대로 결과 반환
replies_by_prompt = {
    "처음": rag_chain.batch(check_questions, config={"max_concurrency": 32}),
    "최적화": optimized_chain.batch(check_questions, config={"max_concurrency": 32}),
}

# 9개 질문 x 2개 프롬프트 = 18개 테스트 케이스
compare_cases = []
for name, replies in replies_by_prompt.items():
    for i, golden in enumerate(check_goldens):
        compare_cases.append(LLMTestCase(
            input=golden.input,
            actual_output=replies[i],
            retrieval_context=golden.retrieval_context,
            name=f"{name}/{i}",
        ))

compare_result = evaluate(
    test_cases=compare_cases,
    metrics=[accuracy_judge],
    async_config=AsyncConfig(max_concurrent=32),
    display_config=DisplayConfig(print_results=False, show_indicator=False),
)

label_by_name = {
    item.name: ("pass" if item.metrics_data[0].success else "fail")
    for item in compare_result.test_results
}

# 각 질문의 유형·전후 pass 여부를 행으로 정리
rows = []
for i, golden in enumerate(check_goldens):
    q_type = "문서에 없음" if golden in out_of_doc_goldens else "문서에 있음"
    rows.append({
        "유형": q_type,
        "처음": label_by_name[f"처음/{i}"] == "pass",
        "최적화": label_by_name[f"최적화/{i}"] == "pass",
    })

pass_check = pd.DataFrame(rows)
pass_rate = pass_check.groupby("유형")[["처음", "최적화"]].mean()
pass_rate.loc["전체"] = pass_check[["처음", "최적화"]].mean()

display(pass_rate.style.format("{:.0%}"))
```

| 문법 | 기능 |
|---|---|
| `.batch(질문목록, config=...)` | 다수 질문에 대해 체인을 실행, 입력 순서대로 결과 반환 |
| `enumerate(리스트)` | 인덱스와 항목을 함께 순회 |
| `f"{name}/{i}"` | 결과 연결용 식별자 문자열 생성 |
| `{key: value for ...}` | 딕셔너리 컴프리헨션 |
| `"pass" if 조건 else "fail"` | 조건부 표현식 |
| `df.groupby("유형")` | 질문 유형별 데이터 묶기 |
| `.mean()` | 불리언 `True=1`, `False=0`의 평균 → **통과율** |
| `.loc["전체"] = ...` | 전체 평균 행 추가 |
| `.style.format("{:.0%}")` | 비율을 정수 백분율로 표시 |

**결과 해석(원본 교안의 시험 실행 기록):** 초기 프롬프트는 전체 **44~67%(4~6/9)**, 최적화 후 **89~100%(8~9/9)**로 설명됨. 실제 값은 골든 생성, 모델 답변과 최적화 과정에 따라 달라짐.

- **문서에 없는 질문:** 추측·환각이 줄어야 함.
- **문서에 있는 질문:** 과잉 거절하지 않고 필요한 내용을 답해야 함.
- 전체 통과율만 보면 일부 질문 유형의 성능이 나빠지는 현상을 놓칠 수 있으므로 **유형별 통과율도 함께 확인**.

## 7. 핵심 문법 요약 및 실전 주의점

| 구분 | 핵심 문법 | 기억할 역할 |
|---|---|---|
| RAG 검색 | `retriever.invoke(question)` | 검색된 문서 가져오기 |
| LCEL 연결 | `retriever \| format_docs`, `chain \| parser` | 실행 단계 연결 |
| 템플릿 | `ChatPromptTemplate.from_messages` | 시스템 규칙과 질문 결합 |
| 골든 생성 | `Synthesizer(...).a_generate_goldens_from_docs(...)` | 평가용 질문·정답 자동 생성 |
| 골든 저장 | `EvaluationDataset(...).save_as(...)` | JSON 저장 |
| 평가 기준 | `Noul("판정 문장")` | 참/거짓 평가 기준 정의 |
| 판사 설정 | `JevEval(evaluation_params=..., questions=...)` | 평가 지표 구성 |
| 단건 판정 | `await judge.a_measure(test_case)` | 테스트 케이스 한 건 평가 |
| 다건 판정 | `evaluate(test_cases=..., metrics=...)` | 여러 건 평가 |
| 프롬프트 최적화 | `PromptOptimizer(model_callback=..., algorithm=GEPA(...))` | 평가 기반 재작성 반복 |
| 최적화 실행 | `await optimizer.a_optimize(...)` | 최종 프롬프트 생성 |
| 다건 추론 | `chain.batch(questions)` | 여러 답변 한번에 생성 |
| 통과율 | `df.groupby("유형").mean()` | 유형별 pass 비율 계산 |

**실행·해석 시 주의할 점**

1. **데이터 의존성:** 업로드된 `.ipynb`만으로 전 실습을 실행할 수 있는 것은 아님. 교안의 `data/부록/fitplus_guide.md`, 기존 Chroma 저장소, API 키 등이 필요.
2. **합성 골든 검토:** 잘린 청크나 부정확한 정답을 그대로 채점 기준으로 쓰면 최적화 방향이 틀어질 수 있음.
3. **판정 근거 일치:** `context`는 골든 생성용 근거, `retrieval_context`는 챗봇이 *실제로 검색한 근거*. Jev는 후자를 보고 판정하도록 설정됨.
4. **학습·평가 분리:** `train_goldens`에서 높은 점수가 나와도 `check_goldens`에서 확인해야 함.
5. **과잉 거절 확인:** 환각을 줄이는 대신 문서에 있는 정답도 거절할 수 있음. 두 질문 유형 모두 평가.
6. **결과 재현성:** `random_seed`가 같아도 LLM 생성 자체의 변동은 남음. 소규모 확인용 골든 9개만으로 배포 품질을 단정하지 말 것.

**한 줄 요약:** `RAG`로 생성한 답을 `Golden`과 `JevEval`로 평가하고, `PromptOptimizer + GEPA`가 평가 피드백으로 프롬프트를 수정한 뒤, **사용하지 않았던 골든으로 전후 성능을 검증**하는 구조.
