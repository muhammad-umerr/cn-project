# Web application simplification — November 24, 2026

## What changed

- Single homepage only: topology, FTP/NAT selectors, real transfer outcome and current-run capture download.
- Removed web actions/pages for setup, teardown, batch experiments, result-history, router diagnostics, capture browsing, and miscellaneous artifact downloads.
- Automatically initializes any missing Linux namespaces and FTP server before Flask accepts requests.
- Preserves a healthy, already-initialized lab instead of resetting it.
- Runs one experiment at a time; the FTP client and `dumpcap` capture actual Linux namespace traffic.
- Fixes capture timing: calls `capture.sh stop` **before** looking for generated files.
- Uses `mergecap` to combine the three router-interface PCAPNGs into **one file** per experiment.
- Makes the file available only from that completed job in the currently running web-server process.
- Converts all shell scripts from Windows CRLF to Unix LF endings, addressing Ubuntu Bash parsing issues.
- Preserves the CLI networking and experiment tools and existing project documentation.

## Live validation

Static checks and a mocked capture lifecycle test were run in the packaging environment. Flask and Linux namespace/capture functionality need verification on the Ubuntu laptop with root privileges.

Run:

```bash
sudo .venv/bin/python -m web.app
```

Open `http://127.0.0.1:5000`; run N0 Passive RETR and verify the Download button produces a `.pcapng` file. Open it in Wireshark and verify packet traffic is present from the three interfaces. Also test a failing case (N1 Active) to ensure its unsuccessful FTP negotiation remains downloadable.
