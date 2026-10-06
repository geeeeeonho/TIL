# Adaptive RAG 예시 코드 정리

질문 유형에 따라 **문서 검색 / 상품 DB 조회 / 둘 다 조회 / 추가 질문** 경로를 선택하는 Adaptive RAG 예시.

- 긴 DataFrame 출력은 필요한 값만 남김.
- 반복 실행 로그와 `DeprecationWarning`은 제거.
- 검색 결과가 많은 경우 일부만 표시하고 `...` 처리.
- 원문에서 `generate()` 함수 본문은 확인되지 않으므로, 답변 체인과 그래프 연결 구조까지만 유지.
- `llm`, `data_dir`, `search_documents()`, `evidence_id()` 등은 앞선 준비 셀에서 정의된 것으로 전제.

## 전체 흐름

```text
[START]
   ↓
┌──────────────────────────────┐
│ 정보 판단                    │
│ route_query                  │
│ - 질문 분석                  │
│ - route 결정                 │
│ - 상품번호/조건 추출         │
│ - search_query 생성          │
└──────────────────────────────┘
   ├─ knowledge ─────────────────────────────────────────────┐
   │                                                         ↓
   │                           ┌──────────────────────────────┐
   │                           │ 문서 검색                    │
   │                           │ search_knowledge            │
   │                           │ - 안내 문서 검색            │
   │                           │ - 기존 상품 근거 유지       │
   │                           │ - 검색 기록 추가            │
   │                           └──────────────────────────────┘
   │                                                         ↓
   ├─ products ─→ ┌──────────────────────────────┐   ┌──────────────────────────────┐
   │              │ 상품 조회                    │   │ 답변 생성                    │
   │              │ lookup_products              │──→│ generate                     │
   │              │ - 상품 DB 조회               │   │ - 근거 기반 답변 생성        │
   │              │ - product_notice 작성        │   │ - evidence_ids 정리          │
   │              │ - 상품 근거/조회 로그 저장   │   └──────────────────────────────┘
   │              └──────────────────────────────┘                 ↓
   │                     │                                         [END]
   │                     ├─ both → search_knowledge 로 이동
   │                     └─ 조회 결과 없음
   │                                ↓
   └─ clarify ─────────────────→ ┌──────────────────────────────┐
                                 │ 추가 안내                    │
                                 │ respond                      │
                                 │ - 미조회 안내 반환           │
                                 │ - 추가 질문 반환             │
                                 └──────────────────────────────┘
                                                ↓
                                              [END]
```

### 경로 요약

```text
knowledge : route_query → search_knowledge → generate → END
products  : route_query → lookup_products → generate → END
both      : route_query → lookup_products → search_knowledge → generate → END
clarify   : route_query → respond → END
예외      : lookup_products에서 상품 근거가 없으면 → respond → END
```

---

# 1. 질문별 State 설계

각 노드가 읽고 갱신할 공통 상태를 정의.

```python
class RAGState(TypedDict):
    # 입력
    question: str
    top_k: int

    # 계획
    route: Literal["knowledge", "products", "both", "clarify"]
    reason: str
    search_query: str

    # 상품 조회 조건
    product_ids: list[str]
    category: str
    max_price: int | None
    in_stock: bool
    wireless: bool

    # 추가 안내
    clarification: str
    product_notice: str

    # 근거·기록
    documents: list[Document]
    search_log: list[dict]

    # 답변
    draft: str
    evidence_ids: list[str]
```

새 질문마다 빈 상태를 생성.

```python
def make_initial_state(question, top_k=6) -> RAGState:
    return {
        "question": question,
        "top_k": top_k,
        "route": "clarify",
        "reason": "",
        "search_query": "",

        "product_ids": [],
        "category": "",
        "max_price": None,
        "in_stock": False,
        "wireless": False,

        "clarification": "",
        "product_notice": "",
        "documents": [],
        "search_log": [],
        "draft": "",
        "evidence_ids": [],
    }
```

---

# 2. 질문 분석과 조회 계획 생성

`route_query`가 질문을 분석해 경로와 상품 조회 조건을 State에 저장.

## 2.1 구조화된 계획 모델

