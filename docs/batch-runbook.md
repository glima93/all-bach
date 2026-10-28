# Batch runbook

What a scheduled run does, start to finish. A run starts in a fresh session with no memory of earlier ones,
so everything it needs is here, in [`data/plan/collections.yaml`](../data/plan/collections.yaml) and in
[`data/sources/README.md`](../data/sources/README.md). The plan behind it is
[`docs/catalogue-plan.md`](catalogue-plan.md).

## 0. Before anything

1. Clone `glima93/all-bach`, check out `main`, and `pip install pyyaml jsonschema`.
2. Run `python scripts/plan_coverage.py`. Stop if it fails.
3. Find the work to do:
   - **To harvest:** collections with status `collecting`. Their snapshot was started by the previous run.
   - **To start:** collections in the lowest run number whose collections are all `todo`.
4. Check the computer is reachable: list the snapshot folder with the device tools, and open the browser
   panel on `https://musicbrainz.org/ws/2/work/7481c7f5-71bd-464e-956a-c670f4117de3?fmt=json`.
   - If either fails, stop. Report "computer unreachable, run N not done" and change nothing.
5. Never run two collectors at once. Before starting one, check in the panel that no `ab_*_running` flag is
   set.

## 1. Harvest (lead agent)

For each `collecting` collection:

1. **Get the snapshot.**
   - In the panel, confirm `done("<id>")` is true. If not, leave it collecting, report how far it got, and
     skip to step 2.
   - Call `download("<id>")`, then stage `musicbrainz-<id>.json` from the snapshot folder into
     `data/sources/`.
   - Check the row count against `rows("<id>").length` in the panel.
2. **Import:** `git checkout -b run-<N>`, then `python scripts/import_musicbrainz.py data/sources/musicbrainz-<id>.json`.
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
   - Set the collection's status to `imported` in `collections.yaml`.
8. **Commit and pull request.**
   - Author `Gonçalo <glima93@gmail.com>`. End the message with the attribution lines the session gives.
   - Push `run-<N>` and open a pull request titled "Run N: <collections>".
   - Make it a draft if more than 5% of rows were disputed.
9. **Clean up:** clear the `ab_<id>_*` keys in the panel.

## 2. Start the next collection (lead agent, plus the work-file writer in parallel)

1. **Find the works in MusicBrainz.** In the panel, find the parent work for each collection (search
   `work?query=bach AND "<title>"`). If there is no parent, collect the individual works by BWV.
   - Save each work tree with `tree("<id>")`, then `download`.
2. **Work files.**
   - Run `python scripts/work_stub.py <tree.json>` to write `data/works/<bwv>.yaml` stubs with movements in
     MusicBrainz order.
   - In parallel, spawn the work-file writer to fill key, scoring, composed, Wikipedia link and a short note
     for each stub. Split into 2–4 writers for more than 40 works.
   - Run `validate.py`.
3. **Start collecting.**
   - Call `startRun(<N>)` in the panel. It runs on its own at one request per second and saves progress in
     the browser's storage.
   - Set status `collecting` in `collections.yaml`.
   - Commit the work files and status to the same `run-<N>` branch, so the pull request carries them. If the
     harvest was skipped, open the pull request with just these.
4. **Report.** One message: what was imported (counts and notable sets), what is collecting now, and any
   decision that needs Gonçalo.

## Stop rules

- **Unattended decisions:** never merge to `main`, never delete tracked files, and never force-push.
- **Contradictions:** if the MusicBrainz movement order disagrees with an existing work file, or a snapshot
  fails its row count, stop at a draft pull request with the problem described.
- **Usage:** if the run is cut short, the next run picks up from the statuses. Every step above is safe to
  repeat.
