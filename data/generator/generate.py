"""Demo dataset for Found (design Sections 14 and 16, Q6).

    python data/generator/generate.py            # writes data/fixtures/demo-v1/
    python data/generator/generate.py --check    # exits 1 if the files are out of date

The scenario is set at Trishuli Bazar, Nuwakot, Nepal, on the Trishuli river that flooded
on 26 August 2026. Output is deterministic: the same seed always gives byte-identical
files, so a demo reset restores exactly the same incident.

Standard library only, so it runs anywhere without the backend installed.
"""

import argparse
import json
import random
import sys
from pathlib import Path

VERSION = "demo-v1"
SEED = 20261002
OUT = Path(__file__).resolve().parents[1] / "fixtures" / VERSION

INCIDENT = {
    "id": "inc_demo",
    "name": "Trishuli flood",
    "area": "Trishuli Bazar, Nuwakot, Nepal",
    "is_demo": True,
    "started_at": "2026-08-26T18:30:00+05:45",
}

# id, name, type, reference prefix
ORGANIZATIONS = [
    ("org_police", "District Police", "POLICE", "DPD"),
    ("org_hospital", "Central Hospital", "HOSPITAL", "CHD"),
    ("org_clinic", "Hill Clinic", "HOSPITAL", "HCD"),
    ("org_ngo", "Flood Relief", "NGO", "FRD"),
    ("org_shelter", "Riverside Shelter", "SHELTER_OPERATOR", "RSD"),
    ("org_volunteers", "Valley Volunteers", "COMMUNITY", "VVD"),
]
ORG = {o[0]: o for o in ORGANIZATIONS}

# Places along the Trishuli at Trishuli Bazar. The coordinates put each one on a sensible spot of the real terrain under the map (the bridges
# on the river course in OpenStreetMap, the ghat and steps on the north bank below the
# bazaar, the hospital and school on real hospital and school grounds), so pins do not land
# on empty hillsides.
PLACES = {
    "old_bridge": ("Old Bridge", 27.9206, 85.1463),
    "upper_village": ("Upper Village", 27.9300, 85.1480),
    "market_ghat": ("Market Ghat", 27.9217, 85.1484),
    "temple_steps": ("Temple Steps", 27.9206, 85.1426),
    "school": ("Valley School Building", 27.9226, 85.1390),
    "shelter": ("Riverside Shelter", 27.9232, 85.1440),
    "hospital": ("Central Hospital grounds", 27.9246, 85.1408),
    "footbridge": ("Upper Footbridge", 27.9290, 85.1491),
}

# The Trishuli Ganga through Trishuli Bazar, upstream first, as (lon, lat): every second
# point of OpenStreetMap ways 27033466 and 915399520. Drawn as the river's course; it is not
# the extent of the flood, which this dataset does not know.
# Nearby rivers and the Nuwakot district boundary, drawn faintly around the flooded river
# for orientation. Rivers are OpenStreetMap waterways (rivers, and streams with a name) in
# 27.84-28.00 N, 85.05-85.25 E; the district is OpenStreetMap relation 4583250. Both are
# simplified to about 20 m so the incident stays one small item.
MAP_CONTEXT = json.loads((Path(__file__).with_name("map_context.json")).read_text("utf-8"))

