#!/usr/bin/env python3
"""Cross-check client using Python's ftplib (set_pasv True/False).
Usage: ip netns exec ftp-client python3 client/ftplib_client.py passive|active"""
import sys, time
from ftplib import FTP
mode = sys.argv[1] if len(sys.argv) > 1 else "passive"
f = FTP(timeout=20); t0 = time.monotonic()
f.connect("172.16.20.10", 21); f.login("ftpuser", "ftppass")
f.set_pasv(mode == "passive")
print("login ok in %.1f ms" % ((time.monotonic() - t0) * 1000))
f.retrlines("LIST")
t = time.monotonic(); n = 0
def cb(b):
    global n; n += len(b)
f.retrbinary("RETR 10MB.bin", cb)
d = time.monotonic() - t
print("RETR %d bytes in %.2f s = %.2f Mbit/s" % (n, d, n * 8 / d / 1e6)); f.quit()
