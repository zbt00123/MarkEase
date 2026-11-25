# Cross-platform builds (Linux & macOS)

MarkEase shares **one business codebase** across Windows, macOS and Linux.
Operating-system differences live in `app/platform/` and in the packaging
directory; you never maintain three copies of a feature.

- Windows: `app/platform/win.py` (WebView2, Win32 clipboard, pythonnet PDF)
- macOS: `app/platform/mac.py` (WKWebView, `pbpaste`, native print PDF)
- Linux: `app/platform/linux.py` (WebKit2GTK, `xclip`/`wl-paste`, WebKit2 print)

Business code calls `platform.<method>()` only. Front-end shortcut labels use
`web/js/platform.js` (`MKPlatform.label('Ctrl+S')` → `⌘S` on macOS).

## GitHub Actions (recommended)

**Single workflow:** `.github/workflows/build.yml`

One run builds every platform in parallel:

| Job | Runner | Output |
|---|---|---|
| `windows-x64` | `windows-latest` | `MarkEase_v<ver>_Windows_x64_portable.zip` |
| `linux-x64` | `ubuntu-22.04` | `MarkEase_v<ver>_Linux_x64.tar.gz`, `.deb` |
| `macos-x64` | `macos-15-intel` | `MarkEase_v<ver>_macOS_x64.dmg` |
| `macos-arm64` | `macos-26` | `MarkEase_v<ver>_macOS_arm64.dmg` |

How to run:

1. Open **Actions → Build all platforms → Run workflow** (branch `main`).
2. Wait for the four jobs; download all artifacts from the same run.
3. Pushing a `v*` tag triggers the same workflow and produces all four files.

The macOS dmg is built with `dmgbuild`: Finder opens it with a custom
background showing an arrow from `MarkEase.app` to an `Applications` shortcut
and the text “拖动 MarkEase 到 Applications 文件夹 / Drag to the Applications
folder”. CI mounts the dmg and checks `.DS_Store`, the background image and the
`Applications` symlink.

PyInstaller cannot cross-compile, so each target is built on its native runner.
Intel and Apple Silicon each get their own dmg; a universal2 build is possible
later but requires every native dependency to be fat.

## Local builds

### Linux

```bash
sudo apt-get install -y pkg-config gobject-introspection \
  libglib2.0-dev libgirepository1.0-dev libffi-dev \
  libcairo2-dev libpango1.0-dev libgtk-3-dev libwebkit2gtk-4.0-dev \
  gir1.2-gtk-3.0 gir1.2-webkit2-4.0

python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --clean --noconfirm packaging/linux.spec
python packaging/package.py --target linux-x64 --dist dist --out out
```

`ubuntu-22.04` is used for CI because its older glibc produces a binary that
runs on more distributions. The `.deb` declares GTK3 / WebKit2GTK dependencies.

### macOS

```bash
python3 -m pip install -r requirements.txt pyinstaller

# Apple Silicon
MK_TARGET_ARCH=arm64 python -m PyInstaller --clean --noconfirm packaging/macos.spec
python packaging/package.py --target macos-arm64 --dist dist --out out

# Intel (on an Intel Mac or macos-15-intel runner)
MK_TARGET_ARCH=x86_64 python -m PyInstaller --clean --noconfirm packaging/macos.spec
python packaging/package.py --target macos-x64 --dist dist --out out
```

### Windows

Unchanged: `python -m PyInstaller --clean --noconfirm MarkEase.spec`.

## macOS notes

- The **business menu is inside the window on macOS** too (same
  File/Edit/View/Help layout as Windows/Linux). The macOS system menu bar keeps
  only the native `MarkEase` application menu (About/Hide/Quit). The Help →
  Settings submenu is hidden on macOS because macOS has no ShellNew; it remains
  on Windows/Linux.
- The app menu's **About MarkEase** item is rewired to the custom About window
  while the app menu is created, so it works on the very first click after
  launch. Changing language updates the in-window menu immediately; no restart.
- Closing with unsaved changes: Discard or Save uses a macOS-specific
  force-close that terminates with `os._exit(0)` after the UI is done. This
  avoids Python finalization waiting forever on pywebview's non-daemon JS API
  thread. The `--close-test` CI step verifies the process exits within 10s.
- Builds are **ad-hoc signed and not notarized** by default. On first launch
  Gatekeeper asks the user to right-click → Open, or run
  `xattr -dr com.apple.quarantine /Applications/MarkEase.app`.
