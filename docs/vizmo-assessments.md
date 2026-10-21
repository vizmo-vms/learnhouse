# Course assessments

Course knowledge checks use native assignments with server grading, an 80%
passing threshold, three total attempts, no deadline, and no answer-key reveal.
Every published lesson must be complete and every required assessment passed
before a new certificate is issued. There is no minimum-duration gate.

Analytics shows the latest assessment score, pass/fail, attempt number, and
whether an earlier course completion was preserved. Lesson completion and
assessment passing are distinct: finishing all activities may show 100%
progress even when the assessment failed; a failing learner is not certified.
Retries replace the previous attempt under the native assignment model.

## Converting existing content

`apps/api/scripts/convert_course_assessments.py` converts standalone inline
quizzes in published courses. Provide a private JSON map of course names to
question banks for courses without quizzes. Never commit the real banks or
answer keys to a public repository.

The script validates the entire plan first, rejects unexpected course counts
or mixed lesson/quiz material, uses one transaction, and is idempotent. Existing
quiz activities retain their IDs and chapter positions; original content is
saved in restricted activity version history. Missing assessments are appended
to the last chapter. Obsolete search snippets are removed for normal reindexing.

Take database and media backups, rehearse on a restored database copy, and check
certificate and enrollment fingerprints before deployment.

1. Run without `--apply` to inspect the plan.
2. Run with `--prepare-schema` to create only the empty private preservation
   ledger before deploying the updated API. This does not stamp or replay
   historical Alembic migrations.
3. Deploy the updated API and frontend.
4. Stop API and collaboration writers and let their database sessions close.
5. Run with `--apply`; restart writers even if the transaction fails.
6. Verify grades, key redaction, existing certificates and completion records.

Example, from `apps/api` with `PYTHONPATH=.`:

```sh
python scripts/convert_course_assessments.py \
  --org-id ORG_ID --expected-count COURSE_COUNT --drafts private-questions.json
```

Add `--database DATABASE_COPY --apply` for the rehearsal. Backups and private
question files belong outside the public source repository.

## Preserved completions

An `AssessmentLegacyCompletion` ledger links earlier completers to the exact
assignment introduced at conversion. It has no public write endpoint or learner
API. These entries preserve completion and certificate validity through optional
assessment retries, rejection, and regrading without inventing a passing score.
Deleting that assignment cascades its ledger entries, so replacement assessments
do not inherit the exception. Future assessments require their own passing grade.

After cutover, prefer rolling forward to fix a release. An image-only rollback to
a build predating the preservation policy can revoke earlier certificates during
assessment retries. A full database restore also loses subsequent learner work;
assess that impact before restoring.

## Review and checks

Astra xhigh independently reviewed conversion, grading, authorization, privacy,
certificate preservation, focus mode, date handling and the drafted questions.
The preservation and privacy findings were fixed and reviewed again.

The UI design hook's neutral status badge warning is a false positive: completed
uses green text on green, and other statuses use gray text on neutral gray.
AI suggestion buttons use teal text and light teal surfaces; long assessment
answers grow vertically instead of using fixed-height rows.
