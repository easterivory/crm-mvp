from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.postback import PostbackParameterMapping


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthorizeIn(StrictModel):
    authorization_query: str = Field(max_length=8192)
    project_ids: list[UUID] = Field(min_length=1, max_length=20)


class SecureInputIn(StrictModel):
    project_id: UUID
    value: str = Field(min_length=1, max_length=8192)


class Mapping(PostbackParameterMapping):
    model_config = ConfigDict(extra="forbid")


class OfferCreate(StrictModel):
    kind: Literal["offer.create_inactive"]
    name: str = Field(min_length=1, max_length=255)
    partner_name: str = Field(min_length=1, max_length=255)
    source_url_ref: UUID
    postbacks_enabled: bool = True
    identifier_parameter: str | None = Field(None, pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,99}$")
    postback_mapping: Mapping | None = None


class OfferUpdate(StrictModel):
    kind: Literal["offer.update_inactive"]
    offer_id: UUID
    name: str | None = Field(None, min_length=1, max_length=255)
    partner_name: str | None = Field(None, min_length=1, max_length=255)
    source_url_ref: UUID | None = None
    postbacks_enabled: bool | None = None
    identifier_parameter: str | None = Field(None, pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,99}$")
    postback_mapping: Mapping | None = None


class PostbackCreate(StrictModel):
    kind: Literal["postback.create_disabled"]
    name: str = Field(min_length=1, max_length=255)
    event_type: Literal["registration", "deposit", "redeposit"] = "registration"
    parameter_mapping: Mapping


class PostbackUpdate(StrictModel):
    kind: Literal["postback.update_disabled"]
    endpoint_id: UUID
    name: str | None = Field(None, min_length=1, max_length=255)
    event_type: Literal["registration", "deposit", "redeposit"] | None = None
    parameter_mapping: Mapping | None = None


class AssignOffer(StrictModel):
    kind: Literal["funnel.assign_offer_draft"]
    version_id: UUID
    offer_id: UUID


Operation = Annotated[OfferCreate | OfferUpdate | PostbackCreate | PostbackUpdate | AssignOffer, Field(discriminator="kind")]


class PrepareIn(StrictModel):
    project_id: UUID
    request_id: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    operations: list[Operation] = Field(min_length=1, max_length=5)
    supersedes_proposal_id: UUID | None = None


class ApprovalIn(StrictModel):
    expected_plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProjectQuery(StrictModel):
    project_id: UUID


class ListQuery(ProjectQuery):
    kind: Literal["bots", "tracking_links", "funnel_versions", "offers", "postback_endpoints"]
    cursor: str | None = Field(None, max_length=200)
    limit: int = Field(25, ge=1, le=100)


class ObjectQuery(ProjectQuery):
    kind: Literal["bot", "funnel_version", "offer", "postback_endpoint"]
    object_id: UUID


class TrackingQuery(ProjectQuery):
    date_from: date | None = None
    date_to: date | None = None
    bot_id: UUID | None = None
    link_id: UUID | None = None
    metric_ids: list[Literal["clicks", "starts", "leads", "submitted_leads", "registrations", "first_deposits", "redeposits", "channel_joins", "channel_leaves", "channel_join_requests"]] = Field(default_factory=lambda: ["starts", "leads", "registrations", "first_deposits", "redeposits"], min_length=1, max_length=10)


class DiagnosticsQuery(ProjectQuery):
    endpoint_id: UUID | None = None
    cursor: str | None = Field(None, max_length=200)
    limit: int = Field(25, ge=1, le=50)
    date_from: date | None = None
    date_to: date | None = None


class LeadQuery(ProjectQuery):
    lead_id: UUID


class ChangeQuery(ProjectQuery):
    proposal_id: UUID


class PreviewQuery(ProjectQuery):
    endpoint_id: UUID | None = None
    draft_contract: Mapping | None = None
    event_type: Literal["registration", "deposit", "redeposit"] = "registration"
    sample: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def one_contract(self):
        if (self.endpoint_id is None) == (self.draft_contract is None): raise ValueError("Select exactly one contract")
        return self
