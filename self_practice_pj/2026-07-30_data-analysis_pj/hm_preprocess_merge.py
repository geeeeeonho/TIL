from pathlib import Path
import pandas as pd

# ============================================================
# 0. 경로와 분석 규칙
# ============================================================
DATA_DIR = Path("data")
OUTPUT_DIR = DATA_DIR / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CUSTOMER_PATH = DATA_DIR / "customer_hm.csv"
ARTICLE_PATH = DATA_DIR / "articles_hm.csv"
TRANSACTION_PATH = DATA_DIR / "transactions_hm.csv"

ARTICLE_KEY = "article_id"
CUSTOMER_KEY = "customer_id"
VALID_CHANNELS = {1, 2}  # 1/2의 온라인·오프라인 의미는 별도 데이터 사전 확인 필요
UNKNOWN_TOKENS = {"", "unknown", "undefined"}

COLOR_NAME_COLUMNS = [
    "colour_group_name",
    "perceived_colour_value_name",
    "perceived_colour_master_name",
]

REQUIRED_TRANSACTION_COLUMNS = {
    "t_dat", "customer_id", "article_id", "price", "sales_channel_id"
}
REQUIRED_ARTICLE_COLUMNS = {
    "article_id", "colour_group_code", "colour_group_name",
    "perceived_colour_value_id", "perceived_colour_value_name",
    "perceived_colour_master_id", "perceived_colour_master_name",
    "product_group_name", "product_type_name",
}
REQUIRED_CUSTOMER_COLUMNS = {
    "customer_id", "FN", "Active", "club_member_status",
    "fashion_news_frequency", "age",
}


def check_required_columns(df: pd.DataFrame, required: set[str], table_name: str) -> None:
    """분석에 필요한 열이 빠졌으면 즉시 중단한다."""
    missing = sorted(required - set(df.columns))
    if missing:
        raise KeyError(f"{table_name}에 필요한 열이 없습니다: {missing}")


def normalize_unknown(series: pd.Series) -> pd.Series:
    """결측, Unknown, Undefined, undefined, 빈 문자열을 UNKNOWN으로 통일한다."""
    cleaned = series.astype("string").str.strip()
    unknown_mask = cleaned.isna() | cleaned.str.casefold().isin(UNKNOWN_TOKENS)
    return cleaned.mask(unknown_mask, "UNKNOWN")


# ============================================================
# 1. 데이터 불러오기
# ============================================================
transactions = pd.read_csv(
    TRANSACTION_PATH,
    dtype={"customer_id": "string"},
    low_memory=False,
)
articles = pd.read_csv(ARTICLE_PATH, low_memory=False)
customers = pd.read_csv(
    CUSTOMER_PATH,
    dtype={"customer_id": "string"},
    low_memory=False,
)

check_required_columns(transactions, REQUIRED_TRANSACTION_COLUMNS, "transactions_hm")
check_required_columns(articles, REQUIRED_ARTICLE_COLUMNS, "articles_hm")
check_required_columns(customers, REQUIRED_CUSTOMER_COLUMNS, "customer_hm")

# 키·숫자 열의 형식을 명시적으로 정리한다.
transactions[ARTICLE_KEY] = pd.to_numeric(
    transactions[ARTICLE_KEY], errors="coerce"
).astype("Int64")
transactions["price"] = pd.to_numeric(
    transactions["price"], errors="coerce"
)
transactions["sales_channel_id"] = pd.to_numeric(
    transactions["sales_channel_id"], errors="coerce"
).astype("Int64")

articles[ARTICLE_KEY] = pd.to_numeric(
    articles[ARTICLE_KEY], errors="coerce"
).astype("Int64")
customers["age"] = pd.to_numeric(customers["age"], errors="coerce")

# ============================================================
# 2. 키와 원본 품질 검증
# ============================================================
if articles[ARTICLE_KEY].isna().any():
    raise ValueError("articles_hm.article_id에 결측 또는 숫자로 바꿀 수 없는 값이 있습니다.")
if articles[ARTICLE_KEY].duplicated().any():
    duplicate_keys = articles.loc[
        articles[ARTICLE_KEY].duplicated(keep=False), ARTICLE_KEY
    ].unique()[:10]
    raise ValueError(f"articles_hm.article_id가 고유하지 않습니다. 예: {duplicate_keys}")

if customers[CUSTOMER_KEY].isna().any():
    raise ValueError("customer_hm.customer_id에 결측값이 있습니다.")
