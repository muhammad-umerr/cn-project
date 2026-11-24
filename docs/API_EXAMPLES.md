# Minimal web API

The web application intentionally exposes only the endpoints needed by a single, current FTP experiment:

- `GET /` — the one-page FTP/NAT laboratory
- `GET /api/status` — current readiness, NAT mode and active job
- `POST /api/experiment` — start one run; JSON `{ "nat":"N1", "mode":"passive", "operation":"retr", "loss":0 }`
- `GET /api/jobs/<job-id>` — poll the current run's progress and outcome
- `GET /api/jobs/<job-id>/capture` — download that completed run's merged PCAPNG

There is no general artifact download, previous-results browser, or web batch-run API. Previous runs are not discoverable across web process restarts. The existing command-line experiment tools remain in `tools/`.

Bind the server to `127.0.0.1`; the app executes privileged namespace configuration commands. Do not expose it to a network interface.
