"""Authorization helpers for tenant-shared campaign templates."""

from sqlalchemy import and_, exists, or_

from models import CampaignTemplate, TemplateCollaborator
from services.business_access import tenant_required


TEMPLATE_OWNER = "OWNER"
TEMPLATE_EDITOR = "EDITOR"
TEMPLATE_VIEWER = "VIEWER"
TEMPLATE_ADMIN = "ADMIN"
_EDIT_ROLES = {TEMPLATE_OWNER, TEMPLATE_EDITOR, TEMPLATE_ADMIN}


def template_query(query, user):
    """Scope a CampaignTemplate query to templates visible to ``user``.

    ``None`` is intentionally kept compatible with service-level tests and
    migration tooling, where tenant context already supplies the boundary.
    """

    query = query.filter(CampaignTemplate.tenant_id == tenant_required(user))
    if user is None or user.is_admin():
        return query

    shared = exists().where(
        and_(
            TemplateCollaborator.template_id == CampaignTemplate.id,
            TemplateCollaborator.tenant_id == CampaignTemplate.tenant_id,
            TemplateCollaborator.user_id == user.id,
            TemplateCollaborator.status == "ACTIVE",
        )
    )
    return query.filter(or_(CampaignTemplate.created_by == user.id, shared))


def template_access_level(db, template, user):
    """Return effective access level, or ``None`` when inaccessible."""

    if not template or user is None:
        return TEMPLATE_OWNER if template else None
    tenant_id = tenant_required(user)
    if template.tenant_id != tenant_id:
        return None
    if user.is_admin():
        return TEMPLATE_ADMIN
    if template.created_by == user.id:
        return TEMPLATE_OWNER
    row = db.query(TemplateCollaborator).filter(
        TemplateCollaborator.tenant_id == tenant_id,
        TemplateCollaborator.template_id == template.id,
        TemplateCollaborator.user_id == user.id,
        TemplateCollaborator.status == "ACTIVE",
    ).first()
    return row.role if row else None


def can_edit_template(db, template, user) -> bool:
    return template_access_level(db, template, user) in _EDIT_ROLES


def can_manage_template_access(db, template, user) -> bool:
    level = template_access_level(db, template, user)
    return level in {TEMPLATE_OWNER, TEMPLATE_ADMIN}
