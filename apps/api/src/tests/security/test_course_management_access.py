"""Management permissions must bypass learner groups without crossing tenants."""

from unittest.mock import patch

import pytest
from sqlmodel import select

from src.db.courses.activities import ActivityRead
from src.db.courses.courses import CourseCreate
from src.db.courses.chapters import ChapterRead
from src.db.roles import Role, RoleTypeEnum
from src.db.user_organizations import UserOrganization
from src.db.usergroup_resources import UserGroupResource
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup
from src.db.users import APITokenUser
from src.security.rbac import AccessAction, AccessContext
from src.security.rbac.resource_access import ResourceAccessChecker
from src.services.courses.activities.activities import _apply_activity_lock
from src.services.courses.chapters import _apply_locks_to_chapters
from src.services.courses.courses import (
    create_course,
    get_course_user_rights,
    get_courses_count_orgslug,
    get_courses_orgslug,
    search_courses,
)
from src.tests.conftest import ADMIN_RIGHTS, USER_RIGHTS


async def assign_role(db, user, org, *, kind="manager"):
    rights = USER_RIGHTS.model_dump()
    rights["dashboard"]["action_access"] = kind != "learner"
    rights["courses"]["action_create"] = kind != "learner"
    rights["courses"]["action_update"] = kind in {"manager", "maintainer"}
    rights["courses"]["action_update_own"] = kind == "instructor"
    role = Role(
        id=2 if kind == "maintainer" else 10,
        name=kind,
        org_id=None if kind == "maintainer" else org.id,
        role_type=RoleTypeEnum.TYPE_GLOBAL if kind == "maintainer" else RoleTypeEnum.TYPE_ORGANIZATION,
        role_uuid=f"role_{kind}",
        rights=rights,
    )
    db.add(role)
    membership = (await db.execute(select(UserOrganization).where(
        UserOrganization.user_id == user.id,
        UserOrganization.org_id == org.id,
    ))).scalars().one()
    membership.role_id = role.id
    db.add(membership)
    await db.commit()


async def restrict_course(db, org, course, user=None):
    course.public = False
    db.add(course)
    group = UserGroup(name="Other Department", description="", org_id=org.id)
    db.add(group)
    await db.flush()
    db.add(UserGroupResource(
        resource_uuid=course.course_uuid, org_id=org.id, usergroup_id=group.id,
    ))
    if user:
        db.add(UserGroupUser(user_id=user.id, org_id=org.id, usergroup_id=group.id))
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["manager", "maintainer"])
async def test_managers_list_count_search_and_read_other_department_courses(
    db, org, course, regular_user, mock_request, kind,
):
    await assign_role(db, regular_user, org, kind=kind)
    await restrict_course(db, org, course)
    for include_unpublished in (False, True):
        result = await get_courses_orgslug(
            mock_request, regular_user, org.slug, db, include_unpublished=include_unpublished,
        )
        assert [c.course_uuid for c in result] == [course.course_uuid]
    assert await get_courses_count_orgslug(mock_request, regular_user, org.slug, db) == 1
    assert len(await search_courses(mock_request, regular_user, org.slug, "Test", db)) == 1
    for context in (AccessContext.DASHBOARD, AccessContext.PUBLIC_VIEW):
        decision = await ResourceAccessChecker(mock_request, db, regular_user).check_access(
            course.course_uuid, AccessAction.READ, context,
        )
        assert decision.allowed


@pytest.mark.asyncio
async def test_manager_dashboard_includes_drafts_but_catalog_does_not(
    db, org, course, regular_user, mock_request,
):
    await assign_role(db, regular_user, org)
    await restrict_course(db, org, course)
    course.published = False
    db.add(course)
    await db.commit()
    assert await get_courses_orgslug(mock_request, regular_user, org.slug, db) == []
    assert len(await get_courses_orgslug(
        mock_request, regular_user, org.slug, db, include_unpublished=True,
    )) == 1
    decision = await ResourceAccessChecker(mock_request, db, regular_user).check_access(
        course.course_uuid, AccessAction.READ, AccessContext.DASHBOARD,
    )
    assert decision.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["learner", "instructor"])
