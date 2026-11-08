# Operations guide

This is the release and incident checklist for a rescue-owned deployment. Live backups contain private locations, names, notes and photos. Keep them encrypted, restrict access, and never commit them.

## Ownership before launch

Assign one named owner and one backup owner for Render, Upstash, the OpenAI project and the admin passcode. Use rescue-owned accounts, enable multi-factor authentication, and store recovery codes in the rescue's password manager. Give reporters the team passcode, but keep the separate admin passcode with the owners.

Replace the fictional demo data only after the rescue has approved the people, colonies, photo permissions and retention period. Test the final deployment on at least one current iPhone and Android phone on cellular data. These account, consent and physical-device steps cannot be completed from the repository.

## Release checklist

1. Run every test listed in the README.
2. Confirm `git status` is clean and push the intended revision.
3. In Render, verify the deploy finished and the revision shown by `/healthz` matches the commit.
4. Confirm `/healthz` returns HTTP 200 with `ready: true` and `storage: upstash`.
5. Sign in at phone width and check Today, all 18 map pins, one colony, one cat and Confirm.
6. Submit a cached test photo, reload, and confirm it persists. Reset the demo if this is still the public demo.
7. Check the OpenAI project budget and usage alerts. The app records cost but intentionally does not impose a daily cap.

Never release with `storage: local` on Render: the local filesystem is temporary and reports would disappear on a restart.

## Health, diagnostics and logs

`GET /healthz` is public and contains no rescue data. It checks that SQLite can answer a query and returns the deploy revision and storage mode. Render uses it for health checks.

`GET /api/operations` requires both a signed-in team session and the admin passcode in `X-Admin-Passcode`. It returns uptime, revision, storage mode, persisted change count, today's recorded API spend, and aggregate photo-report successes, failures and timing. It contains no notes, names, locations or photos.

Every request gets an `X-Request-ID`. Render logs receive one JSON line with that ID, route, status and duration. Photo-report logs add only the report kind, colony ID, timing, cost and outcome; they never include notes, coordinates, passcodes, sponsor tokens or photo data. Use the request ID to connect a user's error with one server operation.

Alert on:

- `/healthz` failing twice in five minutes;
- any photo-report failure after a release;
- repeated HTTP 429 responses that may indicate misuse or reporters sharing one network;
- unexpected OpenAI usage;
- Upstash storage or request limits nearing the account's plan.

The server allows five photo reports per client network in ten minutes and ten failed sign-in attempts in ten minutes. A successful sign-in clears that client's failed-attempt window. These are abuse brakes, not replacements for account-level provider budgets.

## Private backup and restore

Run backups from a trusted computer that has the production Upstash variables in `.env`:

```bash
python -m app.backup --export /private/encrypted-drive/ccw-$(date +%F).json
```

The command exports the append-only changes and every referenced live photo, and creates the file with owner-only permissions. Store it on an encrypted drive. Open one backup monthly in a separate test environment and perform a restore drill.

Restore replaces all current live changes, so stop reporting first and take a fresh backup. Point `.env` at the intended Upstash database, verify it twice, then run:

```bash
python -m app.backup --restore /private/encrypted-drive/ccw-YYYY-MM-DD.json --confirm-replace
```

Redeploy or restart the service, then verify `/healthz`, the change count in `/api/operations`, a recent feeding, a recent photo and an open confirmation. The backup does not include environment secrets or the committed demo seed.

## Incident playbooks

### Photo analysis is unavailable

The form stays filled and offers a retry. Check the request ID, Render logs, OpenAI status and project billing. A failed report is not added to the rescue record, and its unreferenced uploaded photo is deleted. Reporters can keep the original photo and retry later. Do not ask them to send it through a personal channel.

### Reports do not survive a restart

Stop accepting reports. Check that `/healthz` says `storage: upstash` and that both Upstash REST variables are set on Render. Export whatever state remains before changing configuration. Restore the latest verified backup if needed, then run the persistence test before reopening access.

### Passcode or sponsor link is exposed

Change `TEAM_PASSCODE` or `ADMIN_PASSCODE` in Render immediately. Changing the team passcode invalidates existing team sessions. If the sponsor URL was exposed, set a new random `SPONSOR_REPORT_TOKEN`. Redeploy, test the old access no longer works, and share the replacement privately.

### A phone or volunteer should lose access

This version uses a shared team passcode and cannot revoke one person. Rotate the team passcode and redistribute it to current reporters. Individual accounts with per-person revocation are required before a larger or frequently changing team uses the service.

### Incorrect merge or status decision

Stop further decisions on that cat and preserve the current backup. The change log is append-only, but the current interface has no reversal workflow. A developer must add a recorded corrective decision; do not edit SQLite because it is rebuilt on restart.

## Privacy and retention

Choose and document a retention period with the rescue before real use. At least quarterly, remove reporters who left, rotate shared secrets, review the sponsor link, and delete backups beyond the agreed period. Treat approximate colony coordinates as sensitive. Do not put real exports, `.env`, production backups or private photos in Git, tickets, screenshots or chat.

The sponsor page is intentionally counts-only. After any sponsor-report change, test its HTML and network requests for names, phones, locations, cat names and photos.

## Known production boundary

The repository can supply code, tests, deployment configuration and runbooks. A real launch still requires rescue consent and data, rescue-owned provider accounts, secret rotation, an account-level OpenAI budget, a retention decision, and hands-on iPhone/Android testing. The shared passcode is appropriate for a small stable team, not a large organization requiring individual audit and revocation.