```python
import re

class ProductPlan(BaseModel):
    route: Literal["knowledge", "products", "both", "clarify"] = Field(
        description=(
            "일반 사용법·쇼핑몰 정책만 필요하면 knowledge, "
            "상품 DB의 가격·재고·사양만 필요하면 products, "
            "특정 상품 사양과 문서 안내를 함께 확인해야 하면 both, "
            "대상이나 요청 확인이 필요하면 clarify입니다."
        )
    )

    reason: str = Field(
        description="선택한 경로가 필요한 이유를 질문과 연결해 한 문장으로 설명합니다."
    )

    category: Literal[
        "", "키보드", "마우스", "USB허브", "모니터", "웹캠", "헤드셋"
    ] = Field(description="질문에 명시된 상품 종류. 없으면 빈 문자열입니다.")

    max_price: int | None = Field(
        description="상품 한 개의 최대 가격. 가격 조건이 없으면 null입니다."
    )
    in_stock: bool = Field(
        description="재고 있는 상품만 요청했을 때 true입니다."
    )
    wireless: bool = Field(
        description="무선 상품만 요청했을 때 true입니다."
    )

    search_query: str = Field(
        description=(
            "knowledge 또는 both에서 사용할 문서 검색어입니다. "
            "상품번호와 추측한 답은 제외합니다."
        )
    )

    clarification: str = Field(
        description="clarify 경로에서 사용자에게 추가로 물을 내용입니다."
    )
```

```python
plan_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "사용자 질문에 필요한 정보 종류를 보고 경로와 검색 조건을 선택하세요. "
        "가격·재고·기본 사양은 products, 일반 사용법·FAQ·쇼핑몰 안내는 knowledge입니다. "
        "특정 상품의 지원 여부와 설정 방법·호환 조건을 함께 물으면 both입니다. "
        "상품번호로 상품을 지정하거나 종류·가격·재고·무선 조건으로 목록을 조회할 수 있습니다. "
        "질문의 최대 가격은 한 개의 상품 가격이며, 없는 조건을 추가하지 마세요. "
        "상품번호가 명시된 질문에는 해당 번호의 사양과 안내를 확인하고 다른 모델로 바꾸지 마세요. "
        "'이 상품', '그 제품'처럼 대상이 불명확하면 clarify로 상품번호를 물으세요. "
        "주문·결제·배송 추적 기록은 없으므로 특정 주문 상태나 도착일은 조회할 수 없습니다. "
        "검색 전에는 상품의 기능·가격·재고를 추측하지 마세요."
    ),
    ("human", "{question}"),
])

plan_chain = plan_prompt | llm.with_structured_output(ProductPlan)
```

## 2.2 `route_query` 노드

```python
def route_query(state: RAGState):
    # 1. LLM으로 계획 생성
    plan = plan_chain.invoke({"question": state["question"]})

    route = plan.route
    reason = plan.reason
    search_query = plan.search_query
    category = plan.category
    max_price = plan.max_price
    in_stock = plan.in_stock
    wireless = plan.wireless
    clarification = plan.clarification

    # 2. 질문에서 상품번호 추출
    found_ids = re.findall(r"[A-Za-z]+-\d+", state["question"])

    product_ids = []
    for product_id in found_ids:
        product_id = product_id.upper()
        if product_id not in product_ids:
            product_ids.append(product_id)

    # 3. 상품 조회가 필요한데 조회 조건이 하나도 없으면 clarify
    if (
        route in {"products", "both"}
        and not product_ids
        and not category
        and max_price is None
        and not in_stock
        and not wireless
    ):
        route = "clarify"
        reason = "조회할 상품번호나 상품 조건이 없습니다."
        clarification = "조회할 상품번호나 상품 종류·가격·재고·무선 조건을 알려주세요."

    return {
        "route": route,
        "reason": reason,
        "search_query": search_query,
        "product_ids": product_ids,
        "category": category,
        "max_price": max_price,
        "in_stock": in_stock,
        "wireless": wireless,
        "clarification": clarification,
    }
```

### 결과 확인

```python
test_question = "KB-102와 KB-103의 기기 전환 방법 알려줘"
found_ids = re.findall(r"[A-Za-z]+-\d+", test_question)

product_ids = []
for product_id in found_ids:
    product_id = product_id.upper()
    if product_id not in product_ids:
        product_ids.append(product_id)

print(product_ids)
```

```text
['KB-102', 'KB-103']
```

---

# 3. 상품 DB 조회

`route_query`가 만든 상품번호와 조건을 이용해 SQLite 상품 DB를 조회하고, 결과를 `Document` 형식의 근거로 변환.

## 3.1 상품 조회 보조 함수

