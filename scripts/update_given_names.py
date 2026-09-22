"""Rebuild the vendored first-name lexicon from pinned public sources."""
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1] / "app" / "data" / "given_names"
SOURCES = {
    "nen": ("mdanina/nen-imena-dataset", "38b3cad3aa123326be8bb97b0e9a3c0e5c7f54e6"),
    "solvenium": ("solvenium/names-dataset", "6adf76b5b36fb7a3f498c166f02f0b51afcdf69c"),
}


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    provenance = []
    names: set[str] = set()
    for source, (repo, revision) in SOURCES.items():
        paths = ["data/names.json"] if source == "nen" else [
            "dataset/Female_given_names.txt", "dataset/Male_given_names.txt"]
        for path in [*paths, "LICENSE"]:
            url = f"https://raw.githubusercontent.com/{repo}/{revision}/{path}"
            with urlopen(url, timeout=60) as response:
                raw = response.read()
            provenance.append({"url": url, "sha256": hashlib.sha256(raw).hexdigest()})
            text = raw.decode("utf-8-sig")
            if path == "LICENSE":
                (ROOT / f"{source}.LICENSE").write_text(text, encoding="utf-8")
                continue
            if source == "nen":
                for entry in json.loads(text):
                    names.add(entry["name"])
                    names.update(entry.get("short_forms") or [])
                    names.update(entry.get("international_forms") or [])
            else:
                names.update(text.splitlines())
    selected = set()
    for raw_name in names:
        name = unicodedata.normalize("NFC", raw_name.strip())
        if not 2 <= len(name) <= 50 or not re.fullmatch(r"[^\W\d_]+(?:[-'’ʻ‘ʼ][^\W\d_]+)*", name):
            continue
        scripts = {"LATIN" if "LATIN" in unicodedata.name(c, "") else "CYRILLIC"
                   if "CYRILLIC" in unicodedata.name(c, "") else "OTHER"
                   for c in name if c.isalpha() and c not in "ʻʼ"}
        if scripts not in ({"LATIN"}, {"CYRILLIC"}):
            continue
        selected.add(name)
    (ROOT / "names.txt").write_text("\n".join(sorted(selected)) + "\n", encoding="utf-8")
    (ROOT / "sources.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"Vendored {len(selected)} first-name spellings")


if __name__ == "__main__":
    main()
