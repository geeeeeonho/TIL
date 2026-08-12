# LangChain 실전 코드

> 원본 흐름과 예시는 최대한 유지.
> 코드 문법 오류·설명상 오해가 생길 수 있는 부분만 최소 교정.
> 모델 응답은 실행 시 달라질 수 있으므로 아래 결과는 문서에 기록된 실행 예시로 봄.

---

# 1. 기본 모델·프롬프트 사용

## 사전 준비

```python
# [제공 코드] OpenAI 키 준비 — 이 셀은 실행만
# .env 파일에 저장한 OPENAI_API_KEY를 읽음

import os
from dotenv import load_dotenv

load_dotenv(".env")      # 같은 폴더의 .env
load_dotenv("../.env")   # 정답 폴더에서 실행하는 경우

# 모델 생성 전에 API 키 존재 여부 확인
if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError(
        "이 노트북은 실제 OpenAI 호출이 필요합니다 — OPENAI_API_KEY를 찾지 못했습니다.\n"
        " 1) 일차 폴더에서 cp .env.example .env\n"
        " 2) .env를 열어 본인 키를 채우세요\n"
        " 3) 커널을 재시작한 뒤 이 셀부터 다시 실행하세요"
    )

print("OpenAI 키 확인 완료 — 이제 LangChain으로 모델을 만들 수 있습니다.")
```

```python
# [제공 코드] 공통으로 사용할 부품

# AIMessage: 모델의 응답 객체
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

# temperature=0
# 같은 입력에 대해 출력의 무작위성을 낮춰 비교적 일정한 응답을 얻기 위한 설정
# 완전히 동일한 결과를 보장하는 것은 아님
model = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# AIMessage 같은 모델 출력을 일반 문자열로 추출할 때 사용
parser = StrOutputParser()

print("부품 준비 완료 —", type(model).__name__, "+", type(parser).__name__)
```

**결과**

```text
OpenAI 키 확인 완료 — 이제 LangChain으로 모델을 만들 수 있습니다.
부품 준비 완료 — ChatOpenAI + StrOutputParser
```

---

## 모델에게 물어보기

`model.invoke()` 사용.

```python
reply1 = model.invoke(
    "중고 전자기기를 안전하게 거래하려면 무엇을 확인해야 할까? 두 가지만 짧게 알려줘."
)

display(reply1)
```

**결과**

`model.invoke()`는 단순 문자열이 아니라 `AIMessage` 객체를 반환하며, 응답 내용 외에도 토큰 사용량·모델 정보 같은 메타데이터가 포함될 수 있음.

```text
AIMessage(
    content='1. **상태 확인**: 제품의 외관, 작동 여부, 배터리 상태 등을 꼼꼼히 점검하여 문제가 없는지 확인합니다.\n\n2. **판매자 신뢰도**: 판매자의 평판이나 리뷰를 확인하고, 가능하다면 직접 만나 거래하여 신뢰성을 높입니다.',
    ...메타데이터 생략...
)
```

### 응답에서 텍스트만 추출

```python
text1 = reply1.text

display(text1)
```

**결과**

```text
1. **상태 확인**: 제품의 외관, 작동 여부, 배터리 상태 등을 꼼꼼히 점검하여 문제가 없는지 확인합니다.

2. **판매자 신뢰도**: 판매자의 평판이나 리뷰를 확인하고, 가능하다면 직접 만나 거래하여 신뢰성을 높입니다.
```

---

## 역할 지정 후 질문하기

`SystemMessage`로 역할·말투를 지정하고 `HumanMessage`로 실제 질문 전달.

```python
# 역할·질문 메시지를 리스트로 저장
messages2 = [
    # 시스템 프롬프트: 모델의 역할과 응답 방식 지정
    SystemMessage(
        "너는 중고 거래 플랫폼의 친절한 안전거래 안내원이다. 존댓말로 간결하게 답한다."
    ),

    # 사용자의 실제 질문
    HumanMessage("직거래 장소는 어디가 좋을까?")
]

# 메시지 리스트를 모델에 전달
message2 = model.invoke(messages2)

# 응답 텍스트만 추출
text2 = message2.text
print(text2)
```

