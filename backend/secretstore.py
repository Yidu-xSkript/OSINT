"""At-rest protection for secret settings (API keys/tokens).

On Windows, values are sealed with DPAPI (CryptProtectData) under the logged-in user's account — no key
file to steal, no extra dependency (ctypes calls the OS). Sealed values are stored as "dpapi:<base64>".
Off Windows (dev/CI), values are stored as-is: there is no portable user-bound keystore in the stdlib, and
this is a single-user local desktop tool. A value sealed on one account can't be read on another, which is
the point — if decryption fails we treat the secret as absent rather than leaking ciphertext downstream.
"""
import base64
import sys

PREFIX = "dpapi:"
_WIN = sys.platform == "win32"


def available():
    return _WIN


if _WIN:
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _crypt(fn, data):
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        inp = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = _BLOB()
        # (pDataIn, szDataDescr, pEntropy, pvReserved, pPromptStruct, dwFlags, pDataOut)
        if not fn(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
            raise OSError("DPAPI call failed")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)


def seal(value):
    """Plaintext secret -> stored form. Identity if DPAPI is unavailable or the value is empty."""
    if not value or not _WIN:
        return value
    try:
        ct = _crypt(ctypes.windll.crypt32.CryptProtectData, value.encode("utf-8"))
        return PREFIX + base64.b64encode(ct).decode("ascii")
    except OSError:
        return value  # fall back to plaintext rather than lose the key


def unseal(value):
    """Stored form -> plaintext. '' if a sealed value can't be opened on this account."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    if not _WIN:
        return ""
    try:
        pt = _crypt(ctypes.windll.crypt32.CryptUnprotectData, base64.b64decode(value[len(PREFIX):]))
        return pt.decode("utf-8")
    except (OSError, ValueError):
        return ""


if __name__ == "__main__":
    s = "sk-test-ABC123"
    sealed = seal(s)
    print("available:", available(), "sealed-prefix:", sealed[:6] if available() else "(plaintext)")
    assert unseal(sealed) == (s if available() else s)
    assert unseal("plain-legacy-key") == "plain-legacy-key"  # legacy plaintext passes through
    print("ok")
