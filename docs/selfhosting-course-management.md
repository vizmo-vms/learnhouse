# Course management and learner groups

Admins and Maintainers can manage every course in their organization. Custom
roles with the general `courses.action_update` permission have the same course
visibility, including group-restricted content needed for editing and preview.
The role name does not determine access.

`action_read`, `action_create`, and `action_update_own` alone do not bypass
learner group restrictions. Ordinary learners still see their assigned courses.
Managers' catalog lists include published courses; management lists request
`include_unpublished=true` to include drafts.

Deletion and content creation use their respective permissions. Course Manager
does not gain unrelated organization administration rights. Role grants apply
only where the user holds that role, including global Admin/Maintainer roles.
Course creation and cloning check the destination organization's create grant.

Manager inventory reads enforce organization authentication and MFA policies.
API tokens use their own organization and course rights rather than inheriting
their creator's management role. Dashboard course lists have a separate client
cache from learner lists.
