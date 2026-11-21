#!/usr/bin/env python3
"""Build the College of Engineering roster (roster.json) from public sources.

1. The college Faculty & Staff Directory (engr.psu.edu/directory), class = Faculty.
2. Each person's directory profile: research areas, research website, recent publications.
3. OpenAlex, only for people whose profile has no research areas and no publications.

Raw pages are cached on the data drive. Usage:
    python3 build_roster.py [--cache DIR] [--refresh]
"""
import argparse, html, json, os, re, sys, time, unicodedata, urllib.parse, urllib.request
from collections import Counter, defaultdict

BASE = "https://www.engr.psu.edu/directory/"
UA = "coe-team-finder roster builder (+https://github.com/rkn2/coe-team-finder)"
KEEP = re.compile(r"professor|department head|chair in|dean", re.I)
DROP = re.compile(r"emerit|adjunct|instructor|vice president|adviser|coordinator|assistant$|technologist|"
                  r"consultant|director of facilities|visiting|postdoc", re.I)
HERE = os.path.dirname(os.path.abspath(__file__))


def get(url, path, data=None, refresh=False):
    if os.path.exists(path) and not refresh:
        return open(path, encoding="utf-8").read()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                t = r.read().decode("utf-8", "replace")
            break
        except Exception as e:
            print(f"  fetch failed ({attempt+1}/3) {url}: {e!r}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    else:
        raise RuntimeError(f"could not fetch {url}")
    open(path, "w", encoding="utf-8").write(t)
    time.sleep(0.7)
    return t


def directory(cache, refresh):
    p = get(BASE + "index.aspx", f"{cache}/index.html", refresh=refresh)
    form = {m.group(1): html.unescape(m.group(2)) for m in
            re.finditer(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', p)}
    t = ""
    for cls, fn in (("Fac", "all_faculty"), ("Dept_Head", "dept_heads"), ("Dean", "deans")):
        f = dict(form)
        f.update({"uc1$ddl_Dept": "%", "uc1$ddl_Class": cls, "uc1$ddl_ResearchArea": "%",
                  "uc1$txtName": "", "uc1$txtKeywords": "", "uc1$btn_All.x": "5", "uc1$btn_All.y": "5"})
        t += get(BASE + "index.aspx", f"{cache}/{fn}.html", data=urllib.parse.urlencode(f).encode(), refresh=refresh)
    cards = re.findall(r'<p class="name"><a href="directory-detail-g\.aspx\?q=([^"]+)">(.*?)</a></p>\s*'
                       r'<p class="title">(.*?)</p>\s*(?:<p class="address">(.*?)</p>)?.*?'
                       r'<p class="email"><a href="mailto:([^"]*)"', t, re.S)
    out, skipped = {}, Counter()
    for uid, name, title, dept, email in cards:
        uid, title = uid.lower(), html.unescape(title).strip()
        if uid in out:
            continue
        if not KEEP.search(title) or DROP.search(title):
            skipped[title] += 1
            continue
        out[uid] = {"uid": uid, "name": " ".join(html.unescape(name).split()), "title": title,
                    "department": html.unescape(dept or "").strip(), "email": email.strip().lower()}
    if len(out) < 300:
        raise RuntimeError(f"directory returned only {len(out)} faculty; the page format may have changed")
    return list(out.values()), skipped


def text_lines(page):
    page = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", page)
    page = re.sub(r"(?i)<br\s*/?>", " ", page)
    return [x for x in (" ".join(html.unescape(s).split()) for s in re.sub(r"<[^>]+>", "\n", page).split("\n")) if x]


def profile(person, cache, refresh):
    page = get(BASE + "directory-detail-g.aspx?q=" + person["uid"].upper(),
               f"{cache}/profiles/{person['uid']}.html", refresh=refresh)
    site = re.search(r'<a[^>]+href="?([^"\s>]+)"?[^>]*>\s*Research Website', page)
    L = text_lines(page)
    start = max((i for i, x in enumerate(L) if x == "Directory >"), default=0)
    L = L[start:]
    areas = []
    if "Research Areas:" in L:
        areas = [a.strip() for a in L[L.index("Research Areas:") + 1].split(";") if a.strip()]
    affil = []
    if "Affiliation(s):" in L:
        i = L.index("Affiliation(s):") + 1
        while i < len(L) and not re.search(r"Building|Hall|@|\d{3}-\d{3}|Research|Education|Lab", L[i]):
            affil.append(L[i]); i += 1
    pubs = []
    for li in re.findall(r"(?s)<li>(.*?)</li>", page):
        t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", li)).split())
        m = re.match(r'(.{3,1500}?), (\d{4}), "(.{8,400}?)"', t)
        if m:
            pubs.append({"year": int(m.group(2)), "title": m.group(3).strip().rstrip("."), "authors": m.group(1).strip()})
    return {"areas": areas, "website": html.unescape(site.group(1)) if site else "",
            "affiliations": affil, "pubs": pubs}


def fold(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s).split()


def name_key(name):
    w = fold(name)
    return (w[0][0], w[-1]) if len(w) >= 2 else None


def openalex(person, cache, key):
    fn = f"{cache}/openalex/{person['uid']}.json"
    q = urllib.parse.quote(person["name"])
    url = f"https://api.openalex.org/authors?search={q}&filter=last_known_institutions.ror:https://ror.org/04p491231&per-page=5"
    if key:
        url += "&api_key=" + key
    try:
        res = json.loads(get(url, fn))["results"]
    except Exception as e:
        print(f"  openalex failed for {person['name']}: {e!r}", file=sys.stderr)
        return None
    target = name_key(person["name"])
    hits = [a for a in res if name_key(a.get("display_name", "")) == target]
    if len(hits) != 1:
        return {"status": "ambiguous" if hits else "none", "candidates": [a["id"] for a in res[:5]]}
    a = hits[0]
    topics = [t["display_name"] for t in (a.get("topics") or [])[:6]]
    wfn = f"{cache}/openalex/{person['uid']}_works.json"
    wurl = (f"https://api.openalex.org/works?filter=author.id:{a['id'].split('/')[-1]}&sort=publication_year:desc"
            f"&per-page=5&select=title,publication_year")
    if key:
        wurl += "&api_key=" + key
    try:
        works = json.loads(get(wurl, wfn))["results"]
    except Exception as e:
        print(f"  openalex works failed for {person['name']}: {e!r}", file=sys.stderr)
        works = []
    return {"status": "matched", "id": a["id"], "orcid": a.get("orcid"), "topics": topics,
            "works": [{"year": w.get("publication_year"), "title": (w.get("title") or "").strip()} for w in works if w.get("title")]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/Volumes/Samsung990/ResearchData/coe-team-finder/cache")
    ap.add_argument("--refresh", action="store_true", help="refetch directory and profiles")
    args = ap.parse_args()
    for d in ("profiles", "openalex"):
        os.makedirs(f"{args.cache}/{d}", exist_ok=True)
    key = ""
    kp = os.path.expanduser("~/.config/openalex/api_key")
    if os.path.exists(kp):
        key = open(kp).read().strip()
    ov = json.load(open(os.path.join(HERE, "overrides.json"))) if os.path.exists(os.path.join(HERE, "overrides.json")) else {}

    people, skipped = directory(args.cache, args.refresh)
    print(f"directory: {len(people)} faculty kept, {sum(skipped.values())} skipped")
    from concurrent.futures import ThreadPoolExecutor
    todo = [p for p in people if args.refresh or not os.path.exists(f"{args.cache}/profiles/{p['uid']}.html")]
    print(f"fetching {len(todo)} profiles, 4 at a time")
    done = 0
    def fetch_one(p):
        try:
            get(BASE + "directory-detail-g.aspx?q=" + p["uid"].upper(), f"{args.cache}/profiles/{p['uid']}.html", refresh=args.refresh)
        except Exception as e:
            print(f"  gave up on {p['name']}: {e!r}", file=sys.stderr)
    with ThreadPoolExecutor(4) as ex:
        for _ in ex.map(fetch_one, todo):
            done += 1
            if done % 50 == 0:
                print(f"  fetched {done}/{len(todo)}", flush=True)
    review = []
    for n, p in enumerate(people, 1):
        if not os.path.exists(f"{args.cache}/profiles/{p['uid']}.html"):
            review.append({"uid": p["uid"], "name": p["name"], "department": p["department"], "issue": "profile page could not be fetched"})
            p.update(areas=[], website="", recent_papers=[], research_source="")
            continue
        if p["uid"] in ov.get("drop", {}):
            continue
        prof = profile(p, args.cache, False)
        p.update(areas=prof["areas"], website=prof["website"])
        p["recent_papers"] = sorted(prof["pubs"], key=lambda x: -x["year"])[:6]
        p["_all_pubs"] = prof["pubs"]
        p["research_source"] = "profile" if (prof["areas"] or prof["pubs"]) else ""
        if not prof["areas"] and not prof["pubs"]:
            oa = openalex(p, args.cache, key)
            if oa and oa["status"] == "matched":
                p["openalex"] = oa["id"]
                p["topics"] = oa["topics"]
                p["recent_papers"] = oa["works"]
                p["research_source"] = "openalex (name match, unchecked)"
                review.append({"uid": p["uid"], "name": p["name"], "department": p["department"],
                               "issue": "research filled from OpenAlex by name; check it is the right person",
                               "openalex": oa["id"]})
            else:
                review.append({"uid": p["uid"], "name": p["name"], "department": p["department"],
                               "issue": "no research areas, no publications, no unique OpenAlex match",
                               "candidates": (oa or {}).get("candidates", [])})
        if n % 50 == 0:
            print(f"  profiles {n}/{len(people)}")
    people = [p for p in people if p["uid"] not in ov.get("drop", {})]
    for uid, fix in ov.get("people", {}).items():
        for p in people:
            if p["uid"] == uid:
                p.update(fix)

    # co-authors inside the roster, from the author lists on profile publications
    bykey = defaultdict(list)
    for p in people:
        k = name_key(p["name"])
        if k:
            bykey[k].append(p["uid"])
    links = Counter()
    for p in people:
        for pub in p.pop("_all_pubs", []):
            if pub["year"] < 2016:
                continue
            names = re.split(r",\s*|\s+and\s+", pub["authors"])
            found = set()
            for nm in names:
                k = name_key(nm)
                if k and len(bykey.get(k, [])) == 1 and bykey[k][0] != p["uid"]:
                    found.add(bykey[k][0])
            if len(names) <= 25:
                for o in found:
                    links[tuple(sorted((p["uid"], o)))] += 1
    co = defaultdict(set)
    for (a, b), w in links.items():
        co[a].add(b); co[b].add(a)
    for p in people:
        p["coauthors"] = sorted(co[p["uid"]])
        p["recent_papers"] = [{"year": x["year"], "title": x["title"]} for x in p["recent_papers"]]

    out = {"built": time.strftime("%Y-%m-%d"),
           "source": "Penn State College of Engineering Faculty & Staff Directory profiles, with OpenAlex for gaps",
           "count": len(people), "people": people,
           "links": [{"a": a, "b": b, "papers": w} for (a, b), w in sorted(links.items())]}
    json.dump(out, open(os.path.join(HERE, "roster.json"), "w"), indent=1, ensure_ascii=False)
    json.dump(review, open(os.path.join(HERE, "review.json"), "w"), indent=1, ensure_ascii=False)
    with_research = sum(1 for p in people if p["areas"] or p.get("topics") or p["recent_papers"])
    print(f"roster.json: {len(people)} people, {with_research} with research info, {len(links)} co-author links")
    print(f"review.json: {len(review)} to check")
    print("departments:", Counter(p["department"] for p in people).most_common(12))


if __name__ == "__main__":
    main()
