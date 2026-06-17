import os
import json
import time
import requests
import spotipy

from datetime import date
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth


# =========================
# Load secrets/config
# =========================

load_dotenv()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PLAYLIST_ID = os.getenv("SPOTIFY_PLAYLIST_ID")

MARKET = os.getenv("SPOTIFY_MARKET", "CA")

# Modes:
# "bulk_import" = add artists to tracker without scanning old catalogs
# "check" = check already-tracked artists for new releases
TRACKER_MODE = os.getenv("TRACKER_MODE", "bulk_import")

SEEN_RELEASES_FILE = "seen_releases.json"
TRACKED_ARTISTS_FILE = "tracked_artists.json"

RELEASE_PAGE_LIMIT = 10


# =========================
# Validate config
# =========================

required_values = {
    "SPOTIFY_CLIENT_ID": CLIENT_ID,
    "SPOTIFY_CLIENT_SECRET": CLIENT_SECRET,
    "SPOTIFY_REDIRECT_URI": REDIRECT_URI,
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    "SPOTIFY_PLAYLIST_ID": PLAYLIST_ID,
}

missing = [name for name, value in required_values.items() if not value]

if missing:
    raise ValueError(f"Missing required .env values: {', '.join(missing)}")


# =========================
# Spotify auth
# =========================

sp = spotipy.Spotify(
    auth_manager=SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope="playlist-read-private playlist-read-collaborative",
        cache_path=".spotify_token_cache",
        open_browser=True,
    )
)


# =========================
# JSON helpers
# =========================

def load_json_file(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        print(f"⚠️ {path} is invalid. Starting fresh.")
        return default


def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, sort_keys=True)


def load_seen_releases():
    return set(load_json_file(SEEN_RELEASES_FILE, []))


def save_seen_releases(seen_releases):
    save_json_file(SEEN_RELEASES_FILE, sorted(list(seen_releases)))


def load_tracked_artists():
    return load_json_file(TRACKED_ARTISTS_FILE, {})


def save_tracked_artists(tracked_artists):
    save_json_file(TRACKED_ARTISTS_FILE, tracked_artists)


# =========================
# Telegram
# =========================

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(url, data=payload, timeout=15)

        if not response.ok:
            print("❌ Telegram error:", response.status_code, response.text)
            return False

        print("✅ Telegram sent")
        return True

    except requests.RequestException as error:
        print("❌ Telegram request failed:", error)
        return False


# =========================
# Playlist helpers
# =========================

def get_track_from_playlist_item(playlist_item):
    """
    Spotify may return the playable object under either:
    - playlist_item["track"]
    - playlist_item["item"]

    Your account currently gets playlist_item["item"].
    """
    return playlist_item.get("track") or playlist_item.get("item")


def get_artists():
    artist_dict = {}

    results = sp.playlist_items(
        PLAYLIST_ID,
        limit=100,
        additional_types=("track",)
    )

    page_number = 1

    while results:
        items = results.get("items", [])
        print(f"📄 Reading playlist page {page_number}: {len(items)} item(s)")

        for playlist_item in items:
            track = get_track_from_playlist_item(playlist_item)

            if not track:
                print("⚠️ Skipping playlist item with no track/item object")
                continue

            if track.get("type") != "track":
                print(f"⚠️ Skipping non-track item: {track.get('type')}")
                continue

            track_name = track.get("name", "Unknown track")
            artists = track.get("artists") or []

            if not artists:
                print(f"⚠️ No artists found for track: {track_name}")
                continue

            # Tracks every credited artist on the song.
            # Use solo songs if you only want one artist added.
            for artist in artists:
                artist_id = artist.get("id")
                artist_name = artist.get("name")

                if artist_id and artist_name:
                    artist_dict[artist_id] = artist_name
                    print(f"✅ Found artist: {artist_name}")

        if results.get("next"):
            results = sp.next(results)
            page_number += 1
        else:
            break

    return artist_dict


# =========================
# Spotify release checking
# =========================

def spotify_get(url, params=None):
    token = sp.auth_manager.get_access_token(as_dict=False)

    headers = {
        "Authorization": f"Bearer {token}"
    }

    return requests.get(
        url,
        headers=headers,
        params=params,
        timeout=15
    )


