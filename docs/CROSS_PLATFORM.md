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

`ubuntu-22.04` is used for CI because its glibc is the oldest one GitHub still
provides runners for. That sets the real compatibility floor of the Linux
artifact — see the baseline table below. The `.deb` declares the GTK3 /
WebKit2GTK dependencies and, since v2.1.8, no longer ships them itself.

### Linux compatibility baseline

Measured on the v2.1.7 bundle (`GLIBC_*` / `CXXABI_*` strings in `.dynstr` of
each ELF object); the limits come from the frozen interpreter, not from the app:

| Requirement | Minimum | Comes from |
|---|---|---|
| glibc | **2.35** | `_internal/libpython3.14.so.1.0` (built on jammy) |
| GTK 3 | 3.22+ (any) | target distro, `.deb` Depends |
| WebKit2GTK | 4.0 or 4.1 + matching `gir1.2-webkit2-*` | target distro |
| libstdc++ | GCC 5+ for PyMuPDF (`CXXABI_1.3`, `GLIBCXX_3.4`) | target distro |
| libffi | `libffi.so.8` | target distro (GTK3 pulls it) |
| libssl | `libssl.so.3` (OpenSSL 3) for the `ssl` module | target distro |

So the main artifact runs on distributions at or above the jammy baseline:
Ubuntu 22.04+, Debian 12+, Fedora 36+, RHEL/Rocky 9+, deepin 23 (glibc 2.38),
openKylin 2.x. It does **not** run on glibc 2.28/2.31 systems such as
统信 UOS 20 (Debian 10 baseline) or 银河麒麟 V10 (Debian 11 baseline) — the
frozen interpreter needs `GLIBC_2.35`, and the process dies at start with
`GLIBC_2.34 not found`. Those are served by the separate **legacy** build
described below. 信创 arm64 (飞腾 / 鲲鹏) still needs its own arm64 build;
PyInstaller cannot cross-compile.

Quick check on any target system:

```bash
ldd --version | head -1                          # need >= 2.35 (main build)
ldd /opt/markease/_internal/libpython3.14.so.1.0 | grep -i 'not found' || echo 'glibc ok'
ls /usr/lib/*/girepository-1.0/WebKit2-*.typelib  # need 4.0 or 4.1
```

### Legacy build (UOS 20 / Kylin V10 / Debian 10-11)

`build.yml` produces the main package (glibc 2.35) and, in the same workflow
run, the legacy package for the older 信创 baseline.

| | main (`build.yml`) | legacy (same workflow) |
|---|---|---|
| build host | ubuntu-22.04 | `debian:10` container |
| Python | actions/setup-python 3.14 (glibc 2.35) | python-build-standalone 3.14 (glibc 2.17) |
| PyGObject | wheel-less build on jammy | built in the buster userland (GLib 2.58) |
| extra bundled libs | none | `libffi.so.8`, `libssl.so.3`, `libcrypto.so.3` |
| artifact | `..._Linux_x64.deb` | `..._Linux_x64_legacy.deb` |
| covers | Ubuntu 22.04+, Debian 12+, deepin 23, openKylin 2 | UOS 20, Kylin V10, Debian 10/11 (pending first green CI run) |

Both use the same package name (`markease`), so a machine installs exactly one
of them. Build the legacy variant locally with:

```bash
MK_LINUX_LEGACY=1 python -m PyInstaller --clean --noconfirm packaging/linux.spec
python packaging/package.py --target linux-x64 --dist dist --out out --variant legacy
```

The legacy job lives in the same workflow so one run produces every platform,
but it is the only job that needs the Debian 10 container; a failure there
still uploads its diagnostics without blocking the other artifacts.

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
- `Info.plist` exports the `net.daringfireball.markdown` UTI and declares
  `.md/.markdown/.mdown/.mkd`. `application:openFile:` / `openFiles:` are
  implemented on the NSApplicationDelegate; received paths are queued and
  forwarded to the front-end via `open-file` events. Both startup double-click
  and “open with” while running use this path.
- PDF export: Windows uses WebView2 `PrintToPdfAsync`; macOS switches to a
  light print layout, hides the find bar / search highlights / selection, then
  uses `WKWebView.createPDF` and slices the result into Letter pages (no
  external browser, no Chrome/PDF privacy prompt). Linux exports the preview to
  HTML and prints it with a locally installed Chrome/Chromium. Export always
  ignores the on-screen zoom level and uses 100%.
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

The Linux binary is built on Ubuntu 22.04 (glibc 2.35). Since v2.1.8 the bundle
**no longer ships the build host's GTK / GLib / libstdc++** — those come from the
target distribution (declared in the `.deb` `Depends`). That is what makes the
package work on 24.04 / 26.04, where the system WebKitGTK requires newer symbol
versions than jammy provides. Always test the `.deb` on a **newer** LTS as well
as on 22.04: v2.1.7 shipped a jammy `libstdc++.so.6` that lacked
`CXXABI_1.3.15`, so Ubuntu 26.04 could not load WebKit at all (no window, no
error, nothing in the journal).

### Option A — WSL2 + WSLg (Windows 11 22H2 or newer)

WSLg provides a Wayland/X display, so the real GTK window can be tested.

```powershell
wsl --install -d Ubuntu-22.04
wsl
```

Inside Ubuntu:

```bash
sudo apt update
sudo apt install -y libgtk-3-0t64 libwebkit2gtk-4.1-0 \
  gir1.2-gtk-3.0 gir1.2-webkit2-4.1 libglib2.0-0t64 libcairo2 libpango-1.0-0
# On 22.04 the names are libgtk-3-0 / libglib2.0-0 (no t64 suffix).

tar -xzf /mnt/c/path/to/MarkEase_v2.1.8_Linux_x64.tar.gz
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
| PDF export | WebView2 | WKWebView createPDF + Letter pagination | WebKit2 print |
| Set as default app | registry | manual (Finder) | `xdg-mime` |
| Hang watchdog / WebView2 crash recovery | yes | n/a | n/a |

PDF output on macOS should be compared against Windows on real Intel and
Apple-Silicon machines (pagination, CJK fonts, KaTeX) before a public release.