- To sign and notarize, set repository secrets
  `APPLE_CERTIFICATE_P12`, `APPLE_CERTIFICATE_PASSWORD`,
  `MAC_CODESIGN_IDENTITY`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`,
  `APPLE_TEAM_ID`. The workflow then imports the certificate, signs with the
  hardened runtime, submits to `notarytool` and staples the dmg.
- `Info.plist` declares `.md` / `.markdown` documents and a PDF viewer type.
  Opening a file while the app is running is handled through the `open-file`
  Apple Event and forwarded to the front-end.
- PDF export: Windows uses WebView2 `PrintToPdfAsync`; macOS uses
  `WKWebView.createPDF` (no external browser, so no Chrome/PDF privacy prompt;
  long content is chunked and merged); Linux exports the preview to HTML and
  prints it with a locally installed Chrome/Chromium. Export always ignores the
  on-screen zoom level and uses 100%.
- HTTPS requests (network images, update checks) use a bundled `certifi` CA so
  they work on Python.org macOS builds without system CA configuration.
- Fuzzy search falls back to a source-level matcher when the preview DOM cannot
  provide blocks, skipping Markdown markers (`**`, `[]()`, backticks) and
  zero-width characters, so `foo bar` matches `foo **bar**` in every view mode.
- Startup is race-proof: on WKWebView `pywebviewready` can fire before the ES
  module graph (`app.js`) finishes loading, so the front-end also starts
  immediately when `window.pywebview.api` already exists, with a 10-second
  polling fallback.

## Linux notes

- `tar.gz` is portable but requires the host to provide GTK3 + WebKit2GTK.
- `.deb` is recommended; it installs to `/opt/markease`, adds a `markease`
  launcher, a desktop entry and a hicolor icon.
- The first frozen launch writes `~/.local/share/applications/markease.desktop`;
  “set as default program” uses `xdg-mime default`.
- CI runs the packaged binary under `xvfb-run` for 25 seconds to prove the
  window and WebView initialize.

## Smoke test

Every platform supports:

```bash
MarkEase --self-test   # no window: imports, bundled assets, PDF capability
MarkEase --net-test    # no window: fetch one HTTPS image through /proxy
MarkEase --ui-test     # opens a window, waits for init, prints one JSON line
MarkEase --pdf-test /tmp/out.pdf  # opens a window and exports a sample PDF
```

`--ui-test` reports `initialized`, `initStage`, `initError`, `toolbarButtons`,
`editorReady`, `menubarVisible` and early JS errors, then exits `0` (ok) or
`3` (front-end did not initialize). CI runs it on Linux (`xvfb-run`) and macOS
after every build, so a blank window fails the build instead of shipping.

## Testing the Linux build on Windows

The Linux binary is built on Ubuntu 22.04 (glibc 2.35, WebKit2GTK 4.0).
The closer your test environment is to that, the more meaningful the result.

### Option A — WSL2 + WSLg (Windows 11 22H2 or newer)

WSLg provides a Wayland/X display, so the real GTK window can be tested.

```powershell
wsl --install -d Ubuntu-22.04
wsl
```

Inside Ubuntu:

```bash
sudo apt update
sudo apt install -y libgtk-3-0 libwebkit2gtk-4.0-37 \
  gir1.2-gtk-3.0 gir1.2-webkit2-4.0 libglib2.0-0 libcairo2 libpango-1.0-0

tar -xzf /mnt/c/path/to/MarkEase_v2.1.6_Linux_x64.tar.gz
cd MarkEase
./MarkEase
```

- If the window is blank, keep `WEBKIT_DISABLE_DMABUF_RENDERER=1` (the app sets
  it by default) and try `LIBGL_ALWAYS_SOFTWARE=1 ./MarkEase`.
- Test the `.deb` too: `sudo apt install ./MarkEase_v2.1.6_Linux_x64.deb`,
  then run `markease`.
- On Windows 10 (no WSLg), install VcXsrv/X410, then
  `export DISPLAY=$(ip route | awk '/default/ {print $3}'):0` before running.

### Option B — Ubuntu 22.04 virtual machine (most faithful)

VirtualBox / VMware / Hyper-V with an Ubuntu 22.04 desktop image gives the
closest result to a real Linux desktop (GPU, fonts, WebKit helper processes).
Install the `.deb` inside the VM and test the full UI.

### Option C — Docker + X server

Possible with `x11docker`, but WebKitGTK inside containers needs extra
sandbox/DBus flags. Use it only if WSLg/VM are unavailable.

### Headless checks

`--self-test` works without a display and verifies bundled modules/assets.
`--ui-test` needs a display (WSLg, Xvfb or a VM) and is the check that catches
blank-window regressions.

## Remaining differences

| Feature | Windows | macOS | Linux |
|---|---|---|---|
| PDF export | WebView2 | WKWebView print | WebKit2 print |
| Set as default app | registry | manual (Finder) | `xdg-mime` |
| Hang watchdog / WebView2 crash recovery | yes | n/a | n/a |

PDF output on macOS should be compared against Windows on real Intel and
Apple-Silicon machines (pagination, CJK fonts, KaTeX) before a public release.