def get_artist_releases_for_group(artist_id, group):
    releases = []

    base_url = f"https://api.spotify.com/v1/artists/{artist_id}/albums"

    params = {
        "include_groups": group,
        "market": MARKET,
        "limit": RELEASE_PAGE_LIMIT,
        "offset": 0,
    }

    while True:
        response = spotify_get(base_url, params=params)

        if response.status_code == 400 and "Invalid limit" in response.text:
            print(f"⚠️ Spotify rejected limit={params.get('limit')} for {group}. Retrying without limit.")

            fallback_params = {
                "include_groups": group,
                "market": MARKET,
            }

            response = spotify_get(base_url, params=fallback_params)

            if not response.ok:
                print(f"❌ Spotify error while checking {group}:")
                print("Status:", response.status_code)
                print("URL:", response.url)
                print("Body:", response.text)
                return releases

            data = response.json()

            for release in data.get("items", []):
                release["_tracked_group"] = group
                releases.append(release)

            return releases

        if response.status_code == 429:
            raw_retry_after = response.headers.get("Retry-After", "60")

            try:
                retry_after = int(raw_retry_after)
            except ValueError:
                retry_after = 60

            retry_after = min(retry_after, 120)

            print(f"⏳ Spotify rate limit hit. Suggested wait: {retry_after} second(s).")
            print("⚠️ Skipping this request for now. Try again later.")
            return releases

        if not response.ok:
            print(f"❌ Spotify error while checking {group}:")
            print("Status:", response.status_code)
            print("URL:", response.url)
            print("Body:", response.text)
            return releases

        data = response.json()

        for release in data.get("items", []):
            release["_tracked_group"] = group
            releases.append(release)

        if not data.get("next"):
            break

        params["offset"] += params["limit"]
        time.sleep(0.2)

    return releases


def get_artist_releases(artist_id):
    all_releases = []
    seen_release_ids_this_call = set()

    groups_to_check = ["album", "single", "appears_on"]

    for group in groups_to_check:
        group_releases = get_artist_releases_for_group(artist_id, group)

        for release in group_releases:
            release_id = release.get("id")

            if not release_id:
                continue

            release_key = f"{group}:{release_id}"

            if release_key in seen_release_ids_this_call:
                continue

            seen_release_ids_this_call.add(release_key)
            all_releases.append(release)

        time.sleep(0.3)

    return all_releases


# =========================
# Message formatting
# =========================

def format_release_message(artist_name, release):
    release_name = release.get("name", "Unknown release")
    release_url = release.get("external_urls", {}).get("spotify", "")
    release_date = release.get("release_date", "Unknown date")

    tracked_group = release.get("_tracked_group")
    album_type = release.get("album_type", "release").upper()

    if tracked_group == "appears_on":
        return (
            f"🚨 *FEATURE / GUEST APPEARANCE*\n"
            f"*{artist_name}* appears on:\n"
            f"*{release_name}*\n"
            f"📅 {release_date}\n"
            f"🔗 {release_url}"
        )

    if tracked_group == "single":
        return (
            f"🎵 *NEW SINGLE*\n"
            f"*{artist_name}* dropped:\n"
            f"*{release_name}*\n"
            f"📅 {release_date}\n"
            f"🔗 {release_url}"
        )

    return (
        f"💿 *NEW {album_type}*\n"
        f"*{artist_name}* dropped:\n"
        f"*{release_name}*\n"
        f"📅 {release_date}\n"
        f"🔗 {release_url}"
    )


# =========================
# Bulk import mode
# =========================

def bulk_import_artists():
    """
    Adds artists from your Spotify playlist to tracked_artists.json
    WITHOUT scanning their old catalog.

    This avoids rate limits and makes adding 150 artists practical.
    """
    watchlist = get_artists()

    print(f"\n🔍 Found {len(watchlist)} artist(s) in your playlist.")

    if not watchlist:
        print("❌ No artists found.")
        return

    tracked_artists = load_tracked_artists()

    today = str(date.today())
    newly_added = []

    for artist_id, artist_name in watchlist.items():
        if artist_id in tracked_artists:
            print(f"⏭️ Already tracking {artist_name}.")
            continue

        print(f"🆕 Adding new artist without scanning old catalog: {artist_name}")

        tracked_artists[artist_id] = {
            "name": artist_name,
            "added_to_tracker": today,
            "alert_after_date": today
        }

        newly_added.append(artist_name)

    save_tracked_artists(tracked_artists)

    print(f"\n✅ Bulk import complete. New artists added: {len(newly_added)}.")

    if newly_added:
        preview = "\n".join(f"- {name}" for name in newly_added[:25])

        if len(newly_added) > 25:
            preview += f"\n...and {len(newly_added) - 25} more"

        send_telegram(
            f"✅ *Bulk artist import complete*\n"
            f"Added {len(newly_added)} new artist(s):\n\n"
            f"{preview}"
        )


