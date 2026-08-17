# Lunar Base

A browser-based management interface for someone who lives on the moon and manages The Cage. Sits alongside **lunar-tear** and lets you back up, restore, and edit the player database from a browser.

> Web-based control panel for a [Lunar Tear](https://github.com/Walter-Sparrow/lunar-tear) private server. Runs on Linux and Windows.

---

## What it does

| | |
|---|---|
| **Save data** | Snapshot the database at any time, restore any snapshot, automatic rolling pool of 50 |
| **User viewer** | Currencies, inventory counts, and stackable totals for each account |
| **Item Editor** | Grant or top up gems, gold, materials, and consumables |
| **Costume Editor** | Grant playable costumes and reroll their karma effects |
| **Weapon Editor** | Grant weapons, resolving full evolution chains |
| **Upgrade Manager** | Exalt characters, fill slab pages, max companions, weapons, and costumes |
| **Memoir Editor** | Grant memoir sets and edit their stat rolls |

Two things worth knowing before you start:

**Every editor takes a backup before it writes anything.** Snapshots are tagged with the editor that triggered them, so anything you do here can be undone from the Save Data page.

**Nothing is ever removed.** Grants only add; quantities are never reduced. The way back from a mistake is a restore, not an "undo".

---

## How it works

Lunar Base never writes SQL. It reads the database directly over a read-only connection, and performs every change by handing a request to a small compiled Go program (`grant`) that imports lunar-tear's own internal functions:

```
Browser ──► Lunar Base (Python) ──┬── read ──► game.db (read-only)
                                  │
                                  └── write ─► grant binary ──► lunar-tear internals ──► game.db
```

That indirection is the point. Writes go through the same code paths the game server uses, so Lunar Base cannot produce a row shape the server does not understand. Editing the database directly is how saves get corrupted.

---

## Requirements

**Python 3.10 or newer.** That is the only hard requirement if you use a release archive.

- **Linux:** the launcher installs anything missing (`pythonX.Y-venv`, and Go if you are building from source) via `apt`, asking first.
- **Windows:** install Python from [python.org](https://www.python.org/downloads/) and tick **"Add python.exe to PATH"**. Do not use the Microsoft Store version — see [Troubleshooting](#troubleshooting).

**Go 1.25 or newer** — only when building from source. If Go is missing, the launcher offers to download an official toolchain into `.build/` without touching your system, and removes it afterwards.

**A Lunar Tear installation** with:

- `db/game.db` — created when you first run the server
- `assets/release/*.bin.e` — the encrypted master data
- `assets/revisions/…` — the asset dump, for extracting English names

Both lunar-tear layouts are supported: the prebuilt release (flat) and a source checkout (nested under `server/`).

---

## Directory layout

Put Lunar Base beside your Lunar Tear installation:

```
your-folder/
├── lunar-tear/         (any name -- see below)
└── lunar-base/         ← this
```

The launcher finds Lunar Tear by looking for its marker files, not by name, so an unrenamed `lunar-tear-server-v1.0.0-linux-amd64` works fine. If it lives somewhere else entirely:

```bash
./start-lunar-base.sh --lunar-tear /path/to/lunar-tear
```

The path is remembered afterwards.

---

## Installing

### From a release archive (recommended)

The archive contains a prebuilt `grant` binary, so you do not need Go.

1. Download the archive for your platform from the [Releases](../../releases) page
2. Unpack it beside your Lunar Tear installation
3. Run the launcher:

```bash
# Linux
chmod +x start-lunar-base.sh
./start-lunar-base.sh
```

```bat
REM Windows -- or just double-click it
start-lunar-base.bat
```

### From source

Identical, except the launcher has to build the shim. It downloads lunar-tear's source and a Go toolchain into `.build/`, compiles, and offers to delete the scratch folder afterwards.

```bash
git clone https://github.com/NMeliksah/lunar-base.git
cd lunar-base
./start-lunar-base.sh
```

### What the first run does

The launcher is both installer and runner — there is no separate setup step. It will:

1. Check Python, and offer to install what is missing
2. Create a virtual environment and install dependencies
3. Locate your Lunar Tear installation
4. Decode master data from the `.bin.e` into JSON
5. Extract English names from the text bundles
6. Find or build the `grant` shim
7. Offer to install itself as a startup service (Linux)
8. Start, and print the address to open

Steps 4 and 5 take a few minutes and only happen once. Later runs detect the output and skip.

Then open **<http://127.0.0.1:8888>**.

---

## Running it again

```bash
./start-lunar-base.sh --prefer-saved
```

`--prefer-saved` reuses your stored host and port.

### Options

| Flag | Purpose |
|---|---|
| `--prefer-saved` | Reuse saved settings without prompting |
| `--host ADDR` | Bind address. Default `127.0.0.1`; use `0.0.0.0` to reach it from other machines |
| `--port N` | Port. Default `8888` |
| `--lunar-tear PATH` | Path to the Lunar Tear installation |
| `--yes`, `-y` | Accept every prompt: package installs, shim build, startup service |
| `--no-service` | Skip the startup-service offer |
| `--text-revision N` | Read English names from a specific asset revision |
| `--rebuild-shim` | Discard the shim binary and build it again |
| `--lunar-tear-ref TAG` | Lunar Tear version to build the shim from. Default `v1.0.0` |

---

## Reaching it from another machine

By default Lunar Base listens on loopback only. To use it from your phone or another computer — say when the server runs on a headless box:

```bash
./start-lunar-base.sh --host 0.0.0.0
```

> **There is no authentication.** Anyone who can reach the port has complete control over the save, including the ability to overwrite it from a backup. Only do this on a network you trust. If you want remote access without exposing it broadly, bind to a VPN interface address rather than `0.0.0.0`.

---

## Running as a service (Linux, optional)

The launcher offers this at the end of a run. Accepting installs a systemd unit, so Lunar Base starts on boot:

```bash
systemctl status lunar-base
systemctl restart lunar-base
journalctl -u lunar-base -f
```

To install it separately, without a full launcher run:

```bash
sudo ./install-service.sh
```

Decline the offer and Lunar Base simply runs in the foreground each time you start it, which is perfectly fine.

### Automatic server control

Restoring a backup means replacing `game.db`, and that is only safe once the server has let go of it. By default Lunar Base **refuses to restore while Lunar Tear is listening** and asks you to stop it yourself:

```bash
# stop the server, restore in the browser, then
./wizard --prefer-saved
```

Lunar Base can do that dance for you instead — stop the server, wait for the database to actually be released, swap the file, start the server again — but only if **Lunar Tear itself is running as a systemd unit** that Lunar Base can manage. Most people just launch `./wizard` in a terminal, in which case there is no unit to control and the manual path above is what you get. Nothing is broken; the Save Data page will say `MANUAL` and tell you why.

If you would like the automatic version, give Lunar Tear a unit of its own. Something like `/etc/systemd/system/lunar-tear.service`:

```ini
[Unit]
Description=Lunar Tear private server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/lunar-tear
ExecStart=/path/to/lunar-tear/wizard --prefer-saved
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lunar-tear
```

`Restart=` is deliberately absent. Automatic restarts would hide a server that is failing to start, and you generally want to notice that rather than have it papered over.

Name the unit `lunar-tear` and Lunar Base finds it automatically. If you prefer another name, add this to the `[Service]` section of `/etc/systemd/system/lunar-base.service`:

```ini
Environment=LUNAR_TEAR_UNIT=your-unit-name
```

On Windows there is no equivalent, so restore is always the manual path.

---

## Upgrading Lunar Tear

**Rebuild the shim whenever you upgrade the server.**

```bash
./start-lunar-base.sh --rebuild-shim --lunar-tear-ref v1.2.0
```

The shim is compiled against a specific version's internal code. A mismatched one may write rows the running server does not expect — which fails quietly rather than loudly, so it is worth doing as a matter of routine.

---

## Troubleshooting

**Windows: "No Python 3.10 or newer found", but Python is installed.**
You have the Microsoft Store stub — a placeholder that only opens the Store. Install Python from [python.org](https://www.python.org/downloads/) with "Add python.exe to PATH" ticked, then turn off the stub: *Settings → Apps → Advanced app settings → App execution aliases*, and disable `python.exe` and `python3.exe`. Open a new terminal and check `py -3 --version`.

**Windows: "Terminate batch job (Y/N)?" after Ctrl+C.**
Normal. Lunar Base has already shut down cleanly; that prompt is `cmd.exe` asking about the batch file itself. Either answer is fine.

**Windows: the editors report a missing `grant.exe`.**
Antivirus may have quarantined it. It is an unsigned Go binary that writes to a database, which is a reasonable heuristic hit. Restore it and add an exclusion, or build it yourself with `--rebuild-shim`.

**Editors show empty lists.**
English names were not extracted. Delete `data/names/` and run the launcher again — it will report which asset revision it used and warn if few names resolved. If the warning appears, try `--text-revision 0` for the base revision.

**"No English text bundles found under the revisions tree".**
Your asset dump is missing `assetbundle/text/en`. Both `revisions/<n>/assetbundle/…` and the platform-nested `revisions/<n>/android/assetbundle/…` are supported, so this usually means the dump did not finish unpacking.

**Windows: extraction fails with path-length errors.**
The asset tree is deeply nested and hits the 260-character limit. Keep the whole thing near the drive root — `C:\lunar\` rather than somewhere under `Documents` — or enable long path support.

**Restore says the server is listening.**
Expected without automatic server control. Stop Lunar Tear, restore, start it again. On Linux, installing the service (above) automates this.

**The launcher cannot find Lunar Tear.**
Point at it directly with `--lunar-tear /path/to/lunar-tear`. It looks for `db/`, `assets/`, `server/go.mod`, or a `wizard` binary, in either layout.

---

## A word of caution

**Play through at least the first two chapters before running bulk actions**, so the tutorials are all behind you. The tutorials expect specific items in a specific state, and a mass upgrade moves them past what the scripted step is looking for — the weapon it asks you to tap, for instance, stops being clickable and progression stalls. Restoring a backup fixes it, but it is easier to avoid.

**Take a manual backup before trying an editor for the first time.** The automatic ones have you covered, but a snapshot you took deliberately is easier to find in a list of fifty.

**The game client refreshes on menu navigation, not story progression.** If a grant seems not to have applied, open and close the relevant screen.

---

## Licence

MIT — see [LICENSE](LICENSE).

Bundled and linked third-party code is credited in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Lunar Base ships no game content; all game data is read from an installation you supply.
