"""H&M 색상 분석 함수 모음.

전처리 스크립트가 생성한 다음 파일을 기본 입력으로 사용한다.
- data/processed/hm_color_analysis_base.csv
- data/processed/customer_hm_preprocessed.csv

각 공개 분석 함수는 다음 구조를 반환한다.
{
    "tables": {...},
    "tests": {...},
    "figures": {...},
    "metadata": {...},
}

노트북에서는 show=True로 표와 그래프를 표시하고, save=True로 CSV/PNG도 저장한다.
"""

from __future__ import annotations

from itertools import combinations
import warnings
from pathlib import Path
from typing import Any, Iterable

import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats
from scipy.integrate import IntegrationWarning
from scipy.stats import studentized_range
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.oneway import anova_oneway, effectsize_oneway


DEFAULT_COLOR_COL = "perceived_colour_master_name"
UNKNOWN_TOKENS = {"", "unknown", "undefined", "nan", "none", "<na>"}
OTHER_LABEL = "OTHER"
SEASON_ORDER = ["봄", "여름", "가을", "겨울"]
AGE_ORDER = ["11~19세", "20대", "30대", "40대", "50대", "60대 이상"]
CHANNEL_ORDER = ["오프라인", "온라인"]


# -----------------------------------------------------------------------------
# 공통 입출력·검증
# -----------------------------------------------------------------------------
def configure_korean_font() -> str:
    """설치된 한글 글꼴을 찾아 Matplotlib 기본 글꼴로 설정한다."""
    available = {f.name for f in font_manager.fontManager.ttflist}
    candidates = [
        "Malgun Gothic",
        "AppleGothic",
        "NanumGothic",
        "NanumBarunGothic",
        "Noto Sans CJK KR",
        "Noto Sans CJK JP",
    ]
    selected = next((name for name in candidates if name in available), "DejaVu Sans")
    plt.rcParams["font.family"] = selected
    plt.rcParams["axes.unicode_minus"] = False
    return selected


def _validate_columns(df: pd.DataFrame, required: Iterable[str], name: str) -> None:
    missing = sorted(set(required) - set(df.columns))
    if missing:
        raise KeyError(f"{name}에 필요한 열이 없습니다: {missing}")


def _to_bool(series: pd.Series) -> pd.Series:
    """CSV에서 bool이 문자열로 읽혀도 안전하게 True/False로 변환한다."""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return (
        series.astype("string")
        .str.strip()
        .str.casefold()
        .isin({"true", "1", "yes"})
    )


def _eligible_mask(
    df: pd.DataFrame,
    eligibility_col: str,
    fallback: pd.Series | bool = True,
) -> pd.Series:
    if eligibility_col in df.columns:
        return _to_bool(df[eligibility_col])
    if isinstance(fallback, pd.Series):
        return fallback.fillna(False)
    return pd.Series(bool(fallback), index=df.index)


def _normalize_color(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip()
    unknown = cleaned.isna() | cleaned.str.casefold().isin(UNKNOWN_TOKENS)
    return cleaned.mask(unknown, "UNKNOWN")


def _result_dirs(result_dir: str | Path) -> tuple[Path, Path]:
    result_dir = Path(result_dir)
    table_dir = result_dir / "tables"
    figure_dir = result_dir / "figures"
    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)
    return table_dir, figure_dir


def _display_table(df: pd.DataFrame, title: str, show: bool, max_rows: int = 30) -> None:
    if not show:
        return
    print(f"\n[{title}]")
    shown = df if len(df) <= max_rows else df.head(max_rows)
    try:
        from IPython.display import display

        display(shown)
    except ImportError:
        print(shown.to_string())
    if len(df) > max_rows:
        print(f"... 전체 {len(df):,}행 중 앞 {max_rows:,}행만 표시")


def _save_table(df: pd.DataFrame, path: Path, save: bool) -> Path | None:
    if not save:
        return None
    df.to_csv(path, encoding="utf-8-sig")
    return path


def _finish_figure(
    fig: plt.Figure,
    path: Path,
    show: bool,
    save: bool,
) -> Path | None:
    fig.tight_layout()
    saved = None
    if save:
        fig.savefig(path, dpi=160, bbox_inches="tight")
        saved = path
    if show:
        plt.show()
    return saved


def load_analysis_data(
    data_dir: str | Path = "data",
    processed_dir: str | Path | None = None,
) -> dict[str, pd.DataFrame | None]:
    """전처리 산출물을 읽고 분석에 필요한 기본 열을 검증한다."""
    data_dir = Path(data_dir)
    processed_dir = Path(processed_dir) if processed_dir else data_dir / "processed"

    base_path = processed_dir / "hm_color_analysis_base.csv"
    customer_path = processed_dir / "customer_hm_preprocessed.csv"
    dedup_path = processed_dir / "hm_color_analysis_base_dedup.csv"
    quality_path = processed_dir / "hm_preprocessing_quality_report.csv"

    for path in [base_path, customer_path]:
        if not path.exists():
            raise FileNotFoundError(
                f"필수 전처리 파일이 없습니다: {path}\n"
                "먼저 hm_preprocess_merge.py를 실행하세요."
            )

    base = pd.read_csv(
        base_path,
        dtype={"customer_id": "string"},
        low_memory=False,
    )
    customers = pd.read_csv(
        customer_path,
        dtype={"customer_id": "string"},
        low_memory=False,
    )
    base["t_dat"] = pd.to_datetime(base["t_dat"], errors="coerce")

    _validate_columns(
        base,
        {
            "t_dat",
            "customer_id",
            "article_id",
            "price",
            "sales_channel_id",
            "product_group_name",
            "perceived_colour_master_name",
            "colour_group_name",
        },
        "hm_color_analysis_base",
    )
    _validate_columns(
        customers,
        {"customer_id", "age_valid", "age_for_analysis"},
        "customer_hm_preprocessed",
    )

    dedup: pd.DataFrame | None = None
    if dedup_path.exists():
        dedup = pd.read_csv(
            dedup_path,
            dtype={"customer_id": "string"},
            low_memory=False,
        )
        dedup["t_dat"] = pd.to_datetime(dedup["t_dat"], errors="coerce")

    quality: pd.DataFrame | None = None
    if quality_path.exists():
        quality = pd.read_csv(quality_path, low_memory=False)

    return {
        "base": base,
        "customers": customers,
        "dedup": dedup,
        "quality": quality,
    }


