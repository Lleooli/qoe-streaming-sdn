#!/usr/bin/env python3
"""
Gera graficos comparando os cenarios (Etapa 2).

Le results/<cenario>/qoe_c*.json e net_metrics.json e produz em
results/plots/:
  - qoe_startup.png, qoe_stalls.png, qoe_bitrate.png  (metricas de QoE)
  - net_rtt.png, net_throughput.png                   (metricas de rede)
  - bitrate_timeline.png                              (bitrate ao longo do tempo, c1)
  - summary.csv / summary.md                          (tabela consolidada)
"""

import csv
import glob
import json
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
RESULTS = os.path.join(ROOT, 'results')
PLOTS = os.path.join(RESULTS, 'plots')
ORDER = ['baseline', 'banda', 'atraso', 'perda', 'concorrente',
         'concorrente_controle']
COLOR = {'baseline': '#4c9f70', 'banda': '#d1495b', 'atraso': '#edae49',
         'perda': '#00798c', 'concorrente': '#6a4c93',
         'concorrente_controle': '#2a9d8f'}


def load():
    data = {}
    for sc in ORDER:
        d = os.path.join(RESULTS, sc)
        files = sorted(glob.glob(os.path.join(d, 'qoe_c*.json')))
        if not files:
            continue
        clients = [json.load(open(f)) for f in files]
        net = {}
        nm = os.path.join(d, 'net_metrics.json')
        if os.path.exists(nm):
            net = json.load(open(nm))
        data[sc] = {'clients': clients, 'net': net}
    return data


def avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else 0


def bar(ax, labels, values, title, ylabel):
    colors = [COLOR.get(l, '#888') for l in labels]
    ax.bar(labels, values, color=colors)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(axis='y', alpha=0.3)
    for i, v in enumerate(values):
        ax.text(i, v, f'{v:.2f}' if isinstance(v, float) else str(v),
                ha='center', va='bottom', fontsize=9)


def main():
    os.makedirs(PLOTS, exist_ok=True)
    data = load()
    if not data:
        raise SystemExit('Nenhum resultado em results/. Rode os experimentos.')
    scs = [s for s in ORDER if s in data]

    metrics = {}
    for sc in scs:
        cl = [c['summary'] for c in data[sc]['clients']]
        net = data[sc]['net']
        metrics[sc] = {
            'startup_s': avg([c['startup_time_s'] for c in cl]),
            'stalls': avg([c['stalls'] for c in cl]),
            'stall_time_s': avg([c['stall_time_s'] for c in cl]),
            'bitrate_kbps': avg([c['avg_bitrate_bps'] for c in cl]) / 1000,
            'switches': avg([c['switches'] for c in cl]),
            'thr_mbps': avg([c['avg_throughput_bps'] for c in cl]) / 1e6,
            'rtt_ms': (net.get('during', {}) or {}).get('rtt_avg_ms'),
            'ping_loss_pct': (net.get('during', {}) or {}).get('ping_loss_pct'),
            'iperf_mbps': (net.get('pre', {}) or {}).get('throughput_mbps'),
        }

    # --- graficos de QoE ---
    for key, title, ylabel, fname in (
        ('startup_s', 'Tempo de inicio (startup)', 'segundos', 'qoe_startup.png'),
        ('stall_time_s', 'Tempo total de rebuffering', 'segundos', 'qoe_stalls.png'),
        ('bitrate_kbps', 'Bitrate medio reproduzido', 'kbps', 'qoe_bitrate.png'),
        ('switches', 'Trocas de qualidade (ABR)', 'trocas', 'qoe_switches.png'),
    ):
        fig, ax = plt.subplots(figsize=(7, 4))
        bar(ax, scs, [round(metrics[s][key], 2) for s in scs], title, ylabel)
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS, fname), dpi=120)
        plt.close(fig)

    # --- graficos de rede ---
    for key, title, ylabel, fname in (
        ('rtt_ms', 'RTT medio durante streaming (ping c1->srv)', 'ms', 'net_rtt.png'),
        ('iperf_mbps', 'Capacidade TCP pre-streaming (iperf3 c1->srv)', 'Mbps',
         'net_throughput.png'),
        ('ping_loss_pct', 'Perda ICMP durante streaming', '%', 'net_loss.png'),
    ):
        vals = [metrics[s][key] or 0 for s in scs]
        fig, ax = plt.subplots(figsize=(7, 4))
        bar(ax, scs, [round(v, 2) for v in vals], title, ylabel)
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS, fname), dpi=120)
        plt.close(fig)

    # --- timeline de bitrate (cliente c1 de cada cenario) ---
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for sc in scs:
        c1 = data[sc]['clients'][0]
        segs = [s for s in c1['segments'] if 'bitrate' in s]
        ax.plot([s['t'] for s in segs], [s['bitrate'] / 1000 for s in segs],
                marker='.', label=sc, color=COLOR.get(sc))
    ax.set_xlabel('tempo (s)')
    ax.set_ylabel('bitrate do segmento (kbps)')
    ax.set_title('Adaptacao de bitrate ao longo do tempo (cliente c1)')
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, 'bitrate_timeline.png'), dpi=120)
    plt.close(fig)

    # --- tabela consolidada ---
    cols = ['startup_s', 'stalls', 'stall_time_s', 'bitrate_kbps', 'switches',
            'thr_mbps', 'rtt_ms', 'ping_loss_pct', 'iperf_mbps']
    with open(os.path.join(PLOTS, 'summary.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['cenario'] + cols)
        for sc in scs:
            w.writerow([sc] + [round(metrics[sc][c], 3)
                               if metrics[sc][c] is not None else ''
                               for c in cols])
    with open(os.path.join(PLOTS, 'summary.md'), 'w') as f:
        f.write('| cenario | ' + ' | '.join(cols) + ' |\n')
        f.write('|' + '---|' * (len(cols) + 1) + '\n')
        for sc in scs:
            f.write('| ' + sc + ' | ' +
                    ' | '.join(str(round(metrics[sc][c], 3))
                               if metrics[sc][c] is not None else '-'
                               for c in cols) + ' |\n')

    print(f'Graficos e tabelas gerados em {PLOTS}')
    for sc in scs:
        print(sc, metrics[sc])


if __name__ == '__main__':
    main()
