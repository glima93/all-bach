#!/usr/bin/env python3
"""Turn a MusicBrainz snapshot into recording files, merging with existing ones.

Usage:  python scripts/import_musicbrainz.py data/sources/<snapshot>.json

A snapshot lists *performances*: MusicBrainz recordings grouped by performer
and recording year (see data/sources/README.md for how they were made). It is
either a bare list of rows (the first snapshot, the Cello Suites) or
{"works": [BWV, ...], "native": [instrument, ...], "rows": [...]}, where
"works" gives the order of the movement masks and "native" the instruments
the music was written for (anything else counts as an arrangement).

Rules:
- A performance whose MusicBrainz recording ID already appears in a file
  (under `musicbrainz.recordings`) updates that file: empty fields are filled,
  nothing a contributor wrote is overwritten. Running the import twice is safe.
- A hand-made file with no MusicBrainz IDs is matched by performer name and
  recording year, or by release year within one year, or, when the file has
  no dates at all, when MusicBrainz knows exactly one performance by that
  performer. Ambiguous cases are left alone; link them by hand by adding
  `musicbrainz: {recordings: [<id>]}` to the file and re-running.
- Everything else becomes a new draft file.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import DATA, load  # noqa: E402

CELLO_SUITES = ["1007", "1008", "1009", "1010", "1011", "1012"]
ALIASES = {"pau casals": "pablo casals"}

# MusicBrainz "[unknown]" artist: no performer to file the recording under.
UNKNOWN_ARTIST = "125ec42a-7229-4250-afc5-e057484327fe"
NO_ARTIST = "eec63d3c-3b81-4ad4-b1e4-7c147d4d2b61"  # MusicBrainz "[no artist]"

# Recordings MusicBrainz links to a collection's works that are not performances of them, per snapshot
# (data/sources/musicbrainz-<id>.json), keyed by representative recording ID, with the reason. Scoped by
# snapshot because a recording mislinked to one collection is often a real performance of another.
# Fix upstream in MusicBrainz too, then remove the entry here.
EXCLUDE_BY_SNAPSHOT = {
  "cello-suites": {
    "04f657f2-dbb1-4b2a-8c4b-e96a1e4f4080": "release is the Orchestral Suites BWV 1066-1069",
    "91db1c6e-aa80-4cfc-8ef5-50639f20bc1e": "release is Rameau's harpsichord works",
    "a81b39e1-c432-4893-a829-295bfd14ae80": "release is orchestral suites by other composers",
    "9cb32a24-055a-4bb5-aa3d-d5e37830ef5a": "release is trio sonatas",
    "0e978aec-44f7-4839-9f8a-d50b3af73f50": "accompaniment-only track of the Burrowes recording",
    "b0554f83-50e2-4505-8a48-628c6dc792c8": "magazine lesson disc, not a performance",
  },
  "violin-solo": {
    "ce8bd6ab-9ac8-497b-9a92-000f6f5440fd": "Bach's own keyboard versions (BWV 964/968), which have their own BWV numbers",
    "631731fb-8ba3-439c-90de-8ba0d8b397c6": "release is a keyboard partita",
    "30537d65-f1fe-4f4b-93f1-f83c2e106151": "release is Schubert and Mozart",
    "60c1ace9-813b-40ff-a960-0b4029adc451": "release is the sonatas for violin and keyboard",
  },
  "orchestral-suites": {
    "8580bc9d-bfdc-4e33-a087-acd8e8497e2c": "release is the keyboard Partitas (a Partita movement linked to the suites)",
  },
  "violin-concertos": {
    "c67b2daf-9898-4c5c-9657-25cdf01bda0f": "organ concerto album: an organ-solo cantata sinfonia linked to the Sinfonia BWV 1045, which has no organ part",
    "218946ea-bf30-42ee-856a-01570345215e": "the Sinfonia of Cantata BWV 29, also linked to the Sinfonia BWV 1045",
    "9ccf2167-f754-41d7-9c3d-2891b22e19c7": "credited to the NBC SO and Toscanini, but the credits name the Kölner Kammerorchester and Müller-Brühl (their recording is already in)",
  },
  "english-suites": {
    "003f5b50-8a64-499c-8939-7238cd181c74": "anime soundtrack cue (Levius) linked to the whole of English Suite No. 1; not a performance of the suite",
    "d39c3301-a203-41aa-87c2-adfd3776a7ab": "Anna Magdalena Notebook album; the English Suites are not in the notebooks, so these are notebook pieces linked to the wrong works",
  },
  "french-suites": {
    "aa7ac922-b9a2-4665-8dab-a584ce9cecac": "Handel Water Music / Royal Fireworks album (Virtuosi of England, Davison); a Handel Bourrée linked to French Suite No. 6",
  },
  "partitas": {
    "863edf6a-8361-4af1-af05-9134987b5b88": "BWV 1019a (early version of violin sonata No. 6), whose harpsichord Corrente is shared with Partita No. 6; belongs with the violin and keyboard sonatas",
    "70f2471c-70e0-487b-8a65-5c32fa2588d4": "BWV 1019a Corrente on a violin and harpsichord sonatas album; belongs with the violin and keyboard sonatas",
    "655ad01a-da3a-46de-8a67-84bbaee43fb0": "BWV 1019a Corrente on a violin and harpsichord sonatas album; belongs with the violin and keyboard sonatas",
    "c40e125e-f63c-42c4-afa5-19701d010416": "BWV 1019a Corrente on a violin and harpsichord sonatas album; belongs with the violin and keyboard sonatas",
    "109724a2-2bfe-4317-938f-43da1b54d92f": "BWV 1019a Corrente on a violin and harpsichord sonatas album; belongs with the violin and keyboard sonatas",
    "829bbd01-412e-4e50-95a7-0a75a1352c80": "BWV 1019a Gavotta (violin and keyboard version of the Tempo di Gavotta of Partita No. 6) on a violin sonatas album",
    "5d1150fa-3592-48f4-93e4-cfee79a18733": "BWV 1019a Corrente on a violin and harpsichord sonatas album; belongs with the violin and keyboard sonatas",
    "7c9c0660-1fb7-4be8-b163-ecb062ed16c4": "BWV 1019a Corrente on a violin and keyboard sonatas album; belongs with the violin and keyboard sonatas",
    "828fe900-39f9-4f84-b1f8-ce6bad81dcec": "BWV 1019a Corrente (Moroney, from the violin sonatas in the Bach 2000 edition); belongs with the violin and keyboard sonatas",
    "bc8c930f-8b2f-43c0-965e-50895b0fc932": "BWV 1019a Corrente on an album of works for violin and continuo; belongs with the violin and keyboard sonatas",
    "63cdc074-c888-43c6-a1a3-a4d105021911": "Rachmaninoff compilation: the Sarabande is his 1925 recording again (already filed) and the Prelude is his transcription of the violin Partita BWV 1006 Prelude",
    "ce4f1573-a2dc-4a80-ab43-12a90900fc89": "solo violin Sonatas and Partitas album; a violin Partita movement linked to the keyboard Partita No. 1",
  },
  "inventions-sinfonias": {
    "91a8cca1-ff26-446d-bca6-132a9cba0f57": "anime soundtrack cue (A Silent Voice, Kensuke Ushio) linked to an Invention; not a performance of it",
  },
  "art-of-fugue": {
    "9c436181-2b3a-4396-bc07-bcc79d4f5cd0": "credited to Joachim-Ernst Berendt, the writer who compiled the album (Hinübergehen); the performers are not named",
  },
  "harpsichord-concertos": {
    "f8df5ad3-0db2-4dc7-be48-a55397f60b20": "credited to Antonio Vivaldi (composer of the model of BWV 1065) on a Vivaldi compilation; the performers are unknown",
  },
}
EXCLUDE: dict[str, str] = {}  # the current snapshot's entries, set in main()

# One performance that the snapshot splits into two rows (an undated track of a dated set, one set recorded
# over more than three years), per snapshot: representative recording ID of the row to fold in -> that of
# the row it belongs to, with the reason.
JOIN_BY_SNAPSHOT = {
  "inventions-sinfonias": {
    "3bb5b4c3-2e46-4d84-9e77-66eae6f8f5fe": ("c9f09be8-36fc-4c19-add9-6ffffd9d1fef",
        "Schiff's only piano Inventions and Sinfonias (Decca, Kingsway Hall 1983), reissued undated on a compilation"),
    "7e209493-cdab-41d4-8595-1b03a653740a": ("ec241ec0-15b6-4840-a01d-e17b089a75dd",
        "Gould's Columbia Inventions and Sinfonias, one set recorded at the CBS 30th Street Studio 1963-64"),
  },
  "partitas": {
    "e61035ee-d065-40d2-8cb2-5add49b6c154": ("1074a276-1df5-47d6-a7f3-00584d8c6153",
        "Sempe's Menuet of Partita No. 4: same release and place, the one movement missing from the 1993 set"),
    "58f363b5-bb9c-4a75-a4cd-c78d1832481a": ("eb290672-d115-4baa-8257-cb5e408b9333",
        "Leonhardt's Partitas for Harmonia Mundi, one released set recorded at Schloss Kirchheim 1963-70"),
  },
}

# Facts the snapshot gets wrong or leaves out for one row, per snapshot: representative recording ID ->
# fields to set, with the reason. Fix upstream in MusicBrainz too, then remove the entry here.
OVERRIDE_BY_SNAPSHOT = {
  "clavier-ubung-ii": {
    "d85ae950-852b-4653-9c50-fa55854acca8": ({"instrument": "fortepiano"}, "Toby Sermeus, Bach's Piano Silbermann 1749: a Silbermann fortepiano copy"),
    "99b8b346-9242-47ba-aa2e-9edf474555e3": ({"instrument": "organ"}, "Kei Koito, organist, on Organ Masterworks Vol. II; no instrument credit"),
    "4f9b9334-7385-4086-9dec-d9c327346b01": ({"performers": [{"name": "Dubravka Tomšič", "role": "piano"}], "instrument": "piano"},
        "the Italian Concerto is solo: the orchestra and conductor are credited for the violin concertos on the same album"),
  },
  "art-of-fugue": {
    "fb15748c-f29d-402e-9501-e9c741242024": ({"arrangement": True}, "oboe d'amore, bass oboe, cor anglais and bassoon (Paillard's 1977 Erato set): winds are an arrangement for the open-score work"),
    "7d6d9d6d-4317-4799-8c28-07160f62e765": ({"instrument": "harpsichord"}, "Lengellé and Morabito, the two-harpsichord pieces of the 1977 Erato set"),
    "7e58f597-0139-4696-b120-6e3ed94fd70e": ({"instrument": "fortepiano"}, "Toby Sermeus, Bach's Piano Silbermann 1749: a Silbermann fortepiano copy"),
    "bd5461d4-c2cb-4cb3-91fe-bc445e944866": ({"instrument": "piano"}, "Konstantin Lifschitz, pianist; no instrument credit"),
    "45f5123b-b84a-42d1-992b-7f3d2fe15376": ({"instrument": "piano"}, "Schaghajegh Nosrati, pianist; no instrument credit"),
    "69fd0e65-3041-47ca-9bfd-1482b1908e8e": ({"instrument": "piano"}, "Albert Cano Smit, pianist; no instrument credit"),
    "51112582-8d25-44f4-aa5a-3339574614b4": ({"instrument": "organ"}, "Wolfgang Rübsam, Das Orgelwerk; no instrument credit"),
  },
  "inventions-sinfonias": {
    "941ed019-30d3-43be-abe7-731c7665bdcd": ({"arrangement": True}, "Carl Palmer (ELP drummer), Works Volume 1: a rock arrangement"),
    "7891f183-69bc-4eae-951e-69795408202d": ({"arrangement": True}, "Don Dorsey's Bachbusters: synthesizer arrangements"),
    "149a2ed4-5d36-4981-892d-bcd31aefa4e1": ({"arrangement": True}, "Romain Leleu (trumpet) and Thomas Leleu (tuba)"),
    "25e4d294-e1c4-4786-a699-fabe8461e159": ({"arrangement": True}, "Rachel Podger (violin) and Alex Rolton (cello), Duologues"),
    "e55cab64-65f0-410b-b093-6099f0d8755c": ({"arrangement": True}, "Bach re-invented: Dinnerstein with Absolute Ensemble and Järvi, a crossover arrangement"),
    "3e282955-dcaf-4450-a291-cf4d31adf579": ({"instrument": "piano"}, "Walter Gieseking, pianist; no instrument credit"),
    "90974026-180b-4449-afb4-f0a3b5240c38": ({"instrument": "piano"}, "Lili Kraus, pianist; no instrument credit"),
    "d39aa73c-c110-47a5-94de-22716f25fd2e": ({"instrument": "piano"}, "João Carlos Martins, pianist; no instrument credit"),
    "e108e081-d02a-4eae-9d5d-f695dfcd33fa": ({"instrument": "piano"}, "Simone Dinnerstein, pianist; no instrument credit"),
    "987ac9a2-aeaa-4efc-a969-f029dcafb85d": ({"instrument": "piano"}, "Claudio Colombo, pianist; no instrument credit"),
    "64763adb-825f-4d41-ae5f-6d297b1fcce0": ({"instrument": "piano"}, "Dan Tepfer, pianist; the Inventions are played as written between his own Reinventions"),
    "2b4fdf38-9319-46c9-a7d6-bccde298c1d8": ({"instrument": "piano"}, "Alexander Borovsky, pianist; no instrument credit"),
    "5091c92c-e0a7-4b2e-8f59-945f7d1bfa92": ({"arrangement": False}, "Suzuki Piano School recording: the original text on piano, not an arrangement"),
    "9b1b43ba-ab99-4392-8650-7d65a64bc506": ({"instrument": "ensemble"}, "a big band; guitar came from one sideman's credit"),
    "d1d94280-247a-4953-bcd6-471444d92973": ({"performers": [{"name": "Stick&Bow", "role": "marimba and cello"},
                                                             {"name": "Luc Beauséjour", "role": "harpsichord"}],
                                              "instrument": "ensemble", "arrangement": True},
        "two Sinfonias on Stick&Bow and Beauséjour's trio-sonata album; the keyboard-soloist rule kept only Beauséjour"),
    "d450c82a-5373-46d3-ba5c-1df687b73807": ({"arrangement": True}, "Satoru Shiota, jazz pianist, on his solo album piano solo = solo salt"),
    "47d46da6-b109-4188-a280-0b774ece9cfc": ({"instrument": "ensemble", "arrangement": True},
        "eight players, live, in two-voice Inventions: an ensemble arrangement, not one keyboard"),
    "795d4a75-14cc-4d33-872e-8b6828463af9": ({"instrument": "ensemble"},
        "Da Gamba: organ, violin, harpsichord and two gambas credited across the album; which play the Invention is not known"),
  },
  "partitas": {
    "56df13cd-74c2-4bc9-ab40-aa572b5e7fe5": ({"instrument": "fortepiano"},
        "Bach's Piano Silbermann 1749: played on a copy of a Silbermann fortepiano, credited as piano"),
    "09cdac89-6f97-48a0-bdd7-12adbe65371d": ({"instrument": "viola"}, "Nobuko Imai is a violist; credited as violin"),
    "65486ec9-196a-44e6-b027-65f435161e14": ({"arrangement": False},
        "the complete Partita No. 1 on piano, released as the soundtrack of Akerman's A Couch in New York"),
    "e19a63f5-6db5-4619-af99-54df75369aa4": ({"instrument": "piano"}, "Jeremy Denk, pianist; no instrument credit"),
    "933c0e72-eee3-4ffd-a549-0a34645e5382": ({"instrument": "piano"}, "Francesco Tristano, pianist; no instrument credit"),
    "f0b13d7d-2258-4b9d-9177-570322800e9c": ({"instrument": "piano"}, "Anatoly Vedernikov, pianist; no instrument credit"),
    "d0b58c22-a1ae-48ab-a09a-7ab5f79d3f8d": ({"instrument": "piano"}, "Maria Grinberg, pianist; no instrument credit"),
    "d9a1de01-19b6-48ef-8548-d5bb647b9c30": ({"instrument": "piano"}, "David Theodor Schmidt, pianist; no instrument credit"),
  },
}

INSTRUMENTS = {
    "cello": "cello", "violoncello": "cello",
    "baroque cello": "baroque-cello", "baroque violoncello": "baroque-cello",
    "violoncello piccolo": "violoncello-piccolo", "five-string cello": "violoncello-piccolo",
    "violoncello da spalla": "violoncello-da-spalla", "viola da spalla": "violoncello-da-spalla",
    "viola": "viola", "viola da gamba": "viola-da-gamba", "violin": "violin",
    "baroque violin": "baroque-violin",
    "guitar": "guitar", "classical guitar": "guitar", "acoustic guitar": "guitar",
    "lute": "lute", "harpsichord": "harpsichord", "piano": "piano", "grand piano": "piano",
    "organ": "organ", "pipe organ": "organ", "clavichord": "clavichord", "fortepiano": "fortepiano",
    "harpsichord / cembalo": "harpsichord", "cembalo": "harpsichord",
    "lautenwerck": "harpsichord", "tangent piano": "fortepiano", "lute-harpsichord": "harpsichord",
    "flute": "flute", "transverse flute": "flute", "concert flute": "flute",
    "baroque flute": "traverso", "traverso": "traverso", "flauto traverso": "traverso",
    "transverse flute (baroque)": "traverso", "recorder": "recorder", "alto recorder": "recorder",
    "treble recorder": "recorder", "oboe": "oboe", "baroque oboe": "oboe",
}
IMPLIED = {"1048": {1: [0, 2]},
           "811": {4: [3]}}  # the Double of English Suite No. 6 is usually on the Sarabande's track
CELLO_FAMILY = ["cello", "baroque-cello", "violoncello-piccolo", "violoncello-da-spalla"]
HISTORICAL = {"baroque-cello", "violoncello-piccolo", "violoncello-da-spalla", "viola-da-gamba", "baroque-violin",
              "harpsichord", "clavichord", "fortepiano"}
MODERN = {"piano"}
KEYBOARD = ["harpsichord", "piano", "clavichord", "organ", "fortepiano"]
# Chamber mode: instruments that usually play the continuo, so a credit for one of them alone does not say
# what the solo part was played on.
CONTINUO = {"harpsichord", "piano", "organ", "fortepiano", "lute", "cello", "baroque-cello", "viola-da-gamba"}
HISTORICAL_LEAD = {"baroque-violin", "baroque-cello", "viola-da-gamba", "traverso", "recorder"}

# Orchestral and other ensemble works (snapshot native ["ensemble"]): the group plays; what needs
# working out is whether the group plays period instruments, and whether it is an arrangement.
GROUP_TYPES = {"Orchestra", "Group", "Choir"}
# Credits that only a period-instrument performance has.
PERIOD_INSTRUMENT = re.compile(r"baroque|natural (horn|trumpet)|corno da caccia|traverso|transverse flute \(baroque\)")
# Ensembles that play on period instruments. Matched against performer names, so it also
# catches them when MusicBrainz gives no instrument credits.
PERIOD_ENSEMBLE = re.compile(
    r"baroque|barock|barroc|baroc|antiqua|alte musik|ancient music|concentus musicus|leonhardt|collegium aureum|"
    r"petite bande|english concert|taverner|brandenburg consort|giardino armonico|concerto italiano|bach collegium|"
    r"europa galante|age of enlightenment|tafelmusik|concert des nations|caf. zimmermann|dunedin consort|concerto copenhagen|"
    r"musiciens du louvre|zefiro|gardellino|b.rock|\barcangelo\b|accademia bizantina|apollo.s fire|capriccio stravagante|"
    r"freiburger|netherlands bach society|nederlandse bachvereniging|pratum integrum|la stravaganza|collegium musicum 90|"
    r"orchestra of the antipodes|australian brandenburg|concerto k.ln|kammerakademie|cantus c.lln|il pomo d.oro|"
    r"les arts florissants|le concert d.astr.e|ensemble 415|harmonie universelle|sonnerie|la serenissima|"
    r"academy of ancient|monteverdi|english baroque|holland baroque|il complesso barocco|modo antiquo|ensemble 1700|"
    r"incogniti|florilegium|freitagsakademie|hanover band|musica florea|simphonie du marais|ensemble caprice|"
    r"wiener akademie|eighteenth century|new london consort|linde consort|schola cantorum basiliensis|musica amphion|"
    r"combattimento|harmony of nations|nova stravaganza|muses galantes|new dutch academy|magnifica comm?unit|"
    r"dantone|beznosiuk|barok|ensemble masques|les surprises|il fondamento|concert fran.ais|insula orchestra|"
    r"early music|voices of music|tulipa consort|trillium consort|apollon ensemble|american bach soloists|"
    r"ama deus|madeuf|blumenstock|boulder bach festival|king.s consort|musica alta ripa|musica alchemica|harmonie des saisons|"
    r"voce strumentale|capella academica wien|helicon ensemble|mosa.ques|talens lyriques|caravans.rail|retrospect ensemble|"
    r"capricornus|ensemble odyss|parlement de musique|phantasm|fretwork|hesp.rion|suonar parlante|les r.cr.ations", re.I)
# Modern-instrument groups whose names would otherwise match PERIOD_ENSEMBLE or whose credits mention period instruments.
MODERN_ENSEMBLE = re.compile(r"m.nchener bach|kammerakademie potsdam|zurich baroque ensemble|^baroque chamber orchestra|"
                             r"hamburg symphony baroque|festival baroque orchestra|berliner barock solisten|french baroque orchestra", re.I)
# Credits or names that mean the music was arranged for other forces (jazz trio, brass band, synthesizer …).
ARRANGED = re.compile(r"drum|saxophone|synthesi[sz]er|moog|electric|accordion|marimba|vibraphone|tuba|"
                      r"clarinet|banjo|mandolin|ukulele|harmonica|beatbox|bass guitar|guitar", re.I)
ARRANGED_NAMES = re.compile(r"brass|blechbl|\bsax(ophone?)?\b|swingle|jazz|loussier|guitar|gitarr|switched.on|synth|\bbeat\b|"
                            r"loeki|seldom sene|baby einstein|babies|sweet little band|pink mice|\bthe nice\b|"
                            r"\ble orme\b|softcore|camarata|mantovani|rond. veneziano|stringfever|colliery|crusaders|"
                            r"percussion|duckmandu|galliano|trombone|alfee|moorhouse|anugama|dan gibson|syrinx|"
                            r"early learning centre|malmsteen|alkaloid|allegaeon|drinkall|\bfragile\b|ritenour|max richter|pieranunzi|alperin|dellarole|allhoff|joachim k.hn", re.I)
# In orchestral works only: names of groups that are not orchestras, so play the music arranged.
ARRANGED_GROUP_NAMES = re.compile(r"quartet|quartett|quatuor|quartetto|\bcellos\b|(?<!hanover )\bband\b|"
                                  r"trumpet ensemble|brass|\btrio\b", re.I)
# In ensemble works with a scoring: solo wind and other obbligato instruments credited that the work is not
# written for mean an arrangement (a flute and an oboe in the double violin concerto, a violoncello piccolo
# for the second violin, a piccolo trumpet in a violin concerto), checked against the scoring of the works the
# recording plays when it plays only one. Continuo, string-section and recorder credits (often from other tracks of the album) are not checked.
OBBLIGATO = re.compile(r"flute|traverso|oboe|trumpet|horn|clarinet|violoncello piccolo|gamba", re.I)
# Release titles that say the performance is on period instruments.
PERIOD_RELEASE = re.compile(r"(antique|period|original) instruments", re.I)
# Keyboard concertos (BWV 1052–1065): works whose scoring starts with the solo harpsichord(s).
KEYBOARD_SOLO = re.compile(r"^(\d+ )?harpsichords?\b", re.I)
# In a keyboard concerto, melody soloists that mean a reconstruction for the lost original instrument.
RECONSTRUCTED_SOLO = re.compile(r"violin|oboe|flute|trumpet", re.I)
# Credits MusicBrainz lists among instruments that name no instrument ("solo" from "solo piano" credits).
NOT_INSTRUMENTS = {"solo"}
# Performer names that are groups even when MusicBrainz gives no artist type.
SCORINGS: dict[str, str] = {}  # scoring of each work, set in main()
GROUP_NAME = re.compile(r"\bensemble\b|orchest|consort|collegium|camerata|soloists|sinfonia", re.I)
# Release titles that mean an arrangement (film and game soundtracks, lessons, nursery and relaxation albums).
ARRANGED_RELEASES = re.compile(r"soundtrack|learn to play|nursery|lullab|\bbaby\b|babies|bossa|switched.on|"
                               r"\bspa\b|for sleep|relaxation|relaxing|meditation|stress relief|healing|tune your brain|lifescapes|suzuki|dangerous liaisons|פסקול|motion picture|movies go baroque|bach minimaliste|"
                               r"concertos? for recorder|bachbusters|production music|bedtime|majors for minors|f.r inl.rning|classical background|サウンドトラック", re.I)

# Open-score works (mode "open", the Art of Fugue): keyboards, strings, viols and orchestra are native (plan note);
# winds, brass, saxophones, recorders, guitars and crossover groups play it arranged. Credits, then group names.
OPEN_ARRANGED = re.compile(r"recorder|blockfl|brass|trumpet|trombone|saxophon|guitar|accordion", re.I)
OPEN_ARRANGED_NAMES = re.compile(r"(?<!hanover )\bband\b|recorder|blockfl|quinta essentia|cellisten|laibach", re.I)

# Keyboard works: a release title that names the instrument, for a lone performer with no instrument credit.
KEYBOARD_RELEASE = re.compile(r"\b(harpsichord|cembalo|piano)\b|pour (clavecin)", re.I)
INSTRUMENTS_EXTRA = {"clavecin": "harpsichord"}

class Flow(list):
    """A list written in YAML flow style: [a, b]."""


class FlowDict(dict):
    """A mapping written in YAML flow style: { a: 1 }."""


def _dumper():
    class D(yaml.SafeDumper):
        pass
    D.add_representer(Flow, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True))
    D.add_representer(FlowDict, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v.items(), flow_style=True))
    D.add_representer(type(None), lambda d, _: d.represent_scalar("tag:yaml.org,2002:null", "null"))
    return D


def norm(name: str) -> str:
    s = re.sub(r"[‐-―'’]", " ", name.split(",")[0])
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]+", " ", s)
    s = " ".join(s.split())
    return ALIASES.get(s, s)


def slug_for(rec: dict) -> str:
    """Full performer name as a slug; falls back to the MusicBrainz artist ID for non-Latin names, including
    ones that mix in a few Latin look-alike letters (Cyrillic with Latin e and o), which would slug to junk."""
    name = rec["performers"][0]["name"]
    s = norm(name).replace(" ", "-")
    if any(ch.isalpha() and "LATIN" not in unicodedata.name(ch, "") for ch in name):
        s = ""
    if not s:
        artist = (rec.get("musicbrainz") or {}).get("artist", "")
        s = f"artist-{artist[:8]}" if artist else "unknown"
    return s


def year(s) -> int | None:
    return int(str(s)[:4]) if s else None


def movement_names() -> dict[str, list[str]]:
    return {w["bwv"]: w["movements"] for _, w in load("works")}


PAIRED = re.compile(r"^(?:[IVXL]+\.\s*)?(\w+?)t? II(?: - .*da capo| ou .*)?$")


def second_dance(first: str, second: str) -> bool:
    """Whether `second` is the second of a pair of dances whose first is `first`: "Menuet II" after "Menuet I",
    "VII. Bourrée II - Bourrée I da capo" after "VI. Bourrée I", "Passepied II …" after "Passepied I en Rondeau".
    A second dance that stands on its own ("Courante II avec deux Doubles") does not match."""
    if second.endswith(" II") and first == second[:-1]:
        return True
    m = PAIRED.match(second)
    return bool(m) and re.match(rf"^(?:[IVXL]+\.\s*)?{re.escape(m.group(1))}t? I\b", first) is not None


def expand(c: dict, bwvs: list[str], moves: dict[str, list[str]]) -> dict:
    """Snapshot rows are compact; turn one into the shape the importer works with.

    Row keys: n performer names, a artist MBIDs, y recording years, m one bitmask
    per work in snapshot order (bit i = movement i present), f first release year,
    l live, t artist types (Person, Orchestra …) in the order of a,
    ins instruments credited, roles {performer: instrument}, pl places
    recorded at, r [release MBID, title], rep representative recording MBID.
    """
    # Masks were built with JavaScript bitwise operators, which are signed 32-bit:
    # a work with 32 movements all present comes out as -1. Undo that.
    masks = [int(x) % 2**32 if int(x) < 0 else int(x) for x in c["m"].split(",")]
    mv = []
    for bwv, mask in zip(bwvs, masks):
        if mask >> len(moves[bwv]):
            raise SystemExit(f"Row {c['rep']}: BWV {bwv} has more movements in MusicBrainz than in data/works/{bwv}.yaml")
        names = moves[bwv]
        have = {i for i in range(len(names)) if mask >> i & 1}
        # Paired dances (Menuet I / Menuet II) are often one track in MusicBrainz,
        # linked only to the first: count the second as recorded too.
        have |= {i for i in range(1, len(names)) if i - 1 in have and second_dance(names[i - 1], names[i])}
        # Movements that rarely get a track of their own: the two-chord Adagio of Brandenburg
        # No. 3 is usually joined to a neighbouring track. Count it when both outer movements are there.
        for i, needs in IMPLIED.get(bwv, {}).items():
            if all(n in have for n in needs):
                have.add(i)
        mv += [f"{bwv}:{i}" for i in sorted(have)]
    return {
        "names": c["n"], "ids": c["a"], "types": c.get("t") or [],
        "years": [y for y in c["y"] if int(y) >= 1888], "mv": mv,  # MusicBrainz date typos (1107 for 1991)
        "firstRelease": c.get("f"), "live": bool(c.get("l")),
        "ins": c.get("ins") or [], "roles": c.get("roles") or {},
        "places": c.get("pl") or [],
        "releases": [{"id": c["r"][0], "title": c["r"][1]}] if c.get("r") else [],
        "repId": c["rep"], "recIds": [c["rep"]],
    }


def keyboard_soloist(c: dict, native: set[str]) -> dict:
    """Keyboard works: an orchestra and conductor credited with a pianist or harpsichordist (an encore at a
    concerto concert) file the recording under the keyboard player alone."""
    types = c.get("t") or []
    roles = c.get("roles") or {}
    if not any(t in GROUP_TYPES for t in types):
        return c
    keep = [i for i, n in enumerate(c["n"]) if INSTRUMENTS.get((roles.get(n) or "").lower()) in native
            and i < len(types) and types[i] == "Person"]
    if len(keep) != 1:
        return c
    i = keep[0]
    return {**c, "n": [c["n"][i]], "a": [c["a"][i]], "t": [types[i]], "roles": {c["n"][i]: roles[c["n"][i]]},
            "ins": [x for x in c.get("ins") or [] if x.lower() not in NOT_INSTRUMENTS] or c.get("ins")}


def instrument_of(perf: dict, native: set[str]) -> tuple[str, list[str], dict]:
    """Main instrument, other instruments credited, and per-performer roles.

    The main instrument is the first credited one the music was written for;
    failing that, the first credited instrument of any kind.
    """
    roles = {k: v.lower() for k, v in perf["roles"].items()}
    credits = [i for i in perf["ins"] if i.lower() not in NOT_INSTRUMENTS]
    if not credits:
        return "unknown", [], roles
    mapped = [(i, INSTRUMENTS.get(i.lower(), "other")) for i in credits]
    main = next((m for _, m in mapped if m in native), None)
    if main is None and len({m for _, m in mapped}) >= 3:
        return "ensemble", [], roles  # a string trio or similar group arrangement
    main = main or mapped[0][1]
    main_label = next(i for i, m in mapped if m == main)
    others = [i for i, m in mapped if i != main_label and m != main]
    return main, others, roles


def in_scoring(instrument: str, scoring: str) -> bool:
    """Whether a credited instrument is one the work is written for (scoring text of data/works/)."""
    i, sc = instrument.lower(), scoring.lower()
    # Continuo keyboards count; plain "strings" does not, so a violinist or cellist alone on a suite (the Air
    # with piano) is a transcription, while the violinist named in a violin concerto's scoring is a soloist.
    if re.search(r"harpsichord|organ|cembalo", i) and "continuo" in sc:
        return True
    word = re.sub(r"^(baroque|natural|piccolo|transverse|french) ", "", i).split(" ")[0].rstrip("s")
    return bool(word) and word in sc


def ensemble_of(perf: dict, scoring: str = "") -> tuple[str, str, bool, list[str]]:
    """For an ensemble work: instrument, performance practice, arrangement, instruments to mention."""
    roles = {v.lower() for v in perf["roles"].values()}
    ins = [i.lower() for i in perf["ins"]]
    names = " ".join(perf["names"])
    group = (any(t in GROUP_TYPES for t in perf["types"]) or roles & {"conductor", "orchestra"}
             or len(perf["names"]) >= 3 or len(set(ins)) >= 3 or bool(GROUP_NAME.search(names)))
    arranged = [i for i in perf["ins"] if ARRANGED.search(i)]
    if scoring and group:
        played = {m.split(":")[0] for m in perf["mv"]}
        if len(played) == 1:  # with several works, the album's credits may belong to the other one
            own = SCORINGS.get(next(iter(played)), "")
            arranged += [i for i in perf["ins"] if OBBLIGATO.search(i) and not in_scoring(i, own)]
    played = {m.split(":")[0] for m in perf["mv"]}
    keyboard_solo = bool(played) and all(KEYBOARD_SOLO.match(SCORINGS.get(b, "")) for b in played)
    kb_credit = any(INSTRUMENTS.get(i) in KEYBOARD for i in ins)
    single = len(played) == 1 or all(SCORINGS.get(b, "").lower().startswith("harpsichord") for b in played)
    if keyboard_solo and group and not kb_credit and single:
        # A keyboard concerto with a violin, oboe or other melody soloist and no keyboard credited: one of the
        # reconstructions for the lost original instrument (BWV 1052R, 1056R, 1060R …).
        arranged += [i for i in perf["ins"] if RECONSTRUCTED_SOLO.search(i) and i not in arranged
                     and not any(in_scoring(i, SCORINGS.get(b, "")) for b in played)]
    if keyboard_solo and "organ" in {INSTRUMENTS.get(i) for i in ins} and not {INSTRUMENTS.get(i) for i in ins} & {"harpsichord", "piano", "fortepiano"}:
        arranged += [i for i in perf["ins"] if INSTRUMENTS.get(i.lower()) == "organ" and i not in arranged]  # organ for harpsichord
    release = " ".join(r["title"] for r in perf["releases"])
    if (arranged or ARRANGED_NAMES.search(names) or "Choir" in perf["types"] or ARRANGED_RELEASES.search(release)
            or (scoring and ARRANGED_GROUP_NAMES.search(perf["names"][0]))):
        main = "ensemble" if group else (INSTRUMENTS.get(ins[0], "other") if ins else "unknown")
        return main, "unknown", True, arranged
    if group:
        period = (any(PERIOD_INSTRUMENT.search(i) for i in ins) or bool(PERIOD_ENSEMBLE.search(names))
                  or bool(PERIOD_RELEASE.search(release))) \
            and not MODERN_ENSEMBLE.search(perf["names"][0])
        credited = {INSTRUMENTS.get(i) for i in ins}
        modern = keyboard_solo and "piano" in credited and not credited & HISTORICAL  # a piano soloist (plan note)
        return "ensemble", "historical" if period else "modern" if modern else "unknown", False, []
    if ins:
        main = INSTRUMENTS.get(ins[0], "other")
        if keyboard_solo and all(INSTRUMENTS.get(i) in set(KEYBOARD) - {"organ"} for i in ins):
            # Keyboard concertos: a harpsichordist or pianist credited alone is the soloist of a concerto
            # performance whose orchestra is not credited, except a pianist in a slow middle movement alone
            # (the Largo of BWV 1056 and others circulate as solo piano pieces).
            only_middle = all(m.split(":")[1] == "1" for m in perf["mv"])
            if main == "piano" and only_middle:
                return main, "unknown", True, []
            release_period = main != "piano" and bool(PERIOD_RELEASE.search(release))
            return "ensemble", "modern" if main == "piano" else "historical" if release_period else "unknown", False, []
        if scoring:
            # One or two players with credits: soloists named on a compilation when every instrument credited
            # is in the work's scoring (a trumpeter in Brandenburg No. 2); otherwise a transcription.
            if all(in_scoring(i, scoring) for i in ins) and not all(INSTRUMENTS.get(i) in KEYBOARD for i in ins):
                return "ensemble", "unknown", False, []
            return main, "unknown", True, []
        bwvs = {m.split(":")[0] for m in perf["mv"]}
        if main in KEYBOARD and bwvs - {"1050"}:
            return main, "unknown", True, []
        return "ensemble", "unknown", False, []
    return "unknown", "unknown", False, []


def works_block(perf: dict, bwvs: list[str], moves: dict[str, list[str]]) -> list:
    out = []
    have = set(perf["mv"])
    for bwv in bwvs:
        idx = [i for i in range(len(moves[bwv])) if f"{bwv}:{i}" in have]
        if not idx:
            continue
        if len(idx) == len(moves[bwv]):
            out.append(FlowDict(bwv=bwv, complete=True))
        else:
            out.append(FlowDict(bwv=bwv, complete=False, movements=Flow(moves[bwv][i] for i in idx)))
    return out


def mb_links(perf: dict) -> list[dict]:
    links = [{"platform": "musicbrainz", "kind": "release",
              "url": f"https://musicbrainz.org/release/{r['id']}", "title": r["title"]} for r in perf["releases"]]
    if not links:
        links.append({"platform": "musicbrainz", "kind": "page",
                      "url": f"https://musicbrainz.org/recording/{perf['repId']}", "title": None})
    return links


def help_items(rec: dict, same_performer: int) -> list[str]:
    items = []
    if not rec["recorded"]["years"]:
        items.append("Recording year")
        if same_performer > 1:
            items.append("Check whether this is the same performance as another entry by this performer")
    if not rec["recorded"]["place"]:
        items.append("Recording place")
    if rec["instrument"] == "unknown":
        items.append("Instrument (MusicBrainz has no instrument credit)")
    if not any(l["platform"] != "musicbrainz" for l in rec["links"]):
        items.append("Streaming links (Spotify, Apple Music, YouTube …)")
    return items


TYPE_ROLE = {"Orchestra": "orchestra", "Choir": "choir", "Group": "ensemble"}


def is_group(perf: dict) -> bool:
    roles = {v.lower() for v in perf["roles"].values()}
    ins = {i.lower() for i in perf["ins"]}
    return bool(any(t in GROUP_TYPES for t in perf["types"]) or roles & {"conductor", "orchestra"}
                or len(perf["names"]) >= 3 or len(ins) >= 3)


def period_group(perf: dict) -> bool:
    return (any(PERIOD_INSTRUMENT.search(i.lower()) for i in perf["ins"])
            or bool(PERIOD_ENSEMBLE.search(" ".join(perf["names"])))) and not MODERN_ENSEMBLE.search(perf["names"][0])


def arranged_credits(perf: dict) -> list[str]:
    return [i for i in perf["ins"] if ARRANGED.search(i)]


def vocal_of(perf: dict) -> tuple[str, str, bool, list[str]]:
    """Vocal works: choir, orchestra and soloists are all native; only jazz, pop and the like are arrangements."""
    arranged = arranged_credits(perf)
    if arranged or ARRANGED_NAMES.search(" ".join(perf["names"])):
        return "voices-and-instruments", "unknown", True, arranged
    return "voices-and-instruments", "historical" if period_group(perf) else "unknown", False, []


def chamber_of(perf: dict, lead: list[str]) -> tuple[str, str, bool, list[str]]:
    """Chamber works: `lead` is the solo part's instrument family, the written instrument first.

    Another orchestral instrument on the solo part (cello for gamba, recorder for flute) is filed as that
    instrument, not as an arrangement; keyboard and other continuo credits alone don't name the solo part.
    """
    arranged = arranged_credits(perf)
    if arranged or ARRANGED_NAMES.search(" ".join(perf["names"])):
        return ("ensemble" if is_group(perf) else INSTRUMENTS.get(arranged[0].lower(), "other") if arranged else "unknown",
                "unknown", True, arranged)
    mapped = [INSTRUMENTS.get(i.lower(), "other") for i in perf["ins"]]
    if lead == ["ensemble"]:
        main = "ensemble"
    else:
        main = next((m for m in mapped if m in lead), None) \
            or next((m for m in mapped if m not in CONTINUO and m != "other"), None) \
            or (lead[0] if perf["ins"] or len(perf["names"]) > 1 else "unknown")
    practice = ("historical" if main in HISTORICAL_LEAD or period_group(perf)
                else "modern" if "piano" in mapped else "unknown")
    return main, practice, False, []


def from_perf(perf: dict, bwvs: list[str], moves: dict[str, list[str]], native: set[str], same_performer: int,
              mode: str = "classic", lead: list[str] | None = None, scoring: str | None = None) -> dict:
    ensemble_work = mode in ("ensemble", "vocal", "chamber") or (mode == "open" and is_group(perf))
    if ensemble_work:
        instrument, practice, arranged, mention = (
            vocal_of(perf) if mode == "vocal" else chamber_of(perf, lead or []) if mode == "chamber"
            else ensemble_of(perf, scoring or ""))
        others, roles = [], {k: v.lower() for k, v in perf["roles"].items()}
    else:
        instrument, others, roles = instrument_of(perf, native)
        if mode == "organ" and instrument == "unknown" and len(perf["names"]) == 1:
            instrument = "organ"  # a lone performer of an organ work, with no instrument credit
        if mode == "open":
            others = [i for i in others if ARRANGED.search(i)]
    solo = len(perf["names"]) == 1
    performers = []
    types = perf.get("types") or []
    for i, name in enumerate(perf["names"]):
        role = roles.get(name.lower()) or roles.get(name)
        if not role and i < len(types) and types[i] in TYPE_ROLE:
            role = TYPE_ROLE[types[i]]
        if not role:
            role = instrument.replace("-", " ") if solo and instrument not in ("unknown", "other", "ensemble") else "performer"
        performers.append({"name": name, "role": role})
    rec = {
        "id": "",
        "performers": performers,
        "instrument": instrument,
        "performance_practice": "historical" if instrument in HISTORICAL else "modern" if instrument in MODERN else "unknown",
        "arrangement": instrument not in native | {"unknown"} or bool(others),
        "recorded": {"years": Flow(sorted(perf["years"])), "place": "; ".join(dict.fromkeys(perf["places"])) or None},
        "released": year(perf.get("firstRelease")),
        "original_label": None,
        "works": works_block(perf, bwvs, moves),
        "links": mb_links(perf),
        "status": "draft",
        "musicbrainz": {"artist": perf["ids"][0], "recordings": Flow(sorted(perf["recIds"]))},
        "help_wanted": [],
        "notes": "Live recording." if perf.get("live") else None,
    }
    if ensemble_work:
        rec["performance_practice"] = practice
        rec["arrangement"] = arranged
        others = mention
        if mode == "open" and not arranged and (any(OPEN_ARRANGED.search(i) for i in perf["ins"])
                                                 or OPEN_ARRANGED_NAMES.search(" ".join(perf["names"]))):
            rec["performance_practice"], rec["arrangement"] = "unknown", True
            others = [i for i in perf["ins"] if OPEN_ARRANGED.search(i)]
    elif mode == "open":
        rec["arrangement"] = instrument == "other" and bool(arranged_credits(perf)) \
            or bool(ARRANGED_NAMES.search(" ".join(perf["names"])))
    elif mode == "keyboard":
        # A solo keyboard work played by an orchestra or group with no keyboard credited, by a crossover name, or
        # on a soundtrack, relaxation or lesson album is an arrangement (Hooked on Classics, coffee-time albums).
        release = " ".join(r["title"] for r in perf["releases"])
        # Another keyboard credited alongside (often from another track of the album) is not an arrangement.
        rec["arrangement"] = instrument not in native | {"unknown"} or any(
            INSTRUMENTS.get(i.lower()) not in native for i in others)
        group_only = (any(t in GROUP_TYPES for t in types) or bool(GROUP_NAME.search(perf["names"][0]))) \
            and instrument not in native
        if group_only and instrument != "unknown":
            rec["instrument"], rec["performance_practice"] = "ensemble", "unknown"  # a string orchestra arrangement
        if instrument == "unknown" and len(perf["names"]) == 1:
            named = KEYBOARD_RELEASE.search(release)  # "Partitas pour clavecin", "Bach Piano Music"
            if named:
                rec["instrument"] = INSTRUMENTS.get(kw := (named.group(1) or named.group(2)).lower()) or INSTRUMENTS_EXTRA[kw]
                rec["performance_practice"] = "historical" if rec["instrument"] in HISTORICAL else "modern"
        if group_only or ARRANGED_NAMES.search(" ".join(perf["names"])) or ARRANGED_RELEASES.search(release):
            rec["arrangement"] = True
        melody = [i for i in others if INSTRUMENTS.get(i.lower()) not in (None, *KEYBOARD)]
        if melody:  # a cello or violin with the keyboard: a transcription led by the melody instrument
            rec["instrument"], rec["performance_practice"] = INSTRUMENTS[melody[0].lower()], "unknown"
            others = [i for i in others if i != melody[0]] + [i for i in perf["ins"] if INSTRUMENTS.get(i.lower()) == instrument]
    elif mode == "lute" and instrument == "guitar":
        rec["performance_practice"] = "modern"  # decided 28 Oct 2026: guitar is native for the lute works
    elif mode == "lute" and instrument == "lute":
        rec["performance_practice"] = "historical"
    if rec["arrangement"]:
        rec["arranger"] = None
        if instrument == "other" and perf["ins"]:
            rec["notes"] = ((rec["notes"] or "") + f" Played on {', '.join(perf['ins'][:3])}.").strip()
        elif others:
            rec["notes"] = ((rec["notes"] or "") + f" With {', '.join(others[:3])}.").strip()
    rec["help_wanted"] = help_items(rec, same_performer)
    return rec


def merge(old: dict, new: dict) -> dict:
    """Fill gaps in an existing file from MusicBrainz without overwriting anything."""
    out = dict(old)
    out["recorded"] = dict(old.get("recorded") or {})
    years = out["recorded"].get("years") or new["recorded"]["years"]
    out["recorded"]["years"] = Flow(years)
    if not out["recorded"].get("place"):
        out["recorded"]["place"] = new["recorded"]["place"]
    if out.get("released") is None:
        out["released"] = new["released"]
    if out.get("instrument") in (None, "unknown") and new["instrument"] != "unknown":
        out["instrument"] = new["instrument"]
        if out.get("performance_practice") in (None, "unknown"):
            out["performance_practice"] = new["performance_practice"]
    out["works"] = [FlowDict(w, **({"movements": Flow(w["movements"])} if "movements" in w else {})) for w in old["works"]]
    urls = {l["url"] for l in old["links"]}
    out["links"] = list(old["links"]) + [l for l in new["links"] if l["url"] not in urls]
    mb = dict(old.get("musicbrainz") or {})
    mb.setdefault("artist", new["musicbrainz"]["artist"])
    mb["recordings"] = Flow(sorted(set(mb.get("recordings", [])) | set(new["musicbrainz"]["recordings"])))
    out["musicbrainz"] = mb
    answered = []
    if out["recorded"]["years"]:
        answered += ["recording year", "recording dates", "recording and release year", "same performance"]
    if out["recorded"].get("place"):
        answered += ["place"]
    if out.get("instrument") not in (None, "unknown"):
        answered += ["instrument (musicbrainz"]
    out["help_wanted"] = [h for h in old.get("help_wanted") or [] if not any(a in h.lower() for a in answered)]
    return out


def order(rec: dict) -> dict:
    keys = ["id", "performers", "instrument", "performance_practice", "arrangement", "arranger", "recorded",
            "released", "original_label", "works", "links", "status", "help_wanted", "notes", "musicbrainz"]
    return {k: rec[k] for k in keys if k in rec}


def main(snapshot: str) -> int:
    data = json.loads(Path(snapshot).read_text(encoding="utf-8"))
    EXCLUDE.clear()
    EXCLUDE.update(EXCLUDE_BY_SNAPSHOT.get(Path(snapshot).stem.removeprefix("musicbrainz-"), {}))
    if isinstance(data, list):
        data = {"works": CELLO_SUITES, "native": CELLO_FAMILY, "rows": data}
    bwvs, native, rows = data["works"], set(data["native"]), data["rows"]
    # Importer mode (docs/catalogue-plan.md): older snapshots have none; "ensemble" was then the native list.
    mode = data.get("mode") or ("ensemble" if "ensemble" in native else "classic")
    lead = data["native"] if mode == "chamber" else None
    # Scoring of the works, for telling soloists from transcriptions in orchestral works. Snapshots from the
    # browser collector (no "mode" key) keep their original rules, so re-importing them changes nothing.
    scorings = {w["bwv"]: w.get("scoring") or "" for _, w in load("works")}
    SCORINGS.clear()
    SCORINGS.update(scorings)
    scoring = " ".join(scorings.get(b, "") for b in bwvs) if data.get("mode") == "ensemble" else None
    moves = movement_names()
    missing = [b for b in bwvs if b not in moves]
    if missing:
        raise SystemExit(f"Add work files for BWV {', '.join(missing)} before importing")
    if mode == "keyboard":
        rows = [keyboard_soloist(c, native) for c in rows]
    perfs = [expand(c, bwvs, moves) for c in rows if c["a"] and c["rep"] not in EXCLUDE and UNKNOWN_ARTIST not in c["a"]
             and NO_ARTIST not in c["a"]]
    joins = JOIN_BY_SNAPSHOT.get(Path(snapshot).stem.removeprefix("musicbrainz-"), {})
    overrides = OVERRIDE_BY_SNAPSHOT.get(Path(snapshot).stem.removeprefix("musicbrainz-"), {})
    by_rep = {p["repId"]: p for p in perfs}
    for extra, (into, _) in joins.items():
        if extra in by_rep and into in by_rep:
            a, b = by_rep[into], by_rep.pop(extra)
            a["mv"] = sorted(set(a["mv"]) | set(b["mv"]))
            a["years"] = sorted(set(a["years"]) | set(b["years"]))
            a["places"] = list(dict.fromkeys(a["places"] + b["places"]))
            a["recIds"] = a["recIds"] + b["recIds"]
            perfs.remove(b)
    existing = {p: r for p, r in load("recordings")}
    by_mbid = {m: p for p, r in existing.items() for m in (r.get("musicbrainz") or {}).get("recordings", [])}

    per_performer: dict[str, int] = {}
    for perf in perfs:
        per_performer[norm(perf["names"][0])] = per_performer.get(norm(perf["names"][0]), 0) + 1

    used_paths: set[Path] = set()
    results = []
    for perf in perfs:
        main_name = norm(perf["names"][0])
        new = from_perf(perf, bwvs, moves, native, per_performer[main_name], mode, lead, scoring)
        if perf["repId"] in overrides:
            fix = overrides[perf["repId"]][0]
            if "performers" in fix:
                new["performers"] = [dict(p) for p in fix["performers"]]
            if "instrument" in fix:
                new["instrument"] = fix["instrument"]
                new["performance_practice"] = ("historical" if fix["instrument"] in HISTORICAL
                                               else "modern" if fix["instrument"] in MODERN | {"viola"} else "unknown")
                if len(new["performers"]) == 1:
                    new["performers"][0]["role"] = fix["instrument"]
            if "arrangement" in fix:
                new["arrangement"] = fix["arrangement"]
                if not fix["arrangement"]:
                    new.pop("arranger", None)
            new["help_wanted"] = help_items(new, per_performer[main_name])
        target = next((by_mbid[m] for m in perf["recIds"] if m in by_mbid), None)
        if target is None:
            for path, r in existing.items():
                if path in used_paths or r.get("musicbrainz") or norm(r["performers"][0]["name"]) != main_name:
                    continue
                if not {w["bwv"] for w in r["works"]} & set(bwvs):
                    continue
                ys = (r.get("recorded") or {}).get("years") or []
                rel = r.get("released")
                if ys and perf["years"] and set(ys) & set(perf["years"]):
                    target = path
                elif not ys and rel and perf["years"] and abs(min(perf["years"]) - rel) <= 1:
                    target = path
                elif not ys and not rel and per_performer[main_name] == 1:
                    target = path
                if target:
                    break
        if target is not None:
            results.append((target, merge(existing[target], new)))
            used_paths.add(target)
        else:
            results.append((None, new))

    # File names: <performer>-<year>, then -2, -3 … for clashes. Names already on disk are never
    # reused, including those from other snapshots, and a matched file keeps its name when it still fits.
    untouched = [p for p in existing if p not in used_paths]
    occupied = {p.stem for p in untouched}
    stems = []
    for target, rec in results:
        ys = rec["recorded"]["years"]
        stems.append(f"{slug_for(rec)}-{min(ys)}" if ys else f"{slug_for(rec)}-undated")
    ids: list[str | None] = [None] * len(results)
    for i, ((target, rec), stem) in enumerate(zip(results, stems)):
        if target is not None and target.stem not in occupied and re.fullmatch(re.escape(stem) + r"(-\d+)?", target.stem):
            ids[i] = target.stem
            occupied.add(target.stem)
    for i, stem in enumerate(stems):
        if ids[i] is None:
            n = 1
            while (stem if n == 1 else f"{stem}-{n}") in occupied:
                n += 1
            ids[i] = stem if n == 1 else f"{stem}-{n}"
            occupied.add(ids[i])
    out_dir = DATA / "recordings"
    for (target, rec), rid in zip(results, ids):
        rec["id"] = rid
        path = out_dir / f"{rec['id']}.yaml"
        if target is not None and target != path:
            target.unlink()
        with path.open("w", encoding="utf-8") as fh:
            yaml.dump(order(rec), fh, Dumper=_dumper(), allow_unicode=True, sort_keys=False, width=110)

    merged = sum(1 for t, _ in results if t is not None)
    unmatched = [p.name for p in untouched if {w["bwv"] for w in existing[p]["works"]} & set(bwvs)
                 and not existing[p].get("musicbrainz")]
    joined = sum(1 for e, (i, _) in joins.items() if e in {c["rep"] for c in rows})
    print(f"{len(rows) - len(perfs) - joined} rows skipped (see EXCLUDE), {joined} joined, {merged} existing files updated, "
          f"{len(results) - merged} new files; hand-made files for these works not matched: {unmatched}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
