"""One-time OAuth authorization for the film-tv-news YouTube channel --
docs/YOUTUBE_SETUP.md sec 6, with that section's placeholder filenames
replaced by this strategy's real paths. Opens a browser; requires a
human to sign in and approve access. Not something to run inside an
agent session -- see that doc's own sec 6 and the task this was built
under. Claude Code does not run this script.

Paths are hardcoded, not CLI arguments -- this is a one-off setup
action for one specific strategy's one specific channel, not a
reusable multi-strategy tool. A second strategy's channel needs its
own script (or this one edited and rerun), the same way each strategy
gets its own Google Cloud project and its own client secret per the
setup doc.

Refuses to run if the client secret is missing (nothing to authorize
against) or if token.json already exists (so a re-run can't silently
overwrite a working token -- see _refuse_if_token_exists for how to
proceed on purpose instead).

Never prints either file's contents -- both are credentials. Prints
only the output path on success.

Usage:
    uv run python -m scripts.generate_youtube_token
"""

from __future__ import annotations

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_SECRET_PATH = Path("credentials/film-tv-news/client_secret.json")
TOKEN_PATH = Path("credentials/film-tv-news/token.json")

# Widened from youtube.upload-only: that scope alone cannot call
# videos.list, so there was no way to read a video's current metadata
# (e.g. snippet.categoryId, required by videos.update whenever
# snippet.title/description change) before overwriting it. The plain
# "youtube" scope covers both read and write; youtube.upload is a
# subset of what this grants, so nothing already built against the
# narrower scope needs to change.
SCOPES = ["https://www.googleapis.com/auth/youtube"]


class SetupAborted(Exception):
    """Raised for any condition that should stop this script before it
    opens a browser or writes anything."""


def _refuse_if_client_secret_missing() -> None:
    if not CLIENT_SECRET_PATH.exists():
        raise SetupAborted(
            f"refusing to run: {CLIENT_SECRET_PATH} does not exist -- "
            f"see docs/YOUTUBE_SETUP.md secs 1-4 to create it first."
        )


def _refuse_if_token_exists() -> None:
    if TOKEN_PATH.exists():
        raise SetupAborted(
            f"refusing to run: {TOKEN_PATH} already exists. "
            f"This script will not overwrite a working token. "
            f"If you actually want a new one, delete it yourself first:\n"
            f"    rm {TOKEN_PATH}\n"
            f"then rerun this script."
        )


def main() -> int:
    try:
        _refuse_if_client_secret_missing()
        _refuse_if_token_exists()

        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
        credentials = flow.run_local_server(port=0)

        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(credentials.to_json())

    except SetupAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1

    print(f"{TOKEN_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