async def test_read_or_own_only_permissions_do_not_bypass_groups(
    db, org, course, regular_user, mock_request, kind,
):
    await assign_role(db, regular_user, org, kind=kind)
    await restrict_course(db, org, course)
    assert await get_courses_orgslug(
        mock_request, regular_user, org.slug, db, include_unpublished=True,
    ) == []
    assert await get_courses_count_orgslug(mock_request, regular_user, org.slug, db) == 0
    assert await search_courses(mock_request, regular_user, org.slug, "Test", db) == []
    decision = await ResourceAccessChecker(mock_request, db, regular_user).check_access(
        course.course_uuid, AccessAction.READ, AccessContext.DASHBOARD,
    )
    assert not decision.allowed


@pytest.mark.asyncio
async def test_learner_keeps_assigned_group_access(db, org, course, regular_user, mock_request):
    await restrict_course(db, org, course, regular_user)
    assert len(await get_courses_orgslug(mock_request, regular_user, org.slug, db)) == 1


@pytest.mark.asyncio
async def test_manager_permissions_are_scoped_to_the_course_org(
    db, org, other_org, course, regular_user, mock_request,
):
    await assign_role(db, regular_user, org)
    course.org_id = other_org.id
    db.add(course)
    await db.commit()
    await restrict_course(db, other_org, course)
    # Even membership in the second org must not carry the first org's role.
    db.add(UserOrganization(
        user_id=regular_user.id, org_id=other_org.id, role_id=4,
        creation_date="", update_date="",
    ))
    await db.commit()
    assert await get_courses_orgslug(
        mock_request, regular_user, other_org.slug, db, include_unpublished=True,
    ) == []
    assert await get_courses_count_orgslug(mock_request, regular_user, other_org.slug, db) == 0
    assert await search_courses(mock_request, regular_user, other_org.slug, "Test", db) == []
    decision = await ResourceAccessChecker(mock_request, db, regular_user).check_access(
        course.course_uuid, AccessAction.READ, AccessContext.DASHBOARD,
    )
    assert not decision.allowed


@pytest.mark.asyncio
async def test_manager_can_edit_without_getting_delete_permission(
    db, org, course, regular_user, mock_request,
):
    await assign_role(db, regular_user, org)
    await restrict_course(db, org, course)
    rights = await get_course_user_rights(mock_request, course.course_uuid, regular_user, db)
    assert rights["permissions"]["update"]
    assert rights["permissions"]["create_content"]
    assert rights["permissions"]["update_content"]
    assert not rights["permissions"]["delete"]
    assert not rights["permissions"]["delete_content"]
    checker = ResourceAccessChecker(mock_request, db, regular_user)
    assert (await checker.check_access(course.course_uuid, AccessAction.UPDATE)).allowed
    assert not (await checker.check_access(course.course_uuid, AccessAction.DELETE)).allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,locked", [("manager", False), ("maintainer", False), ("learner", True)])
async def test_manager_editor_retains_locked_activity_content(
    db, org, course, chapter, activity, regular_user, kind, locked,
):
    await assign_role(db, regular_user, org, kind=kind)
    chapter.lock_type = "restricted"
    activity.lock_type = "restricted"
    db.add(chapter)
    db.add(activity)
    await db.commit()
    read = ActivityRead.model_validate(activity)
    await _apply_activity_lock(read, activity, course, regular_user, db, parent_chapter=chapter)
    assert read.is_locked == locked
    assert bool(read.content) == (not locked)


@pytest.mark.asyncio
async def test_manager_access_still_enforces_org_auth_policy(
    db, org, course, regular_user, mock_request,
):
    from fastapi import HTTPException
    await assign_role(db, regular_user, org)
    with patch("src.services.orgs.auth_policy.enforce_org_auth_policy", side_effect=HTTPException(403, "Google required")):
        with pytest.raises(HTTPException):
            await ResourceAccessChecker(mock_request, db, regular_user).check_access(
                course.course_uuid, AccessAction.READ, AccessContext.DASHBOARD,
            )


@pytest.mark.asyncio
async def test_admin_in_another_org_does_not_grant_manager_delete_rights(
    db, org, other_org, course, regular_user, mock_request,
):
    await assign_role(db, regular_user, org)
    db.add(Role(
        id=1, name="Admin", org_id=None, role_type=RoleTypeEnum.TYPE_GLOBAL,
        role_uuid="role_global_admin", rights=ADMIN_RIGHTS.model_dump(),
    ))
    db.add(UserOrganization(
        user_id=regular_user.id, org_id=other_org.id, role_id=1,
        creation_date="", update_date="",
    ))
    await db.commit()
    rights = await get_course_user_rights(mock_request, course.course_uuid, regular_user, db)
    assert rights["permissions"]["update"]
    assert not rights["permissions"]["delete"]
    assert not rights["permissions"]["delete_content"]
    assert not (await ResourceAccessChecker(mock_request, db, regular_user).check_access(
        course.course_uuid, AccessAction.DELETE,
    )).allowed


