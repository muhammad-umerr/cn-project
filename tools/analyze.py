#!/usr/bin/env python3
"""Turns results/raw.csv (+ success_matrix.csv, conntrack/, pcap/) into:
   results/summary.csv, results/summary.md, results/dashboard.html (self-contained), results/charts/*.png (if matplotlib)
Everything shown comes from YOUR runs. Nothing here invents data."""
import csv, json, pathlib, statistics as st, sys, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = ROOT / "results"
METRICS = [("control_setup_ms", "Control setup time", "ms"), ("retr_data_setup_ms", "Data setup time", "ms"),
           ("retr_throughput_mbps", "Throughput", "Mbit/s")]


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load():
    if not (RES / "raw.csv").exists():
        sys.exit("results/raw.csv not found. Run: sudo python3 tools/run.py experiments")
    return list(csv.DictReader(open(RES / "raw.csv")))


def summarize(rows):
    groups = {}
    for r in rows:
        groups.setdefault((int(r["loss"]), r["nat"], r["mode"]), []).append(r)
    out = []
    for (loss, nat, mode), rs in sorted(groups.items()):
        ok = [r for r in rs if r["retr_ok"] in ("True", "true", "1")]
        d = {"loss": loss, "nat": nat, "mode": mode, "runs": len(rs), "ok": len(ok),
             "failure": next((r["failure_stage"] for r in rs if r["failure_stage"]), "")}
        for key, _, _ in METRICS:
            pool = [r for r in rs if r["control_ok"] in ("True", "true", "1")] if key == "control_setup_ms" else ok
            v = [fnum(r[key]) for r in pool if fnum(r[key]) is not None]
            d[key] = {"n": len(v), "mean": st.mean(v) if v else None, "sd": st.stdev(v) if len(v) > 1 else 0.0 if v else None,
                      "min": min(v) if v else None, "max": max(v) if v else None}
        out.append(d)
    return out


def fmt(m, unit):
    if m["mean"] is None:
        return "failed"
    return f'{m["mean"]:.1f} ± {m["sd"]:.1f} ({m["min"]:.1f}–{m["max"]:.1f})'


