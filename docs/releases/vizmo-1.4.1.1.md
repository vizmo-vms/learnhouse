# Vizmo LearnHouse 1.4.1-vizmo.1

## Upstream update

Integrates LearnHouse release `1.4.1` (`3288d5f6c4f134f36ddb5dd2bf3bbe1375bd9a05`):

- Access, session, upload and single-use sign-in link hardening.
- Video.js 10 playback, AI video chapters and scheduled content backfills.
- Faster activity-completion feedback and fixes to course copying and media migration.
- Released dependency and runtime updates, including Bun 1.4.3.

## Vizmo behavior retained

- Google-only Workspace membership restricted to the configured employee domain, hidden public signup, invitation recovery and mapped-group joining.
- Organization-scoped course management across learner groups, with token rights and other-organization session restrictions preserved.
- PostgreSQL employee progress and assessment analytics without Tinybird.
- Native graded course assessments: 80% pass mark, three total attempts, no answer-key reveal, no minimum-time gate and private preservation of earlier completions/certificates.
- Automatic sandboxed HTML and Mermaid previews, source view, Vizmo teal/light exercise styling and external AI configuration.
- Library pagination and deferred media previews, focus-mode AI, exit from focus at course end and UTC-aware certificate dates.

The merge combines upstream MFA redirect protection with invite-code preservation and keeps the AI side panel alongside the updated video layout.

## Database upgrade

Back up PostgreSQL and the content volume before deployment. For the existing installation initialized through `create_all`, apply only the exact new additive revisions `d7e8f9a0b1c2` and `e8f9a0b1c2d3` in one transaction after rehearsing on a database copy. These add the single-use sign-in token ledger/index and, where the payments table exists, a default billing interval.

Do not stamp or replay unrelated historical migrations. Preserve the assessment completion ledger, certificates, enrollments, grades and content. These additions are compatible with the previous image, so an application rollback does not require dropping their schema.