if customers[CUSTOMER_KEY].duplicated().any():
    duplicate_keys = customers.loc[
        customers[CUSTOMER_KEY].duplicated(keep=False), CUSTOMER_KEY
    ].unique()[:10]
    raise ValueError(f"customer_hm.customer_id가 고유하지 않습니다. 예: {duplicate_keys}")

# 원본 행 순서를 보존하고, 완전 중복 여부를 표시한다.
transactions.insert(0, "source_row_no", range(len(transactions)))
transaction_identity_columns = [
    "t_dat", "customer_id", "article_id", "price", "sales_channel_id"
]
transactions["is_exact_duplicate_group"] = transactions.duplicated(
    subset=transaction_identity_columns,
    keep=False,
)

# ============================================================
# 3. 거래 데이터 전처리
# ============================================================
# 날짜: 원본을 보존하고 변환 실패는 NaT로 둔다.
transactions["t_dat_raw"] = transactions["t_dat"].astype("string")
transactions["t_dat"] = pd.to_datetime(transactions["t_dat"], errors="coerce")
transactions["date_valid"] = transactions["t_dat"].notna()

# 날짜가 유효한 행만 연·월·분기 값이 생긴다.
transactions["transaction_year"] = transactions["t_dat"].dt.year.astype("Int64")
transactions["transaction_month"] = (
    transactions["t_dat"].dt.to_period("M").astype("string")
    .mask(~transactions["date_valid"], pd.NA)
)
transactions["transaction_quarter"] = (
    transactions["t_dat"].dt.to_period("Q").astype("string")
    .mask(~transactions["date_valid"], pd.NA)
)

# 가격: 행은 유지하되 0 이하·결측은 가격 통계에서만 제외한다.
transactions["price_valid"] = transactions["price"].notna() & transactions["price"].gt(0)
transactions["price_for_analysis"] = transactions["price"].where(
    transactions["price_valid"]
)

# 채널: 0 등 비정상 채널은 전체 분석에는 남기고 채널별 분석에서만 제외한다.
transactions["channel_valid"] = transactions["sales_channel_id"].isin(VALID_CHANNELS)
transactions["channel_for_analysis"] = transactions["sales_channel_id"].where(
    transactions["channel_valid"]
)
transactions["channel_label"] = transactions["sales_channel_id"].map(
    {1: "CHANNEL_1", 2: "CHANNEL_2"}
).fillna("UNKNOWN_CHANNEL")

# ============================================================
# 4. 상품 데이터 전처리
# ============================================================
# 원래 색상 표기도 남겨 두고 분석용 표기를 정규화한다.
for column in COLOR_NAME_COLUMNS:
    articles[f"{column}_raw"] = articles[column].astype("string")
    articles[column] = normalize_unknown(articles[column])

# -1은 삭제하지 않고 '미분류 코드' 플래그로 관리한다.
articles["colour_group_code_unclassified"] = articles["colour_group_code"].eq(-1)
articles["perceived_colour_value_id_unclassified"] = articles[
    "perceived_colour_value_id"
].eq(-1)
articles["perceived_colour_master_id_unclassified"] = articles[
    "perceived_colour_master_id"
].eq(-1)

# detail_desc는 색상 분석에 필요하지 않으므로 원본 결측을 그대로 둔다.

# ============================================================
# 5. 고객 데이터 전처리: 인구통계 분석 때만 사용
# ============================================================
# 확정 규칙: 10세 이하 또는 100세 이상은 이상치로 보고 분석값에서 제외한다.
customers["age_valid"] = customers["age"].gt(10) & customers["age"].lt(100)
customers["age_for_analysis"] = customers["age"].where(customers["age_valid"])

# 회원 상태 결측은 고객 속성 분석에서 UNKNOWN 범주로 보존한다.
customers["club_member_status_raw"] = customers["club_member_status"].astype("string")
customers["club_member_status"] = normalize_unknown(customers["club_member_status"])

# FN·Active는 0/1 외 값이 있는지 플래그만 만든다.
customers["FN_valid"] = customers["FN"].isin([0, 1])
customers["Active_valid"] = customers["Active"].isin([0, 1])

# ============================================================
# 6. 거래 기준 LEFT JOIN: 주 분석용 데이터
# ============================================================
analysis_base = transactions.merge(
    articles,
    on=ARTICLE_KEY,
    how="left",
    validate="many_to_one",
    indicator="article_join_status",
    suffixes=("", "_article"),
)

analysis_base["article_matched"] = analysis_base["article_join_status"].eq("both")
analysis_base["colour_analysis_eligible"] = analysis_base["article_matched"]
analysis_base["price_analysis_eligible"] = (
    analysis_base["article_matched"] & analysis_base["price_valid"]
)
analysis_base["time_analysis_eligible"] = (
    analysis_base["article_matched"] & analysis_base["date_valid"]
)
analysis_base["channel_analysis_eligible"] = (
    analysis_base["article_matched"] & analysis_base["channel_valid"]
)

