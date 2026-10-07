"""Freshness comes from completed report windows, never asset metadata."""
from datetime import datetime, timedelta
from models.report_sync import ReportSyncRun


def report_quality(db, account, start, end, level="account"):
    runs = db.query(ReportSyncRun).filter(
        ReportSyncRun.account_id == account.id,
        ReportSyncRun.status == "SUCCESS",
        ReportSyncRun.start_date <= end,
        ReportSyncRun.end_date >= start,
    ).order_by(ReportSyncRun.finished_at.desc()).all()
    days = {}
    for run in runs:
        if level not in (run.snapshots or {}):
            continue
        day = max(start, run.start_date)
        while day <= min(end, run.end_date):
            if day not in days:
                days[day] = run.finished_at
            day += timedelta(days=1)
    expected = (end - start).days + 1
    timestamps = [value for value in days.values() if value]
    # The oldest covered day determines freshness for the requested window.
    stamp = min(timestamps) if timestamps else None
    age = max((datetime.utcnow() - stamp).total_seconds() / 3600, 0) if stamp else None
    status = "NEVER" if not days else "INCOMPLETE" if len(days) < expected else "FRESH" if age is not None and age <= 3 else "STALE"
    current = str(account.insights_sync_status or "NEVER").upper()
    if current in {"FAILED", "PENDING", "SYNCING"}:
        status = current
    return {"status": status, "latest_synced_at": stamp.isoformat() if stamp else None,
            "age_hours": round(age, 1) if age is not None else None,
            "covered_days": len(days), "expected_days": expected,
            "complete": len(days) == expected, "error": account.insights_last_sync_error}