**결과**

```text
직거래 장소는 사람들이 많이 모이는 공공장소가 좋습니다. 예를 들어, 카페, 쇼핑몰, 또는 공원 등이 안전하고 편리합니다. 거래 전에 미리 장소를 정하고, 밝고 안전한 곳에서 만나시는 것을 추천드립니다.
```

---

## 역할 지정 없이 단일 템플릿 사용

### `ChatPromptTemplate.from_template()`

한 개의 `human` 메시지로 이루어진 간단한 템플릿 생성.

```python
# 1. 한 줄짜리 사용자 메시지 템플릿 만들기
# {name} = 실행할 때 값을 넣는 변수
quick_prompt = ChatPromptTemplate.from_template(
    "{name} 를 중고로 살 때 꼭 확인할 점을 한 문장으로 알려줘."
)

# 2. name에 값을 넣어 완성된 프롬프트 만들기
message3 = quick_prompt.invoke({"name": "무선 이어폰"})

# 3. 모델에 전달하고 응답 텍스트만 저장
text3 = model.invoke(message3).text
print(text3)
```

**결과**

```text
무선 이어폰을 중고로 살 때는 배터리 상태와 충전 케이블, 이어폰 본체의 외관 및 기능 작동 여부를 꼭 확인해야 합니다.
```

---

## 동일 내용을 `from_messages()`로 작성

`from_messages()`에서는 `(역할, 템플릿)`을 **튜플 하나로 묶어** 전달.

```python
# 동일 요청을 from_messages()로 작성
intro_prompt = ChatPromptTemplate.from_messages([
    ("human", "{name} 를 중고로 살 때 꼭 확인할 점을 한 문장으로 알려줘.")
])

# 2. 변수 name에 값 넣기
message4 = intro_prompt.invoke({"name": "무선 이어폰"})

# 3. 모델 호출 후 텍스트 추출
intro1 = model.invoke(message4).text
print(intro1)
```

**결과**

```text
무선 이어폰을 중고로 구매할 때는 배터리 상태와 충전 케이블, 이어폰 본체의 외관 및 기능 작동 여부를 꼭 확인해야 합니다.
```

> 원본의 `from_messages(['human', '...'])` 형태는 `human`과 실제 프롬프트가 각각 별도 문자열 메시지로 해석될 수 있으므로 `(역할, 템플릿)` 튜플 형태로 교정.

---

## 다변수 템플릿

여러 `{변수}`를 하나의 템플릿에서 사용 가능.

```python
grade_prompt = ChatPromptTemplate.from_messages([
    (
        "human",
        "{name} (상태 {condition}) 를 소개하는 문구를 한 문장으로 써줘."
    )
])

# name, condition 두 변수에 값 입력
message5 = grade_prompt.invoke({
    "name": "게이밍 노트북",
    "condition": "중"
})

intro2 = model.invoke(message5).text
print(intro2)
```

**결과**

```text
강력한 성능과 세련된 디자인을 갖춘 게이밍 노트북으로, 몰입감 넘치는 게임 경험을 제공합니다.
```

> 모델 출력은 항상 변수 내용을 완벽히 반영한다고 보장되지 않음. 위 결과처럼 `condition='중'`이 응답에 직접 반영되지 않을 수도 있음.

---

## 출력 파서로 문자열 뽑기

`StrOutputParser`는 모델이 반환한 `AIMessage`에서 텍스트를 문자열 형태로 추출할 때 사용.

```python
# 모델에게 질문하고 AIMessage 받기
given_reply = model.invoke(
    "중고 노트북을 살 때 배터리 상태는 어떻게 확인해?"
)

# AIMessage -> 문자열
parsed6 = parser.invoke(given_reply)

display(parsed6)
```

**결과**