# LEFT JOIN이므로 거래 행 수가 바뀌면 안 된다.
assert len(analysis_base) == len(transactions), "상품 조인 후 거래 행 수가 변했습니다."

# 실제 색상 분석에는 상품 연결에 성공한 행만 사용한다.
color_analysis = analysis_base.loc[
    analysis_base["colour_analysis_eligible"]
].copy()

# ============================================================
# 7. 완전 중복 제거 민감도 분석용 데이터
# ============================================================
# 주 분석에서는 중복을 유지한다.
# 아래 데이터는 '중복 제거 시 색상 순위가 달라지는지' 비교할 때만 사용한다.
transactions_dedup = transactions.drop_duplicates(
    subset=transaction_identity_columns,
    keep="first",
).copy()

analysis_base_dedup = transactions_dedup.merge(
    articles,
    on=ARTICLE_KEY,
    how="left",
    validate="many_to_one",
    indicator="article_join_status",
    suffixes=("", "_article"),
)
analysis_base_dedup["article_matched"] = analysis_base_dedup[
    "article_join_status"
].eq("both")
color_analysis_dedup = analysis_base_dedup.loc[
    analysis_base_dedup["article_matched"]
].copy()

# ============================================================
# 8. 고객 속성이 필요할 때만 선택적으로 LEFT JOIN
# ============================================================
# 고유 고객 수는 color_analysis['customer_id'].nunique()로 계산할 수 있으므로
# 고객 테이블을 조인할 필요가 없다.
# 아래 조인은 연령·회원 상태별 분석에만 사용한다.
color_analysis_with_customer = color_analysis.merge(
    customers,
    on=CUSTOMER_KEY,
    how="left",
    validate="many_to_one",
    indicator="customer_join_status",
    suffixes=("", "_customer"),
)
color_analysis_with_customer["customer_matched"] = color_analysis_with_customer[
    "customer_join_status"
].eq("both")

# ============================================================
# 9. 검증 요약
# ============================================================
article_unmatched_rows = int((~analysis_base["article_matched"]).sum())
customer_unmatched_rows = int(
    color_analysis_with_customer["customer_join_status"].eq("left_only").sum()
)

quality_report = pd.DataFrame(
    {
        "metric": [
            "transactions_rows",
            "articles_rows",
            "customers_rows",
            "article_key_duplicates",
            "customer_key_duplicates",
            "article_unmatched_transaction_rows",
            "customer_unmatched_color_rows",
            "invalid_or_missing_dates",
            "nonpositive_or_missing_prices",
            "invalid_channels",
            "exact_duplicate_excess_rows",
            "main_color_analysis_rows",
            "deduplicated_color_analysis_rows",
        ],
        "value": [
            len(transactions),
            len(articles),
            len(customers),
            int(articles[ARTICLE_KEY].duplicated().sum()),
            int(customers[CUSTOMER_KEY].duplicated().sum()),
            article_unmatched_rows,
            customer_unmatched_rows,
            int((~transactions["date_valid"]).sum()),
            int((~transactions["price_valid"]).sum()),
            int((~transactions["channel_valid"]).sum()),
            int(transactions.duplicated(subset=transaction_identity_columns).sum()),
            len(color_analysis),
            len(color_analysis_dedup),
        ],
    }
)

print("\n[데이터 품질·조인 검증]")
print(quality_report.to_string(index=False))

print("\n[상품 조인 상태]")
print(analysis_base["article_join_status"].value_counts(dropna=False).to_string())

print("\n[고객 조인 상태: 선택적 고객 속성 분석용]")
print(
    color_analysis_with_customer["customer_join_status"]
    .value_counts(dropna=False)
    .to_string()
)

# ============================================================
# 10. 저장
# ============================================================
# 원본은 수정하지 않고 processed 폴더에 별도 저장한다.
articles.to_csv(OUTPUT_DIR / "articles_hm_preprocessed.csv", index=False)
customers.to_csv(OUTPUT_DIR / "customer_hm_preprocessed.csv", index=False)
analysis_base.to_csv(OUTPUT_DIR / "hm_color_analysis_base.csv", index=False)
analysis_base_dedup.to_csv(
    OUTPUT_DIR / "hm_color_analysis_base_dedup.csv", index=False
)
quality_report.to_csv(OUTPUT_DIR / "hm_preprocessing_quality_report.csv", index=False)

print(f"\n저장 완료: {OUTPUT_DIR.resolve()}")