def write_tables(summ):
    with open(RES / "summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["loss_pct", "nat", "mode", "runs", "ok"] + [f"{k}_{s}" for k, _, _ in METRICS for s in ("mean", "sd", "min", "max")])
        for d in summ:
            w.writerow([d["loss"], d["nat"], d["mode"], d["runs"], d["ok"]] +
                       [("" if d[k][s] is None else round(d[k][s], 3)) for k, _, _ in METRICS for s in ("mean", "sd", "min", "max")])
    losses = sorted({d["loss"] for d in summ}); md = ["# Results summary", f"_Generated {datetime.datetime.now():%Y-%m-%d %H:%M} from results/raw.csv. Cells: mean ± sd (min–max); failed runs are excluded from means._\n"]
    for key, title, unit in METRICS:
        md += [f"\n## {title} ({unit})\n", "| NAT | Mode | " + " | ".join(f"{l}% loss" for l in losses) + " | success |", "|---|---|" + "---|" * (len(losses) + 1)]
        for nat in sorted({d["nat"] for d in summ}):
            for mode in ("passive", "active"):
                ds = {d["loss"]: d for d in summ if d["nat"] == nat and d["mode"] == mode}
                if ds:
                    md.append(f"| {nat} | {mode} | " + " | ".join(fmt(ds[l][key], unit) if l in ds else "-" for l in losses) +
                              " | " + ", ".join(f'{ds[l]["ok"]}/{ds[l]["runs"]}' for l in losses if l in ds) + " |")
    (RES / "summary.md").write_text("\n".join(md) + "\n")


def charts(summ):
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    except ImportError:
        return
    (RES / "charts").mkdir(exist_ok=True)
    losses = sorted({d["loss"] for d in summ}); combos = sorted({(d["nat"], d["mode"]) for d in summ})
    for key, title, unit in METRICS:
        fig, ax = plt.subplots(figsize=(9, 4.5)); wd = 0.8 / len(combos)
        for i, (nat, mode) in enumerate(combos):
            xs, ys, es = [], [], []
            for j, l in enumerate(losses):
                d = next((d for d in summ if (d["loss"], d["nat"], d["mode"]) == (l, nat, mode)), None)
                if d and d[key]["mean"] is not None:
                    xs.append(j + i * wd); ys.append(d[key]["mean"]); es.append(d[key]["sd"] or 0)
                else:
                    ax.text(j + i * wd, 0, "fail", rotation=90, ha="center", va="bottom", color="crimson", fontsize=8)
            ax.bar(xs, ys, wd * 0.9, yerr=es, capsize=2, label=f"{nat} {mode}")
        ax.set_xticks([j + 0.4 - wd / 2 for j in range(len(losses))]); ax.set_xticklabels([f"{l}% loss" for l in losses])
        ax.set_ylabel(unit); ax.set_title(f"{title} (mean ± sd)"); ax.legend(ncol=3, fontsize=8); fig.tight_layout()
        fig.savefig(RES / "charts" / f"{key}.png", dpi=160); plt.close(fig)


def dashboard(summ):
    matrix = list(csv.DictReader(open(RES / "success_matrix.csv"))) if (RES / "success_matrix.csv").exists() else []
    ct = {p.stem: p.read_text() for p in sorted((RES / "conntrack").glob("*.txt"))}
    nft = {p.stem: p.read_text() for p in sorted((RES / "nft").glob("*.txt"))}
    pcaps = [p.name for p in sorted((RES / "pcap").glob("*.pcapng"))]
    verify = (RES / "verify.txt").read_text() if (RES / "verify.txt").exists() else ""
    data = json.dumps({"summary": summ, "matrix": matrix, "conntrack": ct, "nft": nft, "pcaps": pcaps, "verify": verify,
                       "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}).replace("<", "\\u003c")
    (RES / "dashboard.html").write_text(TEMPLATE.replace("__DATA__", data))


TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FTP through NAT: measured results</title><style>
:root{--bg:#f3f6f9;--sf:#fff;--tx:#14202b;--mu:#5b6b7a;--ln:#d3dce5;--ok:#0b7a5a;--bad:#b3243f}
@media(prefers-color-scheme:dark){:root{--bg:#0f161d;--sf:#17212b;--tx:#e6edf3;--mu:#8fa1b2;--ln:#2a3948;--ok:#4cd2a0;--bad:#ff7d93}}
body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:20px}
.card{background:var(--sf);border:1px solid var(--ln);border-radius:10px;padding:16px;margin-bottom:16px}h1{margin:0 0 4px}h2{margin:0 0 10px;font-size:17px}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid var(--ln);padding:7px;text-align:left}.y{color:var(--ok);font-weight:700}.n{color:var(--bad);font-weight:700}
pre{background:#0e1a24;color:#9fe3c8;padding:10px;border-radius:8px;overflow:auto;font-size:12px;max-height:300px}.mu{color:var(--mu);font-size:13px}svg text{fill:var(--tx);font-size:11px}
select{padding:6px;font:inherit}</style></head><body><main>
<h1>FTP through NAT: measured results</h1><p class="mu" id="gen"></p>
<div class="card"><h2>Success matrix (what worked, what failed, and where)</h2><div style="overflow-x:auto"><table id="mx"></table></div></div>
<div class="card"><h2>Throughput by loss (mean ± sd, failed runs excluded)</h2><div id="c1"></div></div>
<div class="card"><h2>Data setup time by loss</h2><div id="c2"></div></div>
<div class="card"><h2>Control setup time by loss</h2><div id="c3"></div></div>
<div class="card"><h2>NAT state recorded on R1</h2><select id="sel"></select><pre id="ct"></pre><h2>nftables ruleset</h2><select id="sel2"></select><pre id="nf"></pre></div>
<div class="card"><h2>Packet captures</h2><ul id="pc"></ul></div>
<div class="card"><h2>Routing evidence</h2><pre id="vf"></pre></div></main>
<script>
const D=__DATA__,$=s=>document.querySelector(s);$('#gen').textContent='Generated '+D.generated+' from this machine\'s own runs.';
$('#mx').innerHTML=D.matrix.length?'<tr><th>NAT</th><th>Mode</th><th>Control</th><th>LIST</th><th>RETR</th><th>STOR</th><th>Failure point</th></tr>'+D.matrix.map(r=>{const c=v=>`<td class="${v=='yes'?'y':'n'}">${v}</td>`;return `<tr><td>${r.nat}</td><td>${r.mode}</td>${c(r.control_ok)}${c(r.list_ok)}${c(r.retr_ok)}${c(r.stor_ok)}<td>${r.failure_stage}</td></tr>`}).join(''):'<tr><td>Run: sudo python3 tools/run.py matrix</td></tr>';
const pal=['#1f5fbf','#e07b00','#0b7a5a','#b3243f','#7a4bc0','#5b6b7a'];
function chart(id,key,unit){const S=D.summary,L=[...new Set(S.map(d=>d.loss))].sort((a,b)=>a-b),C=[...new Set(S.map(d=>d.nat+' '+d.mode))].sort();
let max=1;S.forEach(d=>{const m=d[key];if(m.mean!=null)max=Math.max(max,m.mean+m.sd)});
const W=900,H=260,gw=W/L.length,bw=(gw-30)/C.length;let s=`<svg viewBox="0 0 ${W} ${H+50}" width="100%">`;
L.forEach((l,i)=>{C.forEach((c,j)=>{const d=S.find(x=>x.loss==l&&x.nat+' '+x.mode==c);const x=i*gw+15+j*bw;
if(d&&d[key].mean!=null){const m=d[key],h=m.mean/max*H,e=m.sd/max*H;s+=`<rect x="${x}" y="${H-h}" width="${bw-3}" height="${h}" fill="${pal[j%6]}"/><line x1="${x+bw/2-1}" x2="${x+bw/2-1}" y1="${H-h-e}" y2="${H-h+e}" stroke="currentColor"/><text x="${x+bw/2-1}" y="${H-h-e-4}" text-anchor="middle">${m.mean.toFixed(1)}</text>`}
else if(d)s+=`<text x="${x+bw/2}" y="${H-6}" text-anchor="middle" fill="#b3243f" font-weight="700">fail</text>`});
s+=`<text x="${i*gw+gw/2}" y="${H+18}" text-anchor="middle">${l}% loss</text>`});
s+=C.map((c,j)=>`<rect x="${10+j*140}" y="${H+30}" width="10" height="10" fill="${pal[j%6]}"/><text x="${24+j*140}" y="${H+39}">${c}</text>`).join('')+`<text x="2" y="10">${unit}</text></svg>`;$(id).innerHTML=s}
chart('#c1','retr_throughput_mbps','Mbit/s');chart('#c2','retr_data_setup_ms','ms');chart('#c3','control_setup_ms','ms');
function fill(sel,out,obj){const k=Object.keys(obj);$(sel).innerHTML=k.map(x=>`<option>${x}</option>`).join('');const f=()=>{$(out).textContent=obj[$(sel).value]||'(none)'};$(sel).onchange=f;f()}
fill('#sel','#ct',D.conntrack);fill('#sel2','#nf',D.nft);
$('#pc').innerHTML=D.pcaps.length?D.pcaps.map(p=>`<li><a href="pcap/${p}">${p}</a></li>`).join(''):'<li>No captures yet. Run: sudo python3 tools/run.py evidence</li>';$('#vf').textContent=D.verify||'(run scripts/verify.sh)';
</script></body></html>"""

if __name__ == "__main__":
    rows = load(); summ = summarize(rows)
    write_tables(summ); charts(summ); dashboard(summ)
    print("wrote results/summary.csv, summary.md, dashboard.html, charts/")
