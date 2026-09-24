from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from fb_connector.tasks import (
    _confirm_pending_delivery_objects,
    _pending_remote_candidates,
    _pending_remote_match,
    _reconcile_pending_delivery_objects,
)
from fb_connector.api.campaigns import _pending_reconcile_results
from services.meta.errors import MetaApiError


class _Session:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


class _Service:
    def __init__(self, *, campaigns=None, adsets=None, creatives=None, ads=None):
        self.campaigns = campaigns or []
        self.adsets = adsets or []
        self.creatives = creatives or []
        self.ads = ads or []

    def list_campaigns(self, account_id):
        return self.campaigns

    def list_adsets(self, campaign_id):
        return self.adsets

    def list_ads(self, adset_id):
        return self.ads

    def list_creatives(self, account_id):
        return self.creatives


def _submitted_at():
    return (datetime.utcnow() - timedelta(seconds=10)).isoformat() + "Z"


def test_pending_remote_match_requires_unique_recent_exact_name():
    pending = {"name": "campaign-a", "submitted_at": _submitted_at()}
    candidate = {
        "id": "cmp-1",
        "name": "campaign-a",
        "created_time": datetime.utcnow().isoformat() + "Z",
    }

    assert _pending_remote_match([candidate], pending) == ("cmp-1", 1)
    assert _pending_remote_match([candidate, {**candidate, "id": "cmp-2"}], pending) == (None, 2)


def test_pending_remote_candidates_excludes_old_same_name_object():
    pending = {"name": "campaign-a", "submitted_at": _submitted_at()}
    old = {
        "id": "cmp-old",
        "name": "campaign-a",
        "created_time": (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z",
    }

    assert _pending_remote_candidates([old], pending) == []


def test_reconcile_pending_campaign_updates_row_and_clears_marker():
    row = SimpleNamespace(
        task_id="task-1",
        campaign_id=None,
        objects={
            "pending": [
                {
                    "group": "campaign",
                    "client_key": None,
                    "name": "campaign-a",
                    "submitted_at": _submitted_at(),
                }
            ]
        },
        updated_at=None,
    )
    service = _Service(
        campaigns=[
            {
                "id": "cmp-1",
                "name": "campaign-a",
                "created_time": datetime.utcnow().isoformat() + "Z",
            }
        ]
    )

    session = _Session()
    _reconcile_pending_delivery_objects(session, row, service, "act-1")

    assert row.campaign_id == "cmp-1"
    assert row.objects["pending"] == []
    assert session.commits == 1


def test_reconcile_pending_creative_stops_without_guessing():
    row = SimpleNamespace(
        task_id="task-2",
        campaign_id="cmp-1",
        objects={
            "pending": [
                {
                    "group": "creatives",
                    "client_key": "creative-1",
                    "name": "creative-a",
                    "parent_id": "adset-1",
                    "submitted_at": _submitted_at(),
                }
            ]
        },
        updated_at=None,
    )

    _reconcile_pending_delivery_objects(
        _Session(),
        row,
        _Service(
            creatives=[
                {
                    "id": "creative-1",
                    "name": "creative-a",
                    "created_time": datetime.utcnow().isoformat() + "Z",
                }
            ]
        ),
        "act-1",
    )
    assert row.objects["creatives"][0]["id"] == "creative-1"
    assert row.objects["pending"] == []


def test_reconcile_pending_creative_stops_when_no_candidate():
    row = SimpleNamespace(
        task_id="task-3",
        campaign_id="cmp-1",
        objects={
            "pending": [
                {
                    "group": "creatives",
                    "client_key": "creative-1",
                    "name": "creative-a",
                    "parent_id": "act-1",
                    "submitted_at": _submitted_at(),
                }
            ]
        },
        updated_at=None,
    )

    with pytest.raises(MetaApiError, match="RECONCILE_REQUIRED"):
        _reconcile_pending_delivery_objects(_Session(), row, _Service(), "act-1")


def test_confirm_pending_object_requires_candidate_and_clears_only_selected_item():
    row = SimpleNamespace(
        task_id="task-4",
        campaign_id=None,
        objects={
            "pending": [
                {
                    "group": "campaign",
                    "client_key": None,
                    "name": "campaign-a",
                    "submitted_at": _submitted_at(),
                },
                {
                    "group": "creatives",
                    "client_key": "creative-1",
                    "name": "creative-a",
                    "parent_id": "act-1",
                    "submitted_at": _submitted_at(),
                },
            ]
        },
        updated_at=None,
    )
    service = _Service(
        campaigns=[
            {
                "id": "cmp-1",
                "name": "campaign-a",
                "created_time": datetime.utcnow().isoformat() + "Z",
            }
        ],
        creatives=[
            {
                "id": "creative-1",
                "name": "creative-a",
                "created_time": datetime.utcnow().isoformat() + "Z",
            }
        ],
    )

    _confirm_pending_delivery_objects(
        _Session(),
        row,
        service,
        "act-1",
        [{"group": "campaign", "client_key": None, "object_id": "cmp-1"}],
    )

    assert row.campaign_id == "cmp-1"
    assert len(row.objects["pending"]) == 1
    assert row.objects["pending"][0]["group"] == "creatives"


def test_pending_reconcile_results_keeps_remaining_candidates_normalized():
    row = SimpleNamespace(
        account_id="act-1",
        objects={
            "pending": [
                {
                    "group": "campaign",
                    "client_key": None,
                    "name": "campaign-a",
                    "submitted_at": _submitted_at(),
                }
            ]
        },
    )
    results = _pending_reconcile_results(
        row,
        _Service(
            campaigns=[
                {
                    "id": "cmp-1",
                    "name": "campaign-a",
                    "created_time": datetime.utcnow().isoformat() + "Z",
                    "status": "PAUSED",
                }
            ]
        ),
    )

    assert results[0]["can_auto_reconcile"] is True
    assert results[0]["candidates"] == [
        {
            "id": "cmp-1",
            "name": "campaign-a",
            "created_time": results[0]["candidates"][0]["created_time"],
            "status": "PAUSED",
        }
    ]
