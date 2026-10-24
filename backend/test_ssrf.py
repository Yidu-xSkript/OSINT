"""SSRF guard on the user-URL fetch path (builtin.fetch)."""
from builtin import _assert_public_url

BLOCKED = [
    "http://127.0.0.1:8000/api/health",          # loopback sidecar
    "http://localhost/",                         # loopback by name
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
    "http://10.0.0.5/", "http://192.168.1.1/",   # private
    "https://[::1]/",                            # ipv6 loopback
    "file:///etc/passwd", "gopher://127.0.0.1/", "ftp://internal/",  # non-web schemes
]
ALLOWED = ["https://crt.sh/?q=example.com", "https://dns.google/resolve", "http://example.com/"]


def test_blocks_internal_and_bad_schemes():
    for u in BLOCKED:
        try:
            _assert_public_url(u)
        except ValueError:
            continue
        raise AssertionError(f"should have blocked: {u}")


def test_allows_public():
    for u in ALLOWED:
        try:
            _assert_public_url(u)              # resolves to a global IP -> no raise
        except ValueError as e:
            if "resolve" in str(e):            # offline / DNS sinkholed here: not a guard failure
                print(f"(skip, no network) {u}")
                continue
            raise


if __name__ == "__main__":
    test_blocks_internal_and_bad_schemes()
    test_allows_public()
    print("ok")
