# API request and response shapes (illustrative, not measured)

These are **schema examples** showing how to call the service. They are not experimental outcomes and are not included in `results/`.

## Start an experiment

```bash
curl -s -X POST http://127.0.0.1:5000/api/experiment \
  -H 'Content-Type: application/json' \
  -d '{"nat":"N1","mode":"passive","operation":"retr","loss":2}'
```

Returns HTTP 202 with a job object containing `id`, `kind`, `status`, and `step`. Do not interpret job creation as FTP success.

## Poll status

```bash
curl -s http://127.0.0.1:5000/api/jobs/YOUR_JOB_ID
```

A completed job has `status: "completed"` and a `result` object. An actual unsuccessful FTP transfer may still have `status: "completed"` because job completion indicates that the runner finished and collected a *failed protocol operation*; distinguish this from `result.retr_ok` and `result.retr_data_connected`. If the runner itself crashes or times out, status is `failed` with an `error`.

The result object contains `configuration`, `control_ok`, `control_setup_ms`, per-operation fields such as `retr_data_connected`, `retr_ok`, `retr_bytes`, `retr_sha256`, `retr_transfer_s`, `retr_throughput_mbps`, `retr_stage`, `retr_error`, a redacted `transcript`, and `evidence` snapshots. For passive FTP only, `retr_data_conn_ms` is timed by the socket client; the TCP packet capture provides independent handshake measurements.

## Batch campaigns

```bash
curl -s -X POST http://127.0.0.1:5000/api/batch/experiments \
  -H 'Content-Type: application/json' -d '{"reps":5,"reset":true}'
```

Repetitions must be an integer between 1 and 10. `reset:true` replaces previous `results/raw.csv` before the campaign. `reset:false` appends. A second concurrent network job is rejected with HTTP 409.

## Save evidence

```bash
curl -s http://127.0.0.1:5000/api/diagnostics
curl -s http://127.0.0.1:5000/api/results
```

The web UI also lists generated `.pcapng` traces and allows download under `/api/artifacts/pcap/<filename>`. Only an explicitly allowed set of file paths is served.