# -----------------------------------------------------------------------------
# 색상 범주 준비
# -----------------------------------------------------------------------------
def prepare_color_categories(
    df: pd.DataFrame,
    color_col: str = DEFAULT_COLOR_COL,
    test_min_count: int = 50,
    plot_top_n: int = 10,
    other_label: str = OTHER_LABEL,
) -> dict[str, Any]:
    """검정용 범주와 그래프용 범주를 서로 독립적으로 만든다.

    - UNKNOWN은 본 검정·그래프에서 제외하고 metadata로 별도 보고한다.
    - 검정용: 전체 분석 표본에서 빈도가 test_min_count 미만이면 OTHER로 통합한다.
      단, 통합된 OTHER 자체도 test_min_count 미만이면 검정표에서 제외한다.
    - 그래프용: 전체 분석 표본에서 상위 plot_top_n 외에는 OTHER.
    - 범주는 그룹별로 따로 만들지 않고 전체 표본에서 한 번만 결정한다.
    """
    _validate_columns(df, {color_col}, "분석 데이터")
    if test_min_count < 1:
        raise ValueError("test_min_count는 1 이상이어야 합니다.")
    if plot_top_n < 1:
        raise ValueError("plot_top_n은 1 이상이어야 합니다.")

    work = df.copy()
    work["_color_raw"] = _normalize_color(work[color_col])
    unknown_mask = work["_color_raw"].eq("UNKNOWN")
    unknown_rows = int(unknown_mask.sum())
    work = work.loc[~unknown_mask].copy()

    counts = work["_color_raw"].value_counts()
    test_colors = counts[counts >= test_min_count].index.tolist()
    plot_colors = counts.head(plot_top_n).index.tolist()

    rare_mask = ~work["_color_raw"].isin(test_colors)
    rare_total = int(rare_mask.sum())
    # 희소 색상을 합친 OTHER 자체도 test_min_count보다 작으면 검정에서 제외한다.
    # 그래프에서는 가독성과 전체 구성 보존을 위해 계속 OTHER로 표시한다.
    work["_color_test"] = work["_color_raw"].where(~rare_mask, other_label)
    if 0 < rare_total < test_min_count:
        work.loc[rare_mask, "_color_test"] = pd.NA
    work["_color_plot"] = work["_color_raw"].where(
        work["_color_raw"].isin(plot_colors), other_label
    )

    return {
        "data": work,
        "metadata": {
            "color_col": color_col,
            "rows_before_unknown_exclusion": len(df),
            "unknown_rows": unknown_rows,
            "rows_after_unknown_exclusion": len(work),
            "test_min_count": test_min_count,
            "test_colors": test_colors,
            "test_other_rows": rare_total if rare_total >= test_min_count else 0,
            "test_excluded_rare_rows": rare_total if rare_total < test_min_count else 0,
            "plot_top_n": plot_top_n,
            "plot_colors": plot_colors,
            "other_label": other_label,
        },
    }


def _order_table_columns(table: pd.DataFrame, other_label: str = OTHER_LABEL) -> pd.DataFrame:
    if table.empty:
        return table
    totals = table.sum(axis=0).sort_values(ascending=False)
    ordered = [col for col in totals.index if col != other_label]
    if other_label in table.columns:
        ordered.append(other_label)
    return table.reindex(columns=ordered)


def _composition_tables(
    work: pd.DataFrame,
    group_col: str,
    group_order: list[str],
) -> dict[str, pd.DataFrame]:
    count_test = pd.crosstab(work[group_col], work["_color_test"])
    count_plot = pd.crosstab(work[group_col], work["_color_plot"])

    count_test = _order_table_columns(count_test.reindex(group_order, fill_value=0))
    count_plot = _order_table_columns(count_plot.reindex(group_order, fill_value=0))

    ratio_test = count_test.div(count_test.sum(axis=1).replace(0, np.nan), axis=0) * 100
    ratio_plot = count_plot.div(count_plot.sum(axis=1).replace(0, np.nan), axis=0) * 100

    return {
        "count_test": count_test,
        "ratio_pct_test": ratio_test,
        "count_plot": count_plot,
        "ratio_pct_plot": ratio_plot,
    }


