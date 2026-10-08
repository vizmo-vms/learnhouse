import json
import logging
import re
import secrets
import string
import uuid
from datetime import datetime, timedelta
from typing import Optional

import redis
from fastapi import HTTPException, Request
from pydantic import EmailStr
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from config.config import get_learnhouse_config
from src.db.organization_config import OrganizationConfig
from src.db.organizations import Organization, OrganizationRead
from src.db.usergroups import UserGroup
from src.db.users import AnonymousUser, PublicUser, UserRead
from src.services.orgs.orgs import (
    get_org_default_language,
    rbac_check,
    resolve_org_sender_name,
)
from src.services.users.emails import send_invitation_email

logger = logging.getLogger(__name__)

_redis_pool: Optional[redis.ConnectionPool] = None

def _get_redis(redis_conn_string: str) -> redis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool.from_url(redis_conn_string, max_connections=10)
    return redis.Redis(connection_pool=_redis_pool)


# Lua script: atomically count existing org invite codes and add a new one if
# the per-org limit has not been reached.  Runs as a single atomic unit on the
# Redis server, eliminating the check-then-set race condition.
#
# KEYS[1] = glob pattern for existing codes   (e.g. "org_invite_code_*:org:<uuid>:code:*")
# KEYS[2] = the new key to write
# ARGV[1] = JSON value to store
# ARGV[2] = TTL in seconds
# ARGV[3] = maximum number of codes allowed
#
# Returns 1 on success, 0 when the limit is already reached.
_LUA_ATOMIC_INVITE = (
    "local pattern = KEYS[1]\n"
    "local new_key = KEYS[2]\n"
    "local new_value = ARGV[1]\n"
    "local ttl = tonumber(ARGV[2])\n"
    "local max_codes = tonumber(ARGV[3])\n"
    "local existing = redis.call('KEYS', pattern)\n"
    "if #existing >= max_codes then\n"
    "    return 0\n"
    "end\n"
    "redis.call('SET', new_key, new_value, 'EX', ttl)\n"
    "return 1\n"
)


async def create_invite_code(
    request: Request,
    org_id: int,
    current_user: PublicUser | AnonymousUser,
    db_session: AsyncSession,
    usergroup_id: Optional[int] = None,
):
    # Every visitor to the shared demo holds admin on it, so without this an
    # invite code minted there is a way for anyone to have the platform email
    # arbitrary strangers on our domain. This is the abuse vector the demo
    # would otherwise open, and it is blocked at the service rather than in
    # the UI for that reason.
    from src.services.demo.guards import require_not_demo_org

    await require_not_demo_org(org_id, db_session)

    # Redis init
    LH_CONFIG = get_learnhouse_config()
    redis_conn_string = LH_CONFIG.redis_config.redis_connection_string

    if not redis_conn_string:
        raise HTTPException(
            status_code=500,
            detail="Redis connection string not found",
        )

    statement = select(Organization).where(Organization.id == org_id)
    org = (await db_session.execute(statement)).scalars().first()

    if not org:
        raise HTTPException(
            status_code=404,
            detail="Organization not found",
        )

    # RBAC check
    await rbac_check(request, org.org_uuid, current_user, "update", db_session)

    # Free-tier abuse gate: shareable invite links are a self-service member
    # onboarding primitive, so a free org (and the acting user) must be at
    # least FREE_TIER_MIN_AGE_DAYS old before minting one. Paid orgs exempt.
    from src.security.auth import resolve_acting_user_id
    from src.services.security.account_age import enforce_free_tier_age_gate

    await enforce_free_tier_age_gate(
        org_id, resolve_acting_user_id(current_user), db_session,
        action="create invite links",
    )

    # Connect to Redis
    r = _get_redis(redis_conn_string)

    if not r:
        raise HTTPException(
            status_code=500,
            detail="Could not connect to Redis",
        )

    # Validate usergroup exists if provided
    if usergroup_id is not None:
        statement = select(UserGroup).where(
            UserGroup.id == usergroup_id,
            UserGroup.org_id == org_id,
        )
        usergroup = (await db_session.execute(statement)).scalars().first()
        if not usergroup:
            raise HTTPException(
                status_code=404,
                detail="UserGroup not found or does not belong to this organization",
            )

    # Generate invite code using cryptographically secure random
    def generate_code(length=8):
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    generated_invite_code = generate_code()
    invite_code_uuid = f"org_invite_code_{uuid.uuid4()}"

    # time to live in days to seconds
    ttl = int(timedelta(days=365).total_seconds())

    inviteCodeObject = {
        "invite_code": generated_invite_code,
        "invite_code_uuid": invite_code_uuid,
        "invite_code_expires": ttl,
        "invite_code_type": "signup",
        "created_at": datetime.now().isoformat(),
        "created_by": current_user.user_uuid,
    }

    if usergroup_id is not None:
        inviteCodeObject["usergroup_id"] = usergroup_id

    new_invite_key = f"{invite_code_uuid}:org:{org.org_uuid}:code:{generated_invite_code}"
    invite_value = json.dumps(inviteCodeObject)

    # Atomically check the per-org code limit and write the new key.
    # _LUA_ATOMIC_INVITE returns 0 when the limit is reached, 1 on success.
    result = r.eval(  # type: ignore[attr-defined]
        _LUA_ATOMIC_INVITE,
        2,
        f"org_invite_code_*:org:{org.org_uuid}:code:*",
        new_invite_key,
        invite_value,
        str(ttl),
        "6",
    )

    if result == 0:
        raise HTTPException(
            status_code=400,
            detail="Maximum number of invite codes reached",
        )

    return inviteCodeObject


