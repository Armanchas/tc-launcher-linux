# tc-launcher-linux

A Linux-native launcher for **The Cycle** community servers. It is protocol-compatible
with the original Windows launcher (prospect-og), so you get the same server
discovery, Steam OpenID login, mod management, and game arguments. The difference
is that it runs the game on Linux through **umu-launcher + Proton**.

## Why Proton and not plain Wine?

The game authenticates through the Steamworks API (`steam_api64.dll`, appid 480).
Plain Wine has no Windows Steam client for the game to talk to, so it fails with
an authentication error at launch. Proton bridges those Steamworks calls to your
**native Linux Steam client**, which lets the game get its auth ticket. That is
why the original launcher does not work under Wine, and why this one uses
umu/Proton.

## Requirements

- Python 3.11+
- [umu-launcher](https://github.com/Open-Wine-Components/umu-launcher) (`umu-run` on PATH)
- A Proton build (Steam's Proton or [Proton-GE](https://github.com/GloriousEggroll/proton-ge-custom)).
  The launcher auto-detects installs in Steam's `steamapps/common` and `compatibilitytools.d`.
- The **native Steam client**, installed, running, and logged in when you launch the game
- The Cycle game files (the folder with `Prospect/Binaries/Win64/Prospect-Win64-Shipping.exe`)

Optional: `gamemoderun` (Feral GameMode) and `mangohud` for the launch toggles.

## Download

Grab `TCLauncher-<version>-x86_64.AppImage` from the GitHub Releases page, make it
executable, and run it:

```sh
chmod +x TCLauncher-*-x86_64.AppImage
./TCLauncher-*-x86_64.AppImage
```

You still need these on the host: the native Steam client (running and logged in),
umu-launcher (`umu-run` on PATH, or set its path in Settings), and a Proton build
(pick it in Settings; GE-Proton works well).

Prefer running from source? See below.

## Run from source

```sh
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/tclauncher        # or: .venv/bin/python -m tclauncher
```

## First run

1. Locate your game files. While no game directory is set, the main screen shows a
   notice with a Locate link. The install folder is usually named `Release` and
   contains `Prospect/Binaries/Win64/Prospect-Win64-Shipping.exe`. You only need
   this before you press Play, and you can also set it in Settings.
2. Select server. Enter the community server's discovery URL, the same one you
   would use with the Windows launcher.
3. Log in. Your browser opens Steam's OpenID page. Sign in and return to the
   launcher.
4. In Settings, pick a Proton version. Use Refresh after installing one.
5. Press Play, with Steam running first. While the game is running the button
   reads Stop game if you need to close it from the launcher.

Config and logs live in `~/.tclauncher/`. The Logs link in the status bar opens
that folder, and the launcher's version is shown next to it.

> First launch is slow. The first time you press Play, umu downloads the Steam
> Linux Runtime and Proton builds its prefix. This can take several minutes with
> no game window, and the launcher shows a "downloading runtime" message while it
> works. Later launches are fast. All game and Proton output goes to
> `~/.tclauncher/game.log`, so check there if the game never appears or closes
> right away.

## How Steam authentication works

The game authenticates through Steamworks (appid 480) against your native Linux
Steam client, then presents that ticket to the community server. Two things have
to be true for this to work, and the launcher handles both automatically:

1. umu has to report the right Steam appid, so the launcher sets `GAMEID=umu-480`.
2. The Proton prefix needs Steam's `steamclient` bridge files (`steamclient64.dll`
   and friends). Proton is supposed to copy these in from your Steam client, but
   umu does not pass along the path Proton needs for that, so the launcher copies
   them into the prefix itself on every launch. Without them the game's
   `SteamAPI_Init` fails with "conditions not met" and login returns
   `SteamUnavailable`.

All you have to do is keep the native Steam client running and logged in.

Those bridge files come from your Steam client's own Proton support files. If you
hit a login error on a brand-new Steam install, open Steam, let it finish
updating, enable Steam Play in its settings, and restart it once so it downloads
them.

## Troubleshooting

- Nothing happens or no window on first Play: expected while the runtime downloads
  and the prefix builds. Watch `~/.tclauncher/game.log` for progress.
- Login error or `SteamUnavailable`: usually the native Steam client is not running
  or not logged in. Start Steam, log in, then press Play. If it persists on a new
  Steam install, see the note above about Steam's Proton support files.
- `SteamAuthorizationFailed` or "Active session is expired": your launcher login
  has expired. Press Log in to sign in with Steam again, then Play.
- For detail, read `~/.tclauncher/game.log`. The diagnostics block at the top
  reports your Proton, prefix, and Steam state. Look for `Client API initialized 1`
  (Steam OK) versus `conditions not met` (Steam not reachable).

## Settings

- Proton version: auto-detected installs plus manual path entry
- Wine prefix: where the game's prefix lives (default `~/.tclauncher/prefix`)
- Launch flags: extra game command-line arguments (e.g. `-log -nosplash`)
- Environment variables: per-launch env (e.g. `DXVK_HUD=fps`)
- GameMode / MangoHud: wrap the launch command with `gamemoderun` or `mangohud`

## Account status

The account card at the top shows where you stand:

- Not signed in: the main button reads Log in with Steam.
- Signed in: the button reads Play, and a Log out link lets you switch account or
  force a fresh login.
- Session expired: the card says so and the button switches back to Log in with
  Steam.

On startup the launcher checks your saved session against the server, so it will
not offer Play for a session the server has already expired.

## Files and data

Everything the launcher writes lives under `~/.tclauncher/`:

| Path | Purpose |
| --- | --- |
| `config.json` | All settings and the saved session |
| `launcher.log` | The launcher's own log |
| `game.log` | stdout/stderr from umu, Proton, and the game |
| `mods/` | Cached downloaded mod archives |
| `prefix/` | Default Wine/Proton prefix |

A `config.json` written by the original Windows launcher loads without changes.
Keys shared with it include `server_discovery_addr`, `backend_data`, `session_id`,
`refresh_token`, `exp`, and `run_args`. Linux-only keys are `game_dir`,
`proton_path`, `wine_prefix`, `umu_path`, `env_vars`, `use_gamemode`, and
`use_mangohud`.

## Resetting

- Log out or switch account: delete `session_id`, `refresh_token`, and `exp` from
  `config.json`, or just press Log in again.
- Rebuild the Proton prefix: delete `~/.tclauncher/prefix/`. The next launch
  rebuilds it, which is slow because it downloads the runtime again.
- Full reset: delete `~/.tclauncher/`.

## Development

```sh
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

`tests/test_verify_compat.py` checks that file hashing stays byte-compatible with
the original launcher's `FileVerifier` (servers compare its `integrity` values) by
loading the class straight out of `prospect-og/launcher/launcher.py`.
