"""Quick Username Search — a native, bundled check of a username across a curated set of public sites.

This is deliberately a small, honest subset of what the full Sherlock project covers (which checks 400+
sites); it ships with the app and needs no install. A username existing on a platform is NOT proof that the
accounts belong to the same person, so every hit is emitted as a CANDIDATE (candidate.status = Unreviewed)
for the analyst to corroborate. For broad coverage, install Sherlock and use that adapter.
"""
import concurrent.futures as cf
import json
import re
import urllib.error
import urllib.request
from urllib.parse import quote

import builtin
from builtin import UA, transform

# (site, URL template with {u}). Chosen for behaving with a plain GET and reliably 404-ing unknown users;
# soft-404 sites (that return 200 for missing users) are intentionally excluded to keep false positives low.
SITES = [
    ("GitHub", "https://github.com/{u}"),
    ("GitLab", "https://gitlab.com/{u}"),
    ("Reddit", "https://www.reddit.com/user/{u}"),
    ("Keybase", "https://keybase.io/{u}"),
    ("Telegram", "https://t.me/{u}"),
    ("Medium", "https://medium.com/@{u}"),
    ("Dev.to", "https://dev.to/{u}"),
    ("Hacker News", "https://news.ycombinator.com/user?id={u}"),
    ("PyPI", "https://pypi.org/user/{u}/"),
    ("npm", "https://www.npmjs.com/~{u}"),
    ("Replit", "https://replit.com/@{u}"),
    ("Gravatar", "https://en.gravatar.com/{u}"),
    ("Linktree", "https://linktr.ee/{u}"),
    ("Chess.com", "https://www.chess.com/member/{u}"),
    ("Last.fm", "https://www.last.fm/user/{u}"),
    ("SoundCloud", "https://soundcloud.com/{u}"),
    ("About.me", "https://about.me/{u}"),
    ("Steam", "https://steamcommunity.com/id/{u}"),
    ("Pastebin", "https://pastebin.com/u/{u}"),
    ("Kaggle", "https://www.kaggle.com/{u}"),
]

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,40}$")


def _check(site, template, u, timeout=8):
    url = template.replace("{u}", quote(u, safe=""))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return {"site": site, "url": url, "status": r.status, "found": r.status == 200}
    except urllib.error.HTTPError as e:
        return {"site": site, "url": url, "status": e.code, "found": False}
    except Exception as e:  # timeout / blocked / connection → unknown, not a match
        return {"site": site, "url": url, "status": None, "found": None, "error": type(e).__name__}


def search_username(u, timeout=8, workers=10):
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda s: _check(s[0], s[1], u, timeout), SITES))


@transform("username-search", "To Social Accounts [Quick Username Search]", "Phrase",
           "Check a username across ~20 public sites. Results are CANDIDATES — a match is not proof of "
           "identity; corroborate before linking people. Install Sherlock for broader coverage.",
           classification="source-asserted")
def _(v, p, s):
    u = v.strip().lstrip("@")
    if not USERNAME_RE.match(u):
        raise ValueError(f"'{v}' is not a plausible username (letters, digits, . _ - ; 2–40 chars)")
    results = search_username(u)
    # One compact evidence record (the search summary), captured on the transform thread.
    summary = {"username": u, "checked": len(results),
               "found": [r["site"] for r in results if r["found"]],
               "unavailable": [r["site"] for r in results if r["found"] is None],
               "results": results}
    builtin._record(f"quick-username-search:{quote(u, safe='')}", 200, json.dumps(summary, indent=1).encode())
    out = []
    for r in results:
        if r["found"]:
            out.append(("Website", r["url"], f"Account on {r['site']}", {
                "candidate.status": "Unreviewed", "account.platform": r["site"], "account.username": u,
                "note": "Username match only — not proof the same person owns this account; corroborate.",
            }))
    return out
