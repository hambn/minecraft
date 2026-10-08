"""Minimal stdlib HTTP helpers with retries, used by every upstream client."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

USER_AGENT = "hambn/minecraft (+https://github.com/hambn/minecraft)"
RETRIES = 4
BACKOFF = 1.0
TIMEOUT = 60


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


class HashMismatch(Exception):
    pass


@dataclass
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased keys
    body: bytes = b""

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


def request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
    retries: int = RETRIES,
) -> Response:
    """Perform a request; any HTTP status is returned, never raised.

    5xx and 429 responses and connection errors are retried with exponential
    backoff.  :class:`HttpError` is raised only when the network keeps failing.
    """
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries):
        if attempt:
            time.sleep(BACKOFF * 2 ** (attempt - 1))
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return Response(resp.status, _lower(resp.headers), resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read() if exc.fp else b""
            response = Response(exc.code, _lower(exc.headers), body)
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                last = HttpError(f"HTTP {exc.code} for {url}", exc.code, url)
                continue
            return response
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
    raise HttpError(f"request failed for {url}: {last}", None, url)


def _lower(headers: Any) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()} if headers else {}


def _checked(url: str, **kwargs: Any) -> Response:
    resp = request(url, **kwargs)
    if resp.status >= 400:
        raise HttpError(f"HTTP {resp.status} for {url}", resp.status, url)
    return resp


def get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    hdrs = {"Accept": "application/json"}
    hdrs.update(headers or {})
    return json.loads(_checked(url, headers=hdrs).body.decode("utf-8"))


def post_json(url: str, payload: Any, headers: dict[str, str] | None = None) -> Any:
    hdrs = {"Accept": "application/json", "Content-Type": "application/json"}
    hdrs.update(headers or {})
    resp = _checked(url, headers=hdrs, method="POST", data=json.dumps(payload).encode("utf-8"))
    return json.loads(resp.body.decode("utf-8")) if resp.body else None


def get_text(url: str, headers: dict[str, str] | None = None) -> str:
    return _checked(url, headers=headers).body.decode("utf-8")


def download(
    url: str,
    dest: Path,
    *,
    sha1: str | None = None,
    sha256: str | None = None,
    sha512: str | None = None,
) -> str:
    """Download ``url`` to ``dest``, verify the given hashes, return the sha512 hex."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = _checked(url).body
    digests = {
        "sha1": hashlib.sha1(body).hexdigest(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "sha512": hashlib.sha512(body).hexdigest(),
    }
    for algo, expected in (("sha1", sha1), ("sha256", sha256), ("sha512", sha512)):
        if expected and digests[algo] != expected.lower():
            raise HashMismatch(f"{algo} mismatch for {url}: expected {expected}, got {digests[algo]}")
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(body)
    os.replace(tmp, dest)
    return digests["sha512"]
