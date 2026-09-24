"""广告系列层级列表分页回归测试。"""

from datetime import datetime

from api.campaigns import list_ads, list_adsets, list_campaigns
from models import AdInstance, AdSetInstance, CampaignInstance, User


def test_campaign_hierarchy_lists_return_page_metadata_and_slice(db):
    admin = User(
        id="campaign-page-admin",
        tenant_id="test_tenant",
        email="campaign-page-admin@test.local",
        username="campaign-page-admin",
        hashed_password="unused",
        role="tenant_admin",
        is_active=True,
    )
    db.add(admin)

    campaigns = [
        CampaignInstance(
            id=f"campaign-page-{index}",
            tenant_id="test_tenant",
            template_id="campaign-page-template",
            ad_account_id=f"campaign-page-account-{index}",
            meta_campaign_id=f"meta-{index}",
            name=f"Campaign {index}",
            created_at=datetime(2026, 1, index),
        )
        for index in range(1, 4)
    ]
    db.add_all(campaigns)
    db.flush()

    adsets = [
        AdSetInstance(
            id=f"adset-page-{index}",
            tenant_id="test_tenant",
            campaign_instance_id=campaigns[0].id,
            meta_adset_id=f"adset-meta-{index}",
            name=f"AdSet {index}",
            created_at=datetime(2026, 2, index),
        )
        for index in range(1, 4)
    ]
    db.add_all(adsets)
    db.flush()
    db.add_all([
        AdInstance(
            id=f"ad-page-{index}",
            tenant_id="test_tenant",
            adset_instance_id=adsets[0].id,
            meta_ad_id=f"ad-meta-{index}",
            name=f"Ad {index}",
            created_at=datetime(2026, 3, index),
        )
        for index in range(1, 4)
    ])
    db.commit()

    campaigns_page = list_campaigns(page=2, page_size=1, db=db, current_user=admin)
    assert campaigns_page["total"] == 3
    assert campaigns_page["page"] == 2
    assert len(campaigns_page["items"]) == 1

    adsets_page = list_adsets(campaigns[0].id, page=2, page_size=1, db=db, current_user=admin)
    assert adsets_page["total"] == 3
    assert len(adsets_page["items"]) == 1

    ads_page = list_ads(adsets[0].id, page=3, page_size=1, db=db, current_user=admin)
    assert ads_page["total"] == 3
    assert ads_page["items"][0]["name"] == "Ad 1"


def test_campaign_list_merges_same_template_campaigns_across_accounts(db):
    admin = User(
        id="campaign-merge-admin",
        tenant_id="test_tenant",
        email="campaign-merge-admin@test.local",
        username="campaign-merge-admin",
        hashed_password="unused",
        role="tenant_admin",
        is_active=True,
    )
    db.add(admin)
    db.add_all([
        CampaignInstance(
            id="campaign-merge-a",
            tenant_id="test_tenant",
            template_id="merge-template",
            ad_account_id="merge-account-a",
            meta_campaign_id="meta-merge-a",
            name="轮播图",
            created_at=datetime(2026, 4, 2),
        ),
        CampaignInstance(
            id="campaign-merge-b",
            tenant_id="test_tenant",
            template_id="merge-template",
            ad_account_id="merge-account-b",
            meta_campaign_id="meta-merge-b",
            name="轮播图",
            created_at=datetime(2026, 4, 1),
        ),
    ])
    db.commit()

    result = list_campaigns(db=db, current_user=admin)

    assert result["total"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["grouped"] is True
    assert result["items"][0]["grouped_ids"] == ["campaign-merge-a", "campaign-merge-b"]
    assert result["items"][0]["meta_campaign_ids"] == ["meta-merge-a", "meta-merge-b"]
