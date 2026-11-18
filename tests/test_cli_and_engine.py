"""Tests for CLI options, batch readers, profile inputs, and engine behavior."""

import argparse
import tempfile
from pathlib import Path
import pytest

import downloader
from universal_downloader.batch import read_batch_file
from universal_downloader.cli import (
    _build_playlist_entries,
    _extract_supported_qualities,
    validate_url_option,
)
from universal_downloader.engine import DownloadEngine
from universal_downloader.exceptions import ConfigurationError, ProfileError
from universal_downloader.extractor import parse_rate_limit
from universal_downloader.models import AppConfig, ContentType, DetectedTarget, Platform
from universal_downloader.profile import (
    ProfileImageCandidate,
    _build_cookie_header,
    compute_hd_target_dimensions,
    detect_facebook_profile_locked,
    enhance_image_bytes_to_hd,
    extract_facebook_photo_viewer_links,
    extract_facebook_user_id,
    extract_photo_viewer_images,
    extract_profile_metadata_fields,
    extract_public_profile_candidates,
    extract_public_profile_images,
    extract_username_from_profile_url,
    is_generic_site_logo,
    load_cookie_jar,
    resolve_profile_input,
)
from universal_downloader.upscaler import (
    _enhance_rgb_ycbcr_numpy,
    _enhance_rgb_ycbcr_pillow,
)


def test_validate_url_option():
    # Only positional
    args1 = argparse.Namespace(url="https://youtube.com/watch?v=1", url_option=None)
    assert validate_url_option(args1) == "https://youtube.com/watch?v=1"

    # Only flag
    args2 = argparse.Namespace(url=None, url_option="https://youtube.com/watch?v=2")
    assert validate_url_option(args2) == "https://youtube.com/watch?v=2"

    # Both -> must raise ConfigurationError
    args3 = argparse.Namespace(url="https://youtube.com/watch?v=1", url_option="https://youtube.com/watch?v=2")
    with pytest.raises(ConfigurationError):
        validate_url_option(args3)


def test_read_batch_file():
    with tempfile.TemporaryDirectory() as td:
        batch_path = Path(td) / "urls.txt"
        batch_path.write_text(
            """
            # Comments should be ignored
            https://youtube.com/watch?v=1
            https://instagram.com/p/2/

            https://tiktok.com/@user/video/3
            """,
            encoding="utf-8",
        )
        urls = read_batch_file(batch_path)
        assert len(urls) == 3
        assert urls[0] == "https://youtube.com/watch?v=1"
        assert urls[1] == "https://instagram.com/p/2/"
        assert urls[2] == "https://tiktok.com/@user/video/3"


def test_resolve_profile_input():
    # Standard URL
    assert resolve_profile_input("https://instagram.com/testuser/") == "https://instagram.com/testuser/"

    # platform:username syntax
    assert resolve_profile_input("facebook:meta") == "https://facebook.com/meta/"
    assert resolve_profile_input("fb:meta") == "https://facebook.com/meta/"
    assert resolve_profile_input("instagram:john_doe") == "https://instagram.com/john_doe/"
    assert resolve_profile_input("tiktok:@dancer") == "https://tiktok.com/dancer/"
    assert resolve_profile_input("x:techlead") == "https://x.com/techlead/"
    assert resolve_profile_input("youtube:CreatorStudio") == "https://youtube.com/@CreatorStudio"

    # Facebook profile.php?id=... extraction
    assert extract_username_from_profile_url("https://www.facebook.com/profile.php?id=100012345", Platform.FACEBOOK) == "100012345"
    assert extract_username_from_profile_url("https://www.facebook.com/zuck", Platform.FACEBOOK) == "zuck"

    # Generic site logo filter
    assert is_generic_site_logo("https://static.xx.fbcdn.net/rsrc.php/v3/y/r/fb_icon_325x325.png")
    assert not is_generic_site_logo("https://scontent.cdninstagram.com/v/t51.2885-19/123456_n.jpg")

    # Netscape cookies.txt loading (including #HttpOnly_ lines required for Facebook xs/datr/sb)
    with tempfile.TemporaryDirectory() as td:
        cookie_path = Path(td) / "cookies.txt"
        cookie_path.write_text(
            "# Netscape HTTP Cookie File\n"
            ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\tabc123\n"
            "#HttpOnly_.facebook.com\tTRUE\t/\tTRUE\t2147483647\txs\t42%3Afb_secret_xs\n"
            ".facebook.com\tTRUE\t/\tTRUE\t2147483647\tc_user\t1000999\n",
            encoding="utf-8",
        )
        cfg = AppConfig(cookies_file=cookie_path)
        jar = load_cookie_jar(cfg)
        assert jar is not None
        names = {c.name for c in jar}
        assert "sessionid" in names
        assert "xs" in names
        fb_hdr = _build_cookie_header(jar, "https://www.facebook.com/example")
        assert fb_hdr is not None
        assert "xs=42%3Afb_secret_xs" in fb_hdr
        assert "c_user=1000999" in fb_hdr
        assert "sessionid" not in fb_hdr

    # Ambiguous bare @username must raise error
    with pytest.raises(ProfileError, match="ambiguous"):
        resolve_profile_input("@dancer")


