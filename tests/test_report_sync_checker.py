from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts.check_report_sync import ReportVerifier, domestic_url, selected_window


START, END = "2026-09-08", "2026-10-07"


class ReportSession:
    def __init__(self, *, empty=False, covered=30, legacy=False, mismatch=False, active=False):
        self.calls = []
        self.legacy = legacy
        self.mismatch = mismatch
        self.quality = {"account_id": "account-a", "complete": covered == 30, "expected_days": 30,
                        "covered_days": covered, "status": "SYNCING" if active else "FRESH" if covered == 30 else "INCOMPLETE"}
        self.item = {"account_id": "account-a", "account_name": "Account A", "currency": "USD", "spend": 0 if empty else 0.01,
                     "impressions": 0 if empty else 4, "clicks": 0, "conversions": 0, "data_quality": self.quality}

    def get(self, url, *, params, timeout):
        self.calls.append((url, params))
        dates = {} if self.legacy else {"start_date": START, "end_date": END}
        if url.endswith("/account-overview"):
            value = {"start_date": START, "end_date": END, "items": [self.item]}
        elif url.endswith("/breakdown"):
            value = {**dates, "items": [], "data_quality": [self.quality]}
        elif url.endswith("/trend"):
            value = {**dates, "total": self.item, "series": [{"date": START, **self.item}]}
        elif url.endswith("/summary"):
            total = {**self.item, "spend": 9 if self.mismatch else self.item["spend"]}
            value = {"range": {"start_date": START, "end_date": END}, "currency_totals": [total]}
        else:
            raise AssertionError(url)
        return SimpleNamespace(status_code=200, json=lambda: deepcopy(value))


def run(**kwargs):
    session = ReportSession(**kwargs)
    result = ReportVerifier(session, "https://domestic.example", START, END, 30).run()
    assert len(session.calls) == 7
    assert all(params["start_date"] == START and params["end_date"] == END for _, params in session.calls)
    assert not any("/sync" in url for url, _ in session.calls)
    return result


@pytest.mark.parametrize("empty", [False, True])
def test_complete_reports_and_complete_empty_snapshots_pass(empty):
    result = run(empty=empty)
    assert result["passed"] is True
    assert all(row["status"] == "PASS" for row in result["checks"])
    assert result["accounts"][0]["levels"]["ad"]["covered_days"] == 30


def test_recent_three_days_cannot_pass_30_day_acceptance():
    result = run(covered=3)
    assert result["passed"] is False
    assert len([row for row in result["checks"] if row["name"].endswith("coverage") and row["status"] == "FAIL"]) == 4


def test_legacy_api_ignoring_custom_dates_is_detected_even_when_totals_match():
    result = run(legacy=True)
    assert result["passed"] is False
    assert len([row for row in result["checks"] if row["name"].endswith(".dates") and row["status"] == "FAIL"]) == 5


def test_workbench_mismatch_is_failure():
    result = run(mismatch=True)
    assert result["passed"] is False
    assert next(row for row in result["checks"] if row["name"] == "Account A.workbench.metrics")["status"] == "FAIL"


def test_active_sync_does_not_pass_despite_prior_complete_coverage():
    result = run(active=True)
    assert result["passed"] is False


def test_domestic_url_uses_deploy_file_instead_of_shell_override(tmp_path, monkeypatch):
    config = tmp_path / "deployment.env"
    config.write_text("FRONTEND_BASE_URL=http://domestic.local:8094\n", encoding="utf-8")
    monkeypatch.setenv("FRONTEND_BASE_URL", "http://wrong.local")
    assert domestic_url(config) == "http://domestic.local:8094"


@pytest.mark.parametrize("start,end", [(START, None), (None, END), (END, START), ("2026-01-01", "2026-04-01")])
def test_invalid_or_partial_window_is_rejected(start, end):
    with pytest.raises(ValueError):
        selected_window(3, start, end)


def test_90_day_inclusive_boundary():
    assert selected_window(3, "2026-01-01", "2026-03-31") == ("2026-01-01", "2026-03-31", 90)


def test_non_json_proxy_response_does_not_pass_as_report():
    def invalid():
        raise ValueError("HTML")
    session = SimpleNamespace(get=lambda *args, **kwargs: SimpleNamespace(status_code=200, json=invalid))
    with pytest.raises(RuntimeError, match="非 JSON"):
        ReportVerifier(session, "https://domestic.example", START, END, 30).run()


def test_one_cent_mismatch_cannot_be_hidden_by_money_tolerance():
    assert not ReportVerifier.metrics_equal({"spend": 0.01}, {"spend": 0})
    assert ReportVerifier.metrics_equal({"spend": 0.30000000000000004}, {"spend": 0.3})


def test_missing_visible_account_cannot_be_reported_as_success():
    session = ReportSession()
    result = ReportVerifier(session, "https://domestic.example", START, END, 30).run("not-assigned")
    assert result["passed"] is False
    assert result["accounts"] == []


def test_http_permission_failure_is_visible_without_exposing_body():
    session = SimpleNamespace(get=lambda *args, **kwargs: SimpleNamespace(status_code=403, text="private-data"))
    with pytest.raises(RuntimeError, match="HTTP 403") as exc:
        ReportVerifier(session, "https://domestic.example", START, END, 30).run()
    assert "private-data" not in str(exc.value)
