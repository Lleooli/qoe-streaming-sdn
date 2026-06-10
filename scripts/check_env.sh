#!/usr/bin/env bash
# Verifica pré-requisitos do ambiente WSL para o projeto QoE/SDN
echo "=== user: $(whoami) ==="
sudo -n true 2>/dev/null && echo "sudo: NOPASSWD OK" || echo "sudo: precisa senha"
echo "=== python: $(python3 --version 2>&1) ==="
for t in mn ovs-vsctl ryu-manager osken-manager iperf iperf3 ffmpeg tc ping curl pip3; do
    if command -v "$t" >/dev/null 2>&1; then
        echo "$t: OK ($(command -v $t))"
    else
        echo "$t: AUSENTE"
    fi
done
echo "=== systemd: $(ps -p 1 -o comm=) ==="
echo "=== kernel: $(uname -r) ==="
python3 -c "import matplotlib" 2>/dev/null && echo "matplotlib: OK" || echo "matplotlib: AUSENTE"
python3 -c "import mininet" 2>/dev/null && echo "mininet(python): OK" || echo "mininet(python): AUSENTE"
command -v osken-manager >/dev/null 2>&1 && echo "osken-manager: OK" || echo "osken-manager: AUSENTE"
command -v dos2unix >/dev/null 2>&1 && echo "dos2unix: OK" || echo "dos2unix: AUSENTE"
ls /mnt/c/Users/leona/Downloads/ 2>/dev/null | grep -i "rick" || echo "video: nao achei no Downloads"
