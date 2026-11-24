# Live Classroom Demonstration

1. Start the Flask application on Ubuntu as described in the repository README; it creates missing namespaces and starts vsftpd automatically.
2. Open `http://127.0.0.1:5000`. Point out the Client → R1 → R2 → Server topology.
3. Select N0 + Active + RETR and run the transfer. Show the FTP transcript and measured result. Download the current run's PCAPNG.
4. Select N1 + Active + RETR. Show any `PORT` rejection or failed data connection, then download the capture regardless of FTP success.
5. Select N1 + Passive + RETR to demonstrate client-initiated data traffic.
6. Select N2 + Active + RETR and show the helper's effect, comparing its downloaded PCAPNG with N1 in Wireshark.
7. Demonstrate the 0/2/5% loss selector if time allows.

The web application deliberately has no diagnostics, batch-processing, teardown, or capture-history pages. Command-line scripts remain available for advanced evidence collection and recovery. The three router-interface captures are merged into one PCAPNG per web experiment; Wireshark identifies the capture interface for each packet.
