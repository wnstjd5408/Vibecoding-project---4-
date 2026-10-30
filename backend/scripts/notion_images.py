"""Bounded Notion image download; no credentials, redirects, proxies or DNS rebinding."""

import http.client
import ipaddress
import socket
import ssl
from io import BytesIO
from urllib.parse import unquote, urlsplit

from PIL import Image, UnidentifiedImageError

MAX_BYTES = 10_000_000
MAX_SIDE = 8_000
MAX_PIXELS = 25_000_000
# Notion's file-object documentation names this host and bucket prefix.
# Unknown hosts fail closed; changes require documentation and review.
HOST = "s3.us-west-2.amazonaws.com"
PREFIX = "/secure.notion-static.com/"
# Virtual-hosted Notion bucket; never allow arbitrary S3 buckets or subdomains.
FILE_HOST = "prod-files-secure.s3.us-west-2.amazonaws.com"
HOST_PREFIXES = {HOST: PREFIX, FILE_HOST: "/"}


class ImageRejected(Exception):
    """Policy rejection; never include URLs or source bytes in the message."""


def image_target(url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        prefix = HOST_PREFIXES.get(parsed.hostname)
        if (parsed.scheme != "https" or prefix is None
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.fragment or not parsed.path.startswith(prefix)
                or len(parsed.path) <= len(prefix)
                or any(part in {".", ".."} for part in unquote(parsed.path).split("/"))
                or any(ord(c) < 33 or ord(c) > 126 for c in url)
                or "\\" in url):
            raise ImageRejected("url")
        return parsed.hostname, parsed.path + ("?" + parsed.query if parsed.query else "")
    except ValueError:
        raise ImageRejected("url") from None


def public_addresses(host: str) -> list[tuple]:
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ImageRejected("address")
    return addresses


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: tuple):
        super().__init__(host, timeout=15, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        family, socktype, proto, _, sockaddr = self.address
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(self.timeout)
            sock.connect(sockaddr)  # numeric address already checked; no second DNS lookup
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def download(url: str) -> bytes:
    host, target = image_target(url)
    addresses = public_addresses(host)
    connection = PinnedHTTPSConnection(host, addresses[0])
    try:
        connection.request("GET", target, headers={"Accept-Encoding": "identity"})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ImageRejected("redirect")
        if response.status != 200:
            raise OSError("image_http")
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise ImageRejected("encoding")
        if response.getheader("Content-Type", "").split(";")[0].lower() == "image/svg+xml":
            raise ImageRejected("format")
        length = response.getheader("Content-Length")
        if length is not None and (not length.isdecimal() or int(length) > MAX_BYTES):
            raise ImageRejected("size")
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ImageRejected("size")
        return data
    finally:
        connection.close()


def reencode(data: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise ImageRejected("size")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP", "GIF"}:
                raise ImageRejected("format")
            width, height = source.size
            if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
                raise ImageRejected("pixels")
            source.verify()
        with Image.open(BytesIO(data)) as source:
            source.load()
            # A fresh image deliberately discards EXIF, ICC, comments and animation.
            clean = Image.new("RGBA", source.size)
            clean.paste(source.convert("RGBA"))
            output = BytesIO()
            clean.save(output, format="PNG")
            encoded = output.getvalue()
        if len(encoded) > MAX_BYTES:
            raise ImageRejected("size")
        return encoded
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ImageRejected("format") from None
