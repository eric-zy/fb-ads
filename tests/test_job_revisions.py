from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.jobs import discard_job_revision, update_job_revision, RevisionUpdateRequest
from models import CampaignJobRevision


def _user():
    return SimpleNamespace(
        id="revision-user",
        tenant_id="test_tenant",
        is_platform_admin=lambda: False,
    )


def test_discard_revision_keeps_audit_record(db):
    revision = CampaignJobRevision(
        id="revision-draft-1",
        tenant_id="test_tenant",
        base_job_id="source-job-1",
        version=1,
        status="DRAFT",
        source="DIRECT",
        account_ids=["account-1"],
        snapshot={"base": {"name": "old"}, "current": {"name": "new"}},
        diff=[{"path": "name", "before": "old", "after": "new"}],
        created_by="revision-user",
    )
    db.add(revision)
    db.commit()

    result = discard_job_revision(revision.id, db, _user())

    assert result["status"] == "DISCARDED"
    persisted = db.query(CampaignJobRevision).filter(CampaignJobRevision.id == revision.id).one()
    assert persisted.status == "DISCARDED"
    assert persisted.diff == [{"path": "name", "before": "old", "after": "new"}]


def test_discarded_revision_cannot_be_modified(db):
    revision = CampaignJobRevision(
        id="revision-discarded-1",
        tenant_id="test_tenant",
        base_job_id="source-job-2",
        version=1,
        status="DISCARDED",
        snapshot={"base": {"name": "old"}, "current": {"name": "new"}},
        created_by="revision-user",
    )
    db.add(revision)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        update_job_revision(
            revision.id,
            RevisionUpdateRequest(snapshot={"name": "another"}),
            db,
            _user(),
        )

    assert exc.value.status_code == 409


def test_discard_revision_is_tenant_scoped(db):
    revision = CampaignJobRevision(
        id="revision-other-tenant",
        tenant_id="other-tenant",
        base_job_id="source-job-3",
        version=1,
        status="READY",
        snapshot={"base": {}, "current": {}},
        created_by="other-user",
    )
    db.add(revision)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        discard_job_revision(revision.id, db, _user())

    assert exc.value.status_code == 404