def test_extract_public_profile_images_parses_ssr_jsonld_and_og():
    fb_html = r'''
    <html><head>
      <meta property="og:image" content="https://static.xx.fbcdn.net/rsrc.php/v3/y/r/fb_icon_325x325.png" />
      <script type="application/ld+json">{"@type":"Person","image":{"url":"https://scontent.xx.fbcdn.net/v/ld_avatar.jpg"}}</script>
    </head><body>
      <script>{"profilePicLarge":{"uri":"https:\/\/scontent.xx.fbcdn.net\/v\/large_avatar.jpg?a=1\u0026b=2"}}</script>
    </body></html>
    '''
    urls = extract_public_profile_images(fb_html, "https://www.facebook.com/example/")
    assert urls[0] == "https://scontent.xx.fbcdn.net/v/large_avatar.jpg?a=1&b=2"
    assert "https://scontent.xx.fbcdn.net/v/ld_avatar.jpg" in urls
    assert all("rsrc.php" not in u for u in urls)

    ig_tiktok_html = r'''
    <script>{"profile_pic_url_hd":"https:\/\/scontent.cdninstagram.com\/hd.jpg","avatarLarger":"https:\/\/p16-sign.tiktokcdn.com\/av.jpeg"}</script>
    '''
    urls2 = extract_public_profile_images(ig_tiktok_html)
    assert urls2 == [
        "https://scontent.cdninstagram.com/hd.jpg",
        "https://p16-sign.tiktokcdn.com/av.jpeg",
    ]

    # Verify high-resolution owner profilePicLarge outranks 160x160 thumbnail and ignores unrelated random comment avatars
    fb_multi = r'''
    <script>
      {"profilePic160":{"uri":"https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-1\/1_n.jpg?stp=dst-jpg_p160x160"}}
      {"profilePicLarge":{"uri":"https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-1\/2_n.jpg?stp=dst-jpg_tt6\u0026cstp=mx877x858\u0026ctp=mx877x858"}}
      {"unrelated_commenter":{"uri":"https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-1\/stranger.jpg"}}
      {"cover_photo":{"image":{"uri":"https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-6\/cover_n.jpg"}}}
    </script>
    '''
    candidates = extract_public_profile_candidates(fb_multi)
    urls_multi = [c.url for c in candidates]
    assert "mx877x858" in urls_multi[0]
    assert all("stranger.jpg" not in u for u in urls_multi)
    assert any(c.is_cover and "cover_n.jpg" in c.url for c in candidates)
    assert not candidates[0].is_cover

    fmt_dict = ProfileImageCandidate(
        url="https://scontent.xx.fbcdn.net/v/t39.30808-1/2_n.jpg",
        label="Profile Picture (Large)",
        width=877,
        height=858,
        filesize=145000,
        ext="jpg",
        verified=True,
    ).to_format_dict(0)
    assert fmt_dict["format_id"] == "img_0"
    assert fmt_dict["resolution"] == "877x858"
    assert fmt_dict["vcodec"] == "image"
    assert fmt_dict["filesize"] == 145000

    # Verify nested Facebook SVG header avatar with <mask> is extracted
    svg_html = '<svg aria-label="Profile"><mask id="m"><circle/></mask><g><image xlink:href="https://scontent.xx.fbcdn.net/v/t39.30808-1/header_hd.jpg"/></g></svg>'
    assert "https://scontent.xx.fbcdn.net/v/t39.30808-1/header_hd.jpg" in extract_public_profile_images(svg_html)


