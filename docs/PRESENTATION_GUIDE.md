# Presenting this so it lands with the instructor

## Principle
Instructors grade evidence and understanding, not volume. Show that every claim is backed by a packet, a table row or a conntrack entry, and that you can explain it. Report a result that contradicts the proposal as a finding; that scores better than forcing a match.

## Package (what to hand in / show)
1. GitHub-style folder or zip with README (reproducible in minutes).
2. `results/dashboard.html`: success matrix, charts with error bars, conntrack viewer, links to every pcapng. Generated from your data.
3. `presentation/ftp-nat-lab.html`: use it for the first 2 minutes to explain WHY, then switch to real evidence. Say clearly it is a simulation.
4. Annotated Wireshark figures (`docs/SCREENSHOT_GUIDE.md`) in the report and slides.
5. Report PDF (6-10 pages) built from `docs/REPORT_TEMPLATE.md`.

## 10-minute live demo script
1. (1 min) Problem in one sentence: "NAT rewrites headers, but FTP puts addresses in the payload."
2. (1 min) Topology: show `docs/topology.svg`, then `scripts/verify.sh` output (routes, traceroute).
3. (2 min) Passive N1 live: `sudo scripts/poc.sh passive N1`. Point out conntrack entries: only outbound connections.
4. (2 min) Active N1 live: `sudo scripts/poc.sh active N1`. Wait for the 425. Open the saved capture: PORT payload still 192.168.10.2, server SYN retransmitting. Say: "control works, data connection fails."
5. (1 min) Active N2: expectation entry in `conntrack -L expect`; PORT rewritten inside vs outside capture.
6. (2 min) Dashboard: success matrix, then loss charts. Explain one surprising number with a capture (retransmissions).
7. (1 min) Conclusion + limitations + reproducibility + AI disclosure.

## Make it look professional
- Rehearse with `sudo scripts/teardown.sh` then full rebuild; time it. Keep a pre-recorded terminal capture (`script`/asciinema) as backup.
- Pre-open Wireshark with the pcapng files and filters from the screenshot guide.
- Use consistent names N0/N1/N2 and Active/Passive everywhere; same colors in slides and charts.
- One slide per objective, each ending with evidence ("see Fig. 4").
- Every table has n, mean, sd and range; say failed runs are excluded.
- Split speaking by the proposal's roles (client/measurement/topology) and let each member explain their own part's code.
- Prepare for questions: why does Passive survive masquerade? what does the helper actually rewrite? why is loss on the control connection visible as setup delay? what are the limits of veth/netns versus a real network?
- State limitations yourselves before they are asked.
