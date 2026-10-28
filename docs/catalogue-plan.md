# Plan: the rest of the BWV catalogue

Status on 28 Oct 2026: 5 collections and 67 works are on the site (1,480 recordings). This plan covers the
other 47 collections, BWV 1–1128, in 36 scheduled runs.

- **The list:** [`data/plan/collections.yaml`](../data/plan/collections.yaml). It has every collection, the BWV
  numbers it holds, the importer mode it needs and the run that collects it.
  `python scripts/plan_coverage.py` checks that every number from 1 to 1128 sits in exactly one collection.
- **The procedure** each scheduled run follows: [`docs/batch-runbook.md`](batch-runbook.md).

## 1. The collections

| Run | Collection | BWV | Mode |
|---|---|---|---|
| — | Well-Tempered Clavier · Goldberg · solo violin · cello suites · Brandenburg | 846–893, 988, 1001–1012, 1046–1051 | done |
| 1 | Orchestral Suites | 1066–1071 | ensemble |
| 2 | Violin Concertos | 1041–1045 | ensemble |
| 3 | Harpsichord Concertos | 1052–1065 | ensemble |
| 4 | English Suites | 806–811 | keyboard |
| 5 | French Suites | 812–817 | keyboard |
| 6 | Partitas (Clavier-Übung I) | 825–830 | keyboard |
| 7 | Inventions and Sinfonias | 772–801 | keyboard |
| 8 | Italian Concerto and French Overture (Clavier-Übung II) · The Art of Fugue | 831, 971 · 1080 | keyboard · open |
| 9 | The Musical Offering | 1079 | open |
| 10 | Sonatas for violin and harpsichord | 1014–1026 | chamber |
| 11 | Gamba sonatas · Flute sonatas and partita | 1027–1029 · 1013, 1030–1035 | chamber |
| 12 | Trio sonatas · Lute works | 1036–1040 · 995–1000 | chamber · lute |
| 13 | Toccatas · Fantasias, preludes and fugues for keyboard | 910–916 · 894–909, 917–923, 944–962 | keyboard |
| 14 | Concerto transcriptions for keyboard · Little Preludes | 972–987 · 924–943 | keyboard |
| 15 | Sonatas, variations and capriccios · Other suites and pieces | 963–970, 989–994 · 818–824, 832–845 | keyboard |
| 16 | Preludes and fugues for organ | 531–551 | organ |
| 17 | Toccatas, fantasias and other free organ works | 561–591, 1121 | organ |
| 18 | Organ trio sonatas · Organ concerto transcriptions | 525–530 · 592–598 | organ |
| 19 | Orgelbüchlein | 599–644 | organ |
| 20 | Schübler Chorales · Great Eighteen | 645–650 · 651–668 | organ |
| 21 | Clavier-Übung III | 552, 669–689, 802–805 | organ |
| 22 | Mass in B minor · Magnificat | 232 · 243 | vocal |
| 23 | Passions | 244–247 | vocal |
| 24 | Christmas, Easter and Ascension Oratorios | 248, 249, 11 | vocal |
| 25 | Motets · Missae breves and mass movements | 225–231, 118 · 233–242 | vocal |
| 26 | Secular Cantatas | 201–216 | vocal |
| 27–30 | Church Cantatas, in four runs | 1–50 · 51–100 · 101–150 · 151–200, 217–224 (11 and 118 excepted) | vocal |
| 31 | Kirnberger chorales · Chorale partitas and variations | 690–713 · 766–771 | organ |
| 32 | Other chorale preludes for organ | 714–765, 1085, 1128 | organ |
| 33 | Neumeister Chorales · Eight Short Preludes and Fugues | 1090–1120 · 553–560 | organ |
| 34 | Four-part Chorales | 250–438 | vocal |
| 35 | Schemelli Songbook · Songs, arias and quodlibet | 439–507 · 508–524 | vocal |
| 36 | Canons · Later additions and fragments | 1072–1078, 1086, 1087 · 1081–1084, 1088, 1089, 1122–1127 | open |

