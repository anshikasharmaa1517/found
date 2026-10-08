"""Fictional demo dataset for Found (design Sections 14 and 16, Q6).

    python data/generator/generate.py            # writes data/fixtures/demo-v1/
    python data/generator/generate.py --check    # exits 1 if the files are out of date

The scenario is a flood along a fictional Himalayan river valley. Every person,
organization and place is invented. Output is deterministic: the same seed always
gives byte-identical files, so a demo reset restores exactly the same incident.

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
    "name": "Kesari Valley flood (fictional demo)",
    "is_demo": True,
    "started_at": "2026-10-02T18:30:00+05:30",
}

# id, name, type, reference prefix
ORGANIZATIONS = [
    ("org_police", "District Police Demo", "POLICE", "DPD"),
    ("org_hospital", "Central Hospital Demo", "HOSPITAL", "CHD"),
    ("org_clinic", "Hill Clinic Demo", "HOSPITAL", "HCD"),
    ("org_ngo", "Flood Relief Demo", "NGO", "FRD"),
    ("org_shelter", "Riverside Shelter Demo", "SHELTER_OPERATOR", "RSD"),
    ("org_volunteers", "Valley Volunteers Demo", "COMMUNITY", "VVD"),
]
ORG = {o[0]: o for o in ORGANIZATIONS}

# Invented places along the valley; coordinates are only for the map.
PLACES = {
    "old_bridge": ("Old Bridge", 30.7268, 78.4354),
    "upper_village": ("Upper Village", 30.7412, 78.4471),
    "market_ghat": ("Market Ghat", 30.7231, 78.4302),
    "temple_steps": ("Temple Steps", 30.7305, 78.4389),
    "school": ("Valley School Building", 30.7189, 78.4265),
    "shelter": ("Riverside Shelter", 30.7156, 78.4228),
    "hospital": ("Central Hospital Demo grounds", 30.7102, 78.4187),
    "footbridge": ("Upper Footbridge", 30.7357, 78.4420),
}

FIRST_NAMES = [
    "Aarti", "Bhuvan", "Chanda", "Dinesh", "Ekta", "Farhan", "Gita", "Harish", "Isha",
    "Jagdish", "Kamla", "Lokesh", "Mohan", "Nisha", "Om", "Parvati", "Rajesh", "Savita",
    "Tarun", "Uma", "Vinod", "Yamini", "Zoya", "Anil", "Beena", "Chetan",
]  # fmt: skip
LAST_NAMES = [
    "Bhandari", "Chauhan", "Dhyani", "Gusain", "Joshi", "Kathait", "Mehra", "Nautiyal",
    "Panwar", "Rana", "Semwal", "Tomar", "Uniyal", "Bisht", "Negi", "Rawat",
]  # fmt: skip


def place(key: str) -> dict:
    name, lat, lon = PLACES[key]
    return {"name": name, "lat": lat, "lon": lon}


class Builder:
    def __init__(self) -> None:
        self.people: list[dict] = []
        self.reports: list[dict] = []
        self.counters = {o[0]: 0 for o in ORGANIZATIONS}

    def person(self, key: str, name: str, age: int | None, notes: str | None = None) -> str:
        self.people.append({"key": key, "name": name, "age": age, "notes": notes})
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
    ) -> None:
        self.counters[org] += 1
        reference = f"{ORG[org][3]}-{self.counters[org]:04d}"
        self.reports.append(
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
    maya = b.person("maya", "Maya Rawat", 24, "Wears a red jacket.")
    b.report("org_police", maya, "MISSING",
             "Family reports Maya Rawat, 24, missing since the bridge collapse near the "
             "Old Bridge.", "2026-10-02T21:10:00+05:30", where="old_bridge")
    b.report("org_hospital", maya, "FOUND_SAFE",
             "Maya Rawat, 24, admitted to ward 3 at 07:40. Condition stable.",
             "2026-10-03T07:40:00+05:30", value="Ward 3, stable", where="hospital")
    b.report("org_ngo", maya, "FOUND_SAFE",
             "According to Central Hospital Demo, Maya Rawat was admitted to ward 3 and is "
             "stable.", "2026-10-03T08:30:00+05:30")

    arjun = b.person("arjun", "Arjun Negi", 31)
    b.report("org_police", arjun, "MISSING",
             "Arjun Negi, 31, reported missing by his brother after the river rose.",
             "2026-10-02T22:05:00+05:30", where="market_ghat")
    b.report("org_volunteers", arjun, "SEEN_AT_LOCATION",
             "Our team met Arjun Negi at the Upper Footbridge helping neighbours.",
             "2026-10-03T06:15:00+05:30", where="footbridge")
    b.report("org_shelter", arjun, "SHELTERED",
             "Arjun Negi registered at the shelter desk, hall B.",
             "2026-10-03T11:20:00+05:30", value="Hall B", where="shelter")

    deepak = b.person("deepak", "Deepak Joshi", 45)
    b.report("org_hospital", deepak, "INJURED",
             "Deepak Joshi, 45, admitted with leg injuries and taken into surgery.",
             "2026-10-03T05:50:00+05:30", value="Leg injuries", where="hospital")
    b.report("org_ngo", deepak, "FOUND_SAFE",
             "According to Central Hospital Demo, Deepak Joshi is safe and unhurt.",
             "2026-10-03T09:10:00+05:30")

    sunita = b.person("sunita", "Sunita Rana", 38)
    b.report("org_clinic", sunita, "INJURED",
             "Sunita Rana treated for a fractured wrist, kept for observation.",
             "2026-10-03T04:30:00+05:30", value="Fractured wrist")
    b.report("org_ngo", sunita, "INJURED",
             "Per Hill Clinic Demo, Sunita Rana has a fractured wrist and is under "
             "observation.", "2026-10-03T07:05:00+05:30")

    kavita = b.person("kavita", "Kavita Bisht", 29)
    b.report("org_police", kavita, "MISSING",
             "Kavita Bisht, 29, reported missing with her son from Upper Village.",
             "2026-10-02T23:40:00+05:30", where="upper_village")
    b.report("org_shelter", kavita, "SHELTERED",
             "Kavita Bisht and her son registered at the shelter, hall B.",
             "2026-10-03T10:00:00+05:30", value="Hall B, with son", where="shelter")

    vikram = b.person("vikram", "Vikram Singh", 52)
    b.report("org_police", vikram, "MISSING",
             "Vikram Singh, 52, last seen near the market on the evening of the flood.",
             "2026-10-02T20:30:00+05:30", where="market_ghat")
    # No reported time: the watcher cannot order it, so it goes to a reviewer.
    b.report("org_volunteers", vikram, "FOUND_SAFE",
             "Someone at the temple said Vikram Singh is fine.", None, where="temple_steps")

    ramesh = b.person("ramesh", "Ramesh Thapliyal", 67)
    b.report("org_police", ramesh, "MISSING",
             "Ramesh Thapliyal, 67, missing from his house by the river.",
             "2026-10-02T21:55:00+05:30", where="old_bridge")
    # Sensitive: held for a reviewer before anyone else sees it in full.
    b.report("org_hospital", ramesh, "DECEASED",
             "Ramesh Thapliyal, 67, was brought in and declared dead at 03:20.",
             "2026-10-03T03:20:00+05:30", where="hospital")

    pooja = b.person("pooja", "Pooja Rawat", 17)
    b.report("org_shelter", pooja, "SHELTERED",
             "Pooja Rawat, 17, is staying at the shelter in hall A.",
             "2026-10-03T09:30:00+05:30", value="Hall A", where="shelter")
    b.report("org_volunteers", pooja, "SHELTERED",
             "Riverside Shelter Demo says Pooja Rawat moved to the school building.",
             "2026-10-03T12:45:00+05:30", where="school")

    asha = b.person("asha", "Asha Devi", 58)
    b.report("org_police", asha, "MISSING",
             "Asha Devi, 58, missing from Market Ghat.", "2026-10-02T22:40:00+05:30",
             where="market_ghat")
    # The source name is misspelled, so it is not offered as a named source.
    b.report("org_volunteers", asha, "FOUND_SAFE",
             "According to Centrel Hospitl Demo, Asha Devi was admitted.",
             "2026-10-03T13:10:00+05:30")


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
                 f"2026-10-02T{rng.choice(hours)}:00+05:30", where=where)
        if rng.random() < 0.75:
            org = rng.choice(found_by)
            claim_type, template, spot = outcome_text[org]
            hour = rng.randint(5, 16)
            b.report(org, key, claim_type, template.format(name=name, place=place_name),
                     f"2026-10-03T{hour:02d}:{rng.choice(['00', '20', '45'])}:00+05:30",
                     where=spot or where)


def build(seed: int = SEED) -> dict[str, object]:
    b = Builder()
    story(b)
    background(b, random.Random(seed))
    return {
        "incident.json": {**INCIDENT, "version": VERSION, "seed": seed},
        "organizations.json": [
            {"id": oid, "name": name, "org_type": kind} for oid, name, kind, _ in ORGANIZATIONS
        ],
        "people.json": b.people,
        "reports.json": b.reports,
        # Recorded real runs, restored as REPLAYED on reset. Filled only from real runs.
        "runs.json": [],
    }


def render(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the fictional demo dataset.")
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
