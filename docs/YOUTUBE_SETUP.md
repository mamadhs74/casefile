# YouTube upload setup

Manual, one-time, per strategy/channel. Nothing in `packages/publish/youtube.py`
performs any step below — it only loads and refreshes an already-issued
credential file. Run this yourself; do not ask Claude Code to do it.

Each strategy gets its own Google Cloud project, its own OAuth client, and its
own credential file — never a shared credential across strategies. `Strategy.credentials_path`
points at that strategy's file.

---

## 1. Create a Google Cloud project (one per strategy)

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Create a new project, named for the strategy (e.g. `casefile-film-tv-news`).
3. Note the project ID — you'll need it if you ever hit quota and want to check
   usage in the console.

## 2. Enable the YouTube Data API v3

1. In the project, go to **APIs & Services → Library**.
2. Search for **YouTube Data API v3**, select it, click **Enable**.

## 3. Configure the OAuth consent screen

1. **APIs & Services → OAuth consent screen**.
2. User type: **External** (a normal Google/YouTube account, not a Workspace org).
3. App name, support email, developer contact — anything accurate; this is
   never shown to a third party since only you will authorize it.
4. Scopes: add `https://www.googleapis.com/auth/youtube.upload` (see §5 — the
   only scope this project needs).
5. Test users: add the Google account that owns (or manages) the YouTube
   channel for this strategy. While the app is in **Testing** publishing
   status, only listed test users can authorize it — that's fine, this app is
   never meant to go through Google's verification review; it's a private
   tool with one (or a few) authorized users.

## 4. Create an OAuth 2.0 Client ID

1. **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Desktop app**.
3. Name it for the strategy.
4. Download the resulting JSON (the "client secret" file) — this is
   distinct from the *token* file `credentials_path` points at; the client
   secret is only used once, to produce the token, then can be set aside.

## 5. Required scope

Only one:

```
https://www.googleapis.com/auth/youtube.upload
```

This grants upload/manage access to videos on the authorized channel. It does
not grant read access to analytics or comments — a narrower scope would be
better if the API exposes one for "upload only, nothing else," but as of this
writing `youtube.upload` is the standard scope every resumable-upload sample
uses; verify against
[the current scopes list](https://developers.google.com/youtube/v3/guides/auth/installed-apps)
before assuming this is still accurate.

## 6. Produce the token file (the one-time authorization run)

This is the one step that requires running code locally — a short, standard
OAuth "installed app" flow using `google-auth-oauthlib` (already a project
dependency). It opens a browser, you sign in and approve access, and it
writes a token JSON to disk. This is not something to run inside an agent
session — do it yourself, in a terminal, so the browser consent step is
actually yours.

```
uv run python -m scripts.generate_youtube_token
```

`scripts/generate_youtube_token.py` is this section's flow, with real paths
hardcoded for film-tv-news's channel instead of placeholder filenames:
`credentials/film-tv-news/client_secret.json` in, `credentials/film-tv-news/token.json`
out. It refuses to run if the client secret is missing, or if `token.json`
already exists (won't silently overwrite a working token — it prints the
`rm` command to run first if you actually want a new one). Never prints
either file's contents; prints only the output path on success.

A second strategy's channel needs its own run of this same shape — either
edit the two hardcoded paths and rerun, or copy the script under a new name
per strategy. It's a one-off setup action, not a reusable multi-strategy
tool, the same way each strategy gets its own Google Cloud project and its
own client secret above.

The resulting token file is what `Strategy.credentials_path` should point
at — keep it out of the repo (it's a real credential, same posture as every
other secret CLAUDE.md's conventions cover: never committed, never logged).
`credentials/` is gitignored for exactly this reason.

## 7. Point `Strategy.credentials_path` at the token file

Once the schema change adding that column lands (see the task this was built
under — not done as of this document), set each strategy's row to the
absolute path of its own token file from step 6. `packages/publish/youtube.py`
reads it at upload time and refreshes the access token automatically if it's
expired, rewriting the same file with the refreshed token.

## 8. Quota

Uploads bill to a separate ~100/day bucket per the task this was built
under, independent of the 10,000-unit default quota CLAUDE.md's Platform
notes describe for everything else (search, list, analytics). Verify the
current number in the console (**APIs & Services → YouTube Data API v3 →
Quotas**) before relying on it — quota allocations have changed before and
will again.

## 9. What this setup does *not* do

- Does not make anything public. Every upload through `packages/publish/youtube.py`
  is `privacyStatus: private`. Reviewing and publishing is a manual step in
  [YouTube Studio](https://studio.youtube.com).
- Does not set R5's synthetic-content disclosure or complete self-certification
  — `packages/publish/youtube.py`'s own docstring flags this as an open gap.
  Set both manually in Studio for any video before it goes public, until that
  gap is closed in code.
