# Red Pitaya accelerometer acquisition

Two machines, two roles:

- **Red Pitaya board** — runs `rp_collector.py`, acquires samples via the native `rp` API and streams them over TCP.
- **PC** — runs `rp_manager.py`, a single PyQt5 GUI that manages the collector on the board over SSH **and** receives, plots, and saves the streamed data.

```
┌─────────────────────┐          TCP (raw int16)          ┌────────────────────────┐
│   Red Pitaya board   │ ────────────────────────────────▶ │           PC            │
│   rp_collector.py     │                                    │      rp_manager.py       │
└─────────────────────┘ ◀──────────────────────────────── │  (SSH control + receiver │
                            SSH (start/stop/status/log)      │   + live plots + save)   │
                                                             └────────────────────────┘
```

## Files

| File | Runs on | Purpose |
|---|---|---|
| `rp_collector.py` | Red Pitaya | Acquires data (`rp` API) and sends it over TCP to the PC. Self-manages a PID file for remote start/stop. |
| `rp_manager.py` | PC | **Unified PyQt5 GUI.** Manages `rp_collector.py` on the board over SSH (start/stop, status, live log tail), runs a built-in TCP receiver that reassembles the streamed packets, shows them live (waveform + FFT spectrum via pyqtgraph), and saves them to a timestamped `.npz`. |
| `pc_receiver.py` | PC | Standalone headless TCP receiver — the same accept/recv/save logic that `rp_manager.py` now embeds. Kept for scripted/headless capture without a GUI. |
| `rp_ssh_manager.py` | PC | Previous SSH-only GUI, **superseded by `rp_manager.py`** (which adds the receiver and plots). Kept for reference. |
| `PCreceiver.py`, `RPaccAPIThreads.py`, `Rpaccinterface.py` | — | Original drafts, kept for reference. `Rpaccinterface.py` is a separate SCPI-based control GUI (still usable independently). |

## Setup

PC-side dependencies are managed with `uv` (see `pyproject.toml`):

```bash
uv sync
```

The board side only needs Python 3 with the vendor `rp` module already installed (comes with the Red Pitaya OS) — it is not pip-installable, so `rp_collector.py` is not part of the `uv` project.

## Deploying the collector to the board

Copy the script to the board once (path is configurable in `rp_ssh_manager.py`, default `/root/rp_collector.py`):

```bash
scp rp_collector.py root@<rp-ip>:/root/rp_collector.py
```

## Running

Launch the unified GUI on the PC:

```bash
uv run python rp_manager.py
```

Workflow inside the window:

1. **Fill in the connection details** on the left — the board's IP/SSH credentials, remote paths, collector parameters, and the receiver's output directory. The receiver listens on the *PC receiver port* and expects packets of *Samples (N)* — both taken from the collector parameters, so they can't drift apart.
2. **Start the receiver** (*Start receiver*) so the PC is listening before any data arrives.
3. **Start the collector** on the board (*Start collector*). Use *Refresh status* / *Start log tail* to monitor it.
4. Incoming data is plotted live in the **Waveform** and **Spectrum (FFT)** tabs. The FFT frequency axis uses the effective sample rate (125 MHz ÷ decimation).
5. **Save** at any point with *Save now*, or leave *Auto-save on stop* enabled to dump everything to `<out-dir>/data_<timestamp>.npz` when the receiver stops (or the window closes). *Clear buffer* discards accumulated packets.

### Headless alternatives

Run the receiver without a GUI:
```bash
uv run python pc_receiver.py --port 5000 --samples 16384 --out-dir ./data
```
Stop with Ctrl+C — it saves everything buffered so far to `./data/data_<timestamp>.npz`.

Start the collector over a plain SSH session without the GUI:
```bash
ssh root@<rp-ip>
python3 /root/rp_collector.py --pc-host <pc-ip> --pc-port 5000 --decimation 1024 --trigger-src CHB_PE
```

## `rp_collector.py` options

| Flag | Default | Meaning |
|---|---|---|
| `--pc-host` | *(required)* | IP of the PC running `pc_receiver.py` |
| `--pc-port` | `5000` | TCP port of the PC receiver |
| `--samples` | `16384` | Samples per acquisition packet (N) — must match `pc_receiver.py --samples` |
| `--decimation` | `1024` | RP acquisition decimation factor |
| `--trigger-src` | `CHB_PE` | RP trigger source: `NOW`, `CHA_PE`, `CHA_NE`, `CHB_PE`, `CHB_NE` |
| `--channel` | `1` | Input channel to acquire (`1` or `2`) |
| `--queue-size` | `50` | Max packets buffered between acquisition and sender threads |
| `--reconnect-delay` | `2.0` | Seconds between TCP reconnect attempts |
| `--pid-file` | `/tmp/rp_collector.pid` | Where the process writes its own PID (used by `rp_ssh_manager.py` for stop/status) |

## `pc_receiver.py` options

| Flag | Default | Meaning |
|---|---|---|
| `--host` | `0.0.0.0` | Interface to listen on |
| `--port` | `5000` | TCP port to listen on |
| `--samples` | `16384` | Samples per packet (N) — must match the collector |
| `--out-dir` | `.` | Directory for the saved `.npz` |
| `--recv-buffer` | `65536` | Bytes requested per `recv()` call |
