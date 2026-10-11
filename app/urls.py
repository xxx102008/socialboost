import re
from urllib.parse import urlparse

from .models import Platform

PATTERNS = {
    Platform.youtube: re.compile(r"(youtube\.com|youtu\.be)", re.I),
    Platform.instagram: re.compile(r"instagram\.com", re.I),
    Platform.facebook: re.compile(r"(facebook\.com|fb\.watch)", re.I),
    Platform.tiktok: re.compile(r"tiktok\.com", re.I),
}


def detect_platform(url: str) -> Platform | None:
    for platform, pattern in PATTERNS.items():
        if pattern.search(url):
            return platform
    return None


def normalize(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()
