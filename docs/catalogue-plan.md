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

This is one interactive session with Gonçalo at the computer, before any scheduled run.

1. **Hand snapshots over as files, not through the conversation.** The Brandenburg snapshot was copied in 12
   checked chunks through the chat. That one step used most of the session's tokens, so a schedule built
   on it would exhaust the daily allowance.
   - Add `download(name)` to `scripts/musicbrainz-collect.js`. It saves `musicbrainz-<id>.json` from the
     browser panel into a folder on the computer.
   - Connect that folder to Claude once.
   - Each run copies the file into its workspace with the device file tools.
   - Test with the Brandenburg data, which is already known.
   - If downloads from the panel are blocked, the fallback is the chunked transfer. Then the plan needs
     about twice as many runs, each with fewer works.
2. **Collector batch mode.** `startRun(n)` takes the parent works and movement lists for run *n* and collects
   them one after another, resuming after errors. It keeps the 1 request per second limit, and only one
   collector may run at a time, because MusicBrainz limits by IP address.
3. **Importer modes** (`mode` in the list):
   - `ensemble` exists.
   - `keyboard`: the WTC/Goldberg rules.
   - `solo`: the violin and cello rules.
   - `chamber` (new): two or three players are one performance, not an arrangement. Piano, cello or modern
     flute instead of harpsichord, gamba or traverso are filed as instruments with practice "modern", not
     as arrangements.
   - `organ` (new): native organ. Piano or orchestra versions are arrangements, but most of those are
     separate MusicBrainz works and drop out anyway.
   - `lute` (new): see decision 3.
   - `open` (new): Art of Fugue, Musical Offering and canons have no fixed scoring. Every classical
     instrument and combination is native; only jazz, electronic and the like count as arrangements.
   - `vocal` (new): a choir is native, not an arrangement. Performers are grouped by choir and orchestra.
     The singers credited on any recording become soloists, and the conductor leads the performer list.
4. **Work files at scale.** Add `scripts/work_stub.py`. It turns a MusicBrainz work tree, saved as JSON by the
   collector, into `data/works/<bwv>.yaml` stubs with the movement list in MusicBrainz order. The run then
   only adds key, scoring, date, the Wikipedia link and a note.
5. **Make the site hold 20,000+ recordings.** Today everything is inlined into one 1.4 MB page. The full
   catalogue would be 20–30 MB, and the preview artifact is capped at 16 MB.
   - Move each collection's recordings to `site/data/<id>.json`, loaded when the volume is opened.
   - Keep a compact search index in the page.
   - Group the shelf by chapter: Cantatas, Masses and Passions, Organ, Keyboard, Chamber, Orchestral,
     Late contrapuntal works. Each chapter is one shelf of spines.
   - This must land before run 10.
6. **Create the scheduled tasks** (section 4) once the steps above work end to end on run 1, done by hand.

## 3. Who does what in a run

Each run has one lead agent and up to two helpers, spawned in parallel. Parallel agents make a run finish
sooner; they do not make it cheaper. The daily allowance is protected by the schedule, not by parallelism.

| Agent | Job | Needs the browser? |
|---|---|---|
| **Lead** | Harvests the snapshot started by the previous run. Imports it, reviews mislinks and junk (EXCLUDE), validates, builds and checks the site with Playwright, then opens the pull request. Afterwards it starts the next run's collection in the browser panel. | yes (briefly) |
| **Work-file writer** | Writes key, scoring, date, source link and a note for the next run's works, from Wikipedia and Bach Digital. For the church cantatas it splits into 2–4 writers by BWV range. | no |
| **Checker** (fresh context) | Checks ten random imported recordings against their MusicBrainz pages, plus the classification of every arrangement and period-instrument flag. Reports disagreements, which the lead fixes before the pull request. | no (reads the MusicBrainz release links via search) |

**Why each run harvests the previous collection.** Collecting a large set takes from minutes to about an
hour of patient MusicBrainz requests. The browser panel does that work and no agent is billed while it
waits. So each run starts a collection and finishes it at the next run. Progress lives in the browser's
storage (`ab_<id>_*`), so it survives a closed panel or a restarted computer.

## 4. Schedule

- **Cadence:** one run per evening, Monday to Saturday, at **22:47 Copenhagen time**.
- **Length:** 36 runs, plus a spare evening a week for catching up. That is about **7 weeks**.
- **Why that time:** late evening keeps the runs out of the hours Gonçalo uses Claude himself, so they don't
  eat into the same usage window. It is also outside the 15:00–18:00 Copenhagen window, when scheduled
  runs are often delayed.
- **The computer must be on** with the Claude desktop app open: the browser panel and the snapshot folder
  are on it. On a Mac that means keeping it plugged in and set not to sleep while the display is off. A
  run that finds the computer unreachable stops, says so, and the next evening picks up the same run.
- **Halving the time:** add a second daily run (e.g. 07:23) and the plan takes about 3½ weeks, at twice the
  daily usage. Decide after watching what runs 1–3 actually use.
- **Each task's prompt** is the same: "Clone glima93/all-bach and follow docs/batch-runbook.md." The run
  finds its own next step from the `status` fields in `data/plan/collections.yaml`.

## 5. Decisions to settle before Phase 0 ends

1. **Merging.** Unattended runs open a pull request and Gonçalo merges, which is the default. The
   alternative is that runs merge to `main` themselves when the checks pass.
2. **Doubtful and spurious works.** The default keeps them, marked doubtful on their page (BWV 1036,
   1037, 246, 553–560, 217–224 …).
3. **Lute works on guitar.** Most recordings of 995–1000 are on guitar. Either file guitar as the instrument
   with practice "modern" (proposed; it is the work's main life today), or treat it as an arrangement.
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