```text
중고 노트북을 구매할 때 배터리 상태를 확인하는 것은 매우 중요합니다. 다음은 배터리 상태를 확인하는 방법입니다:

1. **배터리 잔량 확인**: 노트북을 켜고 배터리 잔량을 확인하세요. 배터리가 100% 충전된 상태에서 얼마나 오랫동안 사용할 수 있는지 테스트해보는 것이 좋습니다.

2. **배터리 정보 확인**:
- **Windows**: `cmd`를 열고 `powercfg /batteryreport` 명령어를 입력하면 배터리 보고서를 생성할 수 있습니다.
- **Mac**: 시스템 정보의 전원 관련 항목에서 배터리 정보를 확인할 수 있습니다.

3. **배터리 사이클 수 확인**: 충전 사이클 수와 현재 최대 충전 용량 등을 함께 확인합니다. 적정 사이클 수는 제조사와 모델에 따라 다릅니다.

4. **배터리 상태 점검**: 운영체제 또는 제조사 진단 도구에서 배터리 상태를 확인합니다.

5. **물리적 상태 확인**: 배터리가 부풀어 있거나 손상된 흔적이 있는지 확인합니다.

6. **충전 테스트**: 충전이 정상적으로 되는지, 비정상적인 과열은 없는지 확인합니다.

7. **전문가 점검**: 상태 판단이 어렵다면 서비스센터나 전문가 점검을 활용할 수 있습니다.
```

> 원본 답변의 `일반적으로 300~500 사이클이 노트북 배터리의 수명`이라는 표현은 기기마다 기준이 달라 일반 기준으로 단정하기 어려워 수정.

---

# 2. 체인으로 단순화

## 기본 체인

프롬프트 → 모델 → 출력 파서를 `|`로 연결.

```python
# 1. 프롬프트 템플릿 만들기
intro_prompt = ChatPromptTemplate.from_messages([
    ("human", "{name} 를 중고로 살 때 꼭 확인할 점을 한 문장으로 알려줘.")
])

# 입력값 -> 프롬프트 -> 모델 -> 파서 -> 문자열
intro_chain = intro_prompt | model | parser

# 체인 전체 실행
out7 = intro_chain.invoke({"name": "무선 이어폰"})

display(out7)
```

**결과**

```text
배터리 상태와 충전 케이스의 작동 여부를 반드시 확인하세요.
```

---

## 다변수 체인

```python
# 1. 프롬프트 템플릿 만들기
intro_prompt = ChatPromptTemplate.from_messages([
    (
        "human",
        "{name} 의 상태({condition})를 중고 구매자에게 솔직하게 설명하는 한 문장을 써줘."
    )
])

# 입력값 -> 프롬프트 -> 모델 -> 파서 -> 문자열
explain_chain = intro_prompt | model | parser

# 3. 체인 전체 실행
out8 = explain_chain.invoke({
    "name": "게이밍 노트북",
    "condition": "중"
})

display(out8)
```

**결과**

```text
"이 게이밍 노트북은 사용감이 있으며, 성능은 여전히 좋지만 외관에 약간의 스크래치와 마모가 있습니다."
```

---

## `batch()`를 사용한 다중 입력

`batch()`는 여러 입력을 한 번에 전달해 처리할 때 사용.
기본 Runnable 구현에서는 여러 `invoke()`를 병렬로 실행할 수 있음.

```python
# 여러 입력 준비
inputs9 = [
    {"name": "무선 이어폰"},
    {"name": "태블릿 10인치"},
    {"name": "블루투스 스피커"}
]

# intro_chain = intro_prompt | model | parser
results9 = intro_chain.batch(inputs9)

display(results9)
```

**결과**

```text
[
    '배터리 상태와 충전 케이스의 작동 여부를 반드시 확인하세요.',
    '중고 태블릿 10인치를 구매할 때는 배터리 상태, 화면 손상, 작동 여부, 그리고 초기화 여부를 반드시 확인해야 합니다.',
    '블루투스 스피커의 배터리 상태와 연결 기능, 음질을 반드시 확인하고, 외관 손상 여부도 체크하세요.'
]
```

---

## `stream()`으로 응답 조각 받기

완성된 답을 한 번에 받는 대신, 생성되는 조각을 순서대로 받을 수 있음.

```python
# 조각을 저장할 리스트
pieces10 = []

# stream으로 응답 조각을 하나씩 받기
for chunk in intro_chain.stream({"name": "무선 이어폰"}):
    pieces10.append(chunk)

# 조각을 하나의 문자열로 합치기
full10 = "".join(pieces10)

# 출력
display(pieces10)
display(full10)
```

