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
credentials_path). Each strategy/channel gets its own token file;
nothing here reads a shared global credential.

OAuth SETUP IS OUT OF SCOPE HERE ON PURPOSE. This module loads and
refreshes an already-issued token; it never runs the interactive
consent flow itself. See docs/YOUTUBE_SETUP.md for the one-time,
human-run setup that produces credentials_path's file in the first
place.

QUOTA: uploads bill to a separate ~100/day bucket (per the task this
was built under), independent of the 10,000-unit default quota
CLAUDE.md's Platform notes describe for everything else. No quota-
tracking logic exists in this module, deliberately.

R5 (CLAUDE.md): every upload sets YouTube's altered/synthetic content
disclosure. status.containsSyntheticMedia (added October 30, 2024,
settable on videos.insert/videos.update) is that field -- confirmed,
not guessed. Hardcoded True below, not a parameter on UploadRequest,
same posture as PRIVACY_STATUS: this pipeline always uses synthetic
narration and imagery, so the disclosure is never conditional, and a
caller cannot accidentally upload without it. Self-certification
(R5's other half) has no equivalent API field as of this writing --
that stays a manual step in Studio, same as R5's own "completes
self-certification conservatively" already assumed a human in the
loop for.
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

# Always True -- see module docstring's R5 paragraph. Not a parameter on
# UploadRequest, same reasoning as PRIVACY_STATUS: every video this
# pipeline produces uses synthetic narration and imagery, so this is
# never conditional on the caller remembering to set it.
CONTAINS_SYNTHETIC_MEDIA = True


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
                "containsSyntheticMedia": CONTAINS_SYNTHETIC_MEDIA,
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