```python
import sqlite3
from contextlib import closing

product_db_path = data_dir / "products" / "products.sqlite3"

display(pd.read_csv(data_dir / "products" / "products.csv").head(6))
```

### 결과 예시

| product_id | 상품 | 분류 | 가격 | 재고 | 연결 방식 |
|---|---|---|---:|---:|---|
| KB-101 | 모아베이직87 블랙 | 키보드 | 29,000 | 8 | USB 유선 |
| KB-102 | 모아스위치75 블랙 | 키보드 | 59,000 | 15 | Bluetooth |
| KB-103 | 모아컴팩트68 블랙 | 키보드 | 49,000 | 22 | Bluetooth, 2.4GHz |
| ... | ... | ... | ... | ... | ... |

```python
def find_products(
    product_ids,
    category="",
    max_price=None,
    in_stock=False,
    wireless=False,
):
    """번호 조회 또는 조건 검색. 조건 검색은 가격순 최대 6개."""

    conditions = ["active = 1"]
    params = []

    # 상품번호가 있으면 해당 상품을 직접 조회
    if product_ids:
        placeholders = ", ".join(["?"] * len(product_ids))
        conditions.append(f"product_id IN ({placeholders})")
        params.extend(product_ids)
        ending = " ORDER BY product_id"

    # 상품번호가 없으면 조건 검색
    else:
        if category:
            conditions.append("category = ?")
            params.append(category)

        if max_price is not None:
            conditions.append("price <= ?")
            params.append(max_price)

        if in_stock:
            conditions.append("stock > 0")

        if wireless:
            conditions.append(
                "(connection LIKE '%Bluetooth%' OR connection LIKE '%2.4GHz%')"
            )

        ending = " ORDER BY price, product_id LIMIT 6"

    sql = "SELECT * FROM products WHERE " + " AND ".join(conditions) + ending

    uri = product_db_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(sql, params).fetchall()

    return [dict(row) for row in rows]
```

## 3.2 상품 데이터를 `Document`로 변환

```python
def product_document(record):
    doc_id = f"catalog:{record['product_id']}"

    text = (
        f"상품번호: {record['product_id']}\n"
        f"상품명: {record['name']}\n"
        f"분류: {record['category']}\n"
        f"가격: {record['price']}원\n"
        f"재고: {record['stock']}개\n"
        f"연결 방식: {record['connection']}\n"
        f"기본 지원 OS: {record['compatible_os']}\n"
        f"Bluetooth 등록 가능 대수: {record['multi_device']}\n"
        f"보증: {record['warranty_months']}개월\n"
        f"기능·제약: {record['specification']}"
    )

    return Document(
        id=doc_id,
        page_content=text,
        metadata={
            "source_id": doc_id,
            "title": record["name"],
            "source": "모아디지털 가상 상품 카탈로그",
            "source_type": "catalog",
            "product_id": record["product_id"],
            "product": record["name"],
        },
    )
```

## 3.3 `lookup_products` 노드

```python
def lookup_products(state: RAGState):
    # 1. 상품 조회
    products = find_products(
        product_ids=state["product_ids"],
        category=state["category"],
        max_price=state["max_price"],
        in_stock=state["in_stock"],
        wireless=state["wireless"],
    )

    # 2. 조회 결과를 Document로 변환
    product_docs = []
    for product in products:
        product_docs.append(product_document(product))

    # 3. 일부 미조회 / 조건 검색 결과 없음 처리
    product_notice = ""

    if state["product_ids"]:
        found_ids = []
        for product in products:
            found_ids.append(product["product_id"])

        missing_ids = []
        for product_id in state["product_ids"]:
            if product_id not in found_ids:
                missing_ids.append(product_id)

        if missing_ids:
            product_notice = (
                f"조회되지 않은 상품번호: {', '.join(missing_ids)}. "
                "번호를 확인해 주세요."
            )

    elif not products:
        product_notice = "조건에 맞는 상품이 없습니다. 조건을 확인해 주세요."

    # 4. 검색 기록 생성
    if state["product_ids"]:
        query = state["product_ids"]
    else:
        query = {
            "category": state["category"],
            "max_price": state["max_price"],
            "in_stock": state["in_stock"],
            "wireless": state["wireless"],
        }

    candidate_ids = []
    for doc in product_docs:
        candidate_ids.append(doc.metadata["source_id"])

    search_record = {
        "source": "products",
        "query": query,
        "candidate_ids": candidate_ids,
    }

    return {
        "documents": state["documents"] + product_docs,
        "search_log": state["search_log"] + [search_record],
        "product_notice": product_notice,
    }
```