def test_enhance_image_bytes_to_hd_upscales_low_res_cleanly():
    import io
    from PIL import Image

    assert compute_hd_target_dimensions(245, 240) == (960, 940)
    assert compute_hd_target_dimensions(1080, 1080) == (1080, 1080)

    src = Image.new("RGB", (245, 240), color=(40, 110, 190))
    buf = io.BytesIO()
    src.save(buf, format="JPEG", quality=85)

    enhanced_bytes, new_w, new_h, ext = enhance_image_bytes_to_hd(buf.getvalue())
    assert ext == "png"
    assert (new_w, new_h) == (960, 940)
    with Image.open(io.BytesIO(enhanced_bytes)) as out_img:
        assert out_img.size == (960, 940)


def test_extract_facebook_photo_viewer_links_and_images():
    prof_html = r'''
    <script>
      {"profile_photo":{"id":"123","url":"https:\/\/www.facebook.com\/photo\/?fbid=123456\u0026set=a.1"}}
      {"cover_photo":{"photo":{"url":"https:\/\/www.facebook.com\/photo\/?fbid=987654\u0026set=a.2"}}}
    </script>
    '''
    links = extract_facebook_photo_viewer_links(prof_html)
    assert links == [
        ("https://www.facebook.com/photo/?fbid=123456&set=a.1", False),
        ("https://www.facebook.com/photo/?fbid=987654&set=a.2", True),
    ]

    # Relative /photo/?fbid=... URLs and fallback profile_photo.id extraction
    rel_html = r'''
    <script>
      {"profile_photo":{"url":"\/photo\/?fbid=555555\u0026set=a.11"}}
      {"cover_photo":{"id":"7777777"}}
    </script>
    '''
    rel_links = extract_facebook_photo_viewer_links(rel_html)
    assert rel_links == [
        ("https://www.facebook.com/photo/?fbid=555555&set=a.11", False),
        ("https://www.facebook.com/photo/?fbid=7777777", True),
    ]

    viewer_html = r'''
    <script>
      {"viewer_image":{"height":1440,"width":1440,"uri":"https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-6\/full_hd.jpg?a=1\u0026b=2"}}
      {"image":{"height":1080,"width":1080,"uri":"https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-6\/alt_hd.jpg"}}
    </script>
    '''
    imgs = extract_photo_viewer_images(viewer_html, is_cover=False)
    img_urls = [i.url for i in imgs]
    assert "https://scontent.xx.fbcdn.net/v/t39.30808-6/full_hd.jpg?a=1&b=2" in img_urls
    assert "https://scontent.xx.fbcdn.net/v/t39.30808-6/alt_hd.jpg" in img_urls
    assert all(i.label == "Profile Picture (Native HD)" and not i.is_cover for i in imgs)

    # Verify X/Twitter _normal and YouTube =s88 upgrade to high-resolution renditions first
    social_small = r'''
    <meta property="og:image" content="https://yt3.googleusercontent.com/abc=s88-c-k-c0x00ffffff-no-rj" />
    <script>{"profile_image_url_https":"https:\/\/pbs.twimg.com\/profile_images\/123\/pic_normal.jpg"}</script>
    '''
    upgraded = extract_public_profile_images(social_small)
    assert "https://pbs.twimg.com/profile_images/123/pic.jpg" in upgraded
    assert "https://yt3.googleusercontent.com/abc=s1024-c-k-c0x00ffffff-no-rj" in upgraded
    assert upgraded.index("https://yt3.googleusercontent.com/abc=s1024-c-k-c0x00ffffff-no-rj") < upgraded.index("https://yt3.googleusercontent.com/abc=s88-c-k-c0x00ffffff-no-rj")


