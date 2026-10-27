# Source snapshots

## musicbrainz-cello-suites.json

A snapshot of what MusicBrainz knew about recordings of the six Cello Suites, BWV 1007–1012, on 27 October 2026. MusicBrainz core data is released under CC0.

### How it was made

1. Start from the MusicBrainz work "Six Suites for Unaccompanied Cello" (`4e4b97df-403a-4a27-b9fa-5bd8a8333604`) and take its six suites and their 36 movements.
2. For each movement, list every recording linked to it, with its artist credit and recording date (`work/<id>?inc=recording-rels` and `recording?work=<id>&inc=artist-credits`). This gave about 6,150 recordings.
3. Group recordings into performances: same performers (Bach excluded) and same recording year. Groups from consecutive years whose movements don't overlap are joined, because a set is often recorded over several sessions (Casals, 1936–39). Undated recordings join a dated performance only when exactly one dated performance by that performer contains all of their movements.
4. For one representative recording per performance, look up instrument credits, the recording venue and the releases it appears on (`recording/<id>?inc=artist-rels+place-rels+releases`).

Only recordings linked to the original movements are included. MusicBrainz files most transcriptions (guitar, viola, marimba …) under separate arrangement works, so those are not in this snapshot yet.

### Row format

| Key | Meaning |
|---|---|
| `n` | performer names as credited |
| `a` | their MusicBrainz artist IDs |
| `y` | recording years |
| `m` | six numbers, one per suite; bit *i* set = movement *i* recorded |
| `f` | year of first release |
| `l` | 1 if marked as a live recording |
| `ins` | instruments credited |
| `roles` | performer → instrument |
| `pl` | places "recorded at" |
| `r` | earliest official release: [release ID, title] |
| `rep` | one representative recording ID |

### Known limits

- MusicBrainz sometimes holds one performance as several unmerged recordings. When those have no date, they can show up here as a separate "undated" entry. These are flagged on the site.
- Grouping by year cannot separate two different performances by the same artist in the same year.

Re-import with `python scripts/import_musicbrainz.py data/sources/musicbrainz-cello-suites.json`. Files already linked to MusicBrainz are updated without overwriting anything a contributor wrote.
