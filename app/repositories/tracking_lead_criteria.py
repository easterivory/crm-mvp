"""Shared lead qualification, independent of attribution and date-window rules."""
from sqlalchemy import String, and_, cast, func, or_, select

from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.project import Project
from app.models.tag import Tag


def tracking_lead_criterion(status_codes):
    tagged = select(LeadTag.lead_id).join(Tag, Tag.id == LeadTag.tag_id).where(
        LeadTag.lead_id == Lead.id,
        Tag.project_id == Lead.project_id,
        Project.tracking_lead_tag_ids.op("@>")(func.jsonb_build_array(cast(LeadTag.tag_id, String))),
    ).correlate(Lead, Project).exists()
    return select(Project.id).where(
        Project.id == Lead.project_id,
        or_(
            and_(Project.tracking_lead_count_mode == "statuses", LeadStatus.code.in_(status_codes)),
            and_(Project.tracking_lead_count_mode == "tags", tagged),
        ),
    ).correlate(Lead, LeadStatus).exists()
