# OpenAI API 기초

> 강의 자료의 예제와 용어를 기준으로 재배치한 정리본.

## 1. 전체 흐름

```text
.env에 API 키 저장
        ↓
OpenAI 클라이언트 생성
        ↓
모델 + 요청 메시지 전달
        ↓
모델이 다음 토큰을 확률적으로 생성
        ↓
응답 텍스트와 토큰 사용량 확인
```

---

## 2. API 연결 준비

### `.env` 파일

```env
OPENAI_API_KEY=자신의_API_키
```

API 키를 `.env`에 저장한 뒤 코드에서 불러온다.

### 기본 연결 코드

```python
import os
from dotenv import load_dotenv
from openai import OpenAI

# 현재 작업 폴더에 .env가 있을 때
load_dotenv(".env")

# 한 단계 위 폴더에 .env가 있을 때 사용
# load_dotenv("../.env")

# 429 오류 등이 발생하면 자동 재시도
client = OpenAI(max_retries=8)

print(
    "연결 준비 완료 —",
    "키 확인됨" if os.getenv("OPENAI_API_KEY") else "키가 없습니다(.env 확인)"
)
```

- `load_dotenv()` : `.env`의 환경변수를 불러옴
- `OpenAI()` : API 요청에 사용할 클라이언트 생성
- `max_retries=8` : 요청 제한 오류 등이 발생했을 때 자동 재시도

---

## 3. 언어 모델의 답변 생성 원리

언어 모델은 **다음에 올 토큰을 확률로 예측**한다.

```text
입력 문장
   ↓
다음 토큰별 확률 계산
   ↓
후보 중 하나 선택
   ↓
선택한 토큰을 문장에 추가
   ↓
완성될 때까지 반복
```

- **토큰(token)** : 모델이 글을 처리하는 기본 조각
- 답변은 고정된 문장을 꺼내는 방식이 아니라 확률적으로 생성됨
- 같은 질문도 설정에 따라 답이 달라질 수 있음

### BERT와 GPT

| 모델 구조 | 핵심 역할 |
|---|---|
| BERT | 인코더 중심. 문장의 의미를 이해 |
| GPT | 디코더 중심. 앞의 토큰을 보고 다음 토큰 생성 |

GPT의 Masked Attention은 뒤쪽 토큰을 보지 못하게 가리고, 현재까지의 내용만 이용해 다음 토큰을 예측한다.

![Self-attention 구조](assets/self_attention.png)

> 원본 자료 2쪽의 Self-attention 도식.

---

## 4. Chat Completions API

### 기본 호출

```python
resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {
            "role": "user",
            "content": "파이썬을 초보자에게 한 문장으로 설명해줘."
        }
    ]
)

print("답변:", resp.choices[0].message.content)
print("쓴 토큰:", resp.usage.total_tokens)
```

### 핵심 구조

```python
client.chat.completions.create(
    model="모델명",
    messages=[
        {"role": "user", "content": "질문 내용"}
    ]
)
```

응답에서 자주 확인하는 값:

```python
resp.choices[0].message.content  # 모델의 답변 문자열
resp.usage.prompt_tokens         # 입력 토큰
resp.usage.completion_tokens     # 출력 토큰
resp.usage.total_tokens          # 입력 + 출력 토큰
```

### 메시지의 세 가지 역할

| role | 의미 | 예시 |
|---|---|---|
| `system` | 모델의 역할·태도·출력 규칙 | `너는 친절한 한국어 도우미야.` |
| `user` | 사용자의 질문·요청 | `파이썬이 뭐야?` |
| `assistant` | 모델이 이전에 생성한 답 | `파이썬은 프로그래밍 언어야.` |

### System Prompt 기준

- 대화 내내 유지할 역할·말투·출력 규칙 → `system`
- 매번 달라지는 질문과 작업 요청 → `user`
- 중요한 형식이나 제약은 코드에서도 다시 검증 필요

```python
resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {
            "role": "system",
            "content": "너는 이모지를 즐겨 쓰는 발랄한 말투의 도우미야."
        },
        {
            "role": "user",
            "content": "파이썬을 초보자에게 한 문장으로 설명해줘."
        }
    ]
)

print(resp.choices[0].message.content)
```

---

## 5. 답변의 무작위성

모델의 답변은 확률적으로 생성되므로 같은 질문을 반복해도 달라질 수 있다.

```python
for i in range(3):
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": "가을을 한 문장으로 감성적으로 표현해줘."
            }
        ],
        temperature=1
    )

    print(f"{i + 1}번째:", resp.choices[0].message.content)
```