def test_parse_rate_limit():
    assert parse_rate_limit("5M") == 5 * 1024 * 1024
    assert parse_rate_limit("500K") == 500 * 1024
    assert parse_rate_limit("1G") == 1024 ** 3
    assert parse_rate_limit("1024") == 1024
    assert parse_rate_limit(None) is None
    assert parse_rate_limit("invalid") is None


def test_choose_output_template():
    with tempfile.TemporaryDirectory() as td:
        cfg = AppConfig(output_dir=Path(td))
        engine = DownloadEngine(cfg)

        target_video = DetectedTarget(
            original_url="https://youtube.com/watch?v=1",
            normalized_url="https://youtube.com/watch?v=1",
            platform=Platform.YOUTUBE,
            content_type=ContentType.VIDEO,
        )
        tmpl = engine.choose_output_template(target_video)
        assert "%(title)" in tmpl
        assert "%(id)s" in tmpl

        target_playlist = DetectedTarget(
            original_url="https://youtube.com/playlist?list=1",
            normalized_url="https://youtube.com/playlist?list=1",
            platform=Platform.YOUTUBE,
            content_type=ContentType.PLAYLIST,
        )
        tmpl_pl = engine.choose_output_template(target_playlist)
        assert "%(playlist_title)s" in tmpl_pl


def test_backward_compatibility_exports():
    # Ensure all primary symbols are exported on downloader module directly
    assert hasattr(downloader, "DownloadEngine")
    assert hasattr(downloader, "AppConfig")
    assert hasattr(downloader, "Platform")
    assert hasattr(downloader, "sanitize_filename")
    assert hasattr(downloader, "normalize_url")
    assert hasattr(downloader, "main")


def test_build_playlist_entries_skips_private_and_builds_youtube_urls():
    raw = [
        {"id": "PmZdQ4MiqwQ", "title": "First Video", "duration": 215, "uploader": "Creator A"},
        {"id": "deleted1234", "title": "[Private video]", "duration": None},
        {
            "id": "vXL-E4JLPj8",
            "url": "https://www.youtube.com/watch?v=vXL-E4JLPj8",
            "title": "Second Video",
            "duration": 90,
            "thumbnails": [{"url": "https://example.com/small.jpg"}, {"url": "https://example.com/large.jpg"}],
        },
    ]
    entries = _build_playlist_entries(raw, Platform.YOUTUBE, "Fallback Creator")
    assert len(entries) == 2
    assert entries[0]["index"] == 1
    assert entries[0]["url"] == "https://www.youtube.com/watch?v=PmZdQ4MiqwQ"
    assert entries[0]["thumbnail"] == "https://i.ytimg.com/vi/PmZdQ4MiqwQ/hqdefault.jpg"
    assert entries[0]["uploader"] == "Creator A"
    assert entries[1]["index"] == 2
    assert entries[1]["thumbnail"] == "https://example.com/large.jpg"
    assert entries[1]["uploader"] == "Fallback Creator"


def test_extract_supported_qualities_sorts_descending_and_includes_audio():
    info = {
        "formats": [
            {"format_id": "137", "vcodec": "avc1", "acodec": "none", "height": 1080, "ext": "mp4"},
            {"format_id": "248", "vcodec": "vp9", "acodec": "none", "height": 1080, "ext": "webm"},
            {"format_id": "22", "vcodec": "avc1", "acodec": "mp4a", "height": 720, "ext": "mp4"},
            {"format_id": "135", "vcodec": "avc1", "acodec": "none", "height": 480, "ext": "mp4"},
            {"format_id": "sb0", "vcodec": "none", "acodec": "none", "height": 45, "ext": "mhtml"},
            {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "ext": "m4a"},
        ]
    }
    assert _extract_supported_qualities(info) == ["1080p", "720p", "480p", "Audio"]


