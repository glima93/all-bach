# Batch runbook

What a scheduled Claude run does, start to finish. A run starts in a fresh cloud session with no memory of
earlier ones, so everything it needs is here, in [`data/plan/collections.yaml`](../data/plan/collections.yaml)
and in [`data/sources/README.md`](../data/sources/README.md). The plan behind it is
[`docs/catalogue-plan.md`](catalogue-plan.md).

The MusicBrainz collecting is not done here. The GitHub workflow `collect.yml` does it every night at 01:00
Copenhagen time, for every collection marked `queued`. It pushes a `collect/<id>` branch holding
`data/sources/musicbrainz-<id>.json` and `data/sources/tree-<id>.json`, with the collection marked
`collected`. A run never needs Gonçalo's computer.

## 0. Before anything

1. Clone `glima93/all-bach`, check out `main`, and `pip install pyyaml jsonschema`.
2. Run `python scripts/plan_coverage.py`. Stop if it fails.
3. `git fetch origin 'refs/heads/collect/*:refs/remotes/origin/collect/*'`.
   - **To import:** each `collect/<id>` branch not yet merged into `main`.
   - **To queue next:** the collections in the lowest run number whose collections are all `todo`.
4. If nothing was collected and nothing is queued, the workflow is stuck. Report the latest `collect.yml`
   run (`gh run list -w collect.yml -L 3`) and stop.

## 1. Import (lead agent)

For each collected collection, on a branch `run-<N>` from `main` with `collect/<id>` merged in:

1. **Work files.**
   - Run `python scripts/work_stub.py data/sources/tree-<id>.json` to write `data/works/<bwv>.yaml` stubs with
     movements in MusicBrainz order.
   - Spawn the work-file writer in parallel to fill key, scoring, composed, Wikipedia link and a short note.
     Use 2–4 writers for more than 40 works.
   - Run `validate.py` when they finish.
2. **Import:** `python scripts/import_musicbrainz.py data/sources/musicbrainz-<id>.json`.
3. **Review.**
   - List every new file with instrument, practice, arrangement and first performer.
   - Look for mislinks (another composer, another BWV, film soundtracks, baby and relaxation compilations
     that are not arrangements) and add them to `EXCLUDE` with a reason.
   - Fix rules in the importer, never individual YAML files.
   - Re-import from a clean state: `git clean -fq data/recordings` removes only the new, untracked files.
4. **Checker.** Spawn the checker agent (fresh context), giving it the new files and the snapshot. Act on what
   it reports.
5. **Stability.** Re-run every snapshot in `data/sources/` through the importer. `git status` must show no
   modified recording files.
6. **Checks.**
   - `python scripts/validate.py` (0 errors).
   - `python scripts/build.py`.
   - A Playwright test: the shelf shows the new volume, its collection page lists its works, one work page
     renders, and two searches return results. No page errors.
7. **Docs.**
   - Add the snapshot row to `data/sources/README.md`: works, date, parent work id, movements, MusicBrainz
     recordings, performances.
   - Update the coverage sentence in `README.md`.
   - Set the collection's status to `imported`: `python scripts/plan_status.py <id> imported`.

## 2. Queue the next run

1. Set the next run's collections to `queued`: `python scripts/plan_status.py <id> queued`. Give each its MusicBrainz parent work id
   (`mb_parent`) if one exists; the collector otherwise searches by BWV number.
2. **Commit, open the pull request, and merge it if it is clean.**
   - Author `Gonçalo <glima93@gmail.com>`. End the message with the attribution lines the session gives.
   - Push `run-<N>` and open a pull request titled "Run N: <collections>".
   - **Doubtful runs stay open as drafts for Gonçalo.** A run is doubtful if any of these holds:
     - more than 5% of rows were disputed by the review or the checker;
     - the checker reported something the lead could not resolve;
     - a stop rule was hit;
     - a test or check failed.
     For a doubtful run, write the reasons in the pull request description and do not merge.
   - **Otherwise merge it yourself** (Gonçalo's standing decision, 28 Oct 2026):
     - Wait for the pull request's checks to pass, then `gh pr merge --merge`.
     - If `gh` is refused, merge `run-<N>` into an up-to-date `main` locally, re-run `validate.py` and
       `build.py`, and push `main`. Never force-push.
   - The workflow reads the queue from `main`, so a merged run queues the next collection for that night. A
     doubtful run holds the queue until Gonçalo merges it. That is intended.
3. **Report.** One message: what was imported (counts and notable sets), what is queued now, and any
   decision that needs Gonçalo.

## Stop rules

- **Unattended decisions:** merge to `main` only as described in section 2, step 2. Never delete tracked files and never force-push.
- **Contradictions:** if the MusicBrainz movement order disagrees with an existing work file, or a snapshot
  fails to parse, stop at a draft pull request with the problem described.
- **Usage:** if the run is cut short, the next run picks up from the statuses and branches. Every step above
  is safe to repeat.
