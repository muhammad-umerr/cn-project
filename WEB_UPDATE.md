# Web application — presentation simulator integration

The presentation simulator layout is now **the Flask home page**; there is no separate `presentation/` folder.

- Reused its readable SVG network diagram, color-coded FTP command timeline, and compact segmented mode/NAT/loss controls.
- Kept the live Flask experiment backend: automatic topology/server setup, N0/N1/N2, Active/Passive, LIST/RETR/STOR, and per-run merged PCAPNG download.
- Replaced the simulator’s hard-coded FTP messages, outcomes, sample timing, and invented conntrack text with **actual FTP control events returned by `client/ftp_client.py`** and measured result flags.
- After a real transfer finishes, **Play / Step / Restart** replays the recorded control transcript; the moving packet icon illustrates control message direction, not exact timing or real individual packets. The PCAPNG is the packet-level source of truth.
- Removed the presentation simulator’s expected-results and deliverables pages: the web application is still a single page and only runs one FTP experiment at a time.
- Preserved capture merging and restricted downloading to a completed experiment in the current server process.

## Run

```bash
sudo .venv/bin/python -m web.app
```

Open http://127.0.0.1:5000. Test N0 Passive RETR (success) and N1 Active RETR (expected PORT rejection) and download the PCAPNG from both.

## Verification

The web assets and scripts passed static syntax checks. Browser rendering was inspected using a local static preview. Real namespace/Flask integration must be tested on Ubuntu; this packaging environment lacks Flask and privileged lab networking.