### 결과 확인

```python
state = make_initial_state("KB-102와 KB-999를 조회해줘")
state["product_ids"] = ["KB-102", "KB-999"]

result = lookup_products(state)

print("근거 개수:", len(result["documents"]))
print("근거 ID:", [doc.metadata["source_id"] for doc in result["documents"]])
print("조회 기록:", result["search_log"])
print("안내:", result["product_notice"])
```

```text
근거 개수: 1
근거 ID: ['catalog:KB-102']
조회 기록: [{'source': 'products', 'query': ['KB-102', 'KB-999'],
           'candidate_ids': ['catalog:KB-102']}]
안내: 조회되지 않은 상품번호: KB-999. 번호를 확인해 주세요.
```

---

# 4. 상품 근거를 유지하면서 문서 검색

상품 DB에서 찾은 근거를 버리지 않고, 관련 사용법·FAQ 문서를 추가 검색.

```python
def search_knowledge(state: RAGState):
    # 1. 기존 근거와 검색 기록 복사
    documents = list(state["documents"])
    search_log = list(state["search_log"])

    # 2. 상품별 문서 검색 계획 생성
    search_plans = []

    product_docs = [
        doc
        for doc in documents
        if doc.metadata.get("product_id") and doc.metadata.get("product")
    ]

    if product_docs:
        for doc in product_docs:
            product_id = doc.metadata["product_id"]
            product_name = doc.metadata["product"]
            query = f"{product_id} {product_name} / {state['search_query']}"

            existing = None
            for plan in search_plans:
                if plan["query"] == query:
                    existing = plan
                    break

            if existing:
                if product_id not in existing["product_ids"]:
                    existing["product_ids"].append(product_id)
            else:
                search_plans.append({
                    "query": query,
                    "product_ids": [product_id],
                })

    # 상품 근거가 없으면 일반 문서 검색
    elif state["search_query"]:
        search_plans.append({
            "query": state["search_query"],
            "product_ids": [],
        })

    # 3. 계획별 검색 실행
    for plan in search_plans:
        found_docs = search_documents(
            plan["query"],
            top_k=state["top_k"],
        )

        documents.extend(found_docs)

        search_log.append({
            "source": "knowledge",
            "query": plan["query"],
            "product_ids": plan["product_ids"],
            "candidate_ids": [evidence_id(doc) for doc in found_docs],
        })

    # 4. 근거 ID 기준 중복 제거
    unique_documents = []
    seen_ids = set()

    for doc in documents:
        doc_id = evidence_id(doc)
        if doc_id not in seen_ids:
            seen_ids.add(doc_id)
            unique_documents.append(doc)

    return {
        "documents": unique_documents,
        "search_log": search_log,
    }
```

### 결과 확인

```python
state = make_initial_state("KB-102의 기기 등록과 전환 방법을 알려줘")
state["product_ids"] = ["KB-102"]

product_result = lookup_products(state)
state.update(product_result)

state["search_query"] = "기기 등록·전환 방법"
result = search_knowledge(state)

print("문서 ID:")
for doc in result["documents"]:
    print("-", evidence_id(doc))
```

```text
문서 ID:
- catalog:KB-102
- guide:KB-102-pairing
- guide:MS-203-pairing
- guide:KB-102-shortcuts
- guide:KB-103-channels
- faq:keyboard-reconnect
- manual:mouse-switch
```

검색 결과에는 다른 제품 문서도 후보로 포함될 수 있음. 최종 답변 단계에서 **실제 질문 대상과 맞는 근거만 사용하도록 제한**하는 구조.

---

# 5. 근거 기반 답변과 조건부 라우팅

## 5.1 구조화된 답변

```python
class GroundedAnswer(BaseModel):
    answer: str = Field(
        description=(
            "원질문에 대한 답변입니다. 확인된 사실마다 [근거 ID]를 붙이고 "
            "확인되지 않은 항목을 구분합니다."
        )
    )

    evidence_ids: list[str] = Field(
        description="답변에서 실제로 인용한 제공 근거 ID 목록입니다."
    )
```

```python
def format_documents(docs):
    return "\n\n".join(
        f"[{evidence_id(doc)}] {doc.metadata['title']}\n"
        f"출처: {doc.metadata['source']}\n"
        f"{doc.page_content}"
        for doc in docs
    )
```

