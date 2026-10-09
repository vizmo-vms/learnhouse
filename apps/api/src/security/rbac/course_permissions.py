"""Organization-scoped permission to manage courses outside learner groups."""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi import HTTPException

from src.db.roles import Role, RoleTypeEnum
from src.db.user_organizations import UserOrganization
from src.db.users import AnonymousUser, APITokenUser, PublicUser
from src.security.rbac.constants import ADMIN_OR_MAINTAINER_ROLE_IDS
from src.security.superadmin import is_user_superadmin


async def can_manage_org_courses(user_id: int, org_id: int, db_session: AsyncSession) -> bool:
    """Admin/maintainer or an assigned role with update-all course permission.

    Read, create, and update-own permissions do not override learner groups.
    A role in another organization must never grant management access here.
    """
    if not user_id:
        return False
    if await is_user_superadmin(user_id, db_session):
        return True
    roles = (await db_session.execute(
        select(Role)
        .join(UserOrganization, UserOrganization.role_id == Role.id)
        .where(UserOrganization.user_id == user_id, UserOrganization.org_id == org_id)
        .where(
            (Role.org_id == org_id)
            | ((Role.org_id.is_(None)) & (Role.role_type == RoleTypeEnum.TYPE_GLOBAL))
        )
    )).scalars().all()
    for role in roles:
        if role.id in ADMIN_OR_MAINTAINER_ROLE_IDS:
            return True
        rights = role.rights.model_dump() if hasattr(role.rights, "model_dump") else role.rights
        if rights and (rights.get("courses") or {}).get("action_update") is True:
            return True
    return False


async def has_org_course_permission(current_user, org_id: int, action: str, db_session: AsyncSession) -> bool:
    """Check a general course permission against the actual target organization."""
    if isinstance(current_user, AnonymousUser):
        return False
    if isinstance(current_user, APITokenUser):
        if current_user.org_id != org_id:
            return False
        rights = current_user.rights
        rights = rights.model_dump() if hasattr(rights, "model_dump") else rights
        return bool(rights and (rights.get("courses") or {}).get(f"action_{action}") is True)
    if await is_user_superadmin(current_user.id, db_session):
        return True
    from src.security.rbac.rbac import _load_applicable_roles
    for role in await _load_applicable_roles(db_session, current_user.id, org_id):
        rights = role.rights.model_dump() if hasattr(role.rights, "model_dump") else role.rights
        if rights and (rights.get("courses") or {}).get(f"action_{action}") is True:
            return True
    return False


async def can_manage_courses(current_user, org_id: int, db_session: AsyncSession) -> bool:
    """Tokens use their own grants, never their creator's management role."""
    if isinstance(current_user, APITokenUser):
        return (
            await has_org_course_permission(current_user, org_id, "read", db_session)
            and await has_org_course_permission(current_user, org_id, "update", db_session)
        )
    if not isinstance(current_user, PublicUser):
        return False
    return await can_manage_org_courses(current_user.id, org_id, db_session)


async def check_course_collection_access(current_user, org_id: int, db_session: AsyncSession) -> bool:
    """Return management visibility after enforcing token or session restrictions."""
    if isinstance(current_user, APITokenUser):
        if not await has_org_course_permission(current_user, org_id, "read", db_session):
            raise HTTPException(403, "API token does not have course read access in this organization")
        return await can_manage_courses(current_user, org_id, db_session)
    managed = await can_manage_courses(current_user, org_id, db_session)
    if managed and not await is_user_superadmin(current_user.id, db_session):
        from src.security.org_auth import enforce_org_mfa
        await enforce_org_mfa(current_user.id, org_id, db_session)
    return managed
