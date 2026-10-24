"""Quick Username Search transform + tool registry (offline — no network)."""
import builtin
import recon
import tools
from builtin import BUILTINS


def test_username_validation():
    fn = BUILTINS["username-search"]["fn"]
    for bad in ["", "a", "x" * 50, "has space", "drop;table", "@@@"]:
        try:
            fn(bad, {}, {})
            raise AssertionError(f"should reject {bad!r}")
        except ValueError:
            pass


def test_found_sites_become_candidate_websites(monkeypatch):
    # deterministic, no network
    monkeypatch.setattr(recon, "search_username", lambda u, **k: [
        {"site": "GitHub", "url": "https://github.com/alice", "status": 200, "found": True},
        {"site": "Reddit", "url": "https://www.reddit.com/user/alice", "status": 404, "found": False},
        {"site": "Keybase", "url": "https://keybase.io/alice", "status": None, "found": None, "error": "timeout"},
    ])
    builtin._rec.items = []  # capture evidence like the engine does
    try:
        out = BUILTINS["username-search"]["fn"]("alice", {}, {})
    finally:
        ev = list(builtin._rec.items); builtin._rec.items = None
    assert len(out) == 1, out                       # only the 200 becomes a node
    typ, val, label, props = out[0]
    assert typ == "Website" and val == "https://github.com/alice"
    assert "GitHub" in label
    assert props["candidate.status"] == "Unreviewed"   # every hit is a candidate, not proof
    assert props["account.platform"] == "GitHub"
    assert ev and b"alice" in ev[0]["body"]            # search summary recorded as evidence


def test_registry_states():
    reg = {t["id"]: t for t in tools.registry({})}
    assert reg["quick-username"]["kind"] == "native" and reg["quick-username"]["state"] == "built-in"
    allowed = {"built-in", "available", "needs-setup", "unsupported-version", "error"}
    for t in reg.values():
        assert t["state"] in allowed, t
    # an external tool with a bogus explicit path is needs-setup (file doesn't exist)
    reg2 = {t["id"]: t for t in tools.registry({"nmap.path": r"C:\nope\nmap.exe"})}
    assert reg2["nmap"]["state"] == "needs-setup"
    assert reg2["nmap"]["scoped"] is True             # scan adapter must gather scope + authorization


if __name__ == "__main__":
    class _MP:  # tiny monkeypatch shim so this runs without pytest
        def setattr(self, obj, name, val): setattr(obj, name, val)
    test_username_validation()
    test_found_sites_become_candidate_websites(_MP())
    test_registry_states()
    print("ok")