**결과**

```text
[
    '', '배', '터', '리', ' 상태', '와', ' 충', '전', ' 케', '이스',
    '의', ' 작', '동', ' 여부', '를', ' 반드시', ' 확인', '하세요', '.', '', '', ''
]

'배터리 상태와 충전 케이스의 작동 여부를 반드시 확인하세요.'
```

> 스트리밍 조각의 크기와 분리 방식은 모델·SDK·실행 시점에 따라 달라질 수 있음.

---

# 3. 이미지 입력

## 이미지를 읽게 하기

이미지를 Base64로 변환한 뒤 텍스트 블록과 이미지 블록을 같은 `HumanMessage`에 전달.

```python
import base64

with open("data/images/used_earbuds.jpg", "rb") as f:
    photo_url = (
        "data:image/jpeg;base64,"
        + base64.b64encode(f.read()).decode()
    )

# photo_url = "data:image/jpeg;base64,실제데이터" 형태
# 쉼표 뒤쪽의 순수 Base64 데이터만 추출
photo_b64 = photo_url.split(",")[1]
```

```python
# 글자 블록 + 이미지 블록
content11 = [
    {
        # 질문 문장
        "type": "text",
        "text": (
            "이 중고 매물 사진을 보고 판매글에 쓸 소개 문구를 두 문장으로 써줘. "
            "보이는 상태(사용감 등)를 솔직하게 포함해줘."
        )
    },
    {
        # LangChain 표준 Base64 이미지 블록
        "type": "image",
        "base64": photo_b64,
        "mime_type": "image/jpeg"
    }
]

# 글자 + 이미지를 하나의 사용자 메시지로 전달
reply11 = model.invoke([
    HumanMessage(content=content11)
])

# 응답 텍스트 추출
text11 = reply11.text

display(text11)
```

**결과**

```text
사용감이 있는 에어팟 프로입니다. 케이스와 이어폰 모두 약간의 스크래치가 있지만, 기능은 정상적으로 작동합니다.
```

> 원본의 이미지 블록 `source_type='base64'`, `data=photo_b64` 표현은 현재 LangChain 표준 content block에 맞게 `base64=photo_b64` 형태로 교정.

---

# 4. 프롬프트 파일(YAML) 읽어 사용하기

## 프롬프트 파일 작성

`output/my_prompt.yml`

```yaml
seller_intro:
  description: 매물 이름과 상태를 받아 판매글 소개 문구를 쓴다
  system: |
    너는 중고 거래 판매글을 다듬어 주는 편집자다.
  human: |
    다음 매물의 소개 문구를 한 문장으로 써줘.
    이름: {name}
    상태: {condition}
```

## YAML 읽기

```python
import yaml

# 1. YAML 파일 읽기
with open("output/my_prompt.yml", "r", encoding="utf-8") as f:
    my_yaml = yaml.safe_load(f)

# 2. seller_intro 항목 꺼내기
spec12 = my_yaml["seller_intro"]

# 3. YAML의 system, human으로 프롬프트 만들기
file_prompt12 = ChatPromptTemplate.from_messages([
    ("system", spec12["system"]),
    ("human", spec12["human"])
])

# 4. name, condition 값을 채워 프롬프트 완성
message12 = file_prompt12.invoke({
    "name": "태블릿 10인치",
    "condition": "상"
})

# 5. 모델에 전달하고 응답 문자열 추출
text12 = model.invoke(message12).text

display(text12)
```

**결과**

```text
상태 좋은 10인치 태블릿 판매합니다.
```

---

# 5. 체인과 Runnable

## 기본 코드

```python
# [제공 코드] OpenAI 키 준비

import os
from dotenv import load_dotenv

load_dotenv(".env")
load_dotenv("../.env")

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError(
        "이 노트북은 실제 OpenAI 호출이 필요합니다 — OPENAI_API_KEY를 찾지 못했습니다.\n"
        " 1) 일차 폴더에서 cp .env.example .env\n"
        " 2) .env를 열어 본인 키를 채우세요\n"
        " 3) 커널을 재시작한 뒤 이 셀부터 다시 실행하세요"
    )

print("OpenAI 키 확인 완료 — 이제 LangChain으로 모델을 만들 수 있습니다.")
```

