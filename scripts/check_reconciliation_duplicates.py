"""Fail-fast check for duplicate local Meta object mappings before migration."""

from sqlalchemy import func

from core.database import SessionLocal
from models import AdInstance, AdSetInstance


def _duplicate_rows(db, model, group_columns):
    columns = [getattr(model, name) for name in group_columns]
    return (
        db.query(*columns, func.count(model.id).label("row_count"))
        .filter(*[column.isnot(None) for column in columns[1:]])
        .group_by(*columns)
        .having(func.count(model.id) > 1)
        .all()
    )


def main() -> int:
    db = SessionLocal()
    try:
        checks = (
            (
                "adset_instances",
                AdSetInstance,
                ("campaign_instance_id", "meta_adset_id"),
            ),
            (
                "ad_instances",
                AdInstance,
                ("adset_instance_id", "meta_ad_id"),
            ),
        )
        duplicates = []
        for table_name, model, columns in checks:
            for row in _duplicate_rows(db, model, columns):
                values = {
                    column: row._mapping[column]
                    for column in columns
                }
                values["row_count"] = row._mapping["row_count"]
                duplicates.append({"table": table_name, **values})

        if duplicates:
            print("[reconciliation-check] duplicate local Meta mappings detected")
            for item in duplicates:
                print(f"[reconciliation-check] {item}")
            print(
                "[reconciliation-check] stop deployment; resolve duplicate mappings "
                "before applying 0063_reconciliation_idempotency"
            )
            return 1

        print("[reconciliation-check] no duplicate local Meta mappings")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
