"""Boundary checks for the Vizmo customizations on LearnHouse 1.4.0."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.db.users import APITokenUser, SuperadminAPITokenUser
from src.routers import analytics, audit
from src.security.org_auth import require_org_create_permission
from src.security.rbac.course_permissions import (
    can_manage_courses,
    check_course_collection_access,
    has_org_course_permission,
)
from src.services.ai.rag.access import build_rag_access_scope, readable_activity_ids
from src.services.courses.courses import get_course_user_rights
from src.tests.security.test_course_management_access import assign_role, restrict_course


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["manager", "maintainer"])
async def test_managers_keep_ai_access_to_other_department_locked_drafts(
    db, org, course, chapter, activity, regular_user, mock_request, kind,
):
    await assign_role(db, regular_user, org, kind=kind)
    await restrict_course(db, org, course)
    chapter.lock_type = "restricted"
    activity.lock_type = "restricted"
    activity.published = False
    db.add(chapter)
    db.add(activity)
    await db.commit()
    scope = await build_rag_access_scope(mock_request, regular_user, org.id, db, course)
    assert scope.courses[course.id].is_admin
    assert await readable_activity_ids([activity.id], scope, db) == {activity.id}


@pytest.mark.asyncio
async def test_learner_ai_cannot_read_other_department_content(
    db, org, course, regular_user, mock_request,
):
    await restrict_course(db, org, course)
    with pytest.raises(HTTPException):
        await build_rag_access_scope(mock_request, regular_user, org.id, db, course)


@pytest.mark.asyncio
async def test_superadmin_token_never_uses_token_id_as_a_human(
    db, org, course, regular_user, mock_request,
):
    # Token id deliberately collides with a non-admin user id; creator id 0 is
    # not an anonymous principal and must not send this through human RBAC.
    token = SuperadminAPITokenUser(id=regular_user.id)
    with patch("src.security.rbac.course_permissions.is_user_superadmin", side_effect=AssertionError("human lookup")):
        assert await has_org_course_permission(token, org.id, "create", db)
        assert await can_manage_courses(token, org.id, db)
        assert await check_course_collection_access(token, org.id, db)
    with patch("src.security.org_auth.require_org_role_permission", side_effect=AssertionError("human lookup")):
        await require_org_create_permission(token, org.id, db, "courses")
    rights = await get_course_user_rights(mock_request, course.course_uuid, token, db)
    assert not rights["is_anonymous"]
    assert all(rights["permissions"][action] for action in ("read", "create", "update", "delete"))


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["overview", "audit"])
@pytest.mark.parametrize("granted", [False, True])
async def test_employee_reports_require_tokens_own_admin_grant(
    org, admin_user, mock_request, surface, granted,
):
    token = APITokenUser(org_id=org.id, created_by_user_id=admin_user.id,
        rights={"organizations": {"action_update": granted}})
    db = AsyncMock()
    with patch.object(analytics, "_verify_org_membership", new_callable=AsyncMock), \
         patch.object(analytics, "_verify_org_admin", new_callable=AsyncMock), \
         patch.object(analytics, "_query_postgres_overview", new_callable=AsyncMock, return_value={"data": []}) as query, \
         patch.object(audit, "_verify_org_membership", new_callable=AsyncMock), \
         patch.object(audit, "_verify_org_admin", new_callable=AsyncMock):
        async def invoke():
            if surface == "overview":
                return await analytics.query_dashboard_db("basic_overview", org.id, mock_request, token, db)
            return await audit._require_admin(token, org.id, db)
        if granted:
            await invoke()
            if surface == "overview":
                query.assert_awaited_once()
        else:
            with pytest.raises(HTTPException) as exc:
                await invoke()
            assert exc.value.status_code == 403
            query.assert_not_awaited()


def test_employee_report_token_cannot_cross_organizations():
    token = APITokenUser(org_id=1, rights={"organizations": {"action_update": True}})
    with pytest.raises(HTTPException):
        analytics._require_analytics_token_rights(token, 2)