# -----------------------------------------------------------------------------
# 통계 검정
# -----------------------------------------------------------------------------
def _chi_square_independence(count_table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    clean = count_table.loc[count_table.sum(axis=1) > 0, count_table.sum(axis=0) > 0]
    columns = [
        "chi2",
        "p_value",
        "dof",
        "cramers_v",
        "n",
        "expected_min",
        "expected_lt5_cells",
        "expected_lt5_pct",
        "assumption_warning",
    ]
    if clean.shape[0] < 2 or clean.shape[1] < 2:
        row = {
            "chi2": np.nan,
            "p_value": np.nan,
            "dof": np.nan,
            "cramers_v": np.nan,
            "n": int(clean.to_numpy().sum()),
            "expected_min": np.nan,
            "expected_lt5_cells": np.nan,
            "expected_lt5_pct": np.nan,
            "assumption_warning": "검정에 필요한 행 또는 열 범주가 2개 미만입니다.",
        }
        return pd.DataFrame([row], columns=columns), pd.DataFrame()

    chi2, p_value, dof, expected = stats.chi2_contingency(clean, correction=False)
    n = int(clean.to_numpy().sum())
    denom = min(clean.shape[0] - 1, clean.shape[1] - 1)
    cramers_v = np.sqrt(chi2 / (n * denom)) if n > 0 and denom > 0 else np.nan
    expected_df = pd.DataFrame(expected, index=clean.index, columns=clean.columns)
    lt5 = int((expected_df < 5).to_numpy().sum())
    total_cells = expected_df.size
    lt5_pct = lt5 / total_cells * 100 if total_cells else np.nan
    expected_min = float(expected_df.min().min())

    warning = ""
    if expected_min < 1 or lt5_pct > 20:
        warning = "기대빈도 조건이 약합니다. 희소 범주 통합 기준을 재검토하세요."

    result = pd.DataFrame(
        [
            {
                "chi2": chi2,
                "p_value": p_value,
                "dof": dof,
                "cramers_v": cramers_v,
                "n": n,
                "expected_min": expected_min,
                "expected_lt5_cells": lt5,
                "expected_lt5_pct": lt5_pct,
                "assumption_warning": warning,
            }
        ]
    )
    return result, expected_df


def _welch_and_kruskal(groups: dict[str, np.ndarray]) -> pd.DataFrame:
    valid = {name: np.asarray(values, dtype=float) for name, values in groups.items() if len(values) >= 2}
    valid = {name: values[np.isfinite(values)] for name, values in valid.items()}
    valid = {name: values for name, values in valid.items() if len(values) >= 2}
    if len(valid) < 2:
        return pd.DataFrame(
            [
                {
                    "test": "Welch ANOVA",
                    "statistic": np.nan,
                    "p_value": np.nan,
                    "df1": np.nan,
                    "df2": np.nan,
                    "effect_size": np.nan,
                    "effect_size_name": "omega squared (pooled SS)",
                    "secondary_effect_size": np.nan,
                    "secondary_effect_size_name": "Welch-adjusted Cohen f^2",
                    "n": sum(len(v) for v in valid.values()),
                    "groups": len(valid),
                },
                {
                    "test": "Kruskal-Wallis",
                    "statistic": np.nan,
                    "p_value": np.nan,
                    "df1": np.nan,
                    "df2": np.nan,
                    "effect_size": np.nan,
                    "effect_size_name": "epsilon squared",
                    "secondary_effect_size": np.nan,
                    "secondary_effect_size_name": "",
                    "n": sum(len(v) for v in valid.values()),
                    "groups": len(valid),
                },
            ]
        )

    arrays = list(valid.values())
    n = sum(len(values) for values in arrays)
    k = len(arrays)

    try:
        welch = anova_oneway(arrays, use_var="unequal", welch_correction=True)
        welch_f = float(welch.statistic)
        welch_p = float(welch.pvalue)
        df1, df2 = map(float, welch.df)
        means = np.asarray([np.mean(a) for a in arrays], dtype=float)
        variances = np.asarray([np.var(a, ddof=1) for a in arrays], dtype=float)
        nobs = np.asarray([len(a) for a in arrays], dtype=float)
        welch_f2 = float(effectsize_oneway(means, variances, nobs, use_var="unequal"))

        # Welch 검정과 함께 제시할 기술적 효과크기: 일반 ANOVA 분해 기반 omega-squared.
        all_values = np.concatenate(arrays)
        grand_mean = float(np.mean(all_values))
        ss_between = sum(len(a) * (float(np.mean(a)) - grand_mean) ** 2 for a in arrays)
        ss_within = sum(float(np.sum((a - np.mean(a)) ** 2)) for a in arrays)
        ms_within = ss_within / (n - k) if n > k else np.nan
        omega = (ss_between - (k - 1) * ms_within) / (ss_between + ss_within + ms_within)
        omega = float(max(0.0, omega)) if np.isfinite(omega) else np.nan
    except (ValueError, ZeroDivisionError, FloatingPointError):
        welch_f = welch_p = df1 = df2 = omega = welch_f2 = np.nan

    try:
        kruskal = stats.kruskal(*arrays, nan_policy="omit")
        h = float(kruskal.statistic)
        kruskal_p = float(kruskal.pvalue)
        epsilon = (h - k + 1) / (n - k) if n > k else np.nan
        epsilon = float(max(0.0, epsilon)) if np.isfinite(epsilon) else np.nan
    except ValueError:
        h = kruskal_p = epsilon = np.nan

    return pd.DataFrame(
        [
            {
                "test": "Welch ANOVA",
                "statistic": welch_f,
                "p_value": welch_p,
                "df1": df1,
                "df2": df2,
                "effect_size": omega,
                "effect_size_name": "omega squared (pooled SS)",
                "secondary_effect_size": welch_f2,
                "secondary_effect_size_name": "Welch-adjusted Cohen f^2",
                "n": n,
                "groups": k,
            },
            {
                "test": "Kruskal-Wallis",
                "statistic": h,
                "p_value": kruskal_p,
                "df1": k - 1,
                "df2": np.nan,
                "effect_size": epsilon,
                "effect_size_name": "epsilon squared",
                "secondary_effect_size": np.nan,
                "secondary_effect_size_name": "",
                "n": n,
                "groups": k,
            },
        ]
    )


def _games_howell(groups: dict[str, np.ndarray], alpha: float = 0.05) -> pd.DataFrame:
    rows: list[dict[str, float | str | bool]] = []
    valid = {
        name: np.asarray(values, dtype=float)[np.isfinite(values)]
        for name, values in groups.items()
        if len(values) >= 2
    }
    k = len(valid)
    for left, right in combinations(valid, 2):
        x, y = valid[left], valid[right]
        n1, n2 = len(x), len(y)
        mean1, mean2 = float(np.mean(x)), float(np.mean(y))
        var1, var2 = float(np.var(x, ddof=1)), float(np.var(y, ddof=1))
        a, b = var1 / n1, var2 / n2
        se = np.sqrt(a + b)
        if se == 0:
            t_stat = 0.0 if mean1 == mean2 else np.inf
            dof = np.inf
        else:
            t_stat = abs(mean1 - mean2) / se
            denom = (a**2) / (n1 - 1) + (b**2) / (n2 - 1)
            dof = (a + b) ** 2 / denom if denom > 0 else np.inf
        q_stat = t_stat * np.sqrt(2)
        # 자유도가 매우 크면 studentized-range의 무한 자유도 근사를 사용해
        # 불필요한 수치 적분 경고와 계산 지연을 줄인다.
        dof_eval = np.inf if dof > 100_000 else dof
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", IntegrationWarning)
            p_value = float(studentized_range.sf(q_stat, k, dof_eval)) if k >= 2 else np.nan
            critical_q = float(studentized_range.ppf(1 - alpha, k, dof_eval)) if k >= 2 else np.nan
        margin = critical_q / np.sqrt(2) * se if np.isfinite(critical_q) else np.nan
        diff = mean1 - mean2
        rows.append(
            {
                "group1": left,
                "group2": right,
                "mean_diff": diff,
                "se": se,
                "df": dof,
                "q_stat": q_stat,
                "p_value": p_value,
                "ci_low": diff - margin,
                "ci_high": diff + margin,
                "significant": bool(p_value < alpha) if np.isfinite(p_value) else False,
            }
        )
    return pd.DataFrame(rows).sort_values("p_value", ignore_index=True) if rows else pd.DataFrame()


def _dunn_holm(groups: dict[str, np.ndarray], alpha: float = 0.05) -> pd.DataFrame:
    valid = {
        name: np.asarray(values, dtype=float)[np.isfinite(values)]
        for name, values in groups.items()
        if len(values) >= 1
    }
    if len(valid) < 2:
        return pd.DataFrame()

    labels: list[str] = []
    values: list[float] = []
    for name, array in valid.items():
        labels.extend([name] * len(array))
        values.extend(array.tolist())

    values_array = np.asarray(values, dtype=float)
    ranks = stats.rankdata(values_array)
    n = len(values_array)
    frame = pd.DataFrame({"group": labels, "rank": ranks})
    mean_ranks = frame.groupby("group", observed=True)["rank"].mean()
    sizes = frame.groupby("group", observed=True).size()

    _, tie_counts = np.unique(values_array, return_counts=True)
    tie_sum = np.sum(tie_counts**3 - tie_counts)
    variance_base = n * (n + 1) / 12
    tie_adjustment = tie_sum / (12 * (n - 1)) if n > 1 else 0
    variance = variance_base - tie_adjustment

    rows = []
    raw_p = []
    for left, right in combinations(valid, 2):
        denom = np.sqrt(variance * (1 / sizes[left] + 1 / sizes[right]))
        z = abs(mean_ranks[left] - mean_ranks[right]) / denom if denom > 0 else np.nan
        p_value = float(2 * stats.norm.sf(abs(z))) if np.isfinite(z) else np.nan
        rows.append(
            {
                "group1": left,
                "group2": right,
                "mean_rank_diff": float(mean_ranks[left] - mean_ranks[right]),
                "z_stat": z,
                "p_value_raw": p_value,
            }
        )
        raw_p.append(p_value)

    finite_mask = np.isfinite(raw_p)
    adjusted = np.full(len(raw_p), np.nan)
    rejected = np.zeros(len(raw_p), dtype=bool)
    if np.any(finite_mask):
        reject, p_adj, _, _ = multipletests(
            np.asarray(raw_p)[finite_mask], alpha=alpha, method="holm"
        )
        adjusted[finite_mask] = p_adj
        rejected[finite_mask] = reject

    for row, p_adj, reject in zip(rows, adjusted, rejected):
        row["p_value_holm"] = p_adj
        row["significant"] = bool(reject)
    return pd.DataFrame(rows).sort_values("p_value_holm", ignore_index=True)


# -----------------------------------------------------------------------------
# 공통 구성비 그래프
# -----------------------------------------------------------------------------
def _plot_ratio_heatmap(
    ratio_pct: pd.DataFrame,
    title: str,
    x_label: str,
    y_label: str,
) -> plt.Figure:
    fig_width = max(9, 0.85 * max(1, ratio_pct.shape[1]))
    fig, ax = plt.subplots(figsize=(fig_width, max(4.5, 0.75 * ratio_pct.shape[0] + 2)))
    sns.heatmap(
        ratio_pct,
        annot=True,
        fmt=".1f",
        cmap="Blues",
        cbar_kws={"label": "그룹 내부 비율(%)"},
        ax=ax,
    )
    ax.set_title(title)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    return fig


def _plot_stacked_ratio(
    ratio_pct: pd.DataFrame,
    title: str,
    x_label: str,
) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(max(10, ratio_pct.shape[1] * 0.7), 6))
    ratio_pct.plot(kind="bar", stacked=True, ax=ax)
    ax.set_title(title)
    ax.set_xlabel(x_label)
    ax.set_ylabel("그룹 내부 구매 비율(%)")
    ax.set_ylim(0, 100)
    ax.legend(title="색상", bbox_to_anchor=(1.02, 1), loc="upper left")
    return fig