def test_upscaler_both_ycbcr_paths_and_rgba():
    import importlib.util
    import io
    from PIL import Image

    rgb = Image.new("RGB", (240, 240), color=(90, 140, 200))
    if importlib.util.find_spec("numpy") is not None:
        out_np = _enhance_rgb_ycbcr_numpy(rgb, 960, 960)
        assert out_np.size == (960, 960)
        assert out_np.mode == "RGB"

    out_pil = _enhance_rgb_ycbcr_pillow(rgb, 960, 960)
    assert out_pil.size == (960, 960)
    assert out_pil.mode == "RGB"

    rgba = Image.new("RGBA", (200, 200), color=(40, 120, 210, 180))
    buf = io.BytesIO()
    rgba.save(buf, format="PNG")
    out_bytes, w, h, ext = enhance_image_bytes_to_hd(buf.getvalue())
    assert ext == "png"
    assert (w, h) == (800, 800)
    with Image.open(io.BytesIO(out_bytes)) as img:
        assert img.mode == "RGBA"
        assert img.size == (800, 800)


def test_detect_facebook_profile_locked_and_multiplatform_extractors():
    assert detect_facebook_profile_locked('{"is_profile_locked":true}')
    assert detect_facebook_profile_locked("<div>Tina locked her profile</div>")
    assert not detect_facebook_profile_locked('{"is_profile_locked":false}')

    multi_html = r'''
    <script>
      {"hd_profile_pic_url_info":{"url":"https:\/\/scontent.cdninstagram.com\/native_ig.jpg"}}
      {"icon_img":"https:\/\/styles.redditmedia.com\/avatar_r.png","banner_img":"https:\/\/styles.redditmedia.com\/banner_r.png"}
      {"profile_banner_url":"https:\/\/pbs.twimg.com\/profile_banners\/123\/456"}
      {"profile_image_url_https":"https:\/\/pbs.twimg.com\/profile_images\/99\/pic_400x400.jpg"}
    </script>
    <meta property="og:image" content="https://yt3.googleusercontent.com/ch=s176-c-k-c0x00ffffff-no-rj" />
    '''
    cands = extract_public_profile_candidates(multi_html)
    urls = [c.url for c in cands]
    assert "https://scontent.cdninstagram.com/native_ig.jpg" in urls
    assert "https://styles.redditmedia.com/avatar_r.png" in urls
    assert any(c.is_cover and "banner_r.png" in c.url for c in cands)
    assert any(c.is_cover and "1500x500" in c.url for c in cands)
    assert "https://pbs.twimg.com/profile_images/99/pic.jpg" in urls
    assert "https://yt3.googleusercontent.com/ch=s2048-c-k-c0x00ffffff-no-rj" in urls

    fb_php = r'{"profile_photo":{"url":"\/photo.php?fbid=99887766"}}'
    assert extract_facebook_photo_viewer_links(fb_php) == [
        ("https://www.facebook.com/photo.php?fbid=99887766", False)
    ]
    fw_html = r'{"full_width_image":{"uri":"https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-6\/fw.jpg"}}'
    assert extract_photo_viewer_images(fw_html)[0].url == "https://scontent.xx.fbcdn.net/v/t39.30808-6/fw.jpg"

    # Facebook profile numeric ID extraction (must ignore viewer's uppercase USER_ID)
    assert extract_facebook_user_id("https://www.facebook.com/profile.php?id=1000123456789") == "1000123456789"
    assert extract_facebook_user_id(
        "https://www.facebook.com/tina.merzik",
        '<meta property="al:ios:url" content="fb://profile/1000987654321" />',
    ) == "1000987654321"
    assert extract_facebook_user_id(
        "https://www.facebook.com/tina.merzik",
        '{"USER_ID":"999999999","profile_owner":{"id":"1000555555555"}}',
    ) == "1000555555555"
    assert extract_facebook_user_id(
        "https://www.facebook.com/tina.merzik",
        '{"CurrentUserInitialData":{"USER_ID":"999999999"},"props":{"userID":"1000444444444"}}',
    ) == "1000444444444"


