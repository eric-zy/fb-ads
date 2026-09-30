from datetime import date

from api.connector_callbacks_insights import _upsert_account_insights
from models import AccountInsight, AdAccount
from core.tenant import tenant_scope


def test_connector_account_insights_are_upserted_into_canonical_table(db):
    account = AdAccount(
        id="connector-insight-account",
        tenant_id="test_tenant",
        account_id="act_connector_insight",
        account_name="Connector Insight",
        currency="USD",
    )
    db.add(account)
    db.flush()

    payload = [{
        "date_start": "2026-09-29",
        "spend": "12.34",
        "impressions": "1000",
        "clicks": "25",
        "actions": [{"action_type": "purchase", "value": "2"}],
        "action_values": [{"action_type": "purchase", "value": "30.00"}],
    }]

    with tenant_scope("test_tenant"):
        assert _upsert_account_insights(db, account, payload) == 1
        db.commit()

    row = db.query(AccountInsight).filter(
        AccountInsight.ad_account_id == account.id,
        AccountInsight.date == date(2026, 9, 29),
    ).one()
    assert row.spend == 1234
    assert row.impressions == 1000
    assert row.clicks == 25
    assert row.purchases == 2
    assert row.conversion_value == 3000

    payload[0]["spend"] = "20.00"
    with tenant_scope("test_tenant"):
        assert _upsert_account_insights(db, account, payload) == 1
        db.commit()
    assert db.query(AccountInsight).filter(AccountInsight.ad_account_id == account.id).count() == 1
    assert db.query(AccountInsight).filter(AccountInsight.ad_account_id == account.id).one().spend == 2000