**Order of the runs.** Wave 1 (runs 1–21) is instrumental music that the current pipeline nearly handles,
with the most recorded works first. Wave 2 (runs 22–30) is vocal music and needs the vocal mode. Wave 3
(runs 31–36) is the long tail: chorale preludes, chorales, songs and canons. Numbering is BWV2a (1998),
which is what MusicBrainz and record labels use; BWV3 (2022) decimal numbers can be added later as aliases.

## 2. Phase 0: what has to change before the schedule starts

This is one session, not unattended. Nothing in it needs Gonçalo's computer.

1. **Collect on GitHub, not in the browser.** Claude's workspace cannot reach MusicBrainz, which is why the
   first five collections were gathered in the desktop app's browser panel and copied through the chat in
   checked chunks. That needs the computer on, and the copying used most of a session's tokens. GitHub's
   build machines can reach MusicBrainz: a test workflow got HTTP 200 on 28 Oct 2026. So:
   - Port `scripts/musicbrainz-collect.js` to `scripts/collect_musicbrainz.py`: same requests, grouping and
     row format, 1 request per second, and a User-Agent naming the project.
   - Add `.github/workflows/collect.yml`, which runs on a schedule and by hand. It reads the collections
     marked `queued` in `collections.yaml` and writes `data/sources/musicbrainz-<id>.json`.
   - The workflow pushes to a `collect/<id>` branch (never `main`) and marks the collection `collected`.
   - Each job can run for up to 6 hours. Progress is saved in a cache so a cut-off job resumes, which
     matters for the cantatas.
   - **Test:** re-collect the Brandenburg Concertos. The result must match `musicbrainz-brandenburg.json`
     apart from recordings added to MusicBrainz since 28 Oct.
2. **One collector at a time.** The workflow uses a `concurrency` group, because MusicBrainz limits requests
   by IP address and parallel collectors would be throttled.
3. **Importer modes** (`mode` in the list):
   - `ensemble` exists.
   - `keyboard`: the WTC/Goldberg rules.
   - `solo`: the violin and cello rules.
   - `chamber` (new): two or three players are one performance, not an arrangement. Piano, cello or modern
     flute instead of harpsichord, gamba or traverso are filed as instruments with practice "modern", not
     as arrangements.
   - `organ` (new): native organ. Piano or orchestra versions are arrangements, but most of those are
     separate MusicBrainz works and drop out anyway.
   - `lute` (new): lute, lute-harpsichord and guitar are all native; guitar is filed as itself with practice "modern" (decision 3).
   - `open` (new): Art of Fugue, Musical Offering and canons have no fixed scoring. Every classical
     instrument and combination is native; only jazz, electronic and the like count as arrangements.
   - `vocal` (new): a choir is native, not an arrangement. Performers are grouped by choir and orchestra.
     The singers credited on any recording become soloists, and the conductor leads the performer list.
4. **Work files at scale.** The collector also saves each MusicBrainz work tree as
   `data/sources/tree-<id>.json`. `scripts/work_stub.py` turns that into `data/works/<bwv>.yaml` stubs with the
   movement list in MusicBrainz order. The Claude run then only adds key, scoring, date, the Wikipedia link
   and a note.
5. **Make the site hold 20,000+ recordings.** Today everything is inlined into one 1.4 MB page. The full
   catalogue would be 20–30 MB, and the preview artifact is capped at 16 MB.
   - Move each collection's recordings to `site/data/<id>.json`, loaded when the volume is opened.
   - Keep a compact search index in the page.
   - Group the shelf by chapter: Cantatas, Masses and Passions, Organ, Keyboard, Chamber, Orchestral,
     Late contrapuntal works. Each chapter is one shelf of spines.
   - This must land before run 10.
6. **Create the scheduled tasks** (section 4) once the steps above work end to end on run 1, done by hand.

## 3. Who does what