RIVER = {
    "name": "Trishuli river",
    "note": "Flooded on 26 August 2026. The line is the river's course from map data, "
    "not the extent of the flood.",
    "attribution": "River course: OpenStreetMap contributors (ODbL)",
    "coordinates": [
    (85.1561354, 27.9362994), (85.1556677, 27.9351314), (85.1553276, 27.9340437),
    (85.1552937, 27.9336297), (85.1554876, 27.9329836), (85.1548091, 27.9320262),
    (85.1542915, 27.9317982), (85.1538698, 27.9317822), (85.1534774, 27.9318645),
    (85.1532213, 27.9319745), (85.152587, 27.9325771), (85.1521801, 27.9329648),
    (85.1518678, 27.9332424), (85.1512398, 27.9339255), (85.1510516, 27.9340036),
    (85.1508589, 27.9339555), (85.1506095, 27.9337192), (85.150258, 27.9332204),
    (85.1500336, 27.9327027), (85.1499517, 27.9324006), (85.1499089, 27.9320065),
    (85.1498703, 27.9313475), (85.1495471, 27.9301652), (85.1492734, 27.9294425),
    (85.1491171, 27.9290659), (85.1490013, 27.9289195), (85.1489158, 27.9287046),
    (85.1489246, 27.9285362), (85.1491503, 27.928298), (85.1494965, 27.9280735),
    (85.1500355, 27.927574), (85.1505044, 27.9270029), (85.1507258, 27.926606),
    (85.1509359, 27.9260911), (85.1510742, 27.9257019), (85.1511048, 27.9253146),
    (85.1511333, 27.9249894), (85.1511837, 27.9246215), (85.1512911, 27.9241472),
    (85.1513415, 27.9237174), (85.1513305, 27.9231075), (85.1512385, 27.9227958),
    (85.1509383, 27.922335), (85.1506469, 27.9220717), (85.1502678, 27.9220117),
    (85.1498471, 27.921911), (85.1495359, 27.9218491), (85.1492423, 27.9217813),
    (85.1489553, 27.9216342), (85.1485477, 27.9214076), (85.1482541, 27.9212566),
    (85.1477983, 27.9210669), (85.1470818, 27.920821), (85.1466808, 27.9206835),
    (85.1463478, 27.9206313), (85.1457386, 27.9205771), (85.1451295, 27.9205132),
    (85.1444984, 27.9204802), (85.1440689, 27.9204628), (85.1435409, 27.9204551),
    (85.1432494, 27.9204144), (85.1429712, 27.9202382), (85.1426534, 27.9199827),
    (85.1424124, 27.9197058), (85.1421626, 27.9192547), (85.1419435, 27.9188674),
    (85.1415929, 27.9184202), (85.1412029, 27.9180117), (85.1408107, 27.9176109),
    (85.140436, 27.9173553), (85.1400284, 27.9171501), (85.1396712, 27.9169971),
    (85.1393163, 27.9169371), (85.1387578, 27.9168768), (85.1377937, 27.9166871),
    (85.1370177, 27.9165344), (85.1362245, 27.9163136), (85.1349421, 27.9157659),
    (85.1343171, 27.9152245), (85.1341454, 27.9143144), (85.1353721, 27.9134195),
    (85.1380735, 27.9106469), (85.1389519, 27.9082467), (85.1394667, 27.9061918),
    ],
}

FIRST_NAMES = [
    "Anita", "Bimal", "Chandra", "Dawa", "Ganga", "Hira", "Ishwor", "Januka", "Kiran",
    "Lila", "Mina", "Nabin", "Pemba", "Prakash", "Rajan", "Sabina", "Suman", "Tara",
    "Ujjwal", "Yam", "Binita", "Dhan", "Gita", "Nirmala", "Ramesh", "Saraswati",
]  # fmt: skip
LAST_NAMES = [
    "Bhandari", "Dahal", "Gautam", "Ghale", "Hyolmo", "Khadka", "Lama", "Magar",
    "Nepal", "Pandey", "Rai", "Shrestha", "Sherpa", "Tamang", "Thapa", "Tiwari",
]  # fmt: skip


def place(key: str) -> dict:
    name, lat, lon = PLACES[key]
    return {"name": name, "lat": lat, "lon": lon}


