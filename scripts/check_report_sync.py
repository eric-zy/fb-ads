"""Read-only report acceptance checks using the domestic deploy/.env endpoint."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from decimal import Decimal
import getpass
import json
import os
from pathlib import Path
import sys

import requests
from dotenv import dotenv_values


ENV_FILE = Path(__file__).resolve().parents[1] / "deploy" / ".env"
FIELDS = ("spend", "impressions", "clicks", "conversions")
LEVELS = ("account", "campaign", "adset", "ad")


def domestic_url(env_file=ENV_FILE):
    # Read the file directly: a shell FRONTEND_BASE_URL must not override it.
    base = str(dotenv_values(env_file).get("FRONTEND_BASE_URL") or "").rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ValueError("deploy/.env 中缺少有效的 FRONTEND_BASE_URL")
    return base


def selected_window(days, start=None, end=None):
    if bool(start) != bool(end):
        raise ValueError("开始日期和结束日期必须同时提供")
    end = date.fromisoformat(end) if end else date.today()
    start = date.fromisoformat(start) if start else end - timedelta(days=days - 1)
    if start > end or (end - start).days >= 90:
        raise ValueError("日期范围必须为 1 至 90 天（含起止日期）")
    return str(start), str(end), (end - start).days + 1


class ReportVerifier:
    def __init__(self, session, base, start, end, days):
        self.session, self.base = session, base
        self.dates = {"start_date": start, "end_date": end, "days": days}
        self.checks = []

    def check(self, name, ok, detail, *, warning=False):
        self.checks.append({"name": name, "status": "PASS" if ok else "WARN" if warning else "FAIL", "detail": detail})

    def get(self, path, **params):
        # No sync/create/update endpoint is called by this verifier.
        response = self.session.get(self.base + "/api/v1/" + path, params={**self.dates, **params}, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"{path}: HTTP {response.status_code}（检查部署版本、登录或账户权限）")
        try:
            value = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{path}: 返回非 JSON，检查 Nginx API 代理") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"{path}: 返回结构不符合报表协议")
        return value

    def date_contract(self, data, name):
        expected = (self.dates["start_date"], self.dates["end_date"])
        actual = (data.get("start_date"), data.get("end_date"))
        self.check(name + ".dates", actual == expected,
                   "起止日期已生效" if actual == expected else "接口未确认所选起止日期；可能仍是旧版 API，不能据此验收自定义日期")
        return actual == expected

    @staticmethod
    def metrics_equal(left, right):
        for field in FIELDS:
            a, b = Decimal(str(left.get(field) or 0)), Decimal(str(right.get(field) or 0))
            if abs(a - b) > (Decimal("0.000001") if field == "spend" else 0):
                return False
        return True

    def run(self, account_id=None):
        overview = self.get("reports/account-overview")
        self.date_contract(overview, "account-overview")
        accounts = [item for item in overview.get("items", []) if not account_id or item.get("account_id") == account_id]
        self.check("visible-accounts", bool(accounts), f"本次检查 {len(accounts)} 个可见账户")
        breakdowns = {}
        for level in LEVELS:
            data = self.get("reports/breakdown", dimension=level)
            breakdowns[level] = data
            self.date_contract(data, level + ".breakdown")
        results = []
        for item in accounts:
            key, name = item["account_id"], item.get("account_name") or item["account_id"]
            levels = {}
            for level, data in breakdowns.items():
                quality = next((value for value in data.get("data_quality", []) if value.get("account_id") == key), None)
                if level == "account":
                    quality = item.get("data_quality")
                if quality is None:
                    self.check(f"{name}.{level}.coverage", False, "无该层级对象或覆盖信息，不能确认该层级已同步", warning=True)
                    levels[level] = {"status": "UNKNOWN"}
                    continue
                levels[level] = {field: quality.get(field) for field in ("status", "covered_days", "expected_days", "complete", "latest_synced_at")}
                complete = (quality.get("complete") is True and quality.get("expected_days") == self.dates["days"]
                            and quality.get("covered_days") == self.dates["days"])
                self.check(f"{name}.{level}.coverage", complete,
                           f"覆盖 {quality.get('covered_days')}/{quality.get('expected_days')} 天；{quality.get('status', 'UNKNOWN')}")
                healthy = quality.get("status") not in {"FAILED", "PENDING", "SYNCING"}
                self.check(f"{name}.{level}.state", healthy, "采集无活动失败或待完成状态" if healthy else "需检查采集任务状态与服务器日志")
            trend = self.get("reports/trend", dimension="account", entity_id=key)
            if self.date_contract(trend, name + ".trend"):
                inside = all(self.dates["start_date"] <= row.get("date", "") <= self.dates["end_date"] for row in trend.get("series", []))
                self.check(name + ".trend.rows", inside, "趋势日期不超出所选范围" if inside else "趋势包含所选范围外的数据")
                self.check(name + ".trend.metrics", self.metrics_equal(item, trend.get("total", {})), "趋势汇总与账户总览核对")
            summary = self.get("workbench/summary", account_id=key)
            self.check(name + ".workbench.dates", summary.get("range") == {field: self.dates[field] for field in ("start_date", "end_date")}, "工作台起止日期核对")
            total = next((value for value in summary.get("currency_totals", []) if value.get("currency") == item.get("currency")), {})
            self.check(name + ".workbench.metrics", self.metrics_equal(item, total), "工作台与账户总览消耗、展示、点击、转化核对（币种独立）")
            results.append({"account_id": key, "account_name": name, "currency": item.get("currency"),
                            "metrics": {field: item.get(field) for field in FIELDS}, "levels": levels})
        return {"range": {key: self.dates[key] for key in ("start_date", "end_date")}, "accounts": results,
                "checks": self.checks, "passed": bool(accounts) and not any(check["status"] == "FAIL" for check in self.checks),
                "note": "只验收本地报表协议、覆盖和统计一致性；不证明 Meta 后台金额或归因口径一致。完整空报表允许为零。"}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", help="测试登录账号；密码交互输入，不写在命令行")
    parser.add_argument("--days", type=int, choices=range(1, 91), default=3, metavar="1-90")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--account-id", help="可选，本地账户主键")
    parser.add_argument("--output", type=Path, help="可选，保存不含凭据或原始快照的 JSON 结果")
    args = parser.parse_args()
    try:
        start, end, days = selected_window(args.days, args.start_date, args.end_date)
        base = domestic_url()
        with requests.Session() as session:
            token = os.environ.get("REPORT_VERIFY_TOKEN")
            if not token:
                username = args.username or input("测试账号：").strip()
                response = session.post(base + "/api/v1/auth/login", json={"username": username, "password": getpass.getpass("密码：")}, timeout=15)
                if response.status_code != 200:
                    raise RuntimeError(f"登录失败：HTTP {response.status_code}")
                token = response.json().get("access_token")
                if not token:
                    raise RuntimeError("登录返回缺少 access_token")
            session.headers["Authorization"] = "Bearer " + token
            result = ReportVerifier(session, base, start, end, days).run(args.account_id)
        for check in result["checks"]:
            print(f"[{check['status']}] {check['name']}: {check['detail']}")
        print(result["note"])
        if args.output:
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0 if result["passed"] else 2
    except (requests.RequestException, RuntimeError, ValueError, OSError) as exc:
        # Network exception strings can contain URLs or proxy credentials.
        detail = "网络请求失败，请检查服务器和代理连接" if isinstance(exc, requests.RequestException) else str(exc) if isinstance(exc, RuntimeError) else "日期、配置或结果文件无效，请检查参数及 deploy/.env"
        print(f"[ERROR] {detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
