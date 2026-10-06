"""Fetch only credential summaries referenced by the current tenant context."""
from models import AdAccount, MetaAccount, MetaPage
from services.fb_connector_client import FBConnectorClient, FBConnectorError

SUMMARY_FIELDS = {"id", "app_id", "meta_user_id", "token_type", "status", "health", "scopes",
                  "expires_at", "last_error", "last_synced_at"}


def connector_references(db):
    businesses = {row.id: row for row in db.query(MetaAccount).all()}
    refs = {}
    def add(tenant_id, credential_id, kind, entity_id):
        if not credential_id:
            return
        item = refs.setdefault((tenant_id, credential_id), {"tenant_id": tenant_id, "id": credential_id,
                               "business_ids": [], "account_ids": [], "page_ids": []})
        if entity_id not in item[kind]:
            item[kind].append(entity_id)
    for row in businesses.values():
        add(row.tenant_id, row.connector_credential_id, "business_ids", row.id)
    for row in db.query(AdAccount).all():
        business = businesses.get(row.business_id)
        add(row.tenant_id, row.connector_credential_id or getattr(business, "connector_credential_id", None), "account_ids", row.id)
    for row in db.query(MetaPage).all():
        add(row.tenant_id, row.connector_credential_id, "page_ids", row.id)
    return list(refs.values())


def connector_health_rows(db):
    refs = connector_references(db)
    credential_ids = sorted({item["id"] for item in refs})
    summaries = {}
    for start in range(0, len(credential_ids), 100):
        batch = credential_ids[start:start + 100]
        try:
            result = FBConnectorClient().credential_health(batch)
            summaries.update({item["id"]: {key: value for key, value in item.items() if key in SUMMARY_FIELDS}
                              for item in result.get("items", []) if item.get("id") in batch})
        except FBConnectorError:
            summaries.update({key: {"id": key, "status": "UNKNOWN", "health": "UNAVAILABLE",
                                   "last_error": "海外凭据健康检查暂不可用"} for key in batch})
    for item in refs:
        summary = summaries.get(item["id"], {})
        if item["business_ids"] and summary.get("health") in {"ACTIVE", "EXPIRING"} and "business_management" not in summary.get("scopes", []):
            summary["health"] = "PERMISSION_MISSING"
    return [{**item, **summaries.get(item["id"], {"status": "UNKNOWN", "health": "MISSING"}),
             "source": "CONNECTOR", "token_type": summaries.get(item["id"], {}).get("token_type", "USER"),
             "business_count": len(item["business_ids"]), "account_count": len(item["account_ids"]),
             "page_count": len(item["page_ids"]), "credential_count": 1,
             "meta_account_id": next(iter(item["business_ids"]), None)} for item in refs]
