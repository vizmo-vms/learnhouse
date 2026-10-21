# Active learning time

## User requirements

Show administrators each employee's estimated active learning time per course in the existing PostgreSQL Analytics tables. Include lessons and assessments, sum across visits, pause hidden tabs immediately and pause after five minutes without scrolling, clicking or typing. Visible video playback counts without further input. This reports activity, not verified attention.

Stop the completion total when the course's published lessons are complete and its required assessments pass. Later revision does not inflate that first-completion total. This must not add a minimum-time gate or change grades, certificates or existing completion rules.

Historical active time cannot be recovered. Seed existing enrollments as partially tracked; show `Not tracked` until time is actually recorded, and `Partially tracked` on measured totals that omit earlier study. Already-completed courses must not acquire fabricated durations.

## Implementation and acceptance checks

- Store only course totals and session cursors in PostgreSQL. Existing database backups cover them; no Tinybird or new external provider is required.
- The authenticated user owns the recording. Reuse the activity reader gate, require organization membership and a published, linked lesson. Reject API-token recording, other users' sessions, inaccessible courses and cross-course session reuse.
- A browser session sends a cumulative active counter approximately every 15 seconds, with a final keepalive flush on hide/navigation. No text, clicked targets or keystroke contents are transmitted.
- Bound accepted increments by server elapsed time and a short heartbeat window. Ignore duplicate/out-of-order counters. Lock the user's course aggregate so concurrent sessions cannot double-count overlapping time.
- Capture the first qualifying completion time on the server. A late final heartbeat may add only its bounded interval before that completion; later revisits cannot add time.
- Display a human-readable duration and tracking coverage in the shared employee/course Analytics table. No new reporting dashboard, attendance enforcement, rankings or minimum-time requirement is included.
- Test visibility/idle transitions, visible playback, duplicate and concurrent sessions, validation/access boundaries, partial historical records, completion freeze and existing completion/assessment regressions. Independently review with Astra xhigh before release, rehearse the additive schema/seed change on a database copy, back up and deploy the app alone.

## Embedded content and rollout

Native text lessons, assessments and HTML5 video are observed directly. Recognized YouTube embeds use the official iframe player API, with visible playback checked once per second. Browser PDF viewers and other opaque embeds do not expose their internal interactions; their course totals are conservatively marked partially tracked. Their visible page time follows the ordinary five-minute idle cutoff. Downloaded or separately opened documents cannot be tracked.

Run the additive migration before starting this image. For an existing installation, the targeted rollout runner must initialize historical completion sentinels in the same transaction: create the tables and partial seeds, bind an async session to that transaction, and use `is_course_fully_completed` plus `are_course_assignments_passed` for each untouched seed. Set only `completed_at` for qualifying seeds; keep `first_seen_at` null. That timestamp is an internal rollout freeze marker, not a reconstructed completion date. Drain old application writers during initialization and the image swap. Do not stamp or replay unrelated historical migrations. Preserve fingerprints of existing tables and rehearse on a disposable database copy first.