class Builder:
    def __init__(self) -> None:
        self.people: list[dict] = []
        self.reports: list[dict] = []
        # Reports the demo story publishes when someone presses its button (step 3), not
        # at load. They take their reference in order, so every other reference stays put.
        self.prepared: list[dict] = []
        self.counters = {o[0]: 0 for o in ORGANIZATIONS}

    def person(self, key: str, name: str, age: int | None, notes: str | None = None) -> str:
        self.people.append({"key": key, "name": name, "age": age, "notes": notes})
        return key

    def thing(self, key: str, kind: str, name: str) -> str:
        """A road, bridge, shelter, aid point, hazard or place (climate layers)."""
        self.people.append({"key": key, "name": name, "type": kind, "age": None, "notes": None})
        return key

    def report(
        self,
        org: str,
        person: str,
        claim_type: str,
        text: str,
        reported_at: str | None,
        *,
        value: str | None = None,
        where: str | None = None,
        prepared: bool = False,
    ) -> None:
        self.counters[org] += 1
        reference = f"{ORG[org][3]}-{self.counters[org]:04d}"
        (self.prepared if prepared else self.reports).append(
            {
                "org_id": org,
                "external_reference": reference,
                "person": person,
                "claim_type": claim_type,
                "value": value,
                "original_text": text,
                "reported_at": reported_at,
                "location": place(where) if where else None,
            }
        )


def story(b: Builder) -> None:
    """Hand-written people that walk through the design's use cases."""
    sita = b.person("sita", "Sita Tamang", 24, "Wears a red jacket.")
    b.report("org_police", sita, "MISSING",
             "Family reports Sita Tamang, 24, missing since the bridge collapse near the "
             "Old Bridge.", "2026-08-26T21:10:00+05:45", where="old_bridge")
    # Held back until the story's step 3, as in Trace: publishing it is what alerts
    # Sita's followers.
    b.report("org_hospital", sita, "FOUND_SAFE",
             "Sita Tamang, 24, admitted to ward 3 at 07:40. Condition stable.",
             "2026-08-27T07:40:00+05:45", value="Ward 3, stable", where="hospital",
             prepared=True)
    # A volunteer group passing on the police report (step 4 traces it): a relay, which is
    # never independent confirmation. Loaded from the start, so a recorded check of it can
    # be restored on every reset.
    b.report("org_ngo", sita, "MISSING",
             "According to District Police, Sita Tamang, 24, is missing near the Old Bridge.",
             "2026-08-26T22:30:00+05:45")

    bikash = b.person("bikash", "Bikash Shrestha", 31)
    b.report("org_police", bikash, "MISSING",
             "Bikash Shrestha, 31, reported missing by his brother after the river rose.",
             "2026-08-26T22:05:00+05:45", where="market_ghat")
    b.report("org_volunteers", bikash, "SEEN_AT_LOCATION",
             "Our team met Bikash Shrestha at the Upper Footbridge helping neighbours.",
             "2026-08-27T06:15:00+05:45", where="footbridge")
    b.report("org_shelter", bikash, "SHELTERED",
             "Bikash Shrestha registered at the shelter desk, hall B.",
             "2026-08-27T11:20:00+05:45", value="Hall B", where="shelter")

    dipak = b.person("dipak", "Dipak Karki", 45)
    b.report("org_hospital", dipak, "INJURED",
             "Dipak Karki, 45, admitted with leg injuries and taken into surgery.",
             "2026-08-27T05:50:00+05:45", value="Leg injuries", where="hospital")
    b.report("org_ngo", dipak, "FOUND_SAFE",
             "According to Central Hospital, Dipak Karki is safe and unhurt.",
             "2026-08-27T09:10:00+05:45")

    sunita = b.person("sunita", "Sunita Magar", 38)
    b.report("org_clinic", sunita, "INJURED",
             "Sunita Magar treated for a fractured wrist, kept for observation.",
             "2026-08-27T04:30:00+05:45", value="Fractured wrist")
    b.report("org_ngo", sunita, "INJURED",
             "Per Hill Clinic, Sunita Magar has a fractured wrist and is under "
             "observation.", "2026-08-27T07:05:00+05:45")

    kamala = b.person("kamala", "Kamala Lama", 29)
    b.report("org_police", kamala, "MISSING",
             "Kamala Lama, 29, reported missing with her son from Upper Village.",
             "2026-08-26T23:40:00+05:45", where="upper_village")
    b.report("org_shelter", kamala, "SHELTERED",
             "Kamala Lama and her son registered at the shelter, hall B.",
             "2026-08-27T10:00:00+05:45", value="Hall B, with son", where="shelter")

    hari = b.person("hari", "Hari Thapa", 52)
    b.report("org_police", hari, "MISSING",
             "Hari Thapa, 52, last seen near the market on the evening of the flood.",
             "2026-08-26T20:30:00+05:45", where="market_ghat")
    # No reported time: the watcher cannot order it, so it goes to a reviewer.
    b.report("org_volunteers", hari, "FOUND_SAFE",
             "Someone at the temple said Hari Thapa is fine.", None, where="temple_steps")

    gopal = b.person("gopal", "Gopal Adhikari", 67)
    b.report("org_police", gopal, "MISSING",
             "Gopal Adhikari, 67, missing from his house by the river.",
             "2026-08-26T21:55:00+05:45", where="old_bridge")
    # Sensitive: held for a reviewer before anyone else sees it in full.
    b.report("org_hospital", gopal, "DECEASED",
             "Gopal Adhikari, 67, was brought in and declared dead at 03:20.",
             "2026-08-27T03:20:00+05:45", where="hospital")

    puja = b.person("puja", "Puja Tamang", 17)
    b.report("org_shelter", puja, "SHELTERED",
             "Puja Tamang, 17, is staying at the shelter in hall A.",
             "2026-08-27T09:30:00+05:45", value="Hall A", where="shelter")
    b.report("org_volunteers", puja, "SHELTERED",
             "Riverside Shelter says Puja Tamang moved to the school building.",
             "2026-08-27T12:45:00+05:45", where="school")

    laxmi = b.person("laxmi", "Laxmi Basnet", 58)
    b.report("org_police", laxmi, "MISSING",
             "Laxmi Basnet, 58, missing from Market Ghat.", "2026-08-26T22:40:00+05:45",
             where="market_ghat")
    # The source name is misspelled, so it is not offered as a named source.
    b.report("org_volunteers", laxmi, "FOUND_SAFE",
             "According to Centrel Hospitl, Laxmi Basnet was admitted.",
             "2026-08-27T13:10:00+05:45")


