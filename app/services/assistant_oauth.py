"""OAuthLib protocol validation with async persistence and opaque, hashed tokens.

Only preconfigured clients are supported. No DCR, arbitrary metadata fetches,
implicit grant, password grant or service-account superuser credentials.
"""
import base64
import hmac
import json
import re
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, unquote_plus
from uuid import UUID, uuid4

from oauthlib.oauth2 import RequestValidator, WebApplicationServer
from fastapi import HTTPException
from sqlalchemy import select

from app.core.assistant import SCOPES, connection_policy, digest, enabled, fail, issuer_url, now, project_policy, resource_url, user_policy
from app.core.config import settings
from app.models.assistant import AssistantCode, AssistantConnection, AssistantToken
from app.repositories.user_repository import UserRepository


def parameters(query):
    try: pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=25)
    except ValueError: fail("invalid_oauth_parameters", 400)
    if len(dict(pairs)) != len(pairs): fail("duplicate_oauth_parameter", 400)
    return dict(pairs)


def configured_client(client_id):
    try:
        clients = json.loads(settings.ASSISTANT_OAUTH_CLIENTS_JSON)
        client = clients.get(client_id)
        if not client or not isinstance(client.get("redirect_uris"), list): fail("invalid_client", 400)
        for uri in client["redirect_uris"]:
            p = urlsplit(uri)
            if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment: fail("invalid_client_config", 503)
        return client
    except (ValueError, AttributeError, TypeError): fail("oauth_not_configured", 503)


class Validator(RequestValidator):
    def __init__(self, client_id, client, connection=None, code=None, token=None):
        self.client_id, self.client, self.connection = client_id, client, connection
        self.code, self.token, self.saved_code, self.saved_token = code, token, None, None

    def validate_client_id(self, client_id, request, *args, **kwargs):
        return client_id == self.client_id

    def validate_redirect_uri(self, client_id, redirect_uri, request, *args, **kwargs):
        return client_id == self.client_id and redirect_uri in self.client["redirect_uris"]

    def get_default_redirect_uri(self, *args, **kwargs): return None
    def validate_response_type(self, client_id, response_type, request, *args, **kwargs): return response_type == "code"
    def get_default_scopes(self, *args, **kwargs): return ["crm.catalog.read"]
    def validate_scopes(self, client_id, scopes, request, *args, **kwargs):
        allowed = set(self.connection.scopes) if self.connection else SCOPES
        return bool(scopes) and set(scopes) <= allowed

    def is_pkce_required(self, *args, **kwargs): return True
    def save_authorization_code(self, client_id, code, request, *args, **kwargs): self.saved_code = code["code"]
    def client_authentication_required(self, request, *args, **kwargs): return bool(self.client.get("secret_sha256"))
    def authenticate_client(self, request, *args, **kwargs):
        try:
            header = request.headers.get("Authorization", "")
            scheme, value = header.split(" ", 1)
            if scheme.lower() != "basic": return False
            identity, secret = base64.b64decode(value, validate=True).decode().split(":", 1)
            valid = unquote_plus(identity) == self.client_id and hmac.compare_digest(digest(unquote_plus(secret)), self.client.get("secret_sha256", ""))
        except (ValueError, UnicodeError): return False
        if valid: request.client = SimpleNamespace(client_id=self.client_id)
        return valid

    def authenticate_client_id(self, client_id, request, *args, **kwargs):
        valid = client_id == self.client_id and not self.client.get("secret_sha256")
        if valid: request.client = SimpleNamespace(client_id=client_id)
        return valid

    def validate_grant_type(self, client_id, grant_type, request, *args, **kwargs):
        return client_id == self.client_id and grant_type in {"authorization_code", "refresh_token"}

    def validate_code(self, client_id, code, client, request, *args, **kwargs):
        valid = self.code is not None and not self.code.consumed_at and self.code.expires_at > now() and digest(code) == self.code.digest
        if valid:
            request.user = str(self.connection.user_id)
            request.scopes = self.connection.scopes
        return valid

    def confirm_redirect_uri(self, client_id, code, redirect_uri, client, *args, **kwargs):
        return self.code is not None and redirect_uri == self.code.redirect_uri

    def get_code_challenge(self, *args, **kwargs): return self.code.challenge if self.code else None
    def get_code_challenge_method(self, *args, **kwargs): return "S256"
    def invalidate_authorization_code(self, *args, **kwargs): pass  # Persisted after successful protocol validation, under the row lock.
    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        valid = self.token is not None and not self.token.revoked_at and not self.token.refresh_used_at and self.token.refresh_expires_at > now()
        if valid: request.user, request.scopes = str(self.connection.user_id), self.token.scopes
        return valid

    def get_original_scopes(self, *args, **kwargs): return self.token.scopes
    def is_within_original_scope(self, scopes, *args, **kwargs): return set(scopes) <= set(self.token.scopes)
    def rotate_refresh_token(self, request): return True
    def save_bearer_token(self, token, request, *args, **kwargs): self.saved_token = token


def server(validator): return WebApplicationServer(validator, token_expires_in=600)


def authorization_parameters(query):
    enabled(mcp=True)
    p = parameters(query)
    if p.get("resource") != resource_url(): fail("invalid_resource", 400)
    if p.get("code_challenge_method") != "S256" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", p.get("code_challenge", "")): fail("invalid_pkce", 400)
    if not p.get("state") or len(p["state"]) > 1024: fail("invalid_state", 400)
    validator = Validator(p.get("client_id"), configured_client(p.get("client_id")))
    uri = issuer_url() + "/authorize?" + query
    try:
        scopes, _ = server(validator).validate_authorization_request(uri)
    except Exception: fail("invalid_authorization_request", 400)
    if "crm.changes.prepare" in scopes: enabled(changes=True)
    return p, validator, scopes, uri


