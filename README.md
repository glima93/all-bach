# All Bach

An open archive of recordings of Johann Sebastian Bach, catalogued by BWV number, with links to where each recording can be heard.

The pilot covers the Well-Tempered Clavier (BWV 846–893), the Goldberg Variations (BWV 988), Bach's music for unaccompanied strings (the Sonatas and Partitas for solo violin, BWV 1001–1006, and the Cello Suites, BWV 1007–1012) the Brandenburg Concertos (BWV 1046–1051) and the Orchestral Suites (BWV 1066–1070). That is 1,916 recordings, most of them imported from [MusicBrainz](https://musicbrainz.org) (CC0) and listed as drafts until a contributor checks them.

## How it works

```
data/
  works/          one file per BWV number (1007.yaml, 1046a.yaml, anh-3.yaml)
  recordings/     one file per recorded performance (mstislav-rostropovich-1991.yaml)
  sources/        source snapshots used for imports, with notes on how they were made
schema/           JSON Schemas for both file types
scripts/
  validate.py              checks every file; runs on each pull request
  build.py                 turns the data into the website (site/index.html)
  import_musicbrainz.py    creates or updates recording files from a MusicBrainz snapshot
site-template/    the page design
```

**Works** are the backbone: one entry per BWV number with title, key, scoring and movements. BWV numbers are stored as text so variants (`1046a`) and appendix numbers (`Anh. 3`) fit.

**Recordings** are performances. A remaster or reissue of the same performance is an extra link on the same recording, never a new file. Each recording lists which works it contains, and whether each is complete or an excerpt (with the movements named).

**Links** point to listening services (Spotify, Apple Music, YouTube, Idagio …). The site never calls a streaming API; links are stored as plain URLs.

## What comes next

The rest of the catalogue, BWV 1–1128, is split into 47 more collections and 36 scheduled runs: see [docs/catalogue-plan.md](docs/catalogue-plan.md) and the list in [data/plan/collections.yaml](data/plan/collections.yaml).

## Run it locally

```
pip install pyyaml jsonschema
python scripts/validate.py
python scripts/build.py
open site/index.html
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: copy a file, fill in what you know, list what you don't under `help_wanted`, open a pull request.

## Decisions still open

- **Data licence.** CC0 (as MusicBrainz uses) makes the data easiest to reuse.
- **Arrangements.** Currently in scope, tagged with `arrangement: true`.
- **Work data source.** Titles and movements are entered by hand for now; importing from Bach Digital (CC BY-NC) or Wikidata is the likely next step for the full catalogue.