def background(b: Builder, rng: random.Random, count: int = 22) -> None:
    """Generated people with ordinary report sequences, so lists and maps look real."""
    names: set[str] = {p["name"] for p in b.people}
    hours = ["21:15", "21:40", "22:10", "22:35", "23:05", "23:50"]
    found_by = ["org_shelter", "org_hospital", "org_volunteers", "org_clinic"]
    outcome_text = {
        "org_shelter": ("SHELTERED", "{name} registered at the shelter desk.", "shelter"),
        "org_hospital": ("FOUND_SAFE", "{name} treated for exposure and discharged.", "hospital"),
        "org_volunteers": ("FOUND_SAFE", "Our team found {name} safe near {place}.", None),
        "org_clinic": ("INJURED", "{name} treated for cuts and bruises.", None),
    }
    for n in range(count):
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in names:
                names.add(name)
                break
        age = rng.randint(4, 82) if rng.random() > 0.1 else None
        key = b.person(f"bg{n + 1:02d}", name, age)
        where = rng.choice(["old_bridge", "upper_village", "market_ghat", "temple_steps"])
        place_name = PLACES[where][0]
        age_text = f", {age}," if age is not None else ""
        b.report("org_police", key, "MISSING",
                 f"{name}{age_text} reported missing near {place_name}.",
                 f"2026-08-26T{rng.choice(hours)}:00+05:45", where=where)
        if rng.random() < 0.75:
            org = rng.choice(found_by)
            claim_type, template, spot = outcome_text[org]
            hour = rng.randint(5, 16)
            b.report(org, key, claim_type, template.format(name=name, place=place_name),
                     f"2026-08-27T{hour:02d}:{rng.choice(['00', '20', '45'])}:00+05:45",
                     where=spot or where)