```python
answer_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "제공된 근거로만 원질문에 답하세요. 사실에는 [근거 ID]를 붙이고 실제 사용한 ID를 evidence_ids에 넣으세요. "
        "상품번호별 가격·재고·기능을 섞지 마세요. 상품 DB의 사실과 일반 사용 안내의 조건을 구분하세요. "
        "다른 상품의 설정키나 지원 기능을 문의한 상품에 적용하지 마세요. "
        "Bluetooth 기기 등록 대수, 한 대씩 전환, 동시 입력은 서로 다릅니다. "
        "USB-C 단자만 보고 영상·충전·데이터 기능을 확정하지 마세요. "
        "근거가 없는 항목은 확인 불가로 밝혀 주세요. "
        "가격·재고는 catalog 근거에 있을 때만 답하고 실시간 재고라고 표현하지 마세요. "
        "조건 검색은 최대 6개이므로 전체 상품이나 유일한 선택지라고 단정하지 마세요. "
        "조회되지 않은 상품 안내는 마지막 별도 문단에 적고 인용을 붙이지 마세요. "
        "자료에 없는 가격·도착일·입고일·버튼 조합을 만들지 마세요."
    ),
    (
        "human",
        "질문: {question}\n"
        "인용 가능한 ID: {allowed_ids}\n"
        "근거:\n{context}"
    ),
])

answer_chain = answer_prompt | llm.with_structured_output(GroundedAnswer)
```

> **원문 확인 사항**  
> 그래프에서는 `generate` 노드를 사용하지만, 업로드된 문서 안에는 `def generate(...)` 구현이 포함되어 있지 않음. 따라서 실행하려면 기존 교안/앞선 셀에 정의된 `generate` 함수가 필요.

## 5.2 추가 안내 응답 노드

```python
def respond(state: RAGState):
    product_notice = state.get("product_notice", "")
    clarification = state.get("clarification", "")

    if product_notice:
        message = product_notice
    elif clarification:
        message = clarification
    else:
        message = "요청을 처리하기 위한 추가 정보가 필요합니다."

    return {
        "draft": message,
        "evidence_ids": [],
    }
```

## 5.3 라우팅 함수

```python
def route_after_plan(state):
    route = state["route"]

    if route == "knowledge":
        return "search_knowledge"

    if route in {"products", "both"}:
        return "lookup_products"

    return "respond"
```

```python
def route_after_products(state):
    has_products = bool(state["documents"])

    # 상품 근거가 없으면 바로 안내
    if not has_products:
        return "respond"

    # 상품 + 문서 근거가 모두 필요
    if state["route"] == "both":
        return "search_knowledge"

    return "generate"
```

### 결과 확인

```python
state = make_initial_state("확인")

for route in ["knowledge", "products", "both", "clarify"]:
    state["route"] = route
    print(route, "->", route_after_plan(state))
```

```text
knowledge -> search_knowledge
products  -> lookup_products
both      -> lookup_products
clarify   -> respond
```

---

# 6. LangGraph 연결

```python
builder = StateGraph(RAGState)

# 노드 등록
builder.add_node("route_query", route_query)
builder.add_node("lookup_products", lookup_products)
builder.add_node("search_knowledge", search_knowledge)
builder.add_node("generate", generate)
builder.add_node("respond", respond)

# 시작점
builder.add_edge(START, "route_query")

# 질문 분석 후 분기
builder.add_conditional_edges(
    "route_query",
    route_after_plan,
    {
        "search_knowledge": "search_knowledge",
        "lookup_products": "lookup_products",
        "respond": "respond",
    },
)

# 상품 조회 후 분기
builder.add_conditional_edges(
    "lookup_products",
    route_after_products,
    {
        "search_knowledge": "search_knowledge",
        "generate": "generate",
        "respond": "respond",
    },
)

# 고정 연결
builder.add_edge("search_knowledge", "generate")
builder.add_edge("generate", END)
builder.add_edge("respond", END)

shopping_app = builder.compile()

display(Image(shopping_app.get_graph().draw_mermaid_png()))
```

### 그래프 구조

```text
                    ┌───────────────┐
START ─────────────→│  route_query  │
                    └───────┬───────┘
                            │
            ┌───────────────┼────────────────┐
            │               │                │
            ▼               ▼                ▼
   lookup_products   search_knowledge      respond
       │   │                │                │
       │   └────────→ search_knowledge      │
       │                    │                │
       └────────────→ generate              │
                            │                │
                            └──────┬─────────┘
                                   ▼
                                  END
```

