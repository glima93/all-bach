# Source snapshots

Each file here is a snapshot of what [MusicBrainz](https://musicbrainz.org) knew about the recordings of one group of works, taken on the date given. MusicBrainz core data is released under CC0.

| File | Works | Taken | MusicBrainz parent work | Movements | Recordings | Performances |
|---|---|---|---|---|---|---|
| `musicbrainz-cello-suites.json` | Cello Suites, BWV 1007–1012 | 27 Oct 2026 | `4e4b97df-403a-4a27-b9fa-5bd8a8333604` | 36 | ~6,150 | 267 |
| `musicbrainz-violin-solo.json` | Sonatas and Partitas for solo violin, BWV 1001–1006 | 28 Oct 2026 | `4a8c18a0-efe2-4b56-a127-9958dec08ad3` | 32 | 4,315 | 331 |
| `musicbrainz-goldberg.json` | Goldberg Variations, BWV 988 | 28 Oct 2026 | `1d51e560-2a59-4e97-8943-13052b6adc03` | 32 | 6,497 | 249 |
| `musicbrainz-wtc.json` | The Well-Tempered Clavier, Books I and II, BWV 846–893 | 28 Oct 2026 | `dce85d48-7ce6-4bd6-b21e-a7c1be6eb1b4` (Book I), `a9fabb1b-4b9e-4bdb-b177-452dbffeaed6` (Book II) | 96 | 8,072 | 321 |
| `musicbrainz-brandenburg.json` | Brandenburg Concertos, BWV 1046–1051 | 28 Oct 2026 | `7481c7f5-71bd-464e-956a-c670f4117de3` | 19 | 3,860 | 324 |

Snapshots are made with `scripts/musicbrainz-collect.js`, run in a browser tab on musicbrainz.org; its header explains how.

Import or re-import one with:

```
python scripts/import_musicbrainz.py data/sources/<file>.json
```

Files already linked to MusicBrainz are updated without overwriting anything a contributor wrote.

## How a snapshot is made

1. Start from the MusicBrainz parent work and take its works and their movements, in MusicBrainz's order. That order must match the movement lists in `data/works/`, or the importer stops.
2. For each movement, list every recording linked to it, with its artist credit and recording date (`work/<id>?inc=recording-rels` and `recording?work=<id>&inc=artist-credits`).
3. Group recordings into performances: same performers (Bach excluded) and same recording year. Groups from nearby years (up to three apart) whose movements don't overlap are joined, because a set is often recorded over several sessions (Casals, 1936–39; Milstein, 1954–56). Undated recordings join a dated performance only when exactly one dated performance by that performer contains all of their movements.
4. For one representative recording per performance, look up instrument credits, the recording venue and the releases it appears on (`recording/<id>?inc=artist-rels+place-rels+releases`).

Orchestral works are grouped differently: each concerto of a set is often credited to a different line-up of soloists, so recordings are grouped by the orchestra, ensemble or choir credited (when there is one) and the year, and the performance lists everyone credited on any of its recordings.

Only recordings linked to the original movements are included. MusicBrainz files most transcriptions (the Chaconne for piano by Busoni or for guitar, the suites on viola or marimba …) under separate arrangement works, so those are not in these snapshots yet.

## File format

The cello snapshot is a bare list of rows (the first format). Later snapshots are an object:

```json
{ "works": ["1001", "1002", …], "native": ["violin", "baroque-violin"], "rows": [ … ] }
```

`works` gives the order of the movement masks in each row; `native` lists the instruments the music was written for, so any other instrument is filed as an arrangement. For the bare list the importer assumes the Cello Suites and the cello family.

### Row keys

| Key | Meaning |
|---|---|
| `n` | performer names as credited |
| `a` | their MusicBrainz artist IDs |
| `y` | recording years |
| `m` | one number per work, in `works` order; bit *i* set = movement *i* recorded |
| `f` | year of first release |
| `l` | 1 if marked as a live recording |
| `t` | artist types (Person, Orchestra, Group, Choir), in the order of `a` |
| `ins` | instruments credited |
| `roles` | performer → instrument |
| `pl` | places "recorded at" |
| `r` | earliest official release: [release ID, title] |
| `rep` | one representative recording ID |

## Known limits

- MusicBrainz sometimes holds one performance as several unmerged recordings. When those have no date, they can show up here as a separate "undated" entry. These are flagged on the site.
- Grouping by year cannot separate two different performances by the same artist in the same year.
- A complete set where MusicBrainz is missing one movement link shows as five complete works and one excerpt.
- Keyboard works list harpsichord, piano, clavichord, organ and fortepiano as native, since Bach's "Clavier" covers them all. Performance practice follows the instrument: harpsichord, clavichord and fortepiano are filed as historical, piano as modern. That puts Landowska's modern Pleyel harpsichord under period instruments; contributors can correct such cases by hand.
- In MusicBrainz the Goldberg Aria is also linked from albums of the Anna Magdalena Bach Notebook (where Bach copied it) and from film soundtracks; these show as one-movement excerpts.
- For orchestral works (snapshot `native` is `["ensemble"]`) the instrument is "ensemble". Performance practice is "historical" when MusicBrainz credits a period instrument (baroque violin, natural horn, violone …) or the ensemble is a known period-instrument group (the list is `PERIOD_ENSEMBLE` in the importer); otherwise it is left unknown for a contributor to fill in. Jazz, brass, synthesizer and similar versions are filed as arrangements, and so is a keyboard player alone on any concerto but No. 5 (a transcription). `MODERN_ENSEMBLE` lists modern groups whose names or credits would otherwise look like period ensembles. A single soloist credited on a compilation (a trumpeter in No. 2, say) is filed as the ensemble performance it almost certainly is.
- The Adagio of Brandenburg Concerto No. 3 is two chords and rarely has a track of its own; it counts as recorded when both outer movements are.
- Paired dances such as Menuet I and Menuet II are often a single MusicBrainz track linked only to the first dance. The importer counts the second as recorded whenever the first is.
