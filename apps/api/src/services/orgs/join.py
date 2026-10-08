from datetime import datetime
from typing import Optional, Union
from fastapi import HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from src.db.organizations import Organization
from src.db.user_organizations import UserOrganization
from src.db.users import AnonymousUser, InternalUser, PublicUser, User
from src.security.features_utils.usage import (
    check_limits_with_usage,
    increase_feature_usage,
)
from src.services.orgs.invites import resolve_org_invitation, mark_org_invitation_accepted
from src.services.orgs.join_notifications import notify_user_joined_org
from src.services.orgs.orgs import get_org_join_mechanism
from src.services.users.usergroups import add_users_to_usergroup


class JoinOrg(BaseModel):
    org_id: int
    user_id: Union[str, int]
    invite_code: Optional[str] = None

    @field_validator("user_id", mode="before")
    @classmethod
    def coerce_user_id_to_str(cls, v: Union[str, int]) -> str:
        return str(v)


async def join_org(
    request: Request,
    args: JoinOrg,
    current_user: PublicUser | AnonymousUser,
    db_session: AsyncSession,
):
    statement = select(Organization).where(Organization.id == args.org_id)
    org = (await db_session.execute(statement)).scalars().first()

    if not org or org.id is None:
        raise HTTPException(
            status_code=404,
            detail="Organization not found",
        )

    join_method = await get_org_join_mechanism(
        request, args.org_id, current_user, db_session
    )

    # Get User by UUID or numeric ID
    user_id_str = str(args.user_id)
    if user_id_str.isdigit():
        statement = select(User).where(
            (User.user_uuid == user_id_str) | (User.id == int(user_id_str))
        )
    else:
        statement = select(User).where(User.user_uuid == user_id_str)
    user = (await db_session.execute(statement)).scalars().first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    # SECURITY: a user may only join an organization as themselves. Without this
    # check, any authenticated caller could pass an arbitrary user_id in the
    # request body and force-join (or, in inviteOnly orgs, force-attach to a
    # usergroup) any other account — an IDOR / privilege-escalation flaw.
    if isinstance(current_user, AnonymousUser) or str(user.id) != str(current_user.id):
        raise HTTPException(
            status_code=403,
            detail="You can only join an organization as yourself.",
        )

    # Check if user's email is verified
    if not user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email address before joining an organization.",
        )

    from src.services.security.email_domains import enforce_allowed_email_domain, enforce_google_org_join
    enforce_allowed_email_domain(user.email)
    enforce_google_org_join()

    membership = (await db_session.execute(select(UserOrganization).where(
        UserOrganization.user_id == user.id, UserOrganization.org_id == org.id
    ))).scalars().first()
    code_data, pending_key = await resolve_org_invitation(
        request, org, user.email.strip().lower(), args.invite_code, current_user, db_session,
        existing_member=bool(membership),
    )
    if membership and not code_data:
        raise HTTPException(status_code=400, detail="User is already part of that organization")
    if not membership and join_method != "open" and not code_data and not pending_key:
        raise HTTPException(status_code=403, detail="You need an invite to join this organization")

    if not membership:
        await check_limits_with_usage("members", org.id, db_session)
        db_session.add(UserOrganization(
            user_id=user.id, org_id=org.id, role_id=4,
            creation_date=str(datetime.now()), update_date=str(datetime.now()),
        ))
        await db_session.commit()
        await increase_feature_usage("members", org.id, db_session)
        from src.routers.users import _invalidate_session_cache
        _invalidate_session_cache(user.id)
        await notify_user_joined_org(request, db_session, user, org.id, org=org)

    if code_data and code_data.get("usergroup_id"):
        await add_users_to_usergroup(
            request, db_session, InternalUser(id=0), int(code_data["usergroup_id"]), str(user.id)
        )
    if pending_key:
        mark_org_invitation_accepted(pending_key)
    return "Great, You're part of the Organization"