async def get_invite_codes(
    request: Request,
    org_id: int,
    current_user: PublicUser | AnonymousUser,
    db_session: AsyncSession,
):
    # Redis init
    LH_CONFIG = get_learnhouse_config()
    redis_conn_string = LH_CONFIG.redis_config.redis_connection_string

    if not redis_conn_string:
        raise HTTPException(
            status_code=500,
            detail="Redis connection string not found",
        )

    statement = select(Organization).where(Organization.id == org_id)
    org = (await db_session.execute(statement)).scalars().first()

    if not org:
        raise HTTPException(
            status_code=404,
            detail="Organization not found",
        )

    # RBAC check
    await rbac_check(request, org.org_uuid, current_user, "update", db_session)

    # Connect to Redis
    r = _get_redis(redis_conn_string)

    if not r:
        raise HTTPException(
            status_code=500,
            detail="Could not connect to Redis",
        )

    # Get invite codes (use scan_iter to avoid blocking Redis)
    invite_codes = list(r.scan_iter(match=f"org_invite_code_*:org:{org.org_uuid}:code:*", count=100))

    invite_codes_list = []

    for invite_code in invite_codes:  # type: ignore
        invite_code = r.get(invite_code)
        # The key may have expired between scan_iter() and get() (codes carry a
        # TTL). r.get() then returns None and json.loads(None) raises TypeError,
        # crashing the whole listing with a 500. Skip vanished keys instead.
        if invite_code is None:
            continue
        invite_code = json.loads(invite_code)  # type: ignore

        # Enrich with usergroup name if linked
        if invite_code.get("usergroup_id"):
            statement = select(UserGroup).where(
                UserGroup.id == invite_code["usergroup_id"]
            )
            usergroup = (await db_session.execute(statement)).scalars().first()
            invite_code["usergroup_name"] = usergroup.name if usergroup else None

        invite_codes_list.append(invite_code)

    return invite_codes_list


