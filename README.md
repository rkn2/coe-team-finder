# CoE Team Finder

A web page for the Penn State College of Engineering. Paste a funding call and get three possible teams from the college's faculty, each with reasons, the expertise still missing, and a draft intro email. It runs on the visitor's own Claude API key, straight from the browser.

**Open it:** https://rkn2.github.io/coe-team-finder/

Made by Rebecca Napolitano (napolitano@psu.edu), adapted from the Digital Twin Hub's Twin Team Finder.

## How it works
- The page loads `roster.json`, the college roster, and keeps the visitor's key, added people and past searches in their own browser (localStorage). Nothing goes to a server of ours.
- For each call the page ranks everyone by word overlap with the call (BM25 over research areas, topics and paper titles) and sends the top 70 to Claude. Claude returns three teams as structured JSON.
- Visitors can download the roster as CSV, edit it, and upload it again to add people or fix someone's research. Uploaded rows are matched on email and stay in that browser.
- Model is Claude Opus 5.5 by default, with Claude Sonnet 5.5 as a cheaper choice. Requests use server-side refusal fallbacks.

## Where the people come from
All public sources.
1. The [College of Engineering Faculty & Staff Directory](https://www.engr.psu.edu/directory/index.aspx), filtered to Faculty. Emeriti, adjuncts, instructors, lecturers, postdocs and visitors are left out. Affiliates from other colleges listed in the directory are kept.
2. Each person's directory profile gives research areas, a research website and recent publications. Co-author links between roster members come from the author lists on those publications (papers since 2016 with at most 25 authors).
3. When a profile has no research areas and no publications, OpenAlex fills in topics and recent works from a name match restricted to Penn State. These are listed in `review.json` for checking.

## Files
| File | What it is |
|---|---|
| `index.html` | The page (GitHub Pages serves it) |
| `roster.json` | The college roster the page loads |
| `review.json` | People whose research is missing or came from an unchecked OpenAlex match |
| `build_roster.py` | Builds `roster.json` and `review.json` |
| `overrides.json` | Hand fixes. `drop` removes people (uid to reason), `people` overrides fields by uid |
| `.github/workflows/refresh.yml` | Monthly rebuild on GitHub |

## Rebuild by hand
```sh
python3 build_roster.py            # cache on /Volumes/Samsung990/ResearchData/coe-team-finder/cache
python3 build_roster.py --refresh  # refetch every page
```
The build fetches about 600 profile pages and takes 30 to 60 minutes. An OpenAlex key in `~/.config/openalex/api_key` is used if present.

## Later
Penn State Pure and the Libraries' Researcher Metadata Database have richer, cleaner data behind API keys. If the college gets one, `build_roster.py` can switch sources.
