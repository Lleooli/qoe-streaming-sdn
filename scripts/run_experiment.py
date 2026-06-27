#!/usr/bin/env python3
"""
Orquestrador dos experimentos QoE/SDN (executar como root dentro do WSL).

Para cada cenario:
  1. Inicia controlador SDN (os-ken simple_switch_13, OpenFlow 1.3).
  2. Constroi a topologia no Mininet (gargalo s1<->s2 configurado pelo cenario).
  3. Sobe servidor DASH em srv e mede rede (ping + iperf3) antes do streaming.
  4. Dispara trafego concorrente (se o cenario pedir) e 3 clientes DASH.
  5. Salva metricas de rede e QoE em results/<cenario>/.

Uso:
  python3 scripts/run_experiment.py --scenario baseline
  python3 scripts/run_experiment.py --all
"""

import argparse
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.clean import cleanup

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
VIDEO_DIR = os.path.join(ROOT, 'video', 'dash')
CLIENT = os.path.join(ROOT, 'streaming', 'dash_client.py')
SERVER = os.path.join(ROOT, 'streaming', 'dash_server.py')
CONTROLLER_APP = os.path.join(ROOT, 'controller', 'qoe_controller.py')
RESULTS = os.path.join(ROOT, 'results')

SRV_IP = '10.0.0.1'
PORT = 8080
STREAM_TIMEOUT = 240          # limite de parede por cliente (s)

# Cenarios da Etapa 2 — parametros aplicados ao gargalo s1<->s2.
# 'delay' e aplicado em cada sentido (RTT ~= 2x delay).
SCENARIOS = {
    'baseline':    {'bw': 10},
    'banda':       {'bw': 3},
    'atraso':      {'bw': 10, 'delay': '50ms', 'jitter': '20ms'},
    'perda':       {'bw': 10, 'loss': 3},
    'concorrente': {'bw': 10, 'cross': '8M'},
    # Etapa 3: mesmo cenario concorrente, com deteccao + mitigacao no
    # controlador SDN (rate-limit do fluxo UDP via OpenFlow meter).
    'concorrente_controle': {'bw': 10, 'cross': '8M', 'mitigation': True},
}


def wait_port(port, host='127.0.0.1', timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(1)
            try:
                s.connect((host, port))
                return True
            except OSError:
                time.sleep(0.3)
    return False


def start_controller(logdir, mitigation=False):
    log = open(os.path.join(logdir, 'controller.log'), 'w')
    env = dict(os.environ)
    if mitigation:
        env['QOE_MITIGATION'] = 'on'
        env['QOE_DECISION_LOG'] = os.path.join(logdir, 'decisions.log')
    proc = subprocess.Popen(
        ['osken-manager', CONTROLLER_APP,
         '--ofp-tcp-listen-port', '6653'],
        stdout=log, stderr=subprocess.STDOUT, env=env)
    if not wait_port(6653):
        proc.terminate()
        raise RuntimeError('controlador nao abriu porta 6653')
    return proc


def build_net(params):
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink,
                  autoSetMacs=True, waitConnected=True)
    net.addController('c0', controller=RemoteController,
                      ip='127.0.0.1', port=6653)
    s1 = net.addSwitch('s1', protocols='OpenFlow13')
    s2 = net.addSwitch('s2', protocols='OpenFlow13')
    hosts = {}
    for name, ip, sw in (('srv', '10.0.0.1', s1), ('txg', '10.0.0.2', s1),
                         ('c1', '10.0.0.11', s2), ('c2', '10.0.0.12', s2),
                         ('c3', '10.0.0.13', s2), ('rxg', '10.0.0.14', s2)):
        h = net.addHost(name, ip=ip + '/24')
        net.addLink(h, sw, bw=100)
        hosts[name] = h
    # gargalo com parametros do cenario
    link_kw = {'bw': params.get('bw', 10)}
    if 'delay' in params:
        link_kw['delay'] = params['delay']
    if 'jitter' in params:
        link_kw['jitter'] = params['jitter']
    if 'loss' in params:
        link_kw['loss'] = params['loss']
    net.addLink(s1, s2, **link_kw)
    net.start()
    return net, hosts


def pre_metrics(hosts, outdir):
    """ping (RTT/perda) e iperf3 (capacidade) antes do streaming."""
    c1, srv = hosts['c1'], hosts['srv']
    ping_out = c1.cmd(f'ping -c 10 -i 0.2 {SRV_IP}')
    with open(os.path.join(outdir, 'ping_pre.txt'), 'w') as f:
        f.write(ping_out)
    srv.cmd('iperf3 -s -D --logfile /dev/null')
    time.sleep(1)
    iperf_out = c1.cmd(f'iperf3 -c {SRV_IP} -t 5 -J')
    srv.cmd('pkill -f "iperf3 -s" || true')
    with open(os.path.join(outdir, 'iperf_pre.json'), 'w') as f:
        f.write(iperf_out)
    return ping_out, iperf_out


