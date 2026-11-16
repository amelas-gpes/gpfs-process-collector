# Desktop app (Windows)

`desktop/` is an optional Windows host for the same application: a small WebView2 window
(`NativeHost.cs`), its manager (`manage.py`) and two PowerShell scripts that install it. It is
separate from `launcher.py` and the `.cmd` shortcuts, and it behaves differently from them in
two ways that matter:

- **It downloads.** A scheduled task and the window itself fetch the `main` branch of
  `https://github.com/amelas-dev/ai-process-collector.git`.
- **It runs a downloaded build, not your working tree.** The window serves the build you last
  approved, unpacked under `.local/desktop/releases/`. Edits in the checkout do not appear in
  the window until they are pushed to GitHub `main`, downloaded and approved.

## What the build can reach

An approved build runs as you, with this checkout's settings and data: the provider key in
`.env.local` (or your environment), and the stores in `work/documents` and `work/knowledge`.
It writes `work/server-lifecycle.jsonl` like the browser application does. A build that has
the optional recovery copy (off unless you turn it on in Settings) also shares its setting
and its one copy of an unsaved interview in `work/recovery` with the browser application.
The window cannot hold back a Windows shutdown or sign-out, so with that option off an
unsaved interview is lost when Windows closes the window. Approving a build
is therefore the same decision as running code from GitHub `main` on this computer with your
key and your interviews.

### One set of data, several builds

The desktop window does not have data of its own. The approved build, the older build the
window falls back to, and this checkout's own server (`launcher.py`, port 8774) all open the
same `work/documents/documents.sqlite3` and `work/knowledge/knowledge.sqlite3`, and they can
be different versions of the code. They can also run at the same time. Three rules keep an
older build from misreading data that a newer one wrote:

- **Each store records its format.** The number is kept in the file (SQLite's
  `user_version`), and each build declares the formats it opens (`STORE_FORMATS` in
  `documents.py` and `knowledge_graph.py`). A build upgrades an older store in place when it
  opens it, and refuses a store with a higher number: "written by a newer build ... Nothing
  was changed". This applies to every way of starting the application, not only the window.
- **The window checks before it starts a build.** If the saved data is newer than an approved
  build, that build is not started at all (`older-than-saved-data <commit>`), the same check
  refuses a `rollback` to it, and the window shows the reason instead of the page. Builds made
  before formats were recorded are treated as reading format 1, the layout they wrote.
- **A newer index is not called out of date.** Each indexed file records the version of the
  extraction that read it. A build that finds a higher version than its own treats the file as
  indexed; it does not report it as needing re-indexing or re-read it with its older parser.

A build that is already running when a newer one upgrades the stores is not stopped: close the
older one first. Saved interview JSON files have their own `schema_version` and are not part
of this check.

## Which build is running

The window runs a downloaded build and `launcher.py` runs the working tree, and both report the
same release number (`VERSION` in `server.py`) until it is next raised. To tell them apart,
open **Settings > Help & about** in the page. The last line reads, for example,
`Version 0.30.0 · build 4f2a9c1d7e03`:

- In the desktop window the build is the first 12 characters of the commit you approved, the
  same ID the update question and `updates.log` show.
- For a working tree it is `dev+` and 12 characters of a hash of the served source. The hash
  changes with any edit to that source and ignores line endings, so a checkout with Windows
  line endings and a downloaded build of the same commit have the same hash (`build_id` in
  `/api/config`).

The same pair is written into each saved interview (`app_version`, `app_build`), into
transcript exports, and the commit into the `start` row of `work/server-lifecycle.jsonl`, so a
file can be traced to the code that produced it. Builds from before this was added show no such
line and stamp nothing; `CHANGELOG.md` lists what each release changed.

## Update channel and trust model

Downloading and running are separate steps. Only your answer in the window joins them.

