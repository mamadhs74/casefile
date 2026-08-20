"""YouTubeUploader -- uploads a rendered episode as a PRIVATE draft via
the YouTube Data API v3's resumable upload protocol. Never uploads
public: PRIVACY_STATUS is not a caller-configurable field on
UploadRequest, on purpose -- publishing (the visibility change to
public/unlisted) stays a manual click in YouTube Studio for now.

CREDENTIALS ARE PER-STRATEGY, NOT GLOBAL. This module takes a raw
credentials_path (a Path to a serialized google.oauth2.credentials.
Credentials JSON file), not a Strategy row or a session -- it stays
free of any packages.db dependency, same reasoning every other
provider module in this codebase already follows (ClaimForComposition,
ClaimForTagging, etc.). The caller is responsible for resolving that
path off the episode's own strategy at upload time (Strategy.
credentials_path -- NOT YET A REAL COLUMN as of this module's writing,
see the task this was built under; this module is written against the
schema that column will add, not against what exists in
data/casefile.db today). Each strategy/channel gets its own token
file; nothing here reads a shared global credential.

OAuth SETUP IS OUT OF SCOPE HERE ON PURPOSE. This module loads and
refreshes an already-issued token; it never runs the interactive
consent flow itself. See docs/YOUTUBE_SETUP.md for the one-time,
human-run setup that produces credentials_path's file in the first
place.

QUOTA: uploads bill to a separate ~100/day bucket (per the task this
was built under), independent of the 10,000-unit default quota
CLAUDE.md's Platform notes describe for everything else. No quota-
tracking logic exists in this module, deliberately.

KNOWN GAP, flagged rather than guessed: R5 (CLAUDE.md) requires every
upload to set YouTube's altered/synthetic content disclosure and
complete self-certification conservatively. The exact Data API v3
request field(s) for both are NOT filled in below -- this surface has
changed more than once, and CLAUDE.md's own Platform-notes convention
is "verify current numbers in the console, do not hardcode
assumptions." Confirm the current field(s) against
https://developers.google.com/youtube/v3/docs/videos/insert before
this module uploads to a real channel; until then, upload() sends a
private, correctly-titled/described video WITHOUT that disclosure set,
which is not R5-compliant on its own. See _SYNTHETIC_DISCLOSURE_TODO
below for exactly where it needs to go.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

# -1: let the client library pick chunk size (its own default
# resumable-upload chunking) rather than pinning one here -- matches
# Google's own resumable-upload sample. A dropped connection mid-upload
# resumes from the last acknowledged byte on retry via next_chunk(),
# not from byte 0 -- that's what "resumable" buys, independent of any
# stage-level retry policy (there is none here, see module docstring).
_CHUNK_SIZE = -1

# Never anything else -- see module docstring. Not a parameter on
# UploadRequest on purpose: a caller cannot accidentally request public.
PRIVACY_STATUS = "private"

# See module docstring's "KNOWN GAP" paragraph. This constant exists so
# the one line that needs to change, once the real field is confirmed,
# is obvious and greppable -- not scattered reasoning in a comment.
_SYNTHETIC_DISCLOSURE_TODO = (
    "R5 synthetic-content disclosure field not yet confirmed against "
    "the live YouTube Data API v3 docs -- see module docstring"
)


@dataclass(frozen=True)
class UploadRequest:
    video_path: Path
    title: str
    description: str
    tags: list[str]


@dataclass(frozen=True)
class UploadResult:
    video_id: str
    studio_url: str


class YouTubeUploadError(Exception):
    """Raised on any upload failure -- caller stops, no retry built
    into this module (see the task this was built under)."""


class YouTubeUploader:
    def __init__(self, credentials_path: Path) -> None:
        if not credentials_path.exists():
            raise YouTubeUploadError(
                f"credentials file not found: {credentials_path} -- "
                f"see docs/YOUTUBE_SETUP.md"
            )

        credentials = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
            str(credentials_path), [UPLOAD_SCOPE]
        )  # google-auth ships no annotations for this classmethod
        if not credentials.valid:
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                # Persist the refreshed access token back to the same
                # per-strategy file -- otherwise every process restart
                # would re-hit the refresh path unnecessarily.
                credentials_path.write_text(credentials.to_json())
            else:
                raise YouTubeUploadError(
                    f"credentials at {credentials_path} are invalid and cannot "
                    f"be refreshed -- re-run the setup in docs/YOUTUBE_SETUP.md"
                )

        self._client = build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

    def upload(self, request: UploadRequest) -> UploadResult:
        if not request.video_path.exists():
            raise YouTubeUploadError(f"video file not found: {request.video_path}")

        body = {
            "snippet": {
                "title": request.title,
                "description": request.description,
                "tags": request.tags,
            },
            "status": {
                "privacyStatus": PRIVACY_STATUS,
                # TODO(_SYNTHETIC_DISCLOSURE_TODO): the R5 altered/
                # synthetic-content disclosure field belongs here. Not
                # added -- see module docstring's KNOWN GAP paragraph.
            },
        }

        media = MediaFileUpload(str(request.video_path), chunksize=_CHUNK_SIZE, resumable=True)
        insert_request = self._client.videos().insert(
            part="snippet,status", body=body, media_body=media
        )

        response = None
        while response is None:
            try:
                status, response = insert_request.next_chunk()
            except HttpError as exc:
                raise YouTubeUploadError(f"upload failed: {exc}") from exc
            if status is not None:
                print(f"  upload progress: {int(status.progress() * 100)}%")

        video_id = response["id"]
        return UploadResult(
            video_id=video_id,
            studio_url=f"https://studio.youtube.com/video/{video_id}/edit",
        )