| Who | Job | Uses Claude? |
|---|---|---|
| **GitHub workflow** (`collect.yml`) | Collects the queued collections from MusicBrainz overnight and pushes each snapshot and work tree to a `collect/<id>` branch. | no |
| **Lead agent** | Imports the collected snapshot and reviews mislinks and junk (EXCLUDE). Validates, builds and checks the site with Playwright, then opens the pull request. Last, it queues the next run's collections for the workflow. | yes |
| **Work-file writer** (spawned in parallel) | Writes key, scoring, date, source link and a note for this run's work stubs, from Wikipedia and Bach Digital. For the church cantatas it splits into 2–4 writers by BWV range. | yes |
| **Checker** (spawned, fresh context) | Checks ten random imported recordings and every arrangement and period-instrument flag against the data, and reports disagreements, which the lead fixes before the pull request. | yes |

Parallel agents make a run finish sooner; they do not make it cheaper. The daily allowance is protected by
the schedule, and by keeping MusicBrainz work out of Claude entirely: the snapshot arrives in the repository
as a file, so no run spends tokens copying data.

## 4. Schedule

Nothing runs on Gonçalo's computer, so the timings only need to keep runs away from his own use of Claude.

- **01:00 Copenhagen, every night:** the GitHub workflow collects whatever is queued. It costs no Claude
  usage, and a big collection has the whole night.
- **06:43 Copenhagen, Monday to Saturday:** the Claude run (a cloud session) imports what the workflow
  collected and queues the next collections.
  - It finishes before the working day.
  - It sits outside 15:00–18:00 Copenhagen, when scheduled runs are often delayed.
  - Its usage window has reset by the time Gonçalo starts using Claude.
- **Length:** 36 runs, with Sunday spare for catching up: about **6 weeks**.
- **Halving the time:** add a second run at 13:17 (queue two collections a night) for about 3 weeks, at
  twice the daily usage. Decide after seeing what runs 1–3 use.
- **Each task's prompt** is the same: "Clone glima93/all-bach and follow docs/batch-runbook.md." The run
  finds its next step from the `status` fields in `data/plan/collections.yaml`.
- **A run with nothing collected** (for example the workflow failed, or MusicBrainz was down) reports it and
  stops, costing almost nothing. The next morning picks up the same run.

## 5. Decisions

1. **Merging (decided 28 Oct 2026).** A run merges its own pull request into `main` when every check passes
   and the review found nothing doubtful. Doubtful runs (more than 5% of rows disputed, an unresolved
   checker finding, a failed check or a stop rule) stay open as drafts for Gonçalo, with the reasons in
   the description. A doubtful run also holds back the next collection until it is merged.
2. **Doubtful and spurious works (open).** The default keeps them, marked doubtful on their page (BWV 1036,
   1037, 246, 553–560, 217–224 …).
3. **Lute works on guitar (decided 28 Oct 2026).** Guitar is filed as the instrument, with practice
   "modern", not as an arrangement. The `lute` importer mode must therefore exempt guitar from the
   `ARRANGED` rule that applies to every other collection.
4. **Transcriptions under separate MusicBrainz works** (Busoni, Siloti, Stokowski …) stay out, as now. They
   could become their own "arrangements" volume after run 36.

## 6. Risks

- **MusicBrainz shape varies.** Some collections have no parent work, and some works list movements in
  another order than the BWV edition. The run then builds the list from the individual works and stops
  rather than guessing when an order doesn't match.
- **Cantatas are huge.** Complete cycles put 200 works on a single performer group. Grouping by ensemble
  and year works, but a cycle recorded over 10 years becomes several performances per cantata, which is
  correct.
- **Mislinks grow with size.** The checker agent and the EXCLUDE list are the defence. A run with more than
  5% disputed rows stops at a draft pull request.
- **Usage.** Runs 1–3 are the measurement. If one run overruns a day's allowance, split runs further:
  `run` is just a number in the list.
