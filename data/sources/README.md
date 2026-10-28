# Source snapshots

Each file here is a snapshot of what [MusicBrainz](https://musicbrainz.org) knew about the recordings of one group of works, taken on the date given. MusicBrainz core data is released under CC0.

| File | Works | Taken | MusicBrainz parent work | Movements | Recordings | Performances |
|---|---|---|---|---|---|---|
| `musicbrainz-cello-suites.json` | Cello Suites, BWV 1007–1012 | 27 Oct 2026 | `4e4b97df-403a-4a27-b9fa-5bd8a8333604` | 36 | ~6,150 | 267 |
| `musicbrainz-violin-solo.json` | Sonatas and Partitas for solo violin, BWV 1001–1006 | 28 Oct 2026 | `4a8c18a0-efe2-4b56-a127-9958dec08ad3` | 32 | 4,315 | 331 |

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
| `ins` | instruments credited |
| `roles` | performer → instrument |
| `pl` | places "recorded at" |
| `r` | earliest official release: [release ID, title] |
| `rep` | one representative recording ID |

## Known limits

- MusicBrainz sometimes holds one performance as several unmerged recordings. When those have no date, they can show up here as a separate "undated" entry. These are flagged on the site.
- Grouping by year cannot separate two different performances by the same artist in the same year.
- A complete set where MusicBrainz is missing one movement link shows as five complete works and one excerpt.
- Paired dances such as Menuet I and Menuet II are often a single MusicBrainz track linked only to the first dance. The importer counts the second as recorded whenever the first is.
