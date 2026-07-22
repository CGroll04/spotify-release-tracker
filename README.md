# Spotify Release Tracker

Spotify Release Tracker is a Python automation project that monitors new music releases using the Spotify Web API. The system uses a Spotify playlist as a dynamic artist watchlist, checks for albums, singles, and guest features, and sends release notifications through a Telegram bot.

I built this because Spotify does not always make it easy to keep up with every new release, especially guest features or appearances that may not show up clearly on an artist’s page. This project gives me a more customized way to track the artists I care about and get alerts directly on my phone.

## Features

- Uses a Spotify playlist as a custom artist watchlist
- Extracts artist IDs from playlist tracks
- Checks artists for albums, singles, and guest features
- Sends Telegram notifications for new releases
- Prevents duplicate alerts using persistent local state
- Supports bulk artist importing without spamming old releases
- Handles Spotify OAuth authentication
- Handles API pagination and rate-limit responses
- Uses environment variables to keep API keys and tokens private

## How It Works

The tracker uses a Spotify playlist as the source of truth for artists. I add one song from each artist I want to follow, and the script reads that playlist to collect the Spotify artist IDs.

Once the artists are loaded, the script can check Spotify’s release data for each artist, including albums, singles, and guest features. When a new release is found, it sends a Telegram alert with the release name, artist, date, and Spotify link.

To prevent duplicate notifications, the tracker stores releases it has already seen in local JSON state files.

## Modes

The script supports different modes depending on what I am doing.

### Bulk Import Mode

Bulk import mode adds artists from the playlist to the tracker without scanning their full old catalogs. This makes it easier to add many artists at once without triggering old-release notifications or creating unnecessary API usage.

### Check Mode

Check mode checks already-tracked artists for new releases. Releases from before the artist was added are ignored, and releases already seen are skipped.

### Debug Mode

Debug mode prints playlist and track data to help inspect the Spotify API response.

## Tech Stack

- Python
- Spotify Web API
- Spotipy
- Telegram Bot API
- Requests
- python-dotenv
- JSON local storage

## Project Structure

```text
spotify-release-tracker/
├── spotify_release_tracker.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/CGroll04/spotify-release-tracker.git
cd spotify-release-tracker
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create a `.env` file

Create a `.env` file using `.env.example` as a template.

```env
SPOTIFY_CLIENT_ID=your_spotify_client_id_here
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret_here
SPOTIFY_REDIRECT_URI=http://127.0.0

TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

SPOTIFY_PLAYLIST_ID=your_spotify_playlist_id_here
SPOTIFY_MARKET=CA

TRACKER_MODE=bulk_import
```

### 4. Run the tracker

For bulk importing artists:

```bash
python spotify_release_tracker.py
```

For checking releases, set this in `.env`:

```env
TRACKER_MODE=check
```

Then run:

```bash
python spotify_release_tracker.py
```

## Security

This repository does not include API keys, tokens, Spotify secrets, Telegram chat IDs, token cache files, or private release-tracking data.

The following files should stay local and should not be committed:

```text
.env
.spotify_token_cache
.cache
seen_releases.json
tracked_artists.json
```

## Future Improvements

- Add scheduled cloud execution
- Move persistent state from JSON files to Firestore or another database
- Add rotating artist batches for larger watchlists
- Add Friday release-window boost mode
- Add Spotify Search fallback for hidden guest features
- Build a cleaner dashboard or CLI interface

## Why This Project Matters

This project combines music, automation, APIs, and real-world problem solving. It started as a personal tool to avoid missing new music and became a practical exercise in OAuth, API pagination, rate-limit handling, persistent local state, and notifications.