def climate(b: Builder) -> None:
    """Roads, bridges, shelters, aid and hazards along the valley (design UC-7).

    Added after the people so their report references stay the same. The bridge has
    two sources that disagree, and both must stay visible.
    """
    bridge = b.thing("c_old_bridge", "INFRASTRUCTURE", "Old Bridge")
    b.report("org_police", bridge, "BRIDGE_DAMAGED",
             "Old Bridge closed to all traffic after the collapse of its eastern span.",
             "2026-08-26T20:10:00+05:45", where="old_bridge")
    b.report("org_volunteers", bridge, "BRIDGE_OPEN",
             "Old Bridge open on foot, our team crossed it this morning.",
             "2026-08-27T08:15:00+05:45", where="old_bridge")

    road = b.thing("c_village_road", "INFRASTRUCTURE", "Upper Village road")
    b.report("org_police", road, "ROAD_BLOCKED",
             "Upper Village road blocked by a landslide above the temple bend.",
             "2026-08-26T23:30:00+05:45", where="upper_village")
    b.report("org_police", road, "ROAD_OPEN",
             "Upper Village road reopened for light vehicles after clearing.",
             "2026-08-27T15:00:00+05:45", where="upper_village")

    shelter = b.thing("c_riverside_shelter", "SHELTER", "Riverside Shelter")
    b.report("org_shelter", shelter, "SHELTER_OPEN",
             "Riverside Shelter open, 120 places, blankets and hot meals available.",
             "2026-08-26T22:00:00+05:45", where="shelter")
    b.report("org_shelter", shelter, "SHELTER_FULL",
             "Riverside Shelter full; new arrivals sent to the school building.",
             "2026-08-27T11:00:00+05:45", where="shelter")

    school = b.thing("c_school_shelter", "SHELTER", "Valley School Building")
    b.report("org_ngo", school, "SHELTER_OPEN",
             "Valley School Building opened as an overflow shelter with 60 places.",
             "2026-08-27T11:30:00+05:45", where="school")

    aid = b.thing("c_ghat_aid", "AID_POINT", "Market Ghat aid point")
    b.report("org_ngo", aid, "AID_AVAILABLE",
             "Drinking water and dry rations available at the Market Ghat aid point.",
             "2026-08-27T07:00:00+05:45", where="market_ghat")

    river = b.thing("c_river_ghat", "HAZARD", "Trishuli river at Market Ghat")
    b.report("org_police", river, "WATER_RISING",
             "Trishuli river rising fast at Market Ghat, residents moved uphill.",
             "2026-08-26T19:45:00+05:45", where="market_ghat")
    b.report("org_volunteers", river, "WATER_RECEDING",
             "Water at Market Ghat has gone down by about a metre since midnight.",
             "2026-08-27T06:30:00+05:45", where="market_ghat")


def duplicate(b: Builder) -> None:
    """A second record for Sita under a shortened name (design UC-3).

    Same age, same place: the resolver proposes the pair and a reviewer decides. Added
    last so every earlier report reference stays the same.
    """
    sita_t = b.person("sita_t", "Sita T.", 24)
    b.report("org_ngo", sita_t, "SEEN_AT_LOCATION",
             "Volunteer desk: Sita T., 24, was seen near the Old Bridge asking for her family.",
             "2026-08-27T09:30:00+05:45", where="old_bridge")


def build(seed: int = SEED) -> dict[str, object]:
    b = Builder()
    story(b)
    background(b, random.Random(seed))
    climate(b)
    duplicate(b)
    return {
        "incident.json": {
            **INCIDENT,
            "river": RIVER,
            "map_context": MAP_CONTEXT,
            "version": VERSION,
            "seed": seed,
        },
        "organizations.json": [
            {"id": oid, "name": name, "org_type": kind} for oid, name, kind, _ in ORGANIZATIONS
        ],
        "people.json": b.people,
        "reports.json": b.reports,
        "prepared.json": b.prepared,
        # Recorded real runs, restored as REPLAYED on reset. Filled only from real runs.
        "runs.json": [],
    }


def render(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the demo dataset.")
    parser.add_argument("--check", action="store_true", help="Fail if files are out of date.")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    files = build()
    stale = []
    for name, data in files.items():
        path = args.out / name
        if name == "runs.json" and path.exists():
            # Runs are recorded from live investigations, never generated.
            continue
        text = render(data)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    if stale:
        print(f"Out of date: {', '.join(stale)}. Run data/generator/generate.py.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
