# Technical report template (target 6-10 pages)
Fill every [..] from YOUR runs. Do not copy expectations in as results.

1. **Introduction (0.5 p)**: why FTP is awkward for NAT; objectives (from the proposal).
2. **Background (1 p)**: control vs data connection; Active (PORT, server opens) vs Passive (PASV, client opens); NAT/PAT, conntrack, expectations and helpers.
3. **Architecture (1 p)**: `docs/topology.svg`, addressing table, routing tables and traceroute (`results/verify.txt`), N0/N1/N2 rulesets (`results/nft/`), tc settings.
4. **Implementation (1 p)**: scripts, vsftpd settings (passive range, Active allowed), clients, how a run works, timing definitions.
5. **POC and packet analysis (2 p)**: figures 1-8 from `docs/SCREENSHOT_GUIDE.md`, one short paragraph each: what is sent, by whom, what NAT did.
6. **Results (2 p)**: success matrix (`results/success_matrix.csv`); conntrack entries for control vs data, Active vs Passive (`results/conntrack/`); setup-time and throughput tables for 0/2/5 % loss with mean, sd, range, n (`results/summary.md`, charts).
7. **Discussion (1 p)**: was each expectation from the proposal confirmed or contradicted? Why (cite packets/conntrack)? Effect of loss on control vs data. Threats to validity: veth is not a real WAN, one machine, loss applied symmetrically, small n, vsftpd defaults.
8. **Conclusion and limits (0.5 p)**: limits of NAT with FTP; what real deployments do (FTP helpers, passive-only, FTPS/SFTP).
9. **Reproducibility**: point to README; list software versions.
10. **AI-use disclosure**: `docs/AI_DISCLOSURE.md`.
Appendix: file list of pcapng traces, raw.csv.
