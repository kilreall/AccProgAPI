# Red Pitaya accelerometer acquisition

Two machines, two roles:

- **Red Pitaya board** — runs `rp_collector.py`, acquires samples via the native `rp` API and streams them over TCP.
- **PC** — runs `pc_receiver.py` (TCP receiver, saves `.npz`) and `rp_ssh_manager.py` (SSH GUI to start/stop/monitor the collector on the board).

```
┌─────────────────────┐          TCP (raw int16)          ┌───────────────────┐
│   Red Pitaya board   │ ────────────────────────────────▶ │        PC          │
│   rp_collector.py     │                                    │   pc_receiver.py    │
└─────────────────────┘                                    └───────────────────┘
          ▲
          │ SSH (start / stop / status / log tail)
          │
┌─────────────────────┐
│        PC            │
│   rp_ssh_manager.py   │
└─────────────────────┘
```

## Files

| File | Runs on | Purpose |
|---|---|---|
| `rp_collector.py` | Red Pitaya | Acquires data (`rp` API) and sends it over TCP to `pc_receiver.py`. Self-manages a PID file for remote start/stop. |
| `pc_receiver.py` | PC | TCP server that accepts packets from `rp_collector.py` and saves them to a timestamped `.npz` on shutdown. |
| `rp_ssh_manager.py` | PC | PyQt5 GUI that manages `rp_collector.py` on the board over SSH (paramiko): start/stop, status, live log tail. |
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

1. **Start the receiver on the PC**, before starting the collector:
   ```bash
   uv run python pc_receiver.py --port 5000 --samples 16384 --out-dir ./data
   ```
   Stop with Ctrl+C — it saves everything buffered so far to `./data/data_<timestamp>.npz`.

2. **Manage the collector on the board** via the SSH GUI:
   ```bash
   uv run python rp_ssh_manager.py
   ```
   Fill in the board's IP/SSH credentials and the PC receiver's host/port, then use *Start collector* / *Stop collector* / *Refresh status* / *Start log tail*.

   Alternatively, run it directly over a plain SSH session without the GUI:
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
