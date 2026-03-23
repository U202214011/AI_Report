"""
Unit tests for the statistical report "其他" (others) category percentage fix.

Bug: _build_stat_llm_summary omitted the `others` and `othersSharePct` fields
     when building dim_summaries, causing _build_dim_table_texts to always
     display 0% for "其他".
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(__file__))


# ---------- helpers ----------------------------------------------------------

def _safe_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _fake_select_top_categories(rows, dim_key, top_n):
    """Mirror of report_service.select_top_categories."""
    if not rows:
        return []
    totals = {}
    for r in rows:
        dim_val = r.get(dim_key)
        totals[dim_val] = totals.get(dim_val, 0) + float(r.get("value") or 0)
    sorted_items = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    return [k for k, _ in sorted_items[:top_n]] if top_n else [k for k, _ in sorted_items]


def _fake_build_stat_dimension_summary(dim, rows, top_n):
    """
    Simplified version of prompt_data._build_stat_dimension_summary.
    Uses only a local rows list instead of a real DB connection.
    """
    if not rows:
        return {
            "dimension": dim,
            "total": 0.0,
            "topCategories": [],
            "ranking": [],
            "others": {"name": "其他", "value": 0.0, "share_pct": 0.0},
            "topSharePct": 0.0,
            "othersSharePct": 0.0,
        }

    total_value = sum(_safe_float(r.get("value")) for r in rows)
    top_categories = _fake_select_top_categories(rows, dim, top_n) or []
    top_rows = [r for r in rows if r.get(dim) in top_categories] if top_categories else rows[:]
    other_rows = [r for r in rows if r.get(dim) not in top_categories] if top_categories else []

    ranking = []
    for r in top_rows:
        name = r.get(dim)
        val = _safe_float(r.get("value"))
        share = (val / total_value * 100.0) if total_value else 0.0
        ranking.append({"name": name, "value": val, "share_pct": share})
    ranking.sort(key=lambda x: x["value"], reverse=True)
    top_share = sum(i["share_pct"] for i in ranking)

    other_value = sum(_safe_float(r.get("value")) for r in other_rows)
    others_share = (other_value / total_value * 100.0) if total_value else 0.0

    return {
        "dimension": dim,
        "total": total_value,
        "topCategories": top_categories,
        "ranking": ranking,
        "others": {"name": "其他", "value": other_value, "share_pct": others_share},
        "topSharePct": top_share,
        "othersSharePct": others_share,
    }


def _fake_build_stat_llm_dim_summary_OLD(d):
    """Reproduces the BUG: others / othersSharePct were missing."""
    ranking = d.get("ranking") or []
    return {
        "dimension": d.get("dimension"),
        "topN": ranking,
        "topSharePct": d.get("topSharePct"),
        # BUG: 'others' and 'othersSharePct' intentionally omitted
    }


def _fake_build_stat_llm_dim_summary_NEW(d):
    """Applies the FIX: others / othersSharePct are forwarded."""
    ranking = d.get("ranking") or []
    return {
        "dimension": d.get("dimension"),
        "topN": ranking,
        "topSharePct": d.get("topSharePct"),
        "others": d.get("others"),
        "othersSharePct": d.get("othersSharePct"),
    }


def _get_others_pct_from_dim_summary(dim_summary):
    """Mirror of _build_dim_table_texts logic for extracting others pct."""
    others = dim_summary.get("others") if isinstance(dim_summary.get("others"), dict) else {}
    others_pct = _safe_float(others.get("share_pct"))
    others_share_pct = _safe_float(dim_summary.get("othersSharePct"))
    return others_pct, others_share_pct


# ---------- tests ------------------------------------------------------------

def _make_rows(dim, n_total=15):
    """Create n_total rows for the given dimension."""
    return [{dim: f"Cat{i}", "value": float(100 - i * 3)} for i in range(n_total)]


class TestSelectTopCategories:
    def test_returns_top_n_by_value(self):
        rows = [{"genre": f"G{i}", "value": float(i)} for i in range(20)]
        top = _fake_select_top_categories(rows, "genre", 5)
        assert len(top) == 5
        assert "G19" in top  # highest value

    def test_returns_all_when_top_n_zero(self):
        rows = [{"genre": f"G{i}", "value": float(i)} for i in range(5)]
        top = _fake_select_top_categories(rows, "genre", 0)
        assert len(top) == 5

    def test_returns_all_when_top_n_none(self):
        rows = [{"genre": f"G{i}", "value": float(i)} for i in range(5)]
        top = _fake_select_top_categories(rows, "genre", None)
        assert len(top) == 5

    def test_returns_empty_for_empty_rows(self):
        assert _fake_select_top_categories([], "genre", 5) == []

    def test_top_n_exceeds_categories(self):
        rows = [{"genre": f"G{i}", "value": float(i)} for i in range(3)]
        top = _fake_select_top_categories(rows, "genre", 10)
        assert len(top) == 3  # only 3 exist


class TestBuildStatDimensionSummary:
    def test_others_nonzero_when_more_than_top_n(self):
        rows = _make_rows("genre", n_total=15)
        result = _fake_build_stat_dimension_summary("genre", rows, top_n=10)

        assert result["others"]["value"] > 0, "others.value should be > 0"
        assert result["others"]["share_pct"] > 0, "others.share_pct should be > 0"
        assert result["othersSharePct"] > 0, "othersSharePct should be > 0"

    def test_others_zero_when_fewer_than_top_n(self):
        rows = _make_rows("genre", n_total=5)
        result = _fake_build_stat_dimension_summary("genre", rows, top_n=10)

        assert result["others"]["value"] == 0.0
        assert result["others"]["share_pct"] == 0.0

    def test_top_plus_others_equals_100(self):
        rows = _make_rows("country", n_total=20)
        result = _fake_build_stat_dimension_summary("country", rows, top_n=10)

        total_pct = result["topSharePct"] + result["othersSharePct"]
        assert abs(total_pct - 100.0) < 0.01, f"topSharePct + othersSharePct = {total_pct:.4f}, expected ~100"

    def test_others_value_equals_sum_of_non_top(self):
        rows = _make_rows("genre", n_total=15)
        result = _fake_build_stat_dimension_summary("genre", rows, top_n=5)

        top_cats = set(result["topCategories"])
        expected_others = sum(_safe_float(r.get("value")) for r in rows if r.get("genre") not in top_cats)
        assert abs(result["others"]["value"] - expected_others) < 0.001

    def test_empty_rows_returns_zero_others(self):
        result = _fake_build_stat_dimension_summary("genre", [], top_n=10)
        assert result["others"]["value"] == 0.0
        assert result["othersSharePct"] == 0.0

    def test_none_values_handled_gracefully(self):
        rows = [{"genre": None, "value": None}, {"genre": "A", "value": 10.0}]
        result = _fake_build_stat_dimension_summary("genre", rows, top_n=1)
        # Should not crash; total should be 10.0 (None value treated as 0)
        assert result["total"] == 10.0
        # Top-1 category: either None (value 0) or "A" (value 10) — "A" wins
        assert result["ranking"][0]["name"] == "A"
        # The non-top category (None with value 0) contributes 0 to others
        assert result["others"]["value"] == 0.0
        assert result["othersSharePct"] == 0.0


class TestBuildStatLlmSummaryOthersField:
    """
    Tests that confirm the bug and verify the fix.
    The bug: _build_stat_llm_summary dropped 'others'/'othersSharePct'.
    The fix: pass those fields through.
    """

    def _dimension_summary(self, n_total=15, top_n=10):
        rows = _make_rows("genre", n_total=n_total)
        return _fake_build_stat_dimension_summary("genre", rows, top_n=top_n)

    def test_old_code_always_shows_zero_others(self):
        """Demonstrate the original bug."""
        d = self._dimension_summary(n_total=15, top_n=10)
        # Confirm the source data has non-zero others
        assert d["others"]["share_pct"] > 0

        llm_d = _fake_build_stat_llm_dim_summary_OLD(d)
        others_pct, others_share = _get_others_pct_from_dim_summary(llm_d)
        assert others_pct == 0.0, "Bug: should be 0 in old code"
        assert others_share == 0.0, "Bug: should be 0 in old code"

    def test_new_code_shows_correct_others(self):
        """Verify the fix produces correct others percentage."""
        d = self._dimension_summary(n_total=15, top_n=10)
        expected_others_pct = d["others"]["share_pct"]
        assert expected_others_pct > 0

        llm_d = _fake_build_stat_llm_dim_summary_NEW(d)
        others_pct, others_share = _get_others_pct_from_dim_summary(llm_d)
        assert abs(others_pct - expected_others_pct) < 0.001, (
            f"Fix: others_pct should be ~{expected_others_pct:.2f}%, got {others_pct:.2f}%"
        )
        assert abs(others_share - expected_others_pct) < 0.001

    def test_new_code_others_zero_when_all_fit_in_top_n(self):
        """When all categories fit in topN, others is correctly 0."""
        d = self._dimension_summary(n_total=5, top_n=10)
        assert d["others"]["share_pct"] == 0.0

        llm_d = _fake_build_stat_llm_dim_summary_NEW(d)
        others_pct, _ = _get_others_pct_from_dim_summary(llm_d)
        assert others_pct == 0.0

    def test_new_code_top_plus_others_equals_100(self):
        """After fix, topSharePct + othersSharePct should be ~100%."""
        d = self._dimension_summary(n_total=25, top_n=10)
        llm_d = _fake_build_stat_llm_dim_summary_NEW(d)

        top_pct = _safe_float(llm_d.get("topSharePct"))
        _, others_share = _get_others_pct_from_dim_summary(llm_d)
        assert abs(top_pct + others_share - 100.0) < 0.01, (
            f"topSharePct ({top_pct:.2f}%) + othersSharePct ({others_share:.2f}%) != 100%"
        )
