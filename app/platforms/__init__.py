from ..models import Platform
from .facebook import FacebookPlatform
from .instagram import InstagramPlatform
from .tiktok import TikTokPlatform
from .youtube import YouTubePlatform

REGISTRY = {
    Platform.youtube: YouTubePlatform,
    Platform.instagram: InstagramPlatform,
    Platform.tiktok: TikTokPlatform,
    Platform.facebook: FacebookPlatform,
}


def get_platform(platform: Platform) -> "object":
    return REGISTRY[platform]()
