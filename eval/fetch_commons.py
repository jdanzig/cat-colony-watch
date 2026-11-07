"""Download the matching-check photos: up to 8 openly licensed photos of each individually named cat on
Wikimedia Commons, 768 px wide, into eval_data/commons/<cat>/, with manifest.json and SOURCES.md.
Used by the matching check, and about 12 of these cats are the demo cats (credited in data/demo/PHOTO_SOURCES.md).
Safe to re-run; files already downloaded are skipped."""
import json, pathlib, re, time, urllib.error, urllib.parse, urllib.request

UA = {"User-Agent": "cat-colony-watch-eval/0.1 (hackathon matching check)"}
API = "https://commons.wikimedia.org/w/api.php?"
ROOT = pathlib.Path(__file__).resolve().parent.parent / "eval_data" / "commons"
PER_CAT, MIN_FILES = 8, 5
# Categories that group several cats, so a folder would not be one individual.
GROUPS = {"Cats of Wikipedians", "Famous cats", "Fictional cats", "Ships' cats", "Cat mascots",
          "Cats at train stations in Japan", "Cat memorials", "Legendary cats", "Cat actors",
          "Pet cats of presidents of the United States", "Cat train station masters",
          "Mousers in the government of the United Kingdom"}


def get(url, tries=5):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(10 * (i + 1))  # Commons rate limit: back off, never hammer


def api(**p):
    return json.loads(get(API + urllib.parse.urlencode({**p, "format": "json"})))


def subcats(cat):
    r = api(action="query", list="categorymembers", cmtitle=cat, cmtype="subcat", cmlimit=500)
    return [m["title"] for m in r["query"]["categorymembers"]]


def individual_cats():
    cats = subcats("Category:Individual cats")
    for parent in ("Category:Cats of Wikipedians", "Category:Famous cats"):
        cats += subcats(parent)
    return sorted({c for c in cats if c.removeprefix("Category:") not in GROUPS
                   and " and " not in c and "(cats)" not in c})


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for cat in individual_cats():
        slug = re.sub(r"[^a-z0-9]+", "-", cat.removeprefix("Category:").lower()).strip("-")
        r = api(action="query", generator="categorymembers", gcmtitle=cat, gcmtype="file", gcmlimit=50,
                prop="imageinfo", iiprop="url|mime|extmetadata", iiurlwidth=768)
        pages = sorted(r.get("query", {}).get("pages", {}).values(), key=lambda p: p["title"])
        usable = [p for p in pages if p["imageinfo"][0]["mime"] in ("image/jpeg", "image/png")
                  and re.search(r"CC|Public domain|PD|GFDL",
                                p["imageinfo"][0].get("extmetadata", {}).get("LicenseShortName", {}).get("value", ""), re.I)]
        if len(usable) < MIN_FILES:
            continue
        for n, p in enumerate(usable[:PER_CAT], 1):
            ii, md = p["imageinfo"][0], p["imageinfo"][0].get("extmetadata", {})
            fn = ROOT / slug / f"{n:02d}{'.png' if ii['mime'] == 'image/png' else '.jpg'}"
            if not fn.exists():
                fn.parent.mkdir(exist_ok=True)
                fn.write_bytes(get(ii.get("thumburl", ii["url"])))
                time.sleep(2)
            manifest.append({"cat": slug, "file": str(fn.relative_to(ROOT)), "source": ii["descriptionurl"],
                             "license": md.get("LicenseShortName", {}).get("value", "?"),
                             "author": re.sub("<[^>]+>", "", md.get("Artist", {}).get("value", "?")).strip()})
        print(f"{slug}: {min(len(usable), PER_CAT)} photos")
        time.sleep(2)
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    rows = "\n".join(f"| {m['file']} | {m['license']} | {m['author'][:60]} | {m['source']} |" for m in manifest)
    (ROOT / "SOURCES.md").write_text("# Photo sources\n\nWikimedia Commons, downscaled to 768 px.\n\n"
                                     "| file | license | author | source |\n|---|---|---|---|\n" + rows + "\n")
    print(len(manifest), "photos of", len({m["cat"] for m in manifest}), "cats")


if __name__ == "__main__":
    main()
