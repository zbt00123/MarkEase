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

**One-click entry point:** `.github/workflows/build-all-platforms.yml`

One run builds every platform in parallel:

| Job | Runner | Output |
|---|---|---|
| `windows-x64` | `windows-latest` | `MarkEase_v<ver>_Windows_x64_portable.zip` |
| `linux-x64` | `ubuntu-22.04` | `MarkEase_v<ver>_Linux_x64.tar.gz`, `.deb` |
| `macos-x64` | `macos-26-intel` | `MarkEase_v<ver>_macOS_x64.dmg` |
| `macos-arm64` | `macos-26` | `MarkEase_v<ver>_macOS_arm64.dmg` |

How to run:

1. Open **Actions → Build all platforms → Run workflow** (branch `main`).
2. Wait for the four jobs; download all artifacts from the same run.
3. Pushing a `v*` tag triggers the same workflow and produces all four files.

The entry point reuses `build-windows.yml` and `build-linux-macos.yml` via
`workflow_call`. Both can still be run on their own when only one platform
needs to be checked.

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

# Intel (on an Intel Mac or macos-26-intel runner)
MK_TARGET_ARCH=x86_64 python -m PyInstaller --clean --noconfirm packaging/macos.spec
python packaging/package.py --target macos-x64 --dist dist --out out
```

### Windows

Unchanged: `python -m PyInstaller --clean --noconfirm MarkEase.spec`.

## macOS notes

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
- PDF export uses `WKWebView` print output (Letter, 0.4 in margins, matching
  Windows). A blank-page check protects against the old macOS
  `NSPrintSaveJob` bug.

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
MarkEase --self-test
```

It prints one JSON line with the platform, GUI backend, bundled web assets,
icon, PDF capability and whether all business modules import. CI runs it after
every build.

## Remaining differences

| Feature | Windows | macOS | Linux |
|---|---|---|---|
| PDF export | WebView2 | WKWebView print | WebKit2 print |
| Set as default app | registry | manual (Finder) | `xdg-mime` |
| Hang watchdog / WebView2 crash recovery | yes | n/a | n/a |

PDF output on macOS should be compared against Windows on real Intel and
Apple-Silicon machines (pagination, CJK fonts, KaTeX) before a public release.
