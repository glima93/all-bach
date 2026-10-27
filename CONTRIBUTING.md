# Contributing to All Bach

Thank you for helping. Every recording on the site is a small YAML file, and adding one takes a few minutes.

## Rules of thumb

1. **One file = one performance.** A remaster, a box-set reissue or the same album on another service is a new *link* in the existing file. A performer who recorded a work twice gets two files.
2. **Name the file after the main performer's full name and the recording year:** `pierre-fournier-1960.yaml`. If the year is unknown, use `-undated` (`lucia-swarts-undated.yaml`) and rename once someone finds the year. The `id` inside the file must match the file name.
3. **Use BWV numbers as text, in quotes:** `bwv: "1007"`, `bwv: "1046a"`, `bwv: "Anh. 3"`.
4. **Only state what you can check.** Leave a field empty (`null` or `[]`) rather than guess, and add the missing fact to `help_wanted`. The site shows these as open questions.
5. **Clean links.** Remove everything after the `?` in streaming URLs (`?si=…`, `utm_…`). The validator rejects tracking parameters.
6. **Excerpts.** If a recording has only some movements, set `complete: false` and list them using the movement names from the work file.

## Adding a recording

1. Search the work's page on the site, or `data/recordings/`, to make sure it isn't there already.
2. Copy an existing recording file and edit it. Field meanings are in `schema/recording.schema.json`.
3. Run `python scripts/validate.py` (optional; it also runs automatically on your pull request).
4. Open a pull request. Say where your facts come from (booklet, label catalogue, discography).

## Adding a work

Works are added before their recordings. Create `data/works/<bwv>.yaml` following `schema/work.schema.json`. Movement names in the work file are the names recordings must use for excerpts, so use the spelling of the standard edition.

## Recordings imported from MusicBrainz

Most entries were imported from [MusicBrainz](https://musicbrainz.org) and carry a `musicbrainz` block with the IDs they came from. Edit these files like any other: the importer only fills empty fields, so your corrections survive a re-import. If an entry is wrong at the source (a mislinked track, a wrong date), it helps to fix it on MusicBrainz too. How the snapshot was made is described in `data/sources/README.md`.

## Review

New recordings start as `status: draft`. A second contributor checks the facts against a primary source and sets `status: reviewed`, removing any `help_wanted` items that are now answered.

## Vocabulary

| Field | Values |
|---|---|
| `instrument` | cello, baroque-cello, violoncello-piccolo, violoncello-da-spalla, viola, viola-da-gamba, violin, guitar, lute, harpsichord, piano, organ, clavichord, ensemble, voices-and-instruments, other |
| `performance_practice` | historical (period instruments), modern, unknown |
| `links[].platform` | spotify, apple-music, youtube, youtube-music, idagio, qobuz, tidal, deezer, presto, label, archive-org, other |
| `status` | draft, reviewed |

`arrangement: true` is for transcriptions to another medium (the cello suites on guitar). Instrument choices Bach's sources allow, such as a violoncello piccolo for Suite No. 6, are not arrangements.