```python
# 공통 부품
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import (
    RunnableLambda,
    RunnableParallel,
    RunnablePassthrough,
)
from langchain_openai import ChatOpenAI

model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
parser = StrOutputParser()

print("부품 준비 완료 —", type(model).__name__, "+", type(parser).__name__)
```

**결과**

```text
부품 준비 완료 — ChatOpenAI + StrOutputParser
```

---

## 다단 체인 만들기

상세 설명을 만든 뒤, 그 결과를 다시 요약 체인에 전달.

```python
# 상세 설명용 프롬프트
des1 = ChatPromptTemplate.from_messages([
    (
        "human",
        "{name} (특징: {note}) 의 중고 판매 상세 설명을 3~4문장으로 써줘."
    )
])

# 프롬프트 -> 모델 -> 문자열 파서
desc_chain = des1 | model | parser

# 요약용 프롬프트
sum1 = ChatPromptTemplate.from_messages([
    ("human", "다음 글을 한 문장으로 요약해줘:\n{draft}")
])

# 프롬프트 -> 모델 -> 문자열 파서
sum_chain = sum1 | model | parser

# 1단계: 상세 설명 생성
draft1 = desc_chain.invoke({
    "name": "미러리스 카메라",
    "note": "셔터수 적음, 렌즈 2종, 가방 포함"
})

display(draft1)

# 2단계: 생성된 상세 설명을 요약 체인에 입력
summary1 = sum_chain.invoke({
    "draft": draft1
})

display(summary1)
```

**결과**

```text
미러리스 카메라를 판매합니다. 이 카메라는 셔터 수가 적어 상태가 매우 양호하며, 다양한 촬영을 위한 렌즈 2종이 포함되어 있습니다. 가방도 함께 제공되어 안전하게 보관하고 이동할 수 있습니다. 사진 촬영을 즐기는 분들에게 적합한 제품입니다.

상태가 양호한 미러리스 카메라와 렌즈 2종, 가방이 포함된 제품을 사진 촬영을 즐기는 분들에게 판매합니다.
```

---

## 두 체인을 하나로 연결

`RunnableLambda`를 중간 변환 단계로 사용.

```python
# 1. 말투 변환용 프롬프트
pol1 = ChatPromptTemplate.from_messages([
    ("human", "다음 글을 아주 정중하고 친절한 말투로 다시 써줘:\n{draft}")
])

# 2. 프롬프트 -> 모델 -> 문자열 파서
polite_chain = pol1 | model | parser

# 3. 문자열 -> {'draft': 문자열} 형태로 바꾸는 다리
# 앞 체인의 출력 형식을 다음 체인의 입력 형식에 맞춤
to_draft = RunnableLambda(
    lambda x: {"draft": x}
)

# 4. 상세 설명 체인 -> 형식 변환 -> 말투 변환 체인
polite_flow = desc_chain | to_draft | polite_chain

# 5. 전체 흐름 한 번에 실행
polite2 = polite_flow.invoke({
    "name": "미러리스 카메라",
    "note": "셔터수 적음, 렌즈 2종, 가방 포함"
})

display(polite2)
```

**결과**

```text
안녕하세요!

저희는 미러리스 카메라를 판매하고 있습니다. 이 카메라는 셔터 수가 적어 상태가 매우 양호하며, 다양한 촬영을 위한 렌즈 2종이 함께 포함되어 있습니다. 또한, 안전하게 보관하고 이동할 수 있도록 가방도 제공해 드립니다. 사진 촬영을 즐기시는 분들께 매우 적합한 제품이라고 생각합니다.

관심이 있으시다면 언제든지 문의해 주시기 바랍니다. 감사합니다!
```

---

## 함수를 사용하는 체인

### 지정한 연락처 관련 단어 가리기

이 코드는 개인정보 전체를 자동 탐지하는 기능이 아니라, **미리 지정한 문자열을 단순 치환하는 예시**.

