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
  "musical-offering": {
    "b8ac7bbb-b8d9-479f-9005-96a1d30188ea": "Most Beautiful Music, Vol. 1 (Radio Luxembourg, de Froment): the same MusicBrainz recording is filed as their Orchestral Suites track; one track cannot be both",
    "9fa72977-1f2c-44f4-b47f-4c69423ab9db": "Aimard's Ricercar a 3 on his DG album of WTC Book I, which holds only the WTC: a fugue linked to the wrong work",
  },
  "violin-keyboard-sonatas": {
    "a14b8433-630f-454c-b727-92bfe3ab18e7": "Hooked on Classics 2 (Royal Philharmonic, Louis Clark): a medley track, already filed for the English Suite No. 2 Bourrées; not a performance of Sonata No. 4",
    "6d9fe2ff-fa23-4c91-91eb-4f80bb1c5e61": "Poulet's album of the solo violin Sonatas and Partitas: two solo-violin movements linked to Sonata No. 1, which needs a keyboard",
  },
  "harpsichord-concertos": {
    "f8df5ad3-0db2-4dc7-be48-a55397f60b20": "credited to Antonio Vivaldi (composer of the model of BWV 1065) on a Vivaldi compilation; the performers are unknown",
  },
}
EXCLUDE_BY_SNAPSHOT["flute-works"] = {
    "a14b8433-630f-454c-b727-92bfe3ab18e7": "Hooked on Classics 2 (Royal Philharmonic, Louis Clark): the medley track already filed for the English Suite No. 2 Bourrées, linked to the flute sonatas too",
    "1e0f94e6-f9ce-4ce2-93e4-b2f338737db4": "Young Person's Guide to the Classic 1: a compilation of other artists' classical recordings issued under Yngwie Malmsteen's name; he does not play the Bourrée",
    "45ddb272-aa23-4f3b-99d1-62820ab0044e": "RCM exam book disc: the piano accompaniment alone (Longworth), the track for practising with; the flute and piano performance is filed",
}
EXCLUDE: dict[str, str] = {}  # the current snapshot's entries, set in main()

