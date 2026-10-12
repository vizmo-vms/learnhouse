# Vizmo LearnHouse 1.4.0-vizmo.1

Based on upstream LearnHouse 1.4.0, released October 11, 2026.

## Updated

- Upstream security fixes for authentication, API tokens, CSRF, content access,
  exports, account changes and request limits.
- Course-content AI indexing and source locators, with new access checks for
  course and activity content.
- Upstream frontend and backend dependencies and fixes for editor replies,
  callout lists and assignment ordering.

## Preserved

- Google-only joining for verified Vizmo Workspace identities, hidden signup,
  shared/email invite links and their mapped group membership.
- Course Manager and Maintainer management access across learner groups,
  organization boundaries, session policies and separate delete permissions.
- PostgreSQL analytics, employee/course progress and audit reporting without a
  Tinybird dependency; fixed-height panels and corrected timestamp display.
- Automatic sandboxed HTML and Mermaid previews with source view, complete
  exercise revisions, Vizmo teal styling and the light activity AI interface.
- Bounded Library cards, pagination and deferred media previews.
- Existing external AI provider, model, embedding and SMTP configuration.

## Integration fixes

- Prefer upstream role-membership scoping and destination course-create checks
  where they replace the custom implementation.
- Carry manager visibility into the shared activity and AI content reader gates.
- Handle the new superadmin token principal explicitly, without treating token
  row IDs as human user IDs.
- Require org API tokens' own organization-update grant for employee reports.
- Retain upstream markdown image privacy protection alongside interactive previews.
- Org API tokens' own course-read grant now drives course inventory, matching
  upstream resource reads; content lock bypass still requires a management grant.

## Upgrade

Take fresh PostgreSQL and media backups before replacing the app image.
Two additive migrations backfill assignment-task order and add AI embedding
locators, content hashes and indexes. PostgreSQL and Redis can remain running.
The app may be briefly unavailable while it starts and applies migrations.

The immutable deployment image and verification results are recorded with the
GitHub release. Keep the previous image available for rollback; do not remove
volumes or reverse migrations as part of an app rollback.
