#!/usr/bin/env bash
# Configures and starts vsftpd inside the ftp-server namespace (control 21, passive 40000-40100, Active allowed).
set -euo pipefail
source "$(dirname "$0")/lib.sh"; need_root
command -v vsftpd >/dev/null || { echo "Install vsftpd first (see README)."; exit 1; }
id ftpuser >/dev/null 2>&1 || useradd -m -s /bin/bash ftpuser
echo 'ftpuser:ftppass' | chpasswd
mkdir -p /srv/ftp-lab /var/run/vsftpd/empty
[ -f /srv/ftp-lab/10MB.bin ] || dd if=/dev/urandom of=/srv/ftp-lab/10MB.bin bs=1M count=10 status=none
chown -R ftpuser:ftpuser /srv/ftp-lab
cat > /etc/vsftpd-lab.conf <<CONF
listen=YES
listen_ipv6=NO
listen_address=172.16.20.10
anonymous_enable=NO
local_enable=YES
write_enable=YES
local_umask=022
local_root=/srv/ftp-lab
connect_from_port_20=YES
port_enable=YES
pasv_enable=YES
pasv_min_port=40000
pasv_max_port=40100
pasv_address=172.16.20.10
connect_timeout=8
accept_timeout=8
data_connection_timeout=30
idle_session_timeout=300
xferlog_enable=YES
vsftpd_log_file=/tmp/vsftpd-lab.log
secure_chroot_dir=/var/run/vsftpd/empty
pam_service_name=vsftpd
seccomp_sandbox=NO
ssl_enable=NO
CONF
[ -f /tmp/cn-vsftpd.pid ] && kill "$(cat /tmp/cn-vsftpd.pid)" 2>/dev/null || true
nsx $NS_S setsid vsftpd /etc/vsftpd-lab.conf >/tmp/vsftpd-start.log 2>&1 &
echo $! > /tmp/cn-vsftpd.pid
sleep 1
nsx $NS_S ss -ltn | grep -q ':21 ' && echo "vsftpd listening on 172.16.20.10:21 (user ftpuser / ftppass)" || { echo "vsftpd failed, see /tmp/vsftpd-start.log"; exit 1; }