```text
temperature가 낮음 → 비슷하고 일관된 답
                기본 → 적당한 다양성
              높음 → 예상 밖의 토큰이 선택될 가능성 증가
```

자료의 실험 결과:

- `temperature=0` : 반복 실행해도 거의 같은 답
- `temperature=1` : 실행할 때마다 조금씩 다른 답
- `temperature=2` : 문장이 불안정하거나 의미가 깨질 수 있음

---

## 6. 대화 이어가기: Multi-turn

모델은 각 API 호출을 독립적으로 처리한다. 이전 대화를 기억하게 하려면 과거 메시지를 다시 전달해야 한다.

```text
첫 질문(user)
      ↓
첫 답변(assistant)
      ↓
후속 질문(user)
      ↓
전체 messages를 다시 API에 전달
```

```python
messages = [
    {
        "role": "user",
        "content": "간단한 파이썬 팁 하나만 알려줘."
    }
]

reply1 = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=messages
).choices[0].message.content

messages.append({"role": "assistant", "content": reply1})
messages.append({
    "role": "user",
    "content": "방금 그 팁을 초등학생도 알게 더 쉽게 설명해줘."
})

reply2 = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=messages
).choices[0].message.content

print(reply2)
```

- **Single-turn** : 이전 답변을 포함하지 않는 독립 질문
- **Multi-turn** : 이전 `user`·`assistant` 메시지를 누적해서 전달하는 대화

---

## 7. Streaming 출력

긴 답변을 한 번에 기다리지 않고 생성되는 조각부터 출력하는 방식.

```python
stream = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {
            "role": "user",
            "content": "파이썬으로 할 수 있는 일을 세 문장으로 설명해줘."
        }
    ],
    stream=True
)

pieces = []

for chunk in stream:
    piece = chunk.choices[0].delta.content

    if piece:
        print(piece, end="", flush=True)
        pieces.append(piece)

full_text = "".join(pieces)
print("\n\n조각 수:", len(pieces), "| 전체 길이:", len(full_text))
```

- `stream=True` : 응답을 조각 단위로 받음
- `chunk.choices[0].delta.content` : 새로 도착한 글자 조각
- `end=""` : 줄바꿈 없이 이어 출력
- `flush=True` : 출력 버퍼를 즉시 화면에 표시
- `"".join(pieces)` : 조각을 하나의 문자열로 합침

---

## 8. Responses API

Chat Completions보다 단순한 입력 형태를 제공하는 방식.

| 구분 | Chat Completions | Responses |
|---|---|---|
| 호출 | `client.chat.completions.create()` | `client.responses.create()` |
| 기본 입력 | `messages=[...]` | `input="문자열"` |
| 답 꺼내기 | `resp.choices[0].message.content` | `resp.output_text` |

```python
resp = client.responses.create(
    model="gpt-4o-mini",
    input="세종대왕을 한 문장으로 소개해줘."
)

print(resp.output_text)
```

단순 문자열 입력은 간단하지만, 역할을 나누는 대화에서는 메시지 구조가 필요할 수 있다.

---

## 9. 생성 파라미터

| 파라미터 | 범위·형식 | 역할 | 사용 기준 |
|---|---|---|---|
| `temperature` | `0~2` | 확률분포를 조절. 낮으면 일관, 높으면 다양 | 사실·번역 `0~0.3`, 창작 `0.8~1.2` |
| `top_p` | `0~1` | 누적 확률 기준으로 후보 토큰 범위를 제한 | `temperature` 대신 후보 폭 조절 |
| `max_tokens` | 정수 | 생성할 답변의 최대 토큰 수 제한 | 답이 너무 길거나 비용을 제한할 때 |
| `reasoning_effort` | `low / medium / high` | 추론 깊이와 추론 토큰 사용량 조절 | 여러 단계 사고가 필요한 문제 |

### Temperature와 Top-p 차이

```text
temperature
└─ 후보들의 확률 차이를 조절
   낮음: 1등 후보에 확률 집중
   높음: 여러 후보에 확률 분산

top_p
└─ 누적 확률이 기준을 넘을 때까지 후보만 남김
   낮음: 후보 수가 적음
   높음: 후보 수가 많음
```

![temperature와 top_p 비교](assets/temperature_top_p.png)

> 원본 자료 12쪽의 확률분포 비교 그래프.

### API 적용 예시

```python
resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {
            "role": "user",
            "content": "커피를 한 문장으로 표현해줘."
        }
    ],
    temperature=0.7,
    top_p=1.0,
    max_tokens=300
)
```

