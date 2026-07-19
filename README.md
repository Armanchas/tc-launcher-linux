# tc-launcher-linux

A Linux-native launcher for **The Cycle** community servers. Protocol-compatible
with the original Windows launcher (prospect-og): same server discovery, Steam
OpenID login, mod management, and game arguments — plus Linux-specific launch
support through **umu-launcher + Proton**.

## Why Proton and not plain Wine?

The game itself authenticates through the Steamworks API (`steam_api64.dll`,
appid 480). Under plain Wine there is no Windows Steam client for the game to
talk to, so it fails with an authentication error at launch. Proton bridges
those Steamworks calls to your **native Linux Steam client**, so the game can
obtain its auth ticket. This is why the original launcher "doesn't work in
Wine" — and why this launcher runs the game through umu/Proton instead.

## Requirements

- Python 3.11+
- [umu-launcher](https://github.com/Open-Wine-Components/umu-launcher) (`umu-run` on PATH)
- A Proton build (Steam's Proton or [Proton-GE](https://github.com/GloriousEggroll/proton-ge-custom)),
  auto-detected from Steam's `steamapps/common` and `compatibilitytools.d`
- The **native Steam client installed, running, and logged in** at game launch
- The Cycle game files (the folder containing
  `Prospect/Binaries/Win64/Prospect-Win64-Shipping.exe`)

Optional: `gamemoderun` (Feral GameMode) and `mangohud` for the launch toggles.

## Download

Grab `TCLauncher-<version>-x86_64.AppImage` from the GitHub Releases page,
make it executable, and run it:

```sh
chmod +x TCLauncher-*-x86_64.AppImage
./TCLauncher-*-x86_64.AppImage
```

You still need, installed on the host:

- the **native Steam client**, running and logged in (the game authenticates
  through it),
- **umu-launcher** (`umu-run` on PATH, or set its path in Settings),
- a **Proton** build (pick it in Settings; GE-Proton works well).

Prefer running from source? See below.

## Run from source

```sh
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/tclauncher        # or: .venv/bin/python -m tclauncher
```

## First run

1. **Locate your game files** — while no game directory is set, the main screen
   shows a notice with a **Locate…** link (the install folder is usually named
   `Release`; it contains `Prospect/Binaries/Win64/Prospect-Win64-Shipping.exe`).
   You can do this whenever you like — it is only needed before you press Play —
   and you can also set it in **Settings**.
2. **Select server** — enter the community server's discovery URL (same URL you
   would use with the Windows launcher).
3. **Log in** — your browser opens Steam's OpenID page; sign in and return to
   the launcher. If the game directory still isn't set at this point, the Play
   button becomes **Locate game files…** until it is.
4. In **Settings**, pick a Proton version (use **Refresh** after installing one).
5. **Play** — make sure Steam is running first. While the game is running the
   same button reads **Stop game** (with a confirmation prompt) if you need to
   kill it from the launcher.

A **Logs** link in the status bar opens `~/.tclauncher/` in your file manager,
and the launcher's own version (`vX.Y.Z`) is shown next to it. Config and logs
live in `~/.tclauncher/` (`config.json`, `launcher.log`, `game.log`), mod
archives are cached in `~/.tclauncher/mods/`, and the default Wine prefix is
`~/.tclauncher/prefix`.

> **First launch is slow.** The very first time you press Play, umu downloads
> the Steam Linux Runtime and Proton builds its prefix. This can take several
> minutes with **no game window** — the launcher shows "First launch: Proton is
> downloading its runtime…" while it works. Later launches are fast. All game
> and Proton output is written to `~/.tclauncher/game.log`; check it if the game
> never appears or closes immediately.

## How Steam authentication works

The game authenticates through Steamworks (appid 480) against your **native
Linux Steam client**, then presents that ticket to the community server. For
this to work the launcher runs the game with:

- `GAMEID=umu-480` so umu reports Steam appid 480 to the game;
- `UMU_NO_RUNTIME=1` so umu runs Proton **directly on the host** instead of
  inside its pressure-vessel container — inside the container the game cannot
  reach the Steam client's IPC sockets and `SteamAPI_Init` fails with
  "conditions not met" (login error `SteamUnavailable`);
- `STEAM_COMPAT_CLIENT_INSTALL_PATH` pointing at your Steam install so Proton
  installs the `steamclient` bridge into the prefix.

All three are set automatically. You just need the native Steam client running
and logged in.

## Troubleshooting

- **Nothing happens / no window on first Play:** expected while the runtime
  downloads (see above). Watch `~/.tclauncher/game.log` for progress.
- **Login error / `SteamUnavailable`:** the native Steam client is not running
  or not logged in. Start Steam, log in, then press Play.
- **`SteamAuthorizationFailed` / "Active session is expired":** your launcher
  login has expired. Press **Log in** to sign in with Steam again, then Play.
- Detailed game and Proton output is in `~/.tclauncher/game.log`. Look for
  `Client API initialized 1` (Steam OK) vs `conditions not met` (Steam not
  reachable).

## Settings

- **Proton version** — auto-detected installs plus manual path entry
- **Wine prefix** — where the game's prefix lives (default `~/.tclauncher/prefix`)
- **Launch flags** — extra game command-line arguments (e.g. `-log -nosplash`)
- **Environment variables** — per-launch env (e.g. `DXVK_HUD=fps`)
- **GameMode / MangoHud** — wrap the launch command with `gamemoderun` / `mangohud`

## Signing in and the account card

The account card at the top always shows where you stand and lets you change it:

- **Not signed in** — the main button reads **Log in with Steam**.
- **Signed in with Steam** — the main button reads **Play**, and a **Log out**
  link is available so you can switch account or force a fresh login any time.
- **Session expired** — if your saved session is no longer valid, the card says
  so and the button switches back to **Log in with Steam**.

On startup the launcher checks your saved session against the server, so the
button won't offer **Play** for a session the server has already expired. If a
session turns out to be stale at launch time you get a clear prompt to log in
again.

## Files & data

Everything the launcher writes lives under `~/.tclauncher/`:

| Path | Purpose |
| --- | --- |
| `config.json` | All settings and the saved session (see keys below) |
| `launcher.log` | The launcher's own log |
| `game.log` | stdout/stderr from umu + Proton + the game |
| `mods/` | Cached downloaded mod archives |
| `prefix/` | Default Wine/Proton prefix |

`config.json` keys: `server_discovery_addr`, `backend_data`, `session_id`,
`refresh_token`, `exp`, `run_args` (shared with the Windows launcher);
`game_dir`, `proton_path`, `wine_prefix`, `umu_path`, `env_vars`,
`use_gamemode`, `use_mangohud` (Linux-only). A `config.json` written by the
original Windows launcher loads without changes.

## Resetting

- **Log out / switch account:** delete `session_id`, `refresh_token`, `exp` from
  `config.json` (or just press **Log in** again).
- **Rebuild the Proton prefix from scratch:** delete `~/.tclauncher/prefix/`. The
  next launch rebuilds it (slow, downloads the runtime again).
- **Full reset:** delete `~/.tclauncher/`.

## Development

```sh
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

`tests/test_verify_compat.py` checks that file hashing stays byte-compatible
with the original launcher's `FileVerifier` (servers compare its `integrity`
values), by loading the class straight out of `prospect-og/launcher/launcher.py`.