async def get_invite_code(
    request: Request,
    org_id: int,
    invite_code: str,
    current_user: PublicUser | AnonymousUser,
    db_session: AsyncSession,
):
    # Redis init
    LH_CONFIG = get_learnhouse_config()
    redis_conn_string = LH_CONFIG.redis_config.redis_connection_string

    if not redis_conn_string:
        raise HTTPException(
            status_code=500,
            detail="Redis connection string not found",
        )

    statement = select(Organization).where(Organization.id == org_id)
    org = (await db_session.execute(statement)).scalars().first()

    if not org:
        raise HTTPException(
            status_code=404,
            detail="Organization not found",
        )

    # RBAC check - verify user has permission to view invite codes for this org
    await rbac_check(request, org.org_uuid, current_user, "read", db_session)

    # Connect to Redis
    r = _get_redis(redis_conn_string)

    if not r:
        raise HTTPException(
            status_code=500,
            detail="Could not connect to Redis",
        )

    # SECURITY: Validate invite code is alphanumeric to prevent Redis wildcard injection
    if not invite_code.isalnum():
        raise HTTPException(
            status_code=404,
            detail="Invite code not found",
        )

    # Get invite code (use scan_iter to avoid blocking Redis)
    matched_key = None
    for key in r.scan_iter(match=f"org_invite_code_*:org:{org.org_uuid}:code:{invite_code}", count=10):
        matched_key = key
        break

    if not matched_key:
        raise HTTPException(
            status_code=404,
            detail="Invite code not found",
        )

    invite_code_value = r.get(matched_key)
    if not invite_code_value:
        raise HTTPException(status_code=404, detail="Invite code not found")
    invite_code_data = json.loads(invite_code_value)

    return invite_code_data


async def resolve_org_invitation(request, org, email, invite_code, current_user, db_session, *, existing_member=False):
    """Resolve a shared code or the code attached to an email invitation.

    Email invitations store a code UUID, not a group ID. Resolve that UUID in
    this organization only, even on subsequent logins, so retries can finish
    group assignment after a partial onboarding failure.
    """
    optional_pending = existing_member and not invite_code
    code_data = None
    if invite_code:
        code_data = await get_invite_code(request, org.id, invite_code, current_user, db_session)
        if not code_data:
            raise HTTPException(status_code=400, detail="Invite code is incorrect")

    pending_key = None
    redis_url = get_learnhouse_config().redis_config.redis_connection_string
    if redis_url:
        r = None
        try:
            r = redis.Redis.from_url(redis_url)
            key = f"invited_user:{email}:org:{org.org_uuid}"
            raw = r.get(key)
            invitation = json.loads(raw) if raw else None
            if invitation and invitation.get("pending") is True:
                code_uuid = invitation.get("invite_code_uuid")
                # A shared link for a different group must not consume an
                # unrelated email invitation whose mapping was not applied.
                applies_email_code = not code_data or not code_uuid or code_data.get("invite_code_uuid") == code_uuid
                if invitation.get("pending") is True and applies_email_code:
                    pending_key = key
                if code_uuid and not code_data:
                    if not re.fullmatch(r"org_invite_code_[0-9a-fA-F-]{36}", code_uuid):
                        raise HTTPException(status_code=403, detail="Your invitation is no longer valid. Please request a new invite.")
                    for code_key in r.scan_iter(match=f"{code_uuid}:org:{org.org_uuid}:code:*", count=10):
                        value = r.get(code_key)
                        if value:
                            code_data = json.loads(value)
                            break
                    if not code_data:
                        raise HTTPException(status_code=403, detail="Your invite code has expired or been removed. Please request a new invite.")
        except HTTPException:
            if optional_pending:
                return None, None
            raise
        except Exception:
            if optional_pending:
                logger.warning("Could not inspect optional invitation for an existing member")
                return None, None
            logger.exception("Could not resolve organization invitation")
            raise HTTPException(status_code=503, detail="Could not verify your invitation right now, please try again.")

        finally:
            if r is not None:
                try:
                    r.close()
                except Exception:
                    logger.warning("Could not close invitation Redis connection")

    if code_data and code_data.get("usergroup_id"):
        group = (await db_session.execute(select(UserGroup).where(
            UserGroup.id == int(code_data["usergroup_id"]), UserGroup.org_id == org.id,
        ))).scalars().first()
        if not group:
            if optional_pending:
                return None, None
            raise HTTPException(status_code=403, detail="The group attached to your invitation is no longer available. Please request a new invite.")
    return code_data, pending_key


def mark_org_invitation_accepted(key: str) -> None:
    r = None
    try:
        redis_url = get_learnhouse_config().redis_config.redis_connection_string
        if redis_url:
            r = redis.Redis.from_url(redis_url)
            raw = r.get(key)
            if raw:
                invitation = json.loads(raw)
                invitation["pending"] = False
                # Never extend or remove an invitation's expiry.
                r.set(key, json.dumps(invitation), xx=True, keepttl=True)
    except Exception:
        logger.exception("Could not mark invitation as accepted")
    finally:
        if r is not None:
            r.close()