---

# 7. 실제 질문별 실행 확인

## 7.1 일반 정책 문의 → `knowledge`

```python
question = "배송비와 무료 배송 기준을 알려 주세요."
result_policy = shopping_app.invoke(make_initial_state(question))

print("선택 경로:", result_policy["route"])
display(Markdown(result_policy["draft"]))
```

```text
선택 경로: knowledge

일반 지역 배송비는 3,000원이며,
상품 결제금액 합계가 50,000원 이상이면 기본 배송비가 면제됩니다.
[policy:shipping]

도서산간 추가 비용과 분리 출고 여부는 주문 주소와 출고 창고 확인이 필요합니다.
[policy:shipping]
```

---

## 7.2 조건 상품 검색 → `products`

```python
question = "5만 원 이하 무선 마우스 중 재고 있는 상품을 보여 주세요."
result_filter = shopping_app.invoke(make_initial_state(question))

print("선택 경로:", result_filter["route"])
display(Markdown(result_filter["draft"]))
```

```text
선택 경로: products

- MS-202: 29,000원 / 재고 15개 / 2.4GHz
- MS-207: 31,000원 / 재고 50개 / 2.4GHz
- MS-217: 35,000원 / 재고 34개 / 2.4GHz
- ...

조건 검색 결과는 가격순 최대 6개.
재고 수량은 카탈로그 기준이며 실시간 재고는 아님.
```

---

## 7.3 상품 정보 + 사용법 → `both`

```python
question = (
    "KB-102의 가격과 재고를 알려 주세요. "
    "노트북과 태블릿에 번갈아 쓰려는데 지원 여부와 "
    "기기 등록·전환 방법도 설명해 주세요."
)

result_combined = shopping_app.invoke(make_initial_state(question))

print("선택 경로:", result_combined["route"])
display(Markdown(result_combined["draft"]))
```

```text
선택 경로: both

KB-102는 59,000원이며 카탈로그상 재고는 15개입니다.
[catalog:KB-102]

Windows/macOS 노트북과 iPadOS/Android 태블릿은 지원 OS 범위에 포함됩니다.
Bluetooth 기기는 최대 3대까지 등록할 수 있습니다.
[catalog:KB-102]

Fn+1/2/3 채널을 이용해 기기를 등록하고,
등록 후 해당 키를 짧게 눌러 입력 대상을 한 대씩 전환합니다.
[guide:KB-102-pairing]

... 이하 세부 OS 모드 설명 생략 ...
```

핵심 실행 흐름:

```text
route_query
   ↓ both
lookup_products
   ↓
search_knowledge
   ↓
generate
```

---

## 7.4 일부 상품번호가 없는 경우

```python
question = "KB-102와 KB-999의 가격과 재고를 각각 알려 주세요."
result_partial = shopping_app.invoke(make_initial_state(question))

display(Markdown(result_partial["draft"]))
```

```text
KB-102는 가격 59,000원이며 재고는 15개입니다. [catalog:KB-102]
KB-999는 제공된 근거에서 가격과 재고를 확인할 수 없습니다.

조회되지 않은 상품번호: KB-999. 번호를 확인해 주세요.
```

---

## 7.5 대상이 불명확한 경우 → `clarify`

```python
question = "이 상품은 아이패드에서도 되나요?"
result_clarify = shopping_app.invoke(make_initial_state(question))

print("선택 경로:", result_clarify["route"])
display(Markdown(result_clarify["draft"]))
```

```text
선택 경로: clarify

확인하려는 상품의 상품번호나 정확한 제품명을 알려주세요.
```

---

# 핵심 정리

```text
1. route_query
   질문을 분석해 route + 검색 조건 생성

2. lookup_products
   상품 DB 조회 → 상품 데이터를 Document 근거로 변환

3. search_knowledge
   기존 상품 근거를 유지하면서 관련 문서 추가 검색

4. generate
   수집된 근거만 이용해 최종 답변 생성
   ※ 함수 구현은 원문에 없음

5. respond
   상품 미조회 또는 추가 질문이 필요한 경우 처리

6. 조건부 Edge
   State의 route와 조회 결과에 따라 다음 노드를 선택
```

Adaptive RAG의 핵심은 **질문마다 같은 검색을 강제하지 않고, 필요한 데이터 소스와 처리 경로를 먼저 선택한 뒤 해당 경로만 실행하는 것**.