보통 `temperature`와 `top_p`를 동시에 크게 바꾸기보다 하나를 중심으로 조절한다.

---

## 10. 추론 모드와 비용

추론이 필요한 모델에서는 `reasoning_effort`로 사고 깊이를 조절한다.

```python
resp = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[
        {
            "role": "user",
            "content": "일주일은 며칠인가요? 숫자만."
        }
    ],
    reasoning_effort="low"
)

print(resp.choices[0].message.content)
```

추론에 사용된 토큰 확인:

```python
resp.usage.completion_tokens_details.reasoning_tokens
```

```text
단순 문제 + 높은 reasoning_effort
→ 결과 차이는 작을 수 있음
→ 추론 토큰과 비용은 증가할 수 있음
```

### 토큰과 비용

```text
prompt_tokens      = 입력에 사용된 토큰
completion_tokens  = 답변 생성에 사용된 토큰
reasoning_tokens   = 내부 추론에 사용된 토큰
```

모델 선택 시 함께 확인할 요소:

- 문제 해결 성능
- 응답 속도
- 입력·출력 토큰 가격
- 추론 토큰 사용량

---

## 11. 재사용 함수

### Single-turn 함수

질문과 역할을 매번 새로 전달하는 간단한 함수.

```python
def ask(
    question,
    persona="너는 친절한 한국어 도우미야.",
    temperature=0.7
):
    messages = [
        {"role": "system", "content": persona},
        {"role": "user", "content": question}
    ]

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=temperature,
        max_tokens=3000
    )

    return resp.choices[0].message.content


print(ask("추천 취미 하나만 알려줘."))
print(ask(
    "추천 취미 하나만 알려줘.",
    persona="너는 무뚝뚝한 해적이야."
))
```

### Multi-turn 대화 함수

대화 기록을 외부의 `messages` 목록에서 관리하는 형태.

```python
def ask_messages(messages, temperature=1.0):
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=temperature,
        max_tokens=3000
    )

    return resp.choices[0].message.content
```

---

## 12. Multi-turn 콘솔 대화 앱

```python
persona = "너는 친절한 한국어 도우미야."
messages = [
    {"role": "system", "content": persona}
]

while True:
    user_input = input("나: ").strip()

    if user_input in ("종료", "q", "quit"):
        print("대화를 종료합니다.")
        break

    messages.append({
        "role": "user",
        "content": user_input
    })

    answer = ask_messages(messages)

    messages.append({
        "role": "assistant",
        "content": answer
    })

    print("AI:", answer, "\n")
```

핵심 동작:

```text
사용자 입력
   ↓
messages에 user 메시지 추가
   ↓
전체 대화 기록으로 API 호출
   ↓
messages에 assistant 답변 추가
   ↓
다음 질문에서도 이전 맥락 유지
```

---

## 13. 모델 비교와 공식 문서

### 모델 비교 사이트

- Artificial Analysis: 지능 지수·속도·가격 비교  
  <https://artificialanalysis.ai/models>
- Arena: 사람이 두 모델의 답을 비교해 선택한 결과 기반 순위  
  <https://arena.ai/leaderboard>

### OpenAI 문서

- 가격표: <https://developers.openai.com/api/docs/pricing>
- 모델 목록·사양: <https://developers.openai.com/api/docs/models>
- 텍스트 생성 가이드: <https://developers.openai.com/api/docs/guides/text>
- Chat Completions API 레퍼런스: <https://developers.openai.com/api/docs/api-reference/chat>

---

## 14. 핵심 압축

| 주제 | 핵심 |
|---|---|
| 답변 생성 | 다음 토큰을 확률로 예측하고 반복 생성 |
| Chat Completions | `messages`에 `system`·`user`·`assistant` 전달 |
| Responses | `input`으로 간단히 요청하고 `output_text`로 답 확인 |
| `temperature` | 낮으면 일관, 높으면 다양 |
| `top_p` | 사용할 후보 토큰 범위 제한 |
| `max_tokens` | 답변 최대 길이 제한 |
| Multi-turn | 이전 메시지를 다시 전달해야 맥락 유지 |
| Streaming | 생성되는 조각을 즉시 출력 |
| 추론 모드 | 문제 난이도에 맞춰 `reasoning_effort` 조절 |
| 비용 확인 | `usage`의 입력·출력·추론 토큰 확인 |

```text
사실·번역 → 낮은 temperature
창작      → 높은 temperature
단순 문제 → 낮은 reasoning_effort
복잡 문제 → 필요한 수준만큼 reasoning_effort 증가
```