| Step | Command | What it does | What it never does |
| --- | --- | --- | --- |
| Download | `manage.py update` (scheduled task), `manage.py pending` (the window, before it opens) | Fetches `main`, refuses history that does not continue from the last download and from the approved build, checks the signature when you list trusted signers, unpacks the commit to `.local/desktop/releases/<commit>` and checks it statically (`server.py` and `web/index.html` present, top-level Python compiles) | Import or run anything it fetched; change the working tree, the index or `HEAD`; change which build the window serves |
| Ask | the window | Shows the waiting build: 12-character commit ID, commit date, the author's subject line as a quotation, and whether a signature was verified. **Yes** switches; **No** (the default button) keeps the current build and asks again next time | Run the build before you answer |
| Approve | `manage.py approve <commit>` (run by the window on **Yes**) | Repeats the history, signature and static checks, then records the commit in `.local/desktop/approved.json` and `release-approved <commit>` in the update log | Approve anything other than the build that was downloaded and offered |
| Run | `manage.py serve` (the window) | Imports approved builds only, newest first, falling back to the previously approved build if the newest cannot start (see [When a build cannot start](#when-a-build-cannot-start)) | Fetch, or run a build that is only downloaded |

Rules the downloader enforces, all of which fail closed (the window keeps the approved build
and the reason is logged):

- **Fast-forward only.** `main` is fetched beside the manager's own copy of it, and that copy
  only moves forward: the new commit must descend from the commit downloaded before and from
  the approved build (`git merge-base --is-ancestor`). A rewritten or older `main` is refused
  and logged with its commit (`rejected-not-fast-forward <commit>`), so it does not look like
  being offline (`fetch-failed`).
- **Static checks only.** A build that fails them is not offered (`staging-failed <commit>`).
- **Signatures, when you list signers.** See below. An unsigned or unknown-signer build is not
  unpacked or offered (`rejected-untrusted-signature <commit>`).
- **Nothing is approved for you.** On a first installation the window asks before it runs
  anything. If you answer No, the application does not open.

Without a signer list, your approval in the window is the only gate: the question tells you
that the signature was not checked. The subject line shown is whatever the commit's author
wrote; treat it as a claim.

A download cannot hold the window. When an approved build exists, the window allows the fetch
8 seconds before it opens that build (45 seconds on a first run, 90 for the scheduled task).
Git is told to give up on a connection that carries almost nothing for two thirds of that
time, and at the limit Git and every helper process it started are stopped (`fetch-failed`).
Closing a window that is still opening also stops its local service, so the next launch is
not blocked. A startup check that was running for that window (see below) notices that the
service has gone, stops the build it was checking and removes its scratch folder.

### Closing and reopening the window

When the window closes, its local service stops taking requests and ends as soon as the
requests it had already accepted are finished. They get 5 seconds. A request that is still
running then, typically a call to the provider that can take minutes, is abandoned and the
service ends (`closed-while-working <commit>`): the page that asked for the answer is gone,
and until the service ends it holds the window's lock, so the window could not be reopened.
What was already written to `work/` stays; a company-knowledge analysis that was cut off is
marked "Interrupted before completion; retry available" the next time the stores are opened.
The provider may still charge for a call that was under way.

Reopening the window straight away therefore works: the new window waits up to 10 seconds
for the previous session to finish closing. If something still holds the lock after that
(another window, or a service started by an older version that is still waiting for a
provider call), the window says "Process Collector is still closing its previous session, or
is already open in another window. Wait a few seconds and open it again." (`window-busy`).
The rebuilt window host also ends a service that has not ended by itself 9 seconds after the
window closed.

### Trusted signers (optional, recommended)

To accept only builds signed by keys you choose, create an OpenSSH allowed-signers file at
`%USERPROFILE%\.process-collector\allowed_signers`. It is outside the checkout and outside
every downloaded build, so nothing that is fetched can change it. One line per key: an
identity of your choosing, then the public key.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.process-collector" | Out-Null
"you@example.com $(Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub)" |
    Set-Content -Encoding ascii "$env:USERPROFILE\.process-collector\allowed_signers"
```

While that file exists, a build is accepted only if `git verify-commit` reports an SSH
signature by a listed key on the commit itself, or `git verify-tag` reports one on a tag that
names that commit. An empty file trusts nobody, so every build is refused. Deleting the file
returns to approval-only. GPG and X.509 signatures are not accepted. Verification needs
`ssh-keygen` (OpenSSH 8.2 or later), which Git for Windows includes.

Sign what you publish, either the commit or a tag on it:

```powershell
git config gpg.format ssh
git config user.signingkey "$env:USERPROFILE\.ssh\id_ed25519.pub"
git commit -S -m "..."                        # a signed commit
git tag -s desktop-2026-11-13 -m "Desktop release" <commit>   # or a signed tag
git push origin main --tags
```

A signature shows who made a commit or tag, not that it was meant as a release: sign only
what you would run. Merges made on github.com are signed by GitHub, not by your key, so tag
them yourself before expecting the desktop app to accept them.

On GitHub, protect `main` as well (branch protection, no force pushes, required signed
commits). That is defence in depth; the checks above do not depend on it.

## When a build cannot start

The checks made at download are static, so a build can pass them and still fail to start on
this computer. Four things limit the damage:

- **A startup check before your data is involved.** The first time the window is about to
  open a build it has not opened before, it starts that build once by itself: the same
  settings parser, server, `main()` and `/api/config` handshake the window uses, but on a free
  port, with a placeholder key that can spend nothing, with empty stores in a scratch folder
  outside the checkout, and with a plain environment (no keys or tokens). It then requests the
  page, and every script and stylesheet of the build's own that the page names; all must be
  served. Only approved builds are checked this way. A build that fails
  (`startup-check-failed <commit>`) is never given `work/` at all. The check adds a few seconds
  to the first launch of each new build. It is deliberately not run at download: nothing that
  was fetched runs before you approve it, so the build's own test suites are not part of it.
- **A failed build is not tried first again.** A build that fails the check, or passes it and
  then fails with the real stores while an older build starts fine (`startup-failed <commit>`),
  is recorded in `.local/desktop/failed.json`. Later launches go straight to the previous
  approved build. The failed build is tried again only when you choose it again
  (`manage.py rollback <commit>`, below) or when no other approved build is left.
- **A busy port is not a build's failure.** If port 8776 cannot be opened, usually because
  another program is using it, the launch ends and the window says so (`port-unavailable`).
  If the port is already taken when the window opens, no build is started at all. If it is
  taken while the chosen build is starting, that launch ends there. Either way no build is
  recorded as failed and no older build is opened in place of the chosen one. Close the other
  program, or wait a moment, and reopen the window.
- **The window says so.** While an older build is running for this reason the title bar reads
  "Running the previous build: the latest update failed to start (using `<commit>`, not
  `<commit>`)", and the launch on which the failure happened also shows that sentence in a
  message box. The next build you approve is tried as usual.

## Going back to an earlier build, and pausing updates

A build can start and still not work (a page that does not respond, interviews that fail).
The startup check cannot see that, so three things are in your hands. Run the commands in the
checkout with the Python named under [What installation changes](#what-installation-changes),
for example `python.exe -I -B desktop\manage.py rollback`.

- **The build last known to work is always kept.** Opening a build only shows that it started.
  A build counts as *known to work* once the window has requested its page and then stayed
  open for five minutes (`known-good <commit>` in the log, `.local/desktop/known-good.txt`).
  That build is never dropped from the approved list or deleted by later approvals and
  downloads, and it is the first fallback when a newer build cannot start. The list keeps the
  current build, that build and up to two others.
- **`manage.py rollback [commit]`** makes an earlier approved build the one the window opens,
  from the next launch. Without a commit it chooses the build last known to work, or else the
  previous choice. With a commit (the full ID, or its first 7 or more characters, as shown in
  the update question and the log) it chooses that build, which must be one you approved that
  is still on this computer; the error message lists them. Nothing is downloaded or deleted.
  The build you left stays approved and is not offered again; `rollback <its commit>` returns
  to it. The next newer commit on `main` is offered as usual.
- **`manage.py hold`** stops the updater until **`manage.py resume`**: the scheduled task and
  the window download nothing, no build is offered, and `approve` is refused. The approved
  build keeps running and the title bar says that updates are on hold. The scheduled task
  itself stays registered and ends at once (`on-hold`).

Two other ways out do not involve the desktop app at all: revert the commit on GitHub `main`
(the revert arrives as a new build to approve), or run this checkout's own code in a browser
with `launcher.py` on port 8774, which never downloads anything.

## What installation changes

Nothing is installed or downloaded by `desktop/install.ps1` itself. It uses files that must
already exist:

- .NET Framework 4 C# compiler: `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`
- WebView2 SDK 1.0.4258.31 in your NuGet cache:
  `%USERPROFILE%\.nuget\packages\microsoft.web.webview2\1.0.4258.31` (also needed each time
  the window starts), and the WebView2 Runtime that ships with Windows 11
- Python: `python.exe` (for the window) and `pythonw.exe` (for the task) in one folder. If
  `VOICE_INTERVIEWER_PYTHON`, the variable the `.cmd` launchers use, is set in the shell that
  runs `install.ps1`, that interpreter is used; otherwise the Codex runtime at
  `%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\`. The choice
  is made once, at installation: it is written into the scheduled task and into
  `.local\desktop\python.txt`, which the window reads. A scheduled task and a pinned window do
  not see a variable set in one shell, so changing the variable later has no effect until
  `install.ps1` (or `register-updates.ps1`) is run again. A variable that names a missing file,
  or a folder without both executables, stops the installation with a message; nothing falls
  back silently. `install.ps1 -BuildOnly` leaves the choice as it is.
- `git` on `PATH`

Inside the checkout, everything is under the ignored folder `.local/desktop/`:

| Path | Purpose |
| --- | --- |
| `ProcessCollector.exe`, `ProcessCollector.ico` | The compiled window host |
| `python.txt` | The Python chosen at installation (full path of `python.exe`). Without it the window uses the Codex runtime |
| `releases/<commit>/` | Unpacked builds: the approved ones and the one awaiting approval. The manager adds `release.json` (the commit and when it was unpacked) to each, which is how a build [names itself](#which-build-is-running) |
| `approved.json` | Builds you approved, newest first |
| `pending.txt` | The downloaded build awaiting your answer |
| `last-opened.txt` | The build the window last opened |
| `known-good.txt` | The build last known to work here (page requested, window open five minutes) |
| `failed.json` | Approved builds that could not start here, and which event recorded it |
| `hold` | Present while updates are on hold |
| `window.txt` | Where the window was when it last closed: position, size, whether maximized, and the monitor's scale |
| `browser/` | The window's WebView2 profile |
| `updates.log`, `updates.previous.log` | Update events: event names and commit IDs only, 64 KB each |
| `server.log` | Output of the hosted application |
| `*.lock`, `stage-*` | Locks and unpacking scratch space |
| `current.json` | Written by earlier versions. It approves nothing; until your first approval the builds it lists are kept on disk ([after upgrading](#after-upgrading-from-a-version-that-updated-by-itself)) |

The Git repository also gains the refs `refs/collector-desktop/main` (the manager's copy of
`main`), `refs/collector-desktop/incoming` (the last fetch, before it is accepted) and, with a
signer list, `refs/collector-desktop/tags/*`. No branch, tag, index or working-tree file of
yours is changed.

Outside the checkout, for the current user only:

- Scheduled task **GPFS Process Collector Update**: at sign-in and every 15 minutes it runs
  `pythonw.exe -I -B desktop\manage.py update` in the checkout (download only), with the
  Python chosen at installation.
- Start-menu shortcut **GPFS Process Collector.lnk**, and a taskbar pin where Windows allows it.
- Optionally, the signer list you create in `%USERPROFILE%\.process-collector`.

`desktop/install.ps1 -BuildOnly` compiles the window host and changes nothing outside the checkout.

The window is sized for the monitor it opens on. The first time, it takes the size the page
was designed for (1250 x 850 at 100% display scale, so 1875 x 1275 pixels at 150%), or all of
the monitor's working area if that is smaller, centred on the monitor under the pointer. After
that it reopens where it was closed, maximized if it was, provided that place is still on a
connected monitor; if the monitor's scale has changed, the window keeps its apparent size. It
cannot be made smaller than 640 x 480 at the monitor's scale. Delete
`.local\desktop\window.txt` to return to the first-time size. (These rules need the rebuilt
window host: `desktop\install.ps1 -BuildOnly`.)

The window serves `http://127.0.0.1:8776/` and nothing else; other links open in your default
browser. Port 8776 is fixed. An earlier launcher preview also used 8776
([build verification](BUILD_VERIFICATION.md)), so do not run `launcher.py --port 8776` while
the window is open.

## Update log

`.local/desktop/updates.log` holds one line per event: UTC time, event, first 12 characters of
the commit.

| Event | Meaning |
| --- | --- |
| `up-to-date` | `main` is the approved build |
| `release-staged` | A new commit was downloaded, checked and is waiting for approval |
| `awaiting-approval` | The same commit is still waiting |
| `release-approved` | You approved that commit in the window |
| `window-ready` | The window opened that build |
| `known-good` | That build's page was requested and its window stayed open five minutes |
| `closed-while-working` | The window closed while a request was still running; after 5 seconds the service ended without waiting for it |
| `window-busy` | A window could not open: another one is open, or the previous session had not finished closing after 10 seconds |
| `release-selected` | You chose that approved build with `rollback` |
| `not-selected` | `main` is a build you approved and then left with `rollback`; it is not offered again |
| `updates-held`, `updates-resumed`, `on-hold` | `hold` and `resume` were run; a download was skipped because of the hold |
| `startup-check-failed` | The build failed its startup check with empty stores; it was not given `work/` |
| `startup-failed` | The build passed the check but could not start for the window |
| `port-unavailable` | The window's port could not be opened, usually because another program is using it; no build was recorded as failed or replaced by an older one |
| `older-than-saved-data` | The saved data was written by a newer build than this one, so it was not started |
| `fetch-failed` | Offline, or the connection stalled until its time limit |
| `rejected-not-fast-forward` | `main` was rewritten or moved backwards: the commit does not descend from the commit downloaded before, or from the approved build |
| `rejected-untrusted-signature` | A signer list exists and neither the commit nor a tag on it is signed by a listed key |
| `staging-failed` | The commit failed unpacking or the static checks. Invalid archives are skipped until a new head arrives. |
| `release-damaged` | The unpacked files differ from their staging manifest. Download the build again to repair it. |
| `git-missing` | The manager could not find Git on PATH. It needs Git to download and check a build. |
| `git-failed` | Git ran but could not read or verify a required repository object. |
| `approved-list-unreadable` | The manager could not read its approved-build list. The window displays the recovery instructions. |
| `nothing-approved` | The window has no approved build to open. Reopen it to review a downloaded build. |
| `approval-refused` | Updates are on hold or the offered build has changed. Reopen the window to see the current offer. |
| `rollback-refused` | The requested revision does not identify an available approved build. The message lists available choices. |
| `update-busy` | Another update operation holds the lock. Retry after it finishes. |
| `build-in-use` | Another desktop process is using this build. Close that window before retrying. |
| `operation-failed` | A command ended with an error (see the more specific line before it) |

## After upgrading from a version that updated by itself

Earlier versions ran whatever was at the tip of `main`, including in the background task.
After this change:

- The scheduled task registered earlier keeps working unchanged; it now only downloads.
- The build the window last opened stays the approved build. Anything newer waits for approval.
- The earlier version also kept one older release as its fallback (the second entry of
  `current.json`). It is not carried over as approved, because nothing records that you chose
  it. Until you approve another build the window therefore has no fallback, and `rollback` has
  nothing to go back to. The scheduled task does not delete that release: its files stay under
  `releases/` until your first approval, and the first download after that removes them.
- The question is asked by the rebuilt window host. Run `desktop\install.ps1 -BuildOnly` once
  to rebuild it. Until then the old host opens the approved build and never switches. You can
  also decide from PowerShell in the checkout, with the Python named above:
  `python.exe -I -B desktop\manage.py pending` prints the waiting build, and
  `python.exe -I -B desktop\manage.py approve <commit>` approves it.
- The title-bar notices and the specific reasons described in this guide (an older build is
  running, updates are on hold, the saved data is newer than the build) are also shown by the
  rebuilt host only. The old host opens the page without them, or shows its general "could not
  open" message; the update log records the event either way.

If `main` was rewritten on purpose and you want to start again from the new history: close the
window, delete `approved.json`, `pending.txt`, `last-opened.txt`, `known-good.txt` and
`failed.json` in `.local\desktop`, run `git update-ref -d refs/collector-desktop/main`, then
reopen the window and answer the first-run question.

## Removing it

```powershell
Unregister-ScheduledTask -TaskName 'GPFS Process Collector Update' -Confirm:$false
Remove-Item "$([Environment]::GetFolderPath('Programs'))\GPFS Process Collector.lnk"
```

Then unpin the app from the taskbar, close the window and delete `.local\desktop`. Optionally
remove the downloaded refs (`git update-ref -d refs/collector-desktop/main`, and the same for
`refs/collector-desktop/incoming`) and your signer list. `work/` and `.env.local` are not touched by any of these steps.
