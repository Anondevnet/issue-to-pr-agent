from types import SimpleNamespace

from app.feeds import _extract_image_url


def test_video_media_content_is_skipped():
    entry = SimpleNamespace(media_content=[
        {"url": "https://cdn.example/clip.mp4", "type": "video/mp4", "medium": "video"},
        {"url": "https://cdn.example/photo.jpg", "type": "image/jpeg"},
    ])
    assert _extract_image_url(entry) == "https://cdn.example/photo.jpg"


def test_falls_back_to_thumbnail_when_only_video():
    entry = SimpleNamespace(
        media_content=[{"url": "https://cdn.example/clip.mp4", "medium": "video"}],
        media_thumbnail=[{"url": "https://cdn.example/thumb.jpg"}],
    )
    assert _extract_image_url(entry) == "https://cdn.example/thumb.jpg"


def test_untyped_media_content_still_accepted():
    entry = SimpleNamespace(media_content=[{"url": "https://cdn.example/a.png"}])
    assert _extract_image_url(entry) == "https://cdn.example/a.png"