def _save_composition_outputs(
    prefix: str,
    color_col: str,
    tables: dict[str, pd.DataFrame],
    tests: dict[str, pd.DataFrame],
    figures: dict[str, plt.Figure],
    result_dir: str | Path,
    show: bool,
    save: bool,
) -> dict[str, dict[str, Path]]:
    table_dir, figure_dir = _result_dirs(result_dir)
    paths: dict[str, dict[str, Path]] = {"tables": {}, "figures": {}}
    for name, table in tables.items():
        path = table_dir / f"{prefix}_{color_col}_{name}.csv"
        saved = _save_table(table, path, save)
        if saved:
            paths["tables"][name] = saved
    for name, test in tests.items():
        if isinstance(test, pd.DataFrame):
            path = table_dir / f"{prefix}_{color_col}_{name}.csv"
            saved = _save_table(test, path, save)
            if saved:
                paths["tables"][name] = saved
    for name, fig in figures.items():
        path = figure_dir / f"{prefix}_{color_col}_{name}.png"
        saved = _finish_figure(fig, path, show, save)
        if saved:
            paths["figures"][name] = saved
    return paths


# -----------------------------------------------------------------------------
# 1. 계절별 색상 구성
# -----------------------------------------------------------------------------
def analyze_season_color(
    data: pd.DataFrame,
    color_col: str = DEFAULT_COLOR_COL,
    test_min_count: int = 50,
    plot_top_n: int = 10,
    result_dir: str | Path = "data/analysis_results",
    show: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """2019년 표본 내 계절별 색상 구매 구성 차이를 분석한다."""
    configure_korean_font()
    _validate_columns(data, {"t_dat", color_col}, "거래·상품 분석본")

    dates = pd.to_datetime(data["t_dat"], errors="coerce")
    eligible = _eligible_mask(data, "time_analysis_eligible", dates.notna())
    sample = data.loc[eligible & dates.notna()].copy()
    sample["t_dat"] = dates.loc[sample.index]

    month_to_season = {
        1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
        6: "여름", 7: "여름", 8: "여름",
        9: "가을", 10: "가을", 11: "가을", 12: "겨울",
    }
    sample["season"] = sample["t_dat"].dt.month.map(month_to_season)
    sample["season"] = pd.Categorical(sample["season"], SEASON_ORDER, ordered=True)

    prepared = prepare_color_categories(sample, color_col, test_min_count, plot_top_n)
    work = prepared["data"]
    tables = _composition_tables(work, "season", SEASON_ORDER)
    omnibus, expected = _chi_square_independence(tables["count_test"])
    tests = {"omnibus": omnibus, "expected_frequencies": expected}

    figures = {
        "heatmap": _plot_ratio_heatmap(
            tables["ratio_pct_plot"],
            "2019년 계절별 색상 구매 비율",
            "색상",
            "계절",
        ),
        "stacked_bar": _plot_stacked_ratio(
            tables["ratio_pct_plot"],
            "2019년 계절별 색상 구매 구성",
            "계절",
        ),
    }

    metadata = {
        **prepared["metadata"],
        "analysis": "season_color",
        "rows_input": len(data),
        "rows_time_eligible": len(sample),
        "rows_used": len(work),
        "interpretation_scope": "2019년 표본 내 계절별 거래 구성의 연관성",
        "season_rule": "봄=3~5월, 여름=6~8월, 가을=9~11월, 겨울=12·1·2월",
    }

    _display_table(tables["count_test"], "계절×색상 구매 건수", show)
    _display_table(tables["ratio_pct_test"].round(2), "계절 내부 색상 구매 비율(%)", show)
    _display_table(omnibus.round(6), "카이제곱 검정과 Cramér's V", show)

    paths = _save_composition_outputs(
        "season", color_col, tables, tests, figures, result_dir, show, save
    )
    metadata["saved_paths"] = paths
    return {"tables": tables, "tests": tests, "figures": figures, "metadata": metadata}


# -----------------------------------------------------------------------------
# 2. 연령대별 색상 구성
# -----------------------------------------------------------------------------
def analyze_age_color(
    data: pd.DataFrame,
    customer_data: pd.DataFrame,
    color_col: str = DEFAULT_COLOR_COL,
    test_min_count: int = 50,
    plot_top_n: int = 10,
    result_dir: str | Path = "data/analysis_results",
    show: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """거래·상품 분석본과 고객 전처리본을 LEFT JOIN해 연령대별 색상 비율을 분석한다."""
    configure_korean_font()
    _validate_columns(data, {"customer_id", color_col}, "거래·상품 분석본")
    _validate_columns(
        customer_data,
        {"customer_id", "age_valid", "age_for_analysis"},
        "고객 전처리본",
    )
    if customer_data["customer_id"].duplicated().any():
        raise ValueError("고객 전처리본 customer_id가 고유하지 않습니다.")

    base_mask = _eligible_mask(data, "colour_analysis_eligible", True)
    base = data.loc[base_mask].copy()
    customer_cols = ["customer_id", "age_valid", "age_for_analysis"]
    if "age" in customer_data.columns:
        customer_cols.append("age")
    merged = base.merge(
        customer_data[customer_cols],
        on="customer_id",
        how="left",
        validate="many_to_one",
        indicator="_customer_join_status",
    )
    matched = merged["_customer_join_status"].eq("both")
    age_valid = _to_bool(merged["age_valid"])
    age_value = pd.to_numeric(merged["age_for_analysis"], errors="coerce")
    age_mask = matched & age_valid & age_value.notna() & age_value.between(11, 99)
    sample = merged.loc[age_mask].copy()
    sample["age_for_analysis"] = age_value.loc[sample.index]
    sample["age_group"] = pd.cut(
        sample["age_for_analysis"],
        bins=[10, 19, 29, 39, 49, 59, 99],
        labels=AGE_ORDER,
        right=True,
        include_lowest=False,
    )

    prepared = prepare_color_categories(sample, color_col, test_min_count, plot_top_n)
    work = prepared["data"]
    tables = _composition_tables(work, "age_group", AGE_ORDER)
    omnibus, expected = _chi_square_independence(tables["count_test"])
    tests = {"omnibus": omnibus, "expected_frequencies": expected}

    figures = {
        "heatmap": _plot_ratio_heatmap(
            tables["ratio_pct_plot"],
            "연령대별 색상 구매 비율",
            "색상",
            "연령대",
        ),
        "stacked_bar": _plot_stacked_ratio(
            tables["ratio_pct_plot"],
            "연령대별 색상 구매 구성",
            "연령대",
        ),
    }

    metadata = {
        **prepared["metadata"],
        "analysis": "age_color",
        "rows_input": len(data),
        "rows_customer_matched": int(matched.sum()),
        "rows_customer_unmatched": int((~matched).sum()),
        "rows_age_eligible_before_unknown": len(sample),
        "rows_used": len(work),
        "age_rule": "11~19세, 20대, 30대, 40대, 50대, 60~99세",
        "interpretation_scope": "고객 정보와 정상 나이가 연결된 거래 구성의 연관성",
    }

    _display_table(tables["count_test"], "연령대×색상 구매 건수", show)
    _display_table(tables["ratio_pct_test"].round(2), "연령대 내부 색상 구매 비율(%)", show)
    _display_table(omnibus.round(6), "카이제곱 검정과 Cramér's V", show)

    paths = _save_composition_outputs(
        "age", color_col, tables, tests, figures, result_dir, show, save
    )
    metadata["saved_paths"] = paths
    return {"tables": tables, "tests": tests, "figures": figures, "metadata": metadata}


# -----------------------------------------------------------------------------
# 3. 온라인·오프라인 색상 구성
# -----------------------------------------------------------------------------
def analyze_channel_color(
    data: pd.DataFrame,
    color_col: str = DEFAULT_COLOR_COL,
    test_min_count: int = 50,
    plot_top_n: int = 10,
    result_dir: str | Path = "data/analysis_results",
    show: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """오프라인(1)과 온라인(2) 채널 내부 색상 구매 비율을 비교한다."""
    configure_korean_font()
    _validate_columns(data, {"sales_channel_id", color_col}, "거래·상품 분석본")

    channel = pd.to_numeric(data["sales_channel_id"], errors="coerce")
    valid = channel.isin([1, 2])
    eligible = _eligible_mask(data, "channel_analysis_eligible", valid) & valid
    sample = data.loc[eligible].copy()
    sample["channel"] = channel.loc[sample.index].map({1: "오프라인", 2: "온라인"})
    sample["channel"] = pd.Categorical(sample["channel"], CHANNEL_ORDER, ordered=True)

    prepared = prepare_color_categories(sample, color_col, test_min_count, plot_top_n)
    work = prepared["data"]
    tables = _composition_tables(work, "channel", CHANNEL_ORDER)
    omnibus, expected = _chi_square_independence(tables["count_test"])

    ratio_for_diff = tables["ratio_pct_plot"].reindex(CHANNEL_ORDER).fillna(0)
    difference = pd.DataFrame(
        {
            "offline_pct": ratio_for_diff.loc["오프라인"],
            "online_pct": ratio_for_diff.loc["온라인"],
        }
    )
    difference["difference_pct_point"] = difference["online_pct"] - difference["offline_pct"]
    difference = difference.sort_values("difference_pct_point")
    tables["online_minus_offline_pct_point"] = difference

    tests = {"omnibus": omnibus, "expected_frequencies": expected}

    stacked = _plot_stacked_ratio(
        tables["ratio_pct_plot"],
        "오프라인·온라인 채널별 색상 구매 구성",
        "판매 채널",
    )
    fig_diff, ax = plt.subplots(figsize=(10, max(5, len(difference) * 0.45)))
    difference["difference_pct_point"].plot(kind="barh", ax=ax)
    ax.axvline(0, linewidth=1)
    ax.set_title("온라인 비율 - 오프라인 비율")
    ax.set_xlabel("비율 차이(%p): 양수는 온라인 비율이 높음")
    ax.set_ylabel("색상")
    figures = {"stacked_bar": stacked, "difference_bar": fig_diff}

    metadata = {
        **prepared["metadata"],
        "analysis": "channel_color",
        "rows_input": len(data),
        "rows_channel_eligible": len(sample),
        "rows_excluded_invalid_channel": int((~valid).sum()),
        "rows_used": len(work),
        "channel_mapping": {1: "오프라인", 2: "온라인"},
        "interpretation_scope": "채널 내부 거래 구성의 연관성",
    }

    _display_table(tables["count_test"], "채널×색상 구매 건수", show)
    _display_table(tables["ratio_pct_test"].round(2), "채널 내부 색상 구매 비율(%)", show)
    _display_table(difference.round(2), "온라인-오프라인 색상 비율 차이(%p)", show)
    _display_table(omnibus.round(6), "카이제곱 검정과 Cramér's V", show)

    paths = _save_composition_outputs(
        "channel", color_col, tables, tests, figures, result_dir, show, save
    )
    metadata["saved_paths"] = paths
    return {"tables": tables, "tests": tests, "figures": figures, "metadata": metadata}


# -----------------------------------------------------------------------------
# 4. 전체 색상별 가격 차이
# -----------------------------------------------------------------------------
def analyze_color_price(
    data: pd.DataFrame,
    color_col: str = DEFAULT_COLOR_COL,
    test_min_count: int = 50,
    plot_top_n: int = 12,
    alpha: float = 0.05,
    run_posthoc: bool = True,
    result_dir: str | Path = "data/analysis_results",
    show: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """색상별 정규화 상대 가격의 평균·분포 차이를 분석한다.

    Welch ANOVA를 주 검정으로, Kruskal-Wallis를 강건성 확인용으로 사용한다.
    희소 색상은 OTHER로 합치지 않고 가격 검정에서 제외한다.
    """
    configure_korean_font()
    _validate_columns(data, {color_col}, "거래·상품 분석본")

    if "price_for_analysis" in data.columns:
        price = pd.to_numeric(data["price_for_analysis"], errors="coerce")
    elif "price" in data.columns:
        price = pd.to_numeric(data["price"], errors="coerce").where(lambda s: s > 0)
    else:
        raise KeyError("가격 분석에 price_for_analysis 또는 price 열이 필요합니다.")

    eligible = _eligible_mask(data, "price_analysis_eligible", price.notna() & price.gt(0))
    sample = data.loc[eligible & price.notna() & price.gt(0)].copy()
    sample["_price"] = price.loc[sample.index]
    sample["_color_raw"] = _normalize_color(sample[color_col])
    unknown_rows = int(sample["_color_raw"].eq("UNKNOWN").sum())
    sample = sample.loc[~sample["_color_raw"].eq("UNKNOWN")].copy()

    counts = sample["_color_raw"].value_counts()
    test_colors = counts[counts >= test_min_count].index.tolist()
    test_sample = sample.loc[sample["_color_raw"].isin(test_colors)].copy()
    plot_colors = test_sample["_color_raw"].value_counts().head(plot_top_n).index.tolist()
    plot_sample = test_sample.loc[test_sample["_color_raw"].isin(plot_colors)].copy()

    grouped = test_sample.groupby("_color_raw", observed=True)["_price"]
    summary = grouped.agg(
        count="count",
        mean_price="mean",
        median_price="median",
        std_price="std",
        q1=lambda s: s.quantile(0.25),
        q3=lambda s: s.quantile(0.75),
    )
    summary["sem"] = summary["std_price"] / np.sqrt(summary["count"])
    t_critical = stats.t.ppf(0.975, summary["count"] - 1)
    summary["ci95_low"] = summary["mean_price"] - t_critical * summary["sem"]
    summary["ci95_high"] = summary["mean_price"] + t_critical * summary["sem"]
    summary = summary.sort_values("mean_price", ascending=False)

    groups = {
        color: group["_price"].to_numpy()
        for color, group in test_sample.groupby("_color_raw", observed=True)
    }
    omnibus = _welch_and_kruskal(groups)
    welch_p = omnibus.loc[omnibus["test"].eq("Welch ANOVA"), "p_value"].iloc[0]
    kruskal_p = omnibus.loc[omnibus["test"].eq("Kruskal-Wallis"), "p_value"].iloc[0]

    games = pd.DataFrame()
    dunn = pd.DataFrame()
    if run_posthoc and np.isfinite(welch_p) and welch_p < alpha:
        games = _games_howell(groups, alpha=alpha)
    if run_posthoc and np.isfinite(kruskal_p) and kruskal_p < alpha:
        dunn = _dunn_holm(groups, alpha=alpha)

    tables = {"summary": summary}
    tests = {"omnibus": omnibus, "games_howell": games, "dunn_holm": dunn}

    plot_summary = summary.loc[summary.index.intersection(plot_colors)].sort_values("mean_price")
    fig_mean, ax = plt.subplots(figsize=(10, max(5, len(plot_summary) * 0.5)))
    y = np.arange(len(plot_summary))
    means = plot_summary["mean_price"].to_numpy()
    lower = means - plot_summary["ci95_low"].to_numpy()
    upper = plot_summary["ci95_high"].to_numpy() - means
    ax.errorbar(means, y, xerr=np.vstack([lower, upper]), fmt="o", capsize=4)
    ax.set_yticks(y, plot_summary.index)
    ax.set_title("색상별 평균 상대 가격과 95% 신뢰구간")
    ax.set_xlabel("정규화된 상대 가격")
    ax.set_ylabel("색상")

    fig_box, ax = plt.subplots(figsize=(10, max(6, len(plot_colors) * 0.5)))
    box_order = summary.loc[summary.index.intersection(plot_colors)].index.tolist()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PendingDeprecationWarning)
        sns.boxplot(
            data=plot_sample,
            x="_price",
            y="_color_raw",
            order=box_order,
            showfliers=False,
            ax=ax,
        )
    ax.set_title("색상별 상대 가격 분포")
    ax.set_xlabel("정규화된 상대 가격")
    ax.set_ylabel("색상")
    figures = {"mean_ci": fig_mean, "boxplot": fig_box}

    metadata = {
        "analysis": "color_price",
        "color_col": color_col,
        "rows_input": len(data),
        "rows_price_eligible_before_unknown": int((eligible & price.notna() & price.gt(0)).sum()),
        "unknown_rows": unknown_rows,
        "rows_after_unknown_exclusion": len(sample),
        "rows_used": len(test_sample),
        "test_min_count": test_min_count,
        "test_colors": test_colors,
        "excluded_sparse_colors": counts[counts < test_min_count].to_dict(),
        "plot_top_n": plot_top_n,
        "plot_colors": plot_colors,
        "price_unit": "0~1 범위로 정규화된 상대 가격",
        "primary_test": "Welch ANOVA",
        "sensitivity_test": "Kruskal-Wallis",
    }

    _display_table(summary.round(6), "색상별 가격 요약", show)
    _display_table(omnibus.round(6), "가격 차이 전체 검정", show)
    if not games.empty:
        _display_table(games.round(6), "Games-Howell 사후검정", show, max_rows=25)
    if not dunn.empty:
        _display_table(dunn.round(6), "Dunn-Holm 사후검정", show, max_rows=25)

    table_dir, figure_dir = _result_dirs(result_dir)
    paths: dict[str, dict[str, Path]] = {"tables": {}, "figures": {}}
    for name, table in {**tables, **tests}.items():
        if isinstance(table, pd.DataFrame):
            saved = _save_table(
                table,
                table_dir / f"price_{color_col}_{name}.csv",
                save,
            )
            if saved:
                paths["tables"][name] = saved
    for name, fig in figures.items():
        saved = _finish_figure(
            fig,
            figure_dir / f"price_{color_col}_{name}.png",
            show,
            save,
        )
        if saved:
            paths["figures"][name] = saved
    metadata["saved_paths"] = paths
    return {"tables": tables, "tests": tests, "figures": figures, "metadata": metadata}


# -----------------------------------------------------------------------------
# 5. 제품군을 통제한 색상 분석
# -----------------------------------------------------------------------------
def analyze_product_group_color(
    data: pd.DataFrame,
    color_col: str = DEFAULT_COLOR_COL,
    stratify_col: str = "product_group_name",
    min_group_rows: int = 300,
    min_cell_count: int = 30,
    plot_top_n_groups: int = 8,
    plot_top_n_colors: int = 10,
    alpha: float = 0.05,
    result_dir: str | Path = "data/analysis_results",
    show: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """제품군 내부에서 색상 구매 비율과 상대 가격 차이를 비교한다."""
    configure_korean_font()
    _validate_columns(data, {color_col, stratify_col}, "거래·상품 분석본")

    color_eligible = _eligible_mask(data, "colour_analysis_eligible", True)
    base = data.loc[color_eligible].copy()
    base["_color_raw"] = _normalize_color(base[color_col])
    base["_stratum"] = base[stratify_col].astype("string").str.strip().fillna("UNKNOWN")
    valid_base = (~base["_color_raw"].eq("UNKNOWN")) & (~base["_stratum"].str.casefold().isin(UNKNOWN_TOKENS))
    count_sample = base.loc[valid_base].copy()

    group_totals = count_sample["_stratum"].value_counts()
    kept_groups = group_totals[group_totals >= min_group_rows].index.tolist()
    count_sample = count_sample.loc[count_sample["_stratum"].isin(kept_groups)].copy()

    count_long = (
        count_sample.groupby(["_stratum", "_color_raw"], observed=True)
        .size()
        .rename("purchase_count")
        .reset_index()
    )
    count_long["purchase_ratio_pct"] = (
        count_long["purchase_count"]
        / count_long.groupby("_stratum", observed=True)["purchase_count"].transform("sum")
        * 100
    )

    if "price_for_analysis" in data.columns:
        price = pd.to_numeric(data["price_for_analysis"], errors="coerce")
    elif "price" in data.columns:
        price = pd.to_numeric(data["price"], errors="coerce").where(lambda s: s > 0)
    else:
        price = pd.Series(np.nan, index=data.index)

    price_eligible = _eligible_mask(data, "price_analysis_eligible", price.notna() & price.gt(0))
    price_base = data.loc[price_eligible & price.notna() & price.gt(0)].copy()
    price_base["_price"] = price.loc[price_base.index]
    price_base["_color_raw"] = _normalize_color(price_base[color_col])
    price_base["_stratum"] = price_base[stratify_col].astype("string").str.strip().fillna("UNKNOWN")
    price_valid = (
        ~price_base["_color_raw"].eq("UNKNOWN")
        & ~price_base["_stratum"].str.casefold().isin(UNKNOWN_TOKENS)
        & price_base["_stratum"].isin(kept_groups)
    )
    price_sample = price_base.loc[price_valid].copy()

    price_long = (
        price_sample.groupby(["_stratum", "_color_raw"], observed=True)["_price"]
        .agg(price_count="count", mean_price="mean", median_price="median", std_price="std")
        .reset_index()
    )
    long_summary = count_long.merge(
        price_long,
        on=["_stratum", "_color_raw"],
        how="left",
        validate="one_to_one",
    ).rename(columns={"_stratum": stratify_col, "_color_raw": color_col})

    test_rows: list[dict[str, Any]] = []
    for stratum, group in price_sample.groupby("_stratum", observed=True):
        cell_counts = group["_color_raw"].value_counts()
        valid_colors = cell_counts[cell_counts >= max(2, min_cell_count)].index
        test_group = group.loc[group["_color_raw"].isin(valid_colors)]
        arrays = {
            color: color_group["_price"].to_numpy()
            for color, color_group in test_group.groupby("_color_raw", observed=True)
        }
        if len(arrays) < 2:
            continue
        omnibus = _welch_and_kruskal(arrays)
        welch = omnibus.loc[omnibus["test"].eq("Welch ANOVA")].iloc[0]
        kruskal = omnibus.loc[omnibus["test"].eq("Kruskal-Wallis")].iloc[0]
        test_rows.append(
            {
                stratify_col: stratum,
                "rows_used": int(sum(len(v) for v in arrays.values())),
                "colors_tested": len(arrays),
                "welch_f": welch["statistic"],
                "welch_p_value": welch["p_value"],
                "welch_omega_squared_approx": welch["effect_size"],
                "kruskal_h": kruskal["statistic"],
                "kruskal_p_value": kruskal["p_value"],
                "kruskal_epsilon_squared": kruskal["effect_size"],
            }
        )

    within_group = pd.DataFrame(test_rows)
    for p_col, out_col in [
        ("welch_p_value", "welch_p_fdr_bh"),
        ("kruskal_p_value", "kruskal_p_fdr_bh"),
    ]:
        if not within_group.empty:
            values = pd.to_numeric(within_group[p_col], errors="coerce")
            finite = values.notna()
            adjusted = pd.Series(np.nan, index=within_group.index)
            if finite.any():
                _, p_adj, _, _ = multipletests(values[finite], alpha=alpha, method="fdr_bh")
                adjusted.loc[finite] = p_adj
            within_group[out_col] = adjusted

    plot_groups = group_totals.loc[group_totals.index.isin(kept_groups)].head(plot_top_n_groups).index.tolist()
    plot_colors = (
        count_sample.loc[count_sample["_stratum"].isin(plot_groups), "_color_raw"]
        .value_counts()
        .head(plot_top_n_colors)
        .index.tolist()
    )

    count_pivot = (
        count_long.pivot(index="_stratum", columns="_color_raw", values="purchase_count")
        .fillna(0)
        .astype(int)
    )
    ratio_pivot = (
        count_long.pivot(index="_stratum", columns="_color_raw", values="purchase_ratio_pct")
        .fillna(0)
    )
    mean_pivot = price_long.pivot(index="_stratum", columns="_color_raw", values="mean_price")
    price_count_pivot = price_long.pivot(index="_stratum", columns="_color_raw", values="price_count")
    mean_pivot = mean_pivot.mask(price_count_pivot < min_cell_count)

    plot_ratio = ratio_pivot.reindex(index=plot_groups, columns=plot_colors).fillna(0)
    plot_mean = mean_pivot.reindex(index=plot_groups, columns=plot_colors)

    fig_ratio = _plot_ratio_heatmap(
        plot_ratio,
        "제품군 내부 색상 구매 비율",
        "색상",
        "제품군",
    )
    fig_mean, ax = plt.subplots(
        figsize=(max(9, len(plot_colors) * 0.85), max(5, len(plot_groups) * 0.65 + 2))
    )
    sns.heatmap(
        plot_mean,
        annot=True,
        fmt=".4f",
        cmap="Blues",
        cbar_kws={"label": "평균 상대 가격"},
        ax=ax,
    )
    ax.set_title(f"제품군 내부 색상별 평균 상대 가격 (셀 n≥{min_cell_count})")
    ax.set_xlabel("색상")
    ax.set_ylabel("제품군")

    tables = {
        "long_summary": long_summary,
        "count_pivot": count_pivot,
        "ratio_pct_pivot": ratio_pivot,
        "mean_price_pivot": mean_pivot,
    }
    tests = {"within_group": within_group}
    figures = {"purchase_ratio_heatmap": fig_ratio, "mean_price_heatmap": fig_mean}
    metadata = {
        "analysis": "product_group_color",
        "color_col": color_col,
        "stratify_col": stratify_col,
        "rows_count_eligible": len(count_sample),
        "rows_price_eligible": len(price_sample),
        "min_group_rows": min_group_rows,
        "min_cell_count": min_cell_count,
        "groups_kept": kept_groups,
        "plot_groups": plot_groups,
        "plot_colors": plot_colors,
        "interpretation_scope": "같은 제품군 내부의 색상 구성 및 상대 가격 비교",
    }

    _display_table(long_summary.round(6), "제품군×색상 요약", show, max_rows=40)
    _display_table(within_group.round(6), "제품군 내부 가격 차이 검정", show, max_rows=30)

    table_dir, figure_dir = _result_dirs(result_dir)
    paths: dict[str, dict[str, Path]] = {"tables": {}, "figures": {}}
    for name, table in {**tables, **tests}.items():
        saved = _save_table(
            table,
            table_dir / f"product_group_{color_col}_{name}.csv",
            save,
        )
        if saved:
            paths["tables"][name] = saved
    for name, fig in figures.items():
        saved = _finish_figure(
            fig,
            figure_dir / f"product_group_{color_col}_{name}.png",
            show,
            save,
        )
        if saved:
            paths["figures"][name] = saved
    metadata["saved_paths"] = paths
    return {"tables": tables, "tests": tests, "figures": figures, "metadata": metadata}


# -----------------------------------------------------------------------------
# 전체 실행
# -----------------------------------------------------------------------------
def run_all_analyses(
    data: pd.DataFrame | None = None,
    customer_data: pd.DataFrame | None = None,
    data_dir: str | Path = "data",
    processed_dir: str | Path | None = None,
    result_dir: str | Path | None = None,
    color_col: str = DEFAULT_COLOR_COL,
    test_min_count: int = 50,
    plot_top_n: int = 10,
    price_min_count: int = 50,
    product_min_group_rows: int = 300,
    product_min_cell_count: int = 30,
    show: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """다섯 분석을 순서대로 실행한다."""
    if data is None or customer_data is None:
        loaded = load_analysis_data(data_dir=data_dir, processed_dir=processed_dir)
        data = loaded["base"] if data is None else data
        customer_data = loaded["customers"] if customer_data is None else customer_data

    if result_dir is None:
        result_dir = Path(data_dir) / "analysis_results"

    results = {
        "season": analyze_season_color(
            data,
            color_col=color_col,
            test_min_count=test_min_count,
            plot_top_n=plot_top_n,
            result_dir=result_dir,
            show=show,
            save=save,
        ),
        "age": analyze_age_color(
            data,
            customer_data,
            color_col=color_col,
            test_min_count=test_min_count,
            plot_top_n=plot_top_n,
            result_dir=result_dir,
            show=show,
            save=save,
        ),
        "channel": analyze_channel_color(
            data,
            color_col=color_col,
            test_min_count=test_min_count,
            plot_top_n=plot_top_n,
            result_dir=result_dir,
            show=show,
            save=save,
        ),
        "price": analyze_color_price(
            data,
            color_col=color_col,
            test_min_count=price_min_count,
            plot_top_n=plot_top_n,
            result_dir=result_dir,
            show=show,
            save=save,
        ),
        "product_group": analyze_product_group_color(
            data,
            color_col=color_col,
            min_group_rows=product_min_group_rows,
            min_cell_count=product_min_cell_count,
            plot_top_n_groups=8,
            plot_top_n_colors=plot_top_n,
            result_dir=result_dir,
            show=show,
            save=save,
        ),
    }
    return results


if __name__ == "__main__":
    outputs = run_all_analyses(show=False, save=True)
    print("\n전체 분석 완료")
    for name, result in outputs.items():
        print(f"- {name}: {result['metadata']['rows_used'] if 'rows_used' in result['metadata'] else '완료'}")