async def collection_read(operation, request, user, slug, db):
    if operation == "list":
        return await get_courses_orgslug(request, user, slug, db, include_unpublished=True)
    if operation == "count":
        return await get_courses_count_orgslug(request, user, slug, db)
    return await search_courses(request, user, slug, "Test", db)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "count", "search"])
@pytest.mark.parametrize("policy", ["auth_policy.enforce_org_auth_policy", "mfa_policy.enforce_org_mfa_policy"])
async def test_manager_collections_enforce_session_policies(
    db, org, regular_user, mock_request, operation, policy,
):
    from fastapi import HTTPException
    await assign_role(db, regular_user, org)
    with patch(f"src.services.orgs.{policy}", side_effect=HTTPException(403, "Session blocked")):
        with pytest.raises(HTTPException):
            await collection_read(operation, mock_request, regular_user, org.slug, db)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "count", "search"])
async def test_manager_creator_token_without_read_cannot_list_courses(
    db, org, regular_user, mock_request, operation,
):
    from fastapi import HTTPException
    await assign_role(db, regular_user, org)
    token = APITokenUser(org_id=org.id, created_by_user_id=regular_user.id, rights={
        "courses": {"action_read": False, "action_update": True},
    })
    with pytest.raises(HTTPException):
        await collection_read(operation, mock_request, token, org.slug, db)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "count", "search"])
async def test_token_cannot_use_creator_membership_to_cross_orgs(
    db, org, other_org, regular_user, mock_request, operation,
):
    from fastapi import HTTPException
    await assign_role(db, regular_user, org)
    token = APITokenUser(org_id=other_org.id, created_by_user_id=regular_user.id, rights={
        "courses": {"action_read": True, "action_update": True},
    })
    with pytest.raises(HTTPException):
        await collection_read(operation, mock_request, token, org.slug, db)


@pytest.mark.asyncio
@pytest.mark.parametrize("write", [False, True])
async def test_tokens_use_own_management_grants_for_collections_and_locks(
    db, org, course, chapter, activity, regular_user, mock_request, write,
):
    await assign_role(db, regular_user, org)
    await restrict_course(db, org, course)
    token = APITokenUser(org_id=org.id, created_by_user_id=regular_user.id, rights={
        "courses": {"action_read": True, "action_update": write, "action_delete": False},
    })
    courses = await get_courses_orgslug(mock_request, token, org.slug, db, include_unpublished=True)
    assert len(courses) == int(write)
    chapter.lock_type = "restricted"
    read = ActivityRead.model_validate(activity)
    await _apply_activity_lock(read, activity, course, token, db, parent_chapter=chapter)
    assert read.is_locked == (not write)
    rights = await get_course_user_rights(mock_request, course.course_uuid, token, db)
    assert rights["permissions"]["update"] == write
    assert not rights["permissions"]["delete"]


@pytest.mark.asyncio
async def test_manager_can_see_restricted_chapter_and_activity_in_course_tree(
    db, org, course, chapter, activity, regular_user,
):
    await assign_role(db, regular_user, org)
    chapter.lock_type = "restricted"
    activity.lock_type = "restricted"
    read = ChapterRead.model_validate({**chapter.model_dump(), "activities": [activity]})
    await _apply_locks_to_chapters([read], course, regular_user, db)
    assert not read.is_locked
    assert not read.activities[0].is_locked
    assert read.activities[0].content == activity.content


@pytest.mark.asyncio
async def test_manager_in_one_org_cannot_create_courses_as_learner_in_another(
    db, org, other_org, regular_user, mock_request,
):
    from fastapi import HTTPException
    await assign_role(db, regular_user, org)
    db.add(UserOrganization(
        user_id=regular_user.id, org_id=other_org.id, role_id=4,
        creation_date="", update_date="",
    ))
    await db.commit()
    with pytest.raises(HTTPException):
        await create_course(mock_request, other_org.id, CourseCreate(
            name="Unauthorized", description="", org_id=other_org.id,
            public=False, published=False, open_to_contributors=False,
        ), regular_user, db)