def test_extract_profile_metadata_fields_across_platforms():
    # Instagram
    ig_html = r'''
    <meta name="description" content="12.5M Followers, 120 Following, 450 Posts - See Instagram photos" />
    <script>{"profilePage_987654321":true,"is_verified":true,"is_private":false,"biography":"Hello IG \u2764"}</script>
    '''
    pid, bio, verified, private, fields = extract_profile_metadata_fields(
        Platform.INSTAGRAM, "https://www.instagram.com/nasa/", ig_html
    )
    assert pid == "987654321"
    assert verified is True
    assert private is False
    assert bio and "Hello IG" in bio
    by_label = {f.label: f for f in fields}
    assert by_label["ID"].value == "987654321"
    assert by_label["Username"].value == "@nasa"
    assert by_label["Followers"].value == "12.5M"
    assert by_label["Following"].value == "120"
    assert by_label["Posts"].value == "450"

    # TikTok
    tt_html = r'''
    <script>{"userInfo":{"user":{"id":"681234567890","uniqueId":"creator","verified":true,"signature":"Bio TT"},"stats":{"followerCount":1500000,"followingCount":50,"heartCount":42000000,"videoCount":310}}}</script>
    '''
    pid, bio, verified, private, fields = extract_profile_metadata_fields(
        Platform.TIKTOK, "https://www.tiktok.com/@creator", tt_html
    )
    assert pid == "681234567890"
    assert verified is True
    assert bio == "Bio TT"
    by_label = {f.label: f for f in fields}
    assert by_label["Followers"].value == "1.5M"
    assert by_label["Followers"].copy_value == "1500000"
    assert by_label["Likes"].value == "42M"
    assert by_label["Videos"].value == "310"

    # X / Twitter
    tw_html = r'{"rest_id":"44196397","is_blue_verified":true,"followers_count":200000000,"friends_count":800,"statuses_count":50000,"description":"Mars"}'
    pid, bio, verified, private, fields = extract_profile_metadata_fields(
        Platform.TWITTER, "https://x.com/elonmusk", tw_html
    )
    assert pid == "44196397"
    assert verified is True
    assert bio == "Mars"
    assert {f.label: f.value for f in fields}["Followers"] == "200M"

    # YouTube
    yt_html = r'{"externalId":"UC_x5XG1OV2P6uZZ5FSM9Ttw","subscriberCountText":{"simpleText":"2.4M subscribers"},"videosCountText":{"text":"6.1K"}}'
    pid, bio, verified, private, fields = extract_profile_metadata_fields(
        Platform.YOUTUBE, "https://www.youtube.com/@GoogleDevelopers", yt_html
    )
    assert pid == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    by_label = {f.label: f.value for f in fields}
    assert by_label["Channel ID"] == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert by_label["Subscribers"] == "2.4M"

    # Bluesky
    pid, bio, verified, private, fields = extract_profile_metadata_fields(
        Platform.BLUESKY,
        "https://bsky.app/profile/bsky.app",
        extra_data={
            "did": "did:plc:z72i7hdynmk6r22z27h6tvur",
            "handle": "bsky.app",
            "followersCount": 25000000,
            "followsCount": 12,
            "postsCount": 420,
            "description": "Official Bluesky",
        },
    )
    assert pid == "did:plc:z72i7hdynmk6r22z27h6tvur"
    assert bio == "Official Bluesky"
    assert {f.label: f.value for f in fields}["Followers"] == "25M"



