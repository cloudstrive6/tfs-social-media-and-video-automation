"""Fetch the curated Fluent Emoji (Flat) props into engine/assets/emoji/ (MIT, (c) Microsoft Corporation).

    python engine/scripts/fetch_emoji.py

Writes <key>.svg files plus index.json ({key: {"name", "group"}}), the vocabulary the Motion Designer uses.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "emoji"
RAW = "https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/assets/{name}/Flat/{file}_flat.svg"

GROUPS = {
    "money": ["Money bag", "Money with wings", "Dollar banknote", "Coin", "Credit card", "Heavy dollar sign",
              "Bank", "Receipt", "Chart increasing", "Chart decreasing", "Bar chart", "Gem stone", "Balance scale",
              "Abacus", "Red envelope", "Wrapped gift", "Envelope with arrow", "Shopping cart", "Shopping bags"],
    "documents": ["Page facing up", "Page with curl", "Clipboard", "Memo", "Newspaper", "Rolled-up newspaper",
                  "Scroll", "Ledger", "File folder", "Open file folder", "File cabinet", "Card index", "Books",
                  "Open book", "Closed book", "Notebook", "Envelope", "Incoming envelope", "Package", "Label",
                  "Bookmark tabs", "Pushpin", "Round pushpin", "Paperclip", "Pencil", "Fountain pen", "Pen",
                  "Writing hand", "Ballot box with ballot", "Identification card", "Calendar", "Spiral calendar",
                  "Magnifying glass tilted left", "Link", "Chains", "Locked", "Unlocked", "Old key", "Key",
                  "Locked with key", "Inbox tray", "Outbox tray", "Wastebasket", "Placard"],
    "law_power": ["Classical building", "Judge", "Man judge", "Woman judge", "Police officer", "Oncoming police car",
                  "Police car light", "Crown", "Person with crown", "Military medal", "1st place medal", "Trophy",
                  "Crossed swords", "Dagger", "Shield", "Megaphone", "Loudspeaker", "Microphone", "Studio microphone",
                  "Speaking head", "Bust in silhouette", "Busts in silhouette", "Handshake", "Raised fist",
                  "Clapping hands", "Folded hands", "Thumbs up", "Thumbs down", "Index pointing up",
                  "Backhand index pointing right", "Backhand index pointing left", "Ok hand", "Flexed biceps",
                  "Office worker", "Construction worker", "Farmer", "Health worker", "Teacher", "Student",
                  "Factory worker", "Cook", "Firefighter", "Pilot", "Detective"],
    "places": ["House", "Houses", "House with garden", "Derelict house", "Hut", "Office building", "Hospital",
               "School", "Church", "Mosque", "Hotel", "Convenience store", "Department store", "Factory",
               "Building construction", "Construction", "Bridge at night", "Cityscape", "Cityscape at dusk",
               "Night with stars", "Sunrise", "Sunrise over mountains", "Mountain", "Volcano", "Desert island",
               "Beach with umbrella", "National park", "Statue of liberty", "European castle", "Stadium",
               "Fountain", "Tent", "Camping", "Motorway", "Railway track", "Bus stop", "Fuel pump",
               "World map", "Globe showing asia-australia", "Globe with meridians", "Compass"],
    "transport": ["Bus", "Oncoming bus", "Minibus", "Automobile", "Oncoming automobile", "Taxi", "Oncoming taxi",
                  "Delivery truck", "Pickup truck", "Motorcycle", "Motor scooter", "Bicycle", "Ambulance",
                  "Fire engine", "Airplane", "Airplane departure", "Airplane arrival", "Passenger ship", "Ferry",
                  "Motor boat", "Canoe", "Sailboat", "Ship", "Anchor", "Metro", "Train", "Tractor", "Vertical traffic light"],
    "nature_weather": ["Cloud with rain", "Cloud with lightning and rain", "Tornado", "Water wave", "Droplet",
                       "Umbrella with rain drops", "Fire", "Collision", "Sun", "Sun behind cloud", "Rainbow",
                       "Palm tree", "Coconut", "Seedling", "Herb", "Sheaf of rice", "Ear of corn", "Deciduous tree",
                       "Fallen leaf", "Rock", "Wood", "Brick", "Fish", "Chicken", "Pig", "Water buffalo", "Rat",
                       "Snake", "Crocodile", "Mosquito", "Cockroach", "Monkey", "Eagle"],
    "food_home": ["Cooked rice", "Rice ball", "Bowl with spoon", "Pot of food", "Cooking", "Bread", "Egg",
                  "Banana", "Mango", "Pineapple", "Shallow pan of food", "Teacup without handle", "Hot beverage",
                  "Baby bottle", "Basket", "Bucket", "Broom", "Soap", "Chair", "Bed", "Door", "Window",
                  "Toilet", "Candle", "Light bulb", "Electric plug", "Battery", "Low battery", "Television",
                  "Radio", "Mobile phone", "Laptop", "Desktop computer", "Satellite antenna"],
    "health": ["Pill", "Syringe", "Stethoscope", "Microbe", "Face with medical mask", "Hospital", "Ambulance",
               "Drop of blood", "Dna", "Test tube", "Thermometer", "Adhesive bandage", "Tooth", "Brain", "Lungs",
               "Anatomical heart"],
    "symbols": ["Warning", "No entry", "Prohibited", "Cross mark", "Check mark button", "Check mark",
                "Question mark", "Red question mark", "Exclamation question mark", "Double exclamation mark",
                "Hundred points", "Eyes", "Bomb", "Hourglass not done", "Hourglass done", "Alarm clock",
                "Stopwatch", "Stop sign", "Bell", "Light bulb", "Gear", "Hammer", "Hammer and wrench", "Wrench",
                "Scissors", "Balloon", "Party popper", "Confetti ball", "Firecracker", "Fireworks", "Sparkles",
                "Star", "Glowing star", "Heart on fire", "Broken heart", "Skull", "Ghost", "Clown face",
                "Face with steam from nose", "Face with rolling eyes", "Thinking face", "Face with monocle",
                "Money-mouth face", "Lying face", "Zipper-mouth face", "Shushing face", "Face screaming in fear",
                "Face with open mouth", "Grimacing face", "Loudly crying face", "Smirking face",
                "Face with raised eyebrow", "Nerd face", "Sleeping face", "Exploding head",
                "Face with hand over mouth", "Pouting face", "Grinning face with sweat", "Rolling on the floor laughing"],
}


def key_of(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# Our story is in pesos: the Fluent money emoji carry a "$". Each $ glyph is swapped for a ₱ in the same place
# (key: (index of the $ path among the file's <path>s, centre x, centre y, font size, rotation)).
PESO = {
    "money_bag": ("M15.8401 19.3449", 15.84, 20.06, 12.5, 0),
    "money_with_wings": ("M9.65035 14.6466", None, None, 7.5, -45),
    "dollar_banknote": ("M9.5 12C9.77614", 9.6, 16.4, 9, 0),
}
RENAME = {"dollar_banknote": "peso_banknote"}
DROP = {"heavy_dollar_sign"}


def _bbox(d: str) -> tuple[float, float, float, float]:
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", d)]
    xs, ys = nums[0::2], nums[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def pesofy(svg: str, key: str) -> str:
    start, cx, cy, size, rot = PESO[key]
    at = svg.find(start)
    if at < 0:
        return svg
    path_start = svg.rfind("<path", 0, at)
    path_end = svg.find("/>", at) + 2
    d_start = svg.rfind('d="', path_start, at) + 3
    d_end = svg.find('"', at)
    fill = re.search(r'fill="([^"]+)"', svg[path_start:path_end])
    if key == "money_bag":                         # the $ shares a path with the bag's neck band: keep the band
        band = svg[d_start:at].rstrip("ZM ").rstrip() + "Z"
        new_path = svg[path_start:d_start] + band + svg[d_end:path_end]
    else:
        new_path = ""
        if cx is None:                                 # centre of the $ glyph itself
            x0, y0, x1, y1 = _bbox(svg[at:d_end])
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    colour = fill.group(1) if fill else "#8C5543"
    peso = (f'<text x="{cx:.2f}" y="{cy + size * 0.36:.2f}" font-size="{size}" text-anchor="middle" '
            f'font-family="Anton, Impact, Arial, sans-serif" fill="{colour}"'
            + (f' transform="rotate({rot} {cx:.2f} {cy:.2f})"' if rot else "") + ">₱</text>")
    return svg[:path_start] + new_path + svg[path_end:].replace("</svg>", peso + "</svg>", 1)


def peso_pass(index: dict) -> dict:
    for key in PESO:
        f = OUT / f"{key}.svg"
        if f.exists():
            svg = pesofy(f.read_text(encoding="utf-8"), key)
            new_key = RENAME.get(key, key)
            (OUT / f"{new_key}.svg").write_text(svg, encoding="utf-8")
            if new_key != key:
                f.unlink()
                index[new_key] = {**index.pop(key), "name": new_key.replace("_", " ").capitalize()}
    for key in DROP:
        (OUT / f"{key}.svg").unlink(missing_ok=True)
        index.pop(key, None)
    return index


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index, missing = {}, []
    for group, names in GROUPS.items():
        for name in names:
            key = key_of(name)
            if key in index:
                continue
            file = name.lower().replace(" ", "_").replace("-", "_")
            url = RAW.format(name=urllib.parse.quote(name), file=urllib.parse.quote(file))
            try:
                svg = urllib.request.urlopen(url, timeout=30).read()
            except Exception:
                missing.append(name)
                continue
            (OUT / f"{key}.svg").write_bytes(svg)
            index[key] = {"name": name, "group": group}
    index = peso_pass(index)
    (OUT / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"{len(index)} emoji saved; missing: {missing}")


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--peso-only"]:                 # re-run the ₱ pass on files already fetched
        idx = json.loads((OUT / "index.json").read_text(encoding="utf-8"))
        (OUT / "index.json").write_text(json.dumps(peso_pass(idx), indent=1), encoding="utf-8")
    else:
        main()