```python
# 중고 거래 글 예시
POST = (
    "미러리스 카메라 팝니다. 010 으로 연락 주시거나 카카오로 문의 주세요. "
    "입금은 계좌번호 알려 드립니다."
)

# 가릴 단어 목록
ban_word = ["010", "카카오", "계좌번호"]

# 1. 지정한 단어를 가리는 일반 파이썬 함수
def mask_contact(text):
    # 금지 단어를 하나씩 꺼냄
    for word in ban_word:
        # 해당 문자열을 ***로 치환
        text = text.replace(word, "***")

    # 최종 문자열 반환
    return text

# 함수 동작 확인
print(mask_contact(POST))

# 2. 일반 함수를 Runnable로 감싸 체인에서 사용
mask_step = RunnableLambda(mask_contact)
```

**결과**

```text
미러리스 카메라 팝니다. *** 으로 연락 주시거나 ***로 문의 주세요. 입금은 *** 알려 드립니다.
```

```python
# 3. 문자열 -> {'input': 문자열} 형태로 변환
to_input = RunnableLambda(
    lambda x: {"input": x}
)

# 4. 중고 거래 글을 한 문장으로 정리하는 프롬프트
safe_prompt = ChatPromptTemplate.from_messages([
    ("human", "다음 중고 거래 글을 한 문장으로 정리해줘:\n{input}")
])

# 5. 전체 체인
# 원본 문자열
# -> 지정 단어 마스킹
# -> {'input': 문자열}
# -> 프롬프트
# -> 모델
# -> 문자열
safe_chain = mask_step | to_input | safe_prompt | model | parser

# 6. 실행
safe3 = safe_chain.invoke(POST)

display(safe3)
```

**결과**

```text
미러리스 카메라를 판매하며, 연락은 *** 또는 ***로 가능하고 입금 방법은 ***에서 안내합니다.
```

---

## `RunnableParallel`로 동시 처리

### 후기 요약 + 감정 분석

같은 입력을 여러 체인에 동시에 전달하고 결과를 딕셔너리로 모음.

```python
# 리뷰
REVIEW = (
    "거래는 약속 장소에서 빠르게 끝났고 물건 상태도 사진과 똑같아 만족스러웠어요. "
    "다만 충전기가 정품이 아니라 조금 아쉬웠습니다."
)

# 요약 프롬프트
sm1 = ChatPromptTemplate.from_messages([
    ("human", "다음 후기를 한 문장으로 요약해줘:\n{input}")
])

# 감정 판단 프롬프트
st1 = ChatPromptTemplate.from_messages([
    ("human", "다음 후기의 감정을 긍정/부정/중립 중 하나로만 답해줘:\n{input}")
])

# 각각의 체인
sm_chain = sm1 | model | parser
st_chain = st1 | model | parser

# 같은 입력을 두 체인에 전달
analyze4 = RunnableParallel(
    summary=sm_chain,
    sentiment=st_chain
)

# 실행
result4 = analyze4.invoke(REVIEW)

display(result4)
```

**결과**

```text
{
    'summary': '거래는 신속하고 물건 상태도 만족스러웠지만, 충전기가 정품이 아닌 점이 아쉬웠습니다.',
    'sentiment': '긍정'
}
```

---

# 6. 대화 기록을 직접 관리하기

> 아래 방식은 대화 기록을 파이썬 리스트에 직접 저장하고 다시 프롬프트에 넣는 방식.
> 별도의 영구 저장 메모리가 자동으로 생기는 것은 아님.

## 리스트에 대화 기록 누적

```python
# 기존 대화 기록에 새로운 질문과 답변을 추가한 새 리스트 반환
def add_turn(history, user_text, ai_text):
    return history + [
        ("user", user_text),
        ("assistant", ai_text)
    ]

print(add_turn([], "안녕", "반가워요"))
```

**결과**

```text
[('user', '안녕'), ('assistant', '반가워요')]
```

---

## 기록이 너무 길어지면 최근 N턴만 남기기

한 턴 = 사용자 메시지 1개 + AI 메시지 1개.