async def authorize(db, actor, data):
    user_policy(actor)
    p, validator, scopes, uri = authorization_parameters(data.authorization_query)
    ids = sorted(set(str(pid) for pid in data.project_ids))
    from app.models import Project
    for pid in ids:
        project_policy(actor, pid)
        project = await db.get(Project, UUID(pid))
        if not project or project.is_deleted or project.status != "active": fail("project_unavailable", 422)
    connection = AssistantConnection(id=uuid4(), user_id=actor.id, client_id=p["client_id"], resource=resource_url(), issuer=issuer_url(), project_ids=ids, scopes=scopes, policy_version=1)
    headers, _, status = server(validator).create_authorization_response(uri, scopes=scopes, credentials={"user": str(actor.id)})
    if status != 302 or not validator.saved_code: fail("authorization_failed", 400)
    db.add(connection)
    await db.flush()
    db.add(AssistantCode(digest=digest(validator.saved_code), connection_id=connection.id,
        redirect_uri=p["redirect_uri"], challenge=p["code_challenge"], expires_at=now() + timedelta(seconds=60)))
    from app.services.audit_service import AuditService
    for pid in ids:
        await AuditService(db).log(project_id=UUID(pid), actor_id=actor.id, action="assistant.connect",
            entity_type="assistant_connection", entity_id=connection.id, meta={"scopes": scopes})
    location = urlsplit(headers["Location"])
    # Issuer-bound callbacks protect against authorization-server mix-up.
    redirect = urlunsplit((location.scheme, location.netloc, location.path,
        location.query + "&" + urlencode({"iss": issuer_url()}), location.fragment))
    return {"redirect_uri": redirect}


async def exchange(db, body, headers):
    enabled(mcp=True)
    try: p = parameters(body)
    except HTTPException: return {"error": "invalid_request"}, 400
    if p.get("resource") != resource_url(): return {"error": "invalid_target"}, 400
    client_id = p.get("client_id")
    auth = headers.get("Authorization", "")
    if auth:
        try:
            scheme, value = auth.split(" ", 1)
            if scheme.lower() != "basic": raise ValueError()
            encoded_id, _ = base64.b64decode(value, validate=True).decode().split(":", 1)
            basic_id = unquote_plus(encoded_id)
            if client_id and client_id != basic_id: raise ValueError()
            client_id = basic_id
        except (ValueError, UnicodeError): return {"error": "invalid_client"}, 401
    try: client = configured_client(client_id)
    except HTTPException as exc:
        return ({"error": "temporarily_unavailable"}, 503) if exc.status_code == 503 else ({"error": "invalid_client"}, 401)
    if client.get("secret_sha256"):
        probe = SimpleNamespace(headers=headers)
        if not Validator(client_id, client).authenticate_client(probe): return {"error": "invalid_client"}, 401
    grant = p.get("grant_type")
    record = None
    if grant == "authorization_code":
        record = await db.scalar(select(AssistantCode).where(AssistantCode.digest == digest(p.get("code", ""))).with_for_update())
    elif grant == "refresh_token":
        record = await db.scalar(select(AssistantToken).where(AssistantToken.refresh_digest == digest(p.get("refresh_token", ""))).with_for_update())
    if record is None: return {"error": "invalid_grant"}, 400
    conn = await db.scalar(select(AssistantConnection).where(AssistantConnection.id == record.connection_id).with_for_update())
    if conn.client_id != client_id: return {"error": "invalid_grant"}, 400
    actor = await UserRepository(db).get_by_id(conn.user_id)
    try: connection_policy(actor, conn)
    except Exception: return {"error": "invalid_grant"}, 400
    # An already consumed refresh proves replay. Revoke the whole connection family.
    if grant == "refresh_token" and record.refresh_used_at:
        conn.revoked_at = now()
        await db.commit()
        return {"error": "invalid_grant"}, 400
    validator = Validator(client_id, client, conn, code=record if grant == "authorization_code" else None,
        token=record if grant == "refresh_token" else None)
    try:
        _, response, status = server(validator).create_token_response(issuer_url() + "/token", http_method="POST", body=body, headers=headers)
        result = json.loads(response)
    except Exception: return {"error": "invalid_request"}, 400
    if status != 200 or not validator.saved_token: return {"error": result.get("error", "invalid_grant")}, status
    if grant == "authorization_code": record.consumed_at = now()
    else: record.refresh_used_at, record.revoked_at = now(), now()
    refresh_end = conn.created_at + timedelta(days=7)
    if refresh_end <= now(): return {"error": "invalid_grant"}, 400
    db.add(AssistantToken(id=uuid4(), connection_id=conn.id, access_digest=digest(result["access_token"]),
        refresh_digest=digest(result["refresh_token"]), scopes=result["scope"].split(),
        expires_at=now() + timedelta(seconds=600), refresh_expires_at=refresh_end))
    await db.flush()
    return result, 200


async def authenticate(db, bearer):
    enabled(mcp=True)
    if not bearer or len(bearer) > 500: fail("unauthenticated", 401)
    token = await db.scalar(select(AssistantToken).where(AssistantToken.access_digest == digest(bearer)))
    if token is None or token.revoked_at or token.expires_at <= now(): fail("unauthenticated", 401)
    conn = await db.get(AssistantConnection, token.connection_id)
    actor = await UserRepository(db).get_by_id(conn.user_id) if conn else None
    if actor is None: fail("unauthenticated", 401)
    connection_policy(actor, conn)
    try: configured_client(conn.client_id)
    except Exception: fail("connection_revoked", 401)
    if conn.last_used_at is None or conn.last_used_at < now() - timedelta(minutes=1): conn.last_used_at = now()
    return actor, conn, set(token.scopes) & set(conn.scopes)