async def delete_invite_code(
    request: Request,
    org_id: int,
    invite_code_uuid: str,
    current_user: PublicUser | AnonymousUser,
    db_session: AsyncSession,
):
    # Redis init
    LH_CONFIG = get_learnhouse_config()
    redis_conn_string = LH_CONFIG.redis_config.redis_connection_string

    if not redis_conn_string:
        raise HTTPException(
            status_code=500,
            detail="Redis connection string not found",
        )

    statement = select(Organization).where(Organization.id == org_id)
    org = (await db_session.execute(statement)).scalars().first()

    if not org:
        raise HTTPException(
            status_code=404,
            detail="Organization not found",
        )

    # RBAC check
    await rbac_check(request, org.org_uuid, current_user, "update", db_session)

    # Connect to Redis
    r = _get_redis(redis_conn_string)

    if not r:
        raise HTTPException(
            status_code=500,
            detail="Could not connect to Redis",
        )

    # SECURITY: the UUID is interpolated into a Redis SCAN glob pattern. Without
    # validation an admin could pass wildcard characters (e.g. "*") to match —
    # and delete — every invite code key for the org in a single call, instead
    # of the one resource the endpoint is meant to address. Restrict to the
    # exact "org_invite_code_<uuid4>" shape this codebase generates.
    if not re.fullmatch(r"org_invite_code_[0-9a-fA-F-]{36}", invite_code_uuid):
        raise HTTPException(
            status_code=404,
            detail="Invite code not found",
        )

    # Delete invite code (use scan_iter to avoid blocking Redis)
    keys = list(r.scan_iter(match=f"{invite_code_uuid}:org:{org.org_uuid}:code:*", count=10))
    if keys:
        r.delete(*keys)

    if not keys:
        raise HTTPException(
            status_code=404,
            detail="Invite code not found",
        )

    return keys


async def send_invite_email(
    org: OrganizationRead,
    invite_code_uuid: str | None,
    user: UserRead,
    email: EmailStr,
    request: Request,
    db_session=None,
):
    invite_code = None

    # Look up the invite code from Redis if a UUID was provided
    if invite_code_uuid:
        LH_CONFIG = get_learnhouse_config()
        redis_conn_string = LH_CONFIG.redis_config.redis_connection_string

        if redis_conn_string:
            r = _get_redis(redis_conn_string)
            matched = list(r.scan_iter(match=f"{invite_code_uuid}:org:{org.org_uuid}:code:*", count=10))  # type: ignore
            if matched:
                data = r.get(matched[0])
                if data:
                    invite_code = json.loads(data).get("invite_code")

    # Build signup URL rooted at the org's own frontend subdomain (or primary
    # verified custom domain if one is configured — passing db_session opts in).
    from src.services.email.utils import get_org_signup_base_url
    org_base_url = await get_org_signup_base_url(
        org.slug, request, db_session=db_session, org_id=org.id
    )

    if invite_code:
        signup_url = f"{org_base_url}/signup?inviteCode={invite_code}"
    else:
        signup_url = f"{org_base_url}/signup"

    lang = "en"
    sender_name = ""
    if db_session is not None:
        try:
            org_config_stmt = select(OrganizationConfig).where(OrganizationConfig.org_id == org.id)
            org_config = (await db_session.execute(org_config_stmt)).scalars().first()
            lang = get_org_default_language(org_config)
            sender_name = resolve_org_sender_name(org_config)
        except Exception:
            pass

    try:
        # Defense in depth: scrub any link out of the inviter's display name
        # before it is relayed to recipients, even if it slipped past
        # write-time validation (e.g. imported via OAuth).
        from src.services.security.profile_validation import sanitize_display_name

        result = send_invitation_email(
            email=email,
            org_name=sanitize_display_name(org.name, fallback="A LearnHouse organization"),
            inviter_username=sanitize_display_name(user.username),
            invite_code=invite_code,
            signup_url=signup_url,
            lang=lang,
            sender_name=sender_name,
        )
        return result is not None
    except Exception:
        logger.exception("Failed to send invite email to %s", email)
        return False