# =========================
# Check mode
# =========================

def check_releases():
    """
    Checks releases for artists that are already tracked.

    New artists are added without scanning old catalogs.
    Existing artists are checked normally.
    Releases on/before alert_after_date are ignored.
    """
    watchlist = get_artists()

    print(f"\n🔍 Found {len(watchlist)} artist(s) in your playlist.")

    if not watchlist:
        print("❌ No artists found.")
        return

    seen_releases = load_seen_releases()
    new_seen_releases = set(seen_releases)

    tracked_artists = load_tracked_artists()

    today = str(date.today())

    alerts_sent = 0
    newly_tracked_artists = 0
    total_releases_checked = 0

    for artist_id, artist_name in watchlist.items():
        print(f"\n🎧 Checking {artist_name}...")

        is_new_artist = artist_id not in tracked_artists

        if is_new_artist:
            print(f"🆕 New artist detected: {artist_name}")
            print("Adding artist to tracker without scanning old catalog.")

            tracked_artists[artist_id] = {
                "name": artist_name,
                "added_to_tracker": today,
                "alert_after_date": today
            }

            newly_tracked_artists += 1
            continue

        artist_info = tracked_artists.get(artist_id, {})
        alert_after_date = artist_info.get("alert_after_date")

        try:
            releases = get_artist_releases(artist_id)
        except Exception as error:
            print(f"❌ Failed checking {artist_name}: {error}")
            continue

        print(f"Found {len(releases)} release(s) for {artist_name}")

        for release in releases:
            release_id = release.get("id")

            if not release_id:
                continue

            tracked_group = release.get("_tracked_group", "unknown")
            release_key = f"{artist_id}:{tracked_group}:{release_id}"

            release_name = release.get("name", "Unknown release")
            release_date = release.get("release_date", "Unknown date")
            album_type = release.get("album_type")

            total_releases_checked += 1

            print(f"  - {release_name} | {release_date} | {tracked_group} | {album_type}")

            if release_key in seen_releases:
                continue

            # Important:
            # This prevents artists you just added from alerting old catalog.
            # It also skips same-day releases from the day you added the artist.
            if alert_after_date and release_date <= alert_after_date:
                print(f"⏭️ Skipping old/pre-tracking release: {release_name} | {release_date}")
                new_seen_releases.add(release_key)
                continue

            message = format_release_message(artist_name, release)

            sent = send_telegram(message)

            if sent:
                alerts_sent += 1
                new_seen_releases.add(release_key)

        time.sleep(1)

    save_seen_releases(new_seen_releases)
    save_tracked_artists(tracked_artists)

    print(
        f"\n✅ Check complete. "
        f"New artists added: {newly_tracked_artists}. "
        f"Releases checked: {total_releases_checked}. "
        f"Alerts sent: {alerts_sent}."
    )


# =========================
# Debug
# =========================

def debug_playlist_payload():
    print("\n--- PLAYLIST METADATA ---")

    playlist = sp.playlist(
        PLAYLIST_ID,
        fields="id,name,owner.display_name,public,tracks.total"
    )

    print(json.dumps(playlist, indent=2))

    print("\n--- FIRST PLAYLIST ITEMS ---")

    results = sp.playlist_items(
        PLAYLIST_ID,
        limit=5,
        additional_types=("track",)
    )

    print(f"Total according to playlist_items(): {results.get('total')}")
    print(f"Number of items returned in first page: {len(results.get('items', []))}")

    for i, playlist_item in enumerate(results.get("items", []), start=1):
        print(f"\nItem #{i}")
        print("Top-level item keys:", list(playlist_item.keys()))

        track = get_track_from_playlist_item(playlist_item)

        if not track:
            print("❌ No track/item object")
            continue

        print("track type:", track.get("type"))
        print("track name:", track.get("name"))

        artists = track.get("artists") or []
        print("artists:")

        for artist in artists:
            print(f"  - {artist.get('name')} | {artist.get('id')}")


# =========================
# Main
# =========================

if __name__ == "__main__":
    print("▶️ Starting music release tracker...")
    print(f"Mode: {TRACKER_MODE}")

    if TRACKER_MODE == "bulk_import":
        bulk_import_artists()
    elif TRACKER_MODE == "check":
        check_releases()
    elif TRACKER_MODE == "debug":
        debug_playlist_payload()
    else:
        raise ValueError("Invalid TRACKER_MODE. Use 'bulk_import', 'check', or 'debug'.")

    print("✅ Script finished.")