# One performance that the snapshot splits into two rows (an undated track of a dated set, one set recorded
# over more than three years), per snapshot: representative recording ID of the row to fold in -> that of
# the row it belongs to, with the reason.
JOIN_BY_SNAPSHOT = {
  "flute-works": {
    "11486481-cea1-49ec-a54a-f04a3408a632": ("17e4c4b4-8e27-441d-a816-cb8621463153",
        "Brüggen and Leonhardt's BWV 1030 and 1032, first issued with the Brandenburgs: the same 1975 Doopsgezinde kerk sessions as the Complete Sonatas & Partita"),
    "0a1e6c3a-d040-46f6-b62b-36dddf907046": ("7959c4be-5ec7-4eec-845b-488cd20eb535",
        "Grafenauer and Graf's BWV 1031 Siciliano, an undated track of their 1987 flute and harp album"),
    "6df70a08-c374-466a-837b-43ae1ee210a7": ("8fbebf38-6fda-45dd-9a2e-82b0b577f2e5",
        "Sharon Bezaly and Terence Charlston's BWV 1031 Siciliano (BIS, Barocking Together), reissued on a compilation credited to London Baroque"),
    "f808eb7d-58d8-4fe7-9e1f-df298f6a2ce6": ("86f186b6-4732-4954-ada1-a49c991d7e0b",
        "the Siciliana of Preston, Pinnock and Savall's 1975 set on a sampler; the roles still name Savall"),
    "07e798ef-0778-416f-a16d-ebf962286979": ("d1421080-db71-4fbd-bd39-c75ed7719098",
        "Galway, Lumsden and Ryan's BWV 1035 from Serenade for Flute, reissued with the London Virtuosi on the same disc"),
    "979b93b6-00f5-4202-a56e-c7730475c14b": ("da429123-0a77-453a-aacb-5e9b187db74f",
        "the one sonata (BWV 1033) missing from the Moravian Trio's set on the same undated release, credited to its flutist alone"),
  },
  "gamba-sonatas": {
    "81c39663-2804-4301-9c26-a9dc22a524ba": ("941a7e74-08f1-4355-a5ae-f3e012383aab",
        "Wenzinger and Neumeyer: the undated tracks of the same 1952 release"),
    "b5a2c64f-1600-4921-acd1-1b61602da1f4": ("aa46c3f7-dc2d-4a0d-908f-fd6d119d9633",
        "du Pré and Kinloch Anderson's 1962 BWV 1028, reissued on A Jacqueline du Pré Recital without a date"),
    "01b55387-f2e3-400e-8899-1ea839f512ad": ("2e2c40ea-c4ec-4836-925c-4a1a31cb1297",
        "Starker and Sebök's 1963 Mercury BWV 1029, reissued without a date"),
    "b1513c9e-4f71-4cd7-870e-de4e6595a588": ("4c4f0f86-ac36-4387-b995-05eb90db01cb",
        "Casals and Baumgartner, Prades 1950: the same 3 Sonatas release, undated tracks"),
    "f06b65bc-2b9e-4734-9153-f9f0c537c543": ("ebea3461-9c9c-4e1b-a0ed-2e4357be35a4",
        "Harmonie universelle is an Alia Vox sampler; its BWV 1028 is Savall and Koopman's 2000 Alia Vox recording"),
  },
  "violin-keyboard-sonatas": {
    "afcd5ff8-92ab-40c6-a9e0-a2af119ece14": ("638a6dac-6aea-4ed0-831f-381ff481b093",
        "Höbarth's BWV 1023 on A Violino e Cembalo, the one sonata missing from the Höbarth and Häkkinen set on that release (Häkkinen's credit lost)"),
    "0e214ff6-60ba-4298-9c45-c57aeb8d6cb6": ("1370fcbe-5e2c-4df5-9c1a-9e048eee9268",
        "Faust and Bezuidenhout's BWV 1024 Affettuoso: same release, year and place as the rest of their BWV 1024 (cello credit missing)"),
    "7c28b12a-5ecd-4109-8d48-6095b99483cb": ("b2487b66-640c-49fb-9634-13164d5980e8",
        "Szeryng's Adagio of BWV 1014 on the Bach 333 box, recorded at Notre-Dame du Liban: the Szeryng and Walcha set (Walcha's credit lost)"),
    "ab67b2d1-6e9a-492d-b193-67ba0af03986": ("4246ae83-2f09-4348-8c1f-18e69852e982",
        "Harnoncourt and Tachezi's Andante of BWV 1014 on a Classic FM compilation: the Alice Harnoncourt, Nikolaus Harnoncourt and Tachezi set (Alice's credit lost)"),
    "6f8d0fa8-8503-4bd4-91b1-cb3fc16c6e45": ("e394b50b-ebd1-4645-8e57-079b8ac11a75",
        "Hirasaki and Ghielmi's BWV 1022 on the same 2019 release as their continuo sonatas with Camporini: one set"),
    "2e008111-50c0-4945-bb26-263f2c670492": ("076c5943-f196-4439-b345-a8edf1319b28",
        "Manze and Egarr's Violin Sonatas (1999, St George's Bristol): one set, ter Linden added for some sonatas"),
    "1385e8b7-6435-477c-b454-51a0f34e169c": ("033a0c4e-5c54-4e8e-b642-593775e784af",
        "Schmid and Spiri's 2000 set (Kalksburg), Hess added on cello for BWV 1021 and 1023: one release"),
    "2ebb8fb5-0796-4a0f-83c9-cf947959ad7c": ("537f97b2-b8eb-4719-a37a-ffcef83d2bcf",
        "Blumenstock and Butt's Violin Sonatas (Skywalker Sound, 1991-92): BWV 1021 with Le Guin on the same release"),
    "b4f6245b-6391-4fb4-8e28-ed899ebd04d9": ("537f97b2-b8eb-4719-a37a-ffcef83d2bcf",
        "Blumenstock and Butt's Violin Sonatas (Skywalker Sound, 1991-92): BWV 1023 with Lehning on the same release"),
    "ad201ba9-3be1-4113-9b3a-83b64e6c0b4d": ("52ad3974-36c6-4780-8709-c700aa3830d5",
        "Wallfisch and Nicholson's 1996 set (St Michael's Church), Tunnicliffe added on cello for the continuo sonatas: one release"),
    "f92b2c6f-0c8b-4d63-891b-88fe23125302": ("cc69ac77-10d9-464d-b2e6-fb55bf2f07b9",
        "Podger and Pinnock's complete sonatas (2000, St Martin's Church), Manson added on gamba for BWV 1021 and 1023: one release"),
    "e5590383-c0c9-4595-a31a-bceb299e2097": ("404789fe-d9d5-4c5f-a272-cc4da74b72d6",
        "Monosoff and Weaver's sonatas, Davidoff added on gamba for the two continuo sonatas: one release"),
    "a272515b-4650-4cce-8112-02b1ed02766f": ("ab59ee71-5bd7-4251-905f-2a5455e987d8",
        "Grumiaux and Jaccottet's Sonatas BWV 1014-1023 (1978-80), Mermoud added on cello for BWV 1021 and 1023: one release"),
    "df29c099-3d7d-4b0e-9ae5-07db006b8c7b": ("91735c8e-a4d9-4ca6-a78d-3a50994408d0",
        "Gould and Laredo's Sonata No. 4: an undated track of their 1975-76 Columbia set, on the same release"),
    "e7830e07-a999-4e0b-a0cc-e73b18ecd1c1": ("a21f8e62-5163-4721-8654-15307672a14e",
        "Landowska's Sonata No. 3 on The Piano Masters compilation (credited as piano): her 1944 recording with Menuhin"),
  },
  "musical-offering": {
    "f8511c55-7e7c-4193-b463-b588e3181560": ("06ab6365-e351-4f6f-a0a6-ade42d5a2821",
        "the Swingle Singers and the Modern Jazz Quartet's 1966 Ricercar (Place Vendôme), reissued on Compact Jazz"),
    "e0299e6d-d94b-4e28-b2be-9bb4659d5b1c": ("f40c8887-be57-41e4-86a0-d5b76204a646",
        "the trio sonata Largo with Rampal, Stern, Parnas and Ritter, reissued on Stern's birthday box"),
    **{rep: ("4ae4a1ee-d525-429a-b15f-1392c78fabac",
             "Kohnen and the three Kuijkens on the DHM 50 Jahre box: their 1994 Deutsche Harmonia Mundi set")
       for rep in ("4ed98508-0fd8-48cb-8c79-aa1b6b8d9baa", "edda2daf-25a8-4573-97cb-e3299b3096da",
                   "eea6c015-731b-4658-b2a0-3ee96980e5fe", "f2ba8940-e53e-465d-a37d-77e8675b8518")},
    "68be37ad-e11a-4e4d-b305-dc5220cdae73": ("1b8e6a7a-7563-4b1f-b746-d300251795cd",
        "Nicolet and Kobayashi's trio sonata Allegro (Best of Denon) and the Largo with Blacher and Fujiwara (Denon sampler): one Denon set"),
    "28013b26-e02a-44fe-bbaf-16eca5ed548e": ("362967c4-b8c7-40c9-9930-5a660c94918e",
        "Holloway, ter Linden, Moroney and See on a later compilation: Moroney's 1987 set"),
  },
  "clavier-ubung-ii": {
    "df07d6de-65ef-41cc-893d-41b1acc6aba5": ("38f03114-6153-40fa-81c7-3de965c8432c",
        "Alessandrini's Italian Concerto, one performance (2000, Santissima Trinità dei Pellegrini) split across two releases"),
    "4f9b9334-7385-4086-9dec-d9c327346b01": ("50475404-ce1f-44a9-98b7-424e3c50270e",
        "Tomšič's Italian Concerto: the El Barroco compilation (1995) reissues her 1987 recording"),
  },
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

# Snapshots of works whose movements are scored for different forces (the Musical Offering: keyboard
# ricercars, canons for two to four players, a trio sonata). The collector groups by performer line-up, so one
# recorded set comes out as one row per line-up. Here rows on the same earliest release with the same recording
# years (or all undated) are one performance; performers are the union, the row with most movements first.
JOIN_BY_RELEASE = {
  "musical-offering": "each movement has its own line-up, so the collector split recorded sets by line-up",
}
# Chamber sets the collector splits by line-up (the solo partita, the sonatas with keyboard, the continuo sonatas
# with a cellist or gambist added): rows on the same release, with the same recording years and the same solo
# player, are one performance.
JOIN_BY_PLAYER_RELEASE = {
  "flute-works": "a flutist's set is split into the solo Partita, the obbligato sonatas and the continuo sonatas",
  "gamba-sonatas": "a set is split by line-up when a player is credited on only some sonatas",
}

# Instruments the snapshot's `native` list leaves out, per snapshot, with the reason.
NATIVE_EXTRA_BY_SNAPSHOT = {
  "gamba-sonatas": (["violoncello-piccolo"], "a cello-family instrument like the cello the plan files as native (Bylsma, Wispelwey)"),
  "musical-offering": (["flute", "traverso"], "the trio sonata and the canons name the flute (Frederick the Great's instrument)"),
}

# Facts the snapshot gets wrong or leaves out for one row, per snapshot: representative recording ID ->
# fields to set, with the reason. Fix upstream in MusicBrainz too, then remove the entry here.
OVERRIDE_BY_SNAPSHOT = {
  "gamba-sonatas": {
    "64c01010-75cf-477e-a2f7-ce6fd55785fe": ({"performers": [{"name": "Daniil Shafran", "role": "cello"},
                                                             {"name": "Andrei Volkonsky", "role": "harpsichord"}]},
        "roles credited in Cyrillic only"),
    "6a51d113-0208-4327-a6a2-0bb7ccd95650": ({"instrument": "ensemble", "arrangement": True},
        "Holliger, Nicolet and others on a trio-sonata album: BWV 1029 arranged for oboe, flute and continuo"),
    "4690f92a-22ba-45c4-8b57-1bf67f3f9dd1": ({"instrument": "ensemble", "arrangement": True},
        "Sonates en Trio: BWV 1028 arranged as a trio sonata for two flutes and continuo"),
    "b3278980-26eb-4711-8ef6-2db9ac0b2d74": ({"instrument": "ensemble", "arrangement": True},
        "Lifescapes: Bach, a crossover relaxation series by an orchestra; not the sonata as written"),
    "fa7ba7e5-7d87-4f93-8c57-665e32838e1b": ({"instrument": "baroque-cello"}, "Bruno Cocset plays period cellos; credited as cello"),
    "cfb653fb-2df8-4b4b-8d6c-eb611894a7a2": ({"performers": [{"name": "Jordi Savall", "role": "viola da gamba"},
                                                             {"name": "Ton Koopman", "role": "harpsichord"}]},
        "Savall and Koopman's 1977 duo recording (Claydon House); the Amsterdam Baroque Orchestra and a conductor credit are wrong"),
    "84afc15a-347c-4c60-8b4b-4fc53d117b8a": ({"instrument": "violoncello-piccolo"},
        "Amarillis's Aria album: BWV 1028 is played on a piccolo cello (MusicWeb review, March 2001)"),
    "b5bc02f1-bd4f-455a-abe8-a4d63fe9c070": ({"performance_practice": "historical"},
        "Bettina Hoffmann (Modo Antiquo) and Fedi, a period-instrument duo; the cello is filed as credited"),
  },
  "flute-works": {
    "d87e0cd2-fc17-45ae-ae1f-a7fe51ba5e88": ({"instrument": "oboe", "arrangement": True}, "Alex Klein is an oboist; no instrument credit"),
    "1ebc9e67-616b-4fe2-9d22-6a7b82aa4c59": ({"performers": [{"name": "Annegret Bauerle", "role": "flute"}]},
        "the roles credit Annegret Bauerle on flute; Marko Simsa narrates the children's album"),
    "1b1e16fb-8ec4-481f-be9e-b40eea26213a": ({"performers": [{"name": "Kimberly Bryden", "role": "oboe"},
                                                             {"name": "Martha Reikow", "role": "cello"}]},
        "the roles credit Bryden (oboe) and Reikow (cello); Tim Story is the album's compiler"),
    "ea794a52-9fbe-4975-8ba1-a0730f7f88d0": ({"instrument": "violin"}, "Sparf plays the violin with Härenstam on guitar, as in his violin-sonata file"),
    "abaa9a25-3b75-46f3-bb6a-561667c2b86c": ({"instrument": "other"}, "the melody is on Frati's mandolin, with guitar accompaniment"),
    "6098ba08-b4d4-4bcf-ae04-c9455fb54ca1": ({"instrument": "recorder"}, "Horacio Franco is a recorder player; no instrument credit (as in run 10)"),
    "094c67bc-9a53-47ea-bc69-3fb24581450f": ({"movements": ["1013:0", "1013:1", "1013:2", "1013:3"]},
        "Russell's discography lists the whole Partita on Air on a G String; MusicBrainz links only the Bourrée"),
    "8fbebf38-6fda-45dd-9a2e-82b0b577f2e5": ({"performers": [{"name": "Sharon Bezaly", "role": "flute"},
                                                             {"name": "Terence Charlston", "role": "harpsichord"}],
                                              "performance_practice": "unknown"},
        "Barocking Together credits only Bezaly (modern flute) and Charlston on BWV 1031; London Baroque came from the joined reissue"),
    "da429123-0a77-453a-aacb-5e9b187db74f": ({"instrument": "flute"}, "the Moravian Trio's flute sonatas: the flutist's credit is on the joined BWV 1033 row"),
    "3cbed898-2eb3-4598-95ab-253bad84f578": ({"arrangement": True}, "Galway with orchestra (Gerhardt): an orchestral arrangement"),
    "23073e80-c855-42d9-9fa1-5131f2d791af": ({"instrument": "flute", "arrangement": False},
        "BWV 1031 with flute, bassoon and harpsichord credited (the Moravian Trio); the brass group's name is a credit error"),
    "01554053-49c1-4a23-a8e0-a144c63bf0ed": ({"instrument": "recorder", "performance_practice": "historical"},
        "Piers Adams is a recorder player, with Red Priest's period players; no instrument credits"),
    "97eb3b19-fe2a-486b-a148-8535252dcd48": ({"instrument": "recorder", "performance_practice": "historical"},
        "Marion Verbruggen (recorder) and Mitzi Meyerson (harpsichord), period instruments; no instrument credits"),
  },
  "violin-keyboard-sonatas": {
    "8c7367c9-4893-4e1a-bb61-0523a8767ca8": ({"movements": ["1021:2"]},
        "the Brandenburg Consort play the Largo of BWV 1021 as the slow movement of Brandenburg No. 3 (Hyperion's track list); MusicBrainz links the whole sonata"),
    "c8e37a86-2005-4c6a-ab59-5614bcd401f4": ({"performers": [{"name": "Leonid Kogan", "role": "violin"}, {"name": "Vladimir Yampolsky", "role": "piano"}]},
        "Kogan and Yampolsky: the roles are credited in Cyrillic, so no name matches its role"),
    "6b6201d5-8044-49b7-83f3-9999dceb1a85": ({"performers": [{"name": "Marina Kozolupova", "role": "violin"}, {"name": "Maria Yudina", "role": "piano"}]},
        "Kozolupova and Yudina: the roles are credited in Cyrillic, so no name matches its role"),
    "b2b69247-79af-4d66-a810-faa1315c257b": ({"performers": [{"name": "David Oistrakh", "role": "violin"}, {"name": "Lev Oborin", "role": "piano"}]},
        "Oistrakh and Oborin: the roles are credited in Cyrillic, so no name matches its role"),
    "81c7b869-40a8-4dc6-b406-2529c5231f09": ({"performers": [{"name": "Igor Oistrakh", "role": "violin"}, {"name": "Natalia Zertsalova", "role": "harpsichord"}]},
        "Igor Oistrakh and Zertsalova: the roles are credited in Cyrillic, so no name matches its role"),
    "a46cb46b-acb8-47c6-b9d4-c13319fc1d4f": ({"performers": [{"name": "Janine Jansen", "role": "violin"}, {"name": "Jan Jansen", "role": "harpsichord"}]},
        "Jan Jansen is credited on harpsichord for the sonatas but missing from the track credit"),
    "f419a501-b61b-4a95-8ccb-b6e44230ff29": ({"performers": [{"name": "Shunske Sato", "role": "violin"}, {"name": "Menno van Delft", "role": "harpsichord"}], "performance_practice": "historical"},
        "Sato and van Delft (Netherlands Bach Society): baroque violin and harpsichord; no credits in MusicBrainz"),
    "a6789016-4a33-4dc5-acc5-8a513e014cde": ({"instrument": "violin"},
        "David Oistrakh, violinist; no instrument credit"),
    "e2cca82a-2691-460d-a1d8-629f1784d4a0": ({"instrument": "violin"},
        "Emmanuelle Dauvin, violinist (Pièces pour violon et basse); no instrument credit"),
    "e59754ce-912b-4cc1-a784-44d57d93d85b": ({"instrument": "recorder", "arrangement": True},
        "Horacio Franco, recorder player, on a Bach and Beatles crossover album"),
    "82e44550-6e9e-4888-a7c4-5af471561aa5": ({"instrument": "other", "arrangement": True},
        "Per Arne Glorvigen, bandoneon"),
    "870896eb-18b4-4eae-998d-268a4ee2d20d": ({"performers": [{"name": "Capriccio Stravagante", "role": "ensemble"}], "instrument": "violin", "performance_practice": "historical"},
        "Capriccio Stravagante on Il Violino: BWV 1024 for violin and continuo; the group is credited, not its violinist"),
    "4e3822ea-5e83-4bdd-99a2-1d623cfa6549": ({"performers": [{"name": "Sonnerie", "role": "ensemble"}], "instrument": "violin", "performance_practice": "historical"},
        "Sonnerie (Monica Huggett's group) in BWV 1021 and 1023, the violin and continuo sonatas; the group is credited, not its violinist"),
    "a8d6d504-992c-4684-8b11-5ed6f710d6f3": ({"performers": [{"name": "Trio Settecento", "role": "ensemble"}], "instrument": "violin", "performance_practice": "historical"},
        "Trio Settecento: Rachel Barton Pine on baroque violin, with continuo"),
    "1d100057-109f-474d-8802-2d0a40f5af37": ({"performers": [{"name": "Ensemble Gaudior", "role": "ensemble"},
        {"name": "Alexandra MacCracken", "role": "violin"}, {"name": "Elena Tsai", "role": "harpsichord"}]},
        "Ensemble Gaudior: MacCracken (violin) and Tsai (harpsichord) are credited for the track but not in its artist credit"),
    "e9459ec6-9373-4b13-81df-c3c2f8391163": ({"arrangement": True},
        "Lara St. John with Langlamet on harp in place of the harpsichord"),
    "4246ae83-2f09-4348-8c1f-18e69852e982": ({"performance_practice": "historical"},
        "Alice and Nikolaus Harnoncourt and Tachezi: period instruments"),
    "076c5943-f196-4439-b345-a8edf1319b28": ({"performance_practice": "historical"},
        "Manze, Egarr and ter Linden: period instruments"),
    "0b8a43e6-2824-4402-9b46-6194789bd51e": ({"performance_practice": "historical"},
        "Huggett and Koopman: period instruments"),
    "b0bf54af-4786-4e72-89a4-b109cbcf2b69": ({"performance_practice": "historical"},
        "Huggett, Cunningham and Meyerson: period instruments"),
    "ebff4be7-867a-408f-a6d8-078ca050f4a8": ({"performance_practice": "historical"},
        "Holloway, Moroney and Sheppard: period instruments"),
    "cc69ac77-10d9-464d-b2e6-fb55bf2f07b9": ({"performance_practice": "historical"},
        "Podger, Pinnock and Manson: period instruments"),
    "60d64b4b-4b47-4ca8-835c-eaac5663b74a": ({"performance_practice": "historical"},
        "Beyer and Hantaï: period instruments"),
    "ff302624-4fe7-49f7-bacd-e239ee8c43bb": ({"performance_practice": "historical"},
        "Banchini and Bötticher: period instruments"),
    "4acd0909-3344-484a-a9ae-78447d809250": ({"performance_practice": "historical"},
        "Goebel and Hill: period instruments"),
    "c96f3a19-56fd-4de0-a9bf-3dc9ed197180": ({"performance_practice": "historical"},
        "Goebel, Bouman and ter Linden: period instruments"),
    "165a948b-0152-42b6-8209-55c57089d17a": ({"performance_practice": "historical"},
        "Terakado and Bonizzoni: period instruments"),
    "1681abc3-e1f7-46bf-bcdd-98e01902f936": ({"performance_practice": "historical"},
        "Terakado and Bonizzoni: period instruments"),
    "9552b96d-6531-49c5-8ff9-7004c9c84d5e": ({"performance_practice": "historical"},
        "Terakado and Henstra: period instruments"),
    "52ad3974-36c6-4780-8709-c700aa3830d5": ({"performance_practice": "historical"},
        "Wallfisch, Nicholson and Tunnicliffe: period instruments"),
    "19f703d8-bc01-4765-8c33-ad23141c969a": ({"performance_practice": "historical"},
        "van Dael and van Asperen: period instruments"),
    "c536fd11-4765-4ddb-9dc4-d6b6cf781fc8": ({"performance_practice": "historical"},
        "Comberti and Tilney: period instruments"),
    "5761b409-ba05-467f-85e0-2acbca311d3e": ({"performance_practice": "historical"},
        "Biondi and Alessandrini: period instruments"),
    "04e08ac8-ef35-4068-b29a-368f41b9cad0": ({"performance_practice": "historical"},
        "Carmignola and Marcon: period instruments"),
    "3a42af2f-df54-4616-ba8d-1a130a39b18a": ({"performance_practice": "historical"},
        "Schröder and Ingólfsdóttir: period instruments"),
    "7d66126e-f468-456b-a53c-ae2e1412839d": ({"performance_practice": "historical"},
        "Valetti and Frisch: period instruments"),
    "2ae987e2-5467-4f0f-98de-4225f39be90f": ({"performance_practice": "historical"},
        "Malgoire and Rannou: period instruments"),
    "01f6d52d-e41c-453d-a5e1-c389001ac1a0": ({"performance_practice": "historical"},
        "Schmitt, Jansen and Gervreau: period instruments"),
    "677c81dc-c7d0-4ee7-8da5-5c70b7c19907": ({"performance_practice": "historical"},
        "Otávio Santos and Belder: period instruments"),
    "609a7672-77ed-4728-8f12-449f050b2c3e": ({"performance_practice": "historical"},
        "Catherine Manson and Koopman: period instruments"),
    "4c48c518-c434-4861-9676-af93fa53e0ec": ({"performance_practice": "historical"},
        "Lucy Russell and Butt: period instruments"),
    "e724acc5-c1b5-49a1-8152-156fd14627bf": ({"performance_practice": "historical"},
        "Schayegh and Halubek: period instruments"),
    "f2c85d4c-149f-4003-975d-cf99382d8128": ({"performance_practice": "historical"},
        "Christine Busch and Johannsen: period instruments"),
    "edb03a39-b17d-4ca6-b335-32e8a0e29d38": ({"performance_practice": "historical"},
        "Siranossian, Máté and García Alarcón: period instruments"),
    "d037dcf5-f100-436e-af69-3ceaf1a771e2": ({"performance_practice": "historical"},
        "Glodeanu and Haas: period instruments"),
    "e394b50b-ebd1-4645-8e57-079b8ac11a75": ({"performance_practice": "historical"},
        "Hirasaki, Ghielmi and Camporini: period instruments"),
  },
  "musical-offering": {
    "6bd83dce-d70a-4916-a01e-9cee43b5a3e1": ({"arrangement": True}, "Chailly and the Concertgebouw play the Ricercar a 6 in Webern's orchestration"),
    "8056e03d-1333-4b61-bd28-1744c054bb73": ({"instrument": "ensemble"}, "the Munich Instrumental Ensemble is a group; MusicBrainz gives it no type"),
    "58061be1-81fb-4d5f-9958-b70d384f2783": ({"performers": [
        {"name": "Gunārs Larsens", "role": "violin"}, {"name": "Christiane Jaccottet", "role": "harpsichord"},
        {"name": "Aurèle Nicolet", "role": "flute"}, {"name": "Markus Nyikos", "role": "cello"},
        {"name": "Piotr Jan Milewski", "role": "violin"}, {"name": "Max Lesueur", "role": "viola"},
        {"name": "Alfred Steinauer", "role": "double bass"}]},
        "credited in Cyrillic on the 1977 release; Latin names and roles from the same rows' instrument credits"),
    "3a3b9cb5-1dc1-4168-8697-23ba75953711": ({"performance_practice": "historical"}, "Arita, Terakado, Wakamatsu and Nakano: period instruments (transverse flute, baroque strings)"),
    "4ae4a1ee-d525-429a-b15f-1392c78fabac": ({"performance_practice": "historical"}, "the Kuijkens and Kohnen, DHM 1994: period instruments"),
    "e6280388-eff5-425b-ab84-ea46cbd1dbd0": ({"performance_practice": "historical"}, "von der Goltz, Kaiser and Behringer (Freiburger Barockorchester players): period instruments"),
    "f8a62950-7961-497c-9619-a050dd0f6ecc": ({"performance_practice": "historical"}, "Hazelzet (traverso), ter Linden and Ogg: period instruments"),
    "e5a51a43-1816-40f2-b89c-d7698ccf378c": ({"performance_practice": "historical"}, "Moroney, Holloway, ter Linden and See: period instruments"),
  },
  "clavier-ubung-ii": {
    "d85ae950-852b-4653-9c50-fa55854acca8": ({"instrument": "fortepiano"}, "Toby Sermeus, Bach's Piano Silbermann 1749: a Silbermann fortepiano copy"),
    "99b8b346-9242-47ba-aa2e-9edf474555e3": ({"instrument": "organ"}, "Kei Koito, organist, on Organ Masterworks Vol. II; no instrument credit"),
    "38f03114-6153-40fa-81c7-3de965c8432c": ({"performers": [{"name": "Rinaldo Alessandrini", "role": "harpsichord"}], "instrument": "harpsichord"},
        "the Italian Concerto is solo: Concerto Italiano and the conductor credit belong to the concertos on the same albums"),
    "f6655e44-ba0d-4787-9789-d06ca6022ca1": ({"instrument": "harpsichord"},
        "Landowska recorded the Italian Concerto on harpsichord; the piano credit comes from the compilation's title, The Piano Masters"),
    "3962d116-3ebf-48bb-8d4f-180aa972282e": ({"arrangement": False},
        "the claviorganum (harpsichord and organ in one) is a historical keyboard, native to a Clavier work"),
    "a4334c5f-9399-4cbe-9e67-15fd3e160ba1": ({"performers": [{"name": "Barbara Matthias", "role": "performer"}]},
        "the Italian Concerto is solo: the orchestra and conductor are credited for the Brandenburg Concertos on the same album"),
    "3f614938-9a27-40da-80a5-918d2b837083": ({"instrument": "harpsichord"}, "Andrew Appel, harpsichordist; no instrument credit"),
  },
  "art-of-fugue": {
    "fb15748c-f29d-402e-9501-e9c741242024": ({"arrangement": True}, "oboe d'amore, bass oboe, cor anglais and bassoon (Paillard's 1977 Erato set): winds are an arrangement for the open-score work"),
    "7d6d9d6d-4317-4799-8c28-07160f62e765": ({"instrument": "harpsichord"}, "Lengellé and Morabito, the two-harpsichord pieces of the 1977 Erato set"),
    "7e58f597-0139-4696-b120-6e3ed94fd70e": ({"instrument": "fortepiano"}, "Toby Sermeus, Bach's Piano Silbermann 1749: a Silbermann fortepiano copy"),
    "bd5461d4-c2cb-4cb3-91fe-bc445e944866": ({"instrument": "piano"}, "Konstantin Lifschitz, pianist; no instrument credit"),
    "45f5123b-b84a-42d1-992b-7f3d2fe15376": ({"instrument": "piano"}, "Schaghajegh Nosrati, pianist; no instrument credit"),
    "69fd0e65-3041-47ca-9bfd-1482b1908e8e": ({"instrument": "piano"}, "Albert Cano Smit, pianist; no instrument credit"),
    "51112582-8d25-44f4-aa5a-3339574614b4": ({"instrument": "organ"}, "Wolfgang Rübsam, Das Orgelwerk; no instrument credit"),
    "7c02db84-fabf-429f-ab54-5aa4006d52b9": ({"instrument": "piano"}, "Joanna MacGregor, pianist, Counterpoint; no instrument credit"),
    "71b8ca58-26b5-4ec7-b669-f7a7276d519a": ({"arrangement": True}, "Austrian Art Gang, a jazz ensemble: a crossover arrangement"),
    "96160808-8c2a-40c4-998c-754c8f5a31be": ({"arrangement": True},
        "KPM library compilation Essential Classic Barocco: an orchestral arrangement, like its Italian Concerto track"),
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
    "bass viol": "viola-da-gamba", "treble recorder / alto recorder": "recorder",
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
HISTORICAL_LEAD = {"baroque-violin", "baroque-cello", "viola-da-gamba", "traverso", "recorder", "violoncello-piccolo"}
# Chamber mode: credits for an accompaniment the music was not written for (a harp or kantele for the
# harpsichord, percussion added). The solo part keeps its instrument; the recording is an arrangement.
CHAMBER_ARRANGED = re.compile(r"\bharp\b|kantele|percussion", re.I)
# Chamber mode: players known to play the flute parts on a period flute, often credited just "flute" or
# "transverse flute" (which maps to the modern flute).
TRAVERSO_PLAYERS = re.compile(r"barthold kuijken|frans br.ggen|wilbert hazelzet|lazarevitch|frank theuns|konrad h.nteler|"
                              r"karl kaiser|jed wentz|alexander murray|ashley solomon|janet see|kossenko|marc hanta|"
                              r"stephen preston|beznosiuk|linde brunmayr|stephen schultz|toshiyuki shibata|anna besson|"
                              r"emi ferguson|diana baroni|marten root|pauliina fred|leopold stastny", re.I)

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
    r"capricornus|ensemble odyss|parlement de musique|phantasm|fretwork|hesp.rion|suonar parlante|les r.cr.ations|"
    r"musica ad rhenum|ricercar consort|ausonia|ensemble diderot|aulos ensemble|basses r.unies", re.I)
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
                            r"early learning centre|malmsteen|alkaloid|allegaeon|drinkall|\bfragile\b|ritenour|max richter|pieranunzi|alperin|dellarole|allhoff|joachim k.hn|"
                            r"glorvigen|horacio franco|mehmari", re.I)
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
# Chamber mode: credits for a solo instrument the schema has no name for (filed as "other").
CHAMBER_OTHER_SOLO = re.compile(r"\bharp\b|pardessus|bandone|bassoon|fagott|pan flute", re.I)
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
    mapped = [INSTRUMENTS.get(i.lower(), "other") for i in perf["ins"] if i.lower() not in NOT_INSTRUMENTS]
    if len(perf["names"]) == 1 and mapped and all(m in CONTINUO and m not in lead for m in mapped):
        # One player credited only with a keyboard or continuo instrument (a pianist's Siciliano, a gambist's
        # flute Partita): the solo part is played on it, arranged.
        return mapped[0], "unknown", True, []
    if not arranged and any(m in lead for m in mapped):
        arranged = [i for i in perf["ins"] if CHAMBER_ARRANGED.search(i)]
    if arranged or ARRANGED_NAMES.search(" ".join(perf["names"])):
        # The solo part on its own instrument with an arranged accompaniment (violin with guitar continuo) is
        # filed under the solo instrument.
        played = next((m for m in mapped if m in lead), None)
        return (played or ("ensemble" if is_group(perf) else INSTRUMENTS.get(arranged[0].lower(), "other")
                           if arranged else "unknown"), "unknown", True, arranged)
    if lead == ["ensemble"]:
        main = "ensemble"
    else:
        main = next((m for m in mapped if m in lead), None) \
            or next((m for m in mapped if m not in CONTINUO and m != "other"), None) \
            or ("other" if any(CHAMBER_OTHER_SOLO.search(i) for i in perf["ins"]) else None) \
            or (lead[0] if perf["ins"] or len(perf["names"]) > 1 else "unknown")
    if main not in lead and main not in ("unknown", "ensemble"):
        # Any instrument outside the solo part's family (a flute or recorder in a violin sonata, a violoncello
        # piccolo, a harp): an arrangement.
        return main, "unknown", True, [i for i in perf["ins"]
                                       if INSTRUMENTS.get(i.lower(), "other") not in {*lead, *CONTINUO}]
    if main == "flute" and TRAVERSO_PLAYERS.search(" ".join(perf["names"])):
        main = "traverso"
    # Another instrument of the solo part's family than the written one (cello or viola for the gamba) is
    # filed as itself with practice modern, unless a period instrument or group says otherwise (plan note).
    substitute = main in lead[1:] and main not in HISTORICAL_LEAD
    practice = ("historical" if main in HISTORICAL_LEAD or period_group(perf)
                else "modern" if "piano" in mapped or substitute else "unknown")
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
            played = {INSTRUMENTS.get(i.lower()) for i in perf["ins"]} & native
            if len(perf["names"]) >= 2 and len(played) >= 2:
                instrument = "ensemble"  # a duo of different instruments (flute and keyboard in the trio sonata)
    solo = len(perf["names"]) == 1
    performers = []
    types = perf.get("types") or []
    # A credit in another script than the role list (정경화 credited, "Kyung-Wha Chung" in the roles): when one name
    # and one role are left unmatched, they belong together.
    lost = [n for n in perf["names"] if not (roles.get(n.lower()) or roles.get(n))]
    spare = [k for k in roles if k not in {n.lower() for n in perf["names"]} | set(perf["names"])]
    for i, name in enumerate(perf["names"]):
        role = roles.get(name.lower()) or roles.get(name)
        if role in NOT_INSTRUMENTS:
            role = None  # "solo": the instrument is named below
        if not role and len(lost) == 1 and len(spare) == 1:
            role = roles[spare[0]]
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
        lead_arranged = [i for i in perf["ins"] if OPEN_ARRANGED.search(i)]
        if lead_arranged and not rec["arrangement"]:  # a recorder with harpsichord, as in the group rule above
            rec["instrument"] = INSTRUMENTS.get(lead_arranged[0].lower(), "other")
            rec["performance_practice"], rec["arrangement"] = "unknown", True
            others = [i for i in perf["ins"] if i != lead_arranged[0]]
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


def solo_player(p: dict, lead: list[str]) -> str | None:
    """Artist ID of the player credited with the solo part's instrument (or of a lone performer)."""
    for name, aid in zip(p["names"], p["ids"]):
        role = (p["roles"].get(name) or p["roles"].get(name.lower()) or "").lower()
        if INSTRUMENTS.get(role) in lead:
            return aid
    return p["ids"][0] if len(p["ids"]) == 1 else None


def join_by_release(perfs: list[dict], lead: list[str] | None = None) -> list[dict]:
    """Fold rows on the same earliest release with the same recording years into one performance; with `lead`,
    only rows with the same solo player, who then leads the performer list."""
    groups: dict[tuple, list[dict]] = {}
    for p in perfs:
        key = (p["releases"][0]["id"], tuple(sorted(p["years"]))) if p["releases"] else (p["repId"],)
        if lead is not None:
            player = solo_player(p, lead) if p["releases"] else None
            key = key + (player,) if player else (p["repId"],)
        groups.setdefault(key, []).append(p)
    out = []
    for group in groups.values():
        if len(group) == 1:
            out.append(group[0])
            continue
        group.sort(key=lambda p: (-len(p["mv"]), -len(p["names"])))
        a = {**group[0], "names": list(group[0]["names"]), "ids": list(group[0]["ids"]),
             "types": list(group[0]["types"]), "roles": dict(group[0]["roles"]), "ins": list(group[0]["ins"]),
             "places": list(group[0]["places"]), "recIds": list(group[0]["recIds"]), "mv": list(group[0]["mv"])}
        for b in group[1:]:
            for i, (name, aid) in enumerate(zip(b["names"], b["ids"])):
                if aid not in a["ids"]:
                    a["names"].append(name)
                    a["ids"].append(aid)
                    if len(a["types"]) == len(a["ids"]) - 1 and i < len(b["types"]):
                        a["types"].append(b["types"][i])
            a["roles"] = {**b["roles"], **a["roles"]}
            a["ins"] += [i for i in b["ins"] if i not in a["ins"]]
            a["places"] += [x for x in b["places"] if x not in a["places"]]
            a["recIds"] += b["recIds"]
            a["mv"] = sorted(set(a["mv"]) | set(b["mv"]), key=lambda m: (m.split(":")[0], int(m.split(":")[1])))
            fr = [x for x in (a["firstRelease"], b["firstRelease"]) if x]
            a["firstRelease"] = min(fr) if fr else None
            a["live"] = a["live"] or b["live"]
        # Lead with the groups, then the players heard on the most rows (the set's leader).
        seen = {aid: sum(aid in p["ids"] for p in group) for aid in a["ids"]}
        grp = lambda i: i < len(a["types"]) and a["types"][i] in GROUP_TYPES
        first = solo_player(group[0], lead) if lead is not None else None
        order_ = sorted(range(len(a["ids"])), key=lambda i: (a["ids"][i] != first, not grp(i), -seen[a["ids"][i]], i))
        a["names"] = [a["names"][i] for i in order_]
        a["ids"] = [a["ids"][i] for i in order_]
        a["types"] = [a["types"][i] for i in order_] if len(a["types"]) == len(order_) else a["types"]
        out.append(a)
    return out


def main(snapshot: str) -> int:
    data = json.loads(Path(snapshot).read_text(encoding="utf-8"))
    EXCLUDE.clear()
    EXCLUDE.update(EXCLUDE_BY_SNAPSHOT.get(Path(snapshot).stem.removeprefix("musicbrainz-"), {}))
    if isinstance(data, list):
        data = {"works": CELLO_SUITES, "native": CELLO_FAMILY, "rows": data}
    bwvs, native, rows = data["works"], set(data["native"]), data["rows"]
    native |= set(NATIVE_EXTRA_BY_SNAPSHOT.get(Path(snapshot).stem.removeprefix("musicbrainz-"), ([], ""))[0])
    # Importer mode (docs/catalogue-plan.md): older snapshots have none; "ensemble" was then the native list.
    mode = data.get("mode") or ("ensemble" if "ensemble" in native else "classic")
    lead = data["native"] + [i for i in NATIVE_EXTRA_BY_SNAPSHOT.get(Path(snapshot).stem.removeprefix("musicbrainz-"),
                                                                   ([], ""))[0] if i not in data["native"]] \
        if mode == "chamber" else None
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
            # Players heard only on the folded-in row (a cellist added for the continuo sonatas) join the set.
            for i, (name, aid) in enumerate(zip(b["names"], b["ids"])):
                if aid not in a["ids"]:
                    a["names"], a["ids"] = a["names"] + [name], a["ids"] + [aid]
                    if len(a["types"]) == len(a["ids"]) - 1 and i < len(b["types"]):
                        a["types"] = a["types"] + [b["types"][i]]
            a["roles"] = {**b["roles"], **a["roles"]}
            a["ins"] = a["ins"] + [i for i in b["ins"] if i not in a["ins"]]
            a["mv"] = sorted(set(a["mv"]) | set(b["mv"]))
            a["years"] = sorted(set(a["years"]) | set(b["years"]))
            a["places"] = list(dict.fromkeys(a["places"] + b["places"]))
            a["recIds"] = a["recIds"] + b["recIds"]
            perfs.remove(b)
    if Path(snapshot).stem.removeprefix("musicbrainz-") in JOIN_BY_PLAYER_RELEASE:
        perfs = join_by_release(perfs, lead or [])
    if Path(snapshot).stem.removeprefix("musicbrainz-") in JOIN_BY_RELEASE:
        perfs = join_by_release(perfs)
    if Path(snapshot).stem.removeprefix("musicbrainz-") in JOIN_BY_RELEASE | JOIN_BY_PLAYER_RELEASE.keys():
        for p in perfs:  # players credited only with their instrument (the album credits, not the track's)
            named = set(p["names"]) | {n.lower() for n in p["names"]}
            unmatched = [n for i, n in enumerate(p["names"]) if n not in p["roles"] and n.lower() not in p["roles"]
                         and not (i < len(p["types"]) and p["types"][i] in GROUP_TYPES)]
            if not unmatched:
                p["names"] = p["names"] + [k for k in p["roles"] if k not in named and k.lower() not in named
                                           and p["roles"][k].lower() not in ("conductor", "orchestra")]
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
        key = perf["repId"] if perf["repId"] in overrides or Path(snapshot).stem.removeprefix("musicbrainz-") not in JOIN_BY_RELEASE \
            else next((r for r in perf["recIds"] if r in overrides), perf["repId"])  # a joined set: any of its rows
        if key in overrides:
            fix = overrides[key][0]
            if "performers" in fix:
                new["performers"] = [dict(p) for p in fix["performers"]]
            if "instrument" in fix:
                new["instrument"] = fix["instrument"]
                new["performance_practice"] = ("historical" if fix["instrument"] in HISTORICAL
                                               else "modern" if fix["instrument"] in MODERN | {"viola"} else "unknown")
                if len(new["performers"]) == 1 and "performers" not in fix:
                    new["performers"][0]["role"] = fix["instrument"]
            if "performance_practice" in fix:
                new["performance_practice"] = fix["performance_practice"]
            if "movements" in fix:  # the movements the recording actually plays, as "<bwv>:<index>"
                new["works"] = works_block({**perf, "mv": fix["movements"]}, bwvs, moves)
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