```python
# 최근 n_turns턴만 남기기
def keep_recent(history, n_turns):
    # 한 턴은 user + assistant 두 항목
    # 뒤에서 2 * n_turns개 항목만 반환
    return history[-2 * n_turns:]

# 테스트
sample = [
    ("user", "a"),
    ("assistant", "b"),
    ("user", "c"),
    ("assistant", "d"),
    ("user", "e"),
    ("assistant", "f")
]

print(keep_recent(sample, 2))
```

**결과**

```text
[('user', 'c'), ('assistant', 'd'), ('user', 'e'), ('assistant', 'f')]
```

> `n_turns`는 1 이상의 값을 넣는 전제로 작성된 단순 예시.

---

## 대화 기록을 프롬프트에 넣기

`MessagesPlaceholder`를 사용해 이전 대화를 현재 프롬프트에 포함.
즉, 모델이 자동으로 기억하는 것이 아니라 **호출할 때 이전 기록을 다시 전달**하는 구조.

```python
# 기존 대화 기록
hist7 = [
    ("user", "미러리스 카메라 팔아요"),
    ("assistant", "네, 미러리스 카메라 문의 주셨네요. 무엇을 도와드릴까요?")
]

# 1. 시스템 메시지 + 과거 대화 기록 + 현재 질문
chat_prompt7 = ChatPromptTemplate.from_messages([
    (
        "system",
        "너는 중고 거래 상담원이다. 존댓말로 간결하게 답한다."
    ),

    # 이전 대화 기록이 들어갈 자리
    MessagesPlaceholder("history"),

    # 현재 질문
    ("human", "{input}")
])

# 2. 체인
chat7 = chat_prompt7 | model | parser

# 3. 이전 기록 + 현재 질문을 함께 전달
answer7 = chat7.invoke({
    "history": hist7,
    "input": "그거 상태가 어때?"
})

display(answer7)
```

**결과**

```text
카메라의 상태는 어떤가요? 사용 기간이나 외관, 작동 여부 등을 알려주시면 더 정확한 답변을 드릴 수 있습니다.
```

> 이전 대화에는 판매 의도만 있고 실제 제품 상태 정보는 없으므로, 모델이 상태를 확정해서 답할 수 없음.

---

# 7. `RunnablePassthrough`으로 원본 유지

요약 결과를 만들면서 원본 입력도 함께 남길 때 사용.

```python
# 1. 후기 요약용 프롬프트
sum_prompt8 = ChatPromptTemplate.from_messages([
    ("human", "다음 후기를 한 문장으로 요약해줘:\n{input}")
])

# 2. 요약 체인
sum_chain8 = sum_prompt8 | model | parser

# 3. 같은 입력을 두 갈래로 전달
# original: 입력을 그대로 통과
# summary: 입력을 요약 체인으로 처리
keep_original = RunnableParallel(
    original=RunnablePassthrough(),
    summary=sum_chain8
)

# 4. 실행
result8 = keep_original.invoke(REVIEW)

display(result8)
```

**결과**

```text
{
    'original': '거래는 약속 장소에서 빠르게 끝났고 물건 상태도 사진과 똑같아 만족스러웠어요. 다만 충전기가 정품이 아니라 조금 아쉬웠습니다.',
    'summary': '거래는 신속하고 물건 상태도 만족스러웠지만, 충전기가 정품이 아닌 점이 아쉬웠습니다.'
}
```

---

# 핵심 흐름

```text
단일 호출
입력 -> model.invoke() -> AIMessage

문자열 추출
AIMessage -> .text
또는
AIMessage -> StrOutputParser -> 문자열

프롬프트 체인
입력값 -> ChatPromptTemplate -> model -> StrOutputParser -> 문자열

함수 포함 체인
입력 -> RunnableLambda -> 프롬프트 -> model -> parser

병렬 처리
입력 -> RunnableParallel -> 여러 체인 -> 결과 dict

대화 기록
history 리스트 -> MessagesPlaceholder -> 현재 질문과 함께 model에 다시 전달

원본 보존
입력 -> RunnableParallel(
    original=RunnablePassthrough(),
    summary=요약체인
)
```