def parse_ping(text):
    m = re.search(r'(\d+(?:\.\d+)?)% packet loss', text)
    loss = float(m.group(1)) if m else None
    m = re.search(r'rtt [^=]+= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)', text)
    rtt = {'min': float(m.group(1)), 'avg': float(m.group(2)),
           'max': float(m.group(3)), 'mdev': float(m.group(4))} if m else None
    return {'loss_pct': loss, 'rtt_ms': rtt}


def parse_ping_during(text):
    """RTT e perda a partir do log de ping continuo.

    Perda = sequencias ausentes: respostas recebidas vs maior icmp_seq
    (ping morto com SIGTERM nao imprime o sumario)."""
    rtts = [float(m) for m in re.findall(r'time=([\d.]+)', text)]
    seqs = [int(m) for m in re.findall(r'icmp_seq=(\d+)', text)]
    sent = max(seqs) if seqs else 0
    return {
        'rtt_avg_ms': round(sum(rtts) / len(rtts), 2) if rtts else None,
        'rtt_max_ms': max(rtts) if rtts else None,
        'ping_loss_pct': round(100 * (1 - len(seqs) / sent), 2)
        if sent else None,
        'samples': len(rtts),
    }


def parse_iperf(text):
    try:
        data = json.loads(text)
        bps = data['end']['sum_received']['bits_per_second']
        return {'throughput_mbps': round(bps / 1e6, 3)}
    except Exception:
        return {'throughput_mbps': None}


def run_scenario(name, params, duration):
    outdir = os.path.join(RESULTS, name)
    os.makedirs(outdir, exist_ok=True)
    print(f'=== Cenario: {name} {params} ===')

    cleanup()
    ctl = start_controller(outdir, mitigation=params.get('mitigation', False))
    net = None
    try:
        net = build_net(params)
        net, hosts = net
        srv, c1 = hosts['srv'], hosts['c1']

        # conectividade + popular tabelas de fluxo
        loss = net.pingAll(timeout='2')
        print(f'pingAll: {loss}% perda')

        # servidor DASH
        srv_log = os.path.join(outdir, 'server.log')
        srv.cmd(f'python3 {shlex.quote(SERVER)} --dir {shlex.quote(VIDEO_DIR)}'
                f' --port {PORT} --log {shlex.quote(srv_log)}'
                f' > /dev/null 2>&1 &')
        time.sleep(1)

        # metricas pre-streaming
        ping_out, iperf_out = pre_metrics(hosts, outdir)
        net_metrics = {'scenario': name, 'params': params,
                       'pre': {**parse_ping(ping_out), **parse_iperf(iperf_out)}}
        print(f"pre: {net_metrics['pre']}")

        # ping continuo durante o streaming
        ping_log = open(os.path.join(outdir, 'ping_during.txt'), 'w')
        pinger = c1.popen(['ping', '-i', '0.5', SRV_IP],
                          stdout=ping_log, stderr=subprocess.STDOUT)

        # trafego concorrente
        if 'cross' in params:
            hosts['rxg'].cmd('iperf3 -s -D --logfile /dev/null')
            time.sleep(1)
            hosts['txg'].cmd(
                f'iperf3 -c 10.0.0.14 -u -b {params["cross"]} '
                f'-t {duration + 60} > {shlex.quote(outdir)}/iperf_cross.txt '
                f'2>&1 &')

        # clientes DASH
        procs = []
        for cname in ('c1', 'c2', 'c3'):
            cmd = ['python3', CLIENT,
                   '--url', f'http://{SRV_IP}:{PORT}/manifest.mpd',
                   '--out', outdir, '--name', cname,
                   '--duration', str(STREAM_TIMEOUT)]
            procs.append((cname, hosts[cname].popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)))
        for cname, p in procs:
            try:
                out, _ = p.communicate(timeout=STREAM_TIMEOUT + 30)
                print(f'{cname}: {out.decode().strip().splitlines()[-1]}')
            except subprocess.TimeoutExpired:
                p.kill()
                print(f'{cname}: TIMEOUT')

        # encerra medicoes
        pinger.terminate()
        ping_log.close()
        with open(os.path.join(outdir, 'ping_during.txt')) as f:
            during = f.read()
        net_metrics['during'] = parse_ping_during(during)
        with open(os.path.join(outdir, 'net_metrics.json'), 'w') as f:
            json.dump(net_metrics, f, indent=1)
        print(f"during: {net_metrics['during']}")
    finally:
        if net:
            net.stop()
        ctl.terminate()
        cleanup()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenario', choices=SCENARIOS.keys())
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--duration', type=int, default=90,
                    help='duracao prevista do streaming (p/ trafego cross)')
    args = ap.parse_args()

    if not os.path.exists(os.path.join(VIDEO_DIR, 'manifest.mpd')):
        sys.exit('Conteudo DASH ausente. Rode: bash video/generate_video.sh')

    names = list(SCENARIOS) if args.all else [args.scenario]
    if not names or names == [None]:
        sys.exit('Informe --scenario <nome> ou --all')
    for n in names:
        run_scenario(n, SCENARIOS[n], args.duration)
    print('Concluido. Resultados em results/')


if __name__ == '__main__':
    main()
