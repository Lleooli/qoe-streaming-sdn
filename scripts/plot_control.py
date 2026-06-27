#!/usr/bin/env python3
"""
Graficos da Etapa 3 — efeito do controle SDN no cenario concorrente.

Compara tres condicoes:
  - baseline              (referencia, sem disputa de banda)
  - concorrente           (degradado, UDP 8 Mbps, SEM controle)
  - concorrente_controle  (UDP 8 Mbps, COM deteccao + mitigacao no controlador)

Saidas em results/plots/:
  - control_qoe.png         barras das metricas de QoE (3 condicoes)
  - control_timeline.png    bitrate do cliente c1 ao longo do tempo
"""

import glob
import json
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
RESULTS = os.path.join(ROOT, 'results')
PLOTS = os.path.join(RESULTS, 'plots')

CONDS = ['baseline', 'concorrente', 'concorrente_controle']
LABEL = {'baseline': 'baseline\n(referencia)',
         'concorrente': 'concorrente\n(sem controle)',
         'concorrente_controle': 'concorrente\n(com controle)'}
COLOR = {'baseline': '#4c9f70', 'concorrente': '#6a4c93',
         'concorrente_controle': '#2a9d8f'}


def load(sc):
    d = os.path.join(RESULTS, sc)
    files = sorted(glob.glob(os.path.join(d, 'qoe_c*.json')))
    return [json.load(open(f)) for f in files] if files else None


def avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else 0


def main():
    os.makedirs(PLOTS, exist_ok=True)
    data = {sc: load(sc) for sc in CONDS}
    conds = [sc for sc in CONDS if data.get(sc)]
    if 'concorrente_controle' not in conds:
        raise SystemExit('Rode antes: run_experiment.py --scenario '
                         'concorrente_controle')

    metrics = {}
    for sc in conds:
        cl = [c['summary'] for c in data[sc]]
        metrics[sc] = {
            'bitrate_kbps': avg([c['avg_bitrate_bps'] for c in cl]) / 1000,
            'stall_time_s': avg([c['stall_time_s'] for c in cl]),
            'startup_s': avg([c['startup_time_s'] for c in cl]),
            'switches': avg([c['switches'] for c in cl]),
        }

    # --- barras de QoE (4 metricas x condicoes) ---
    panels = [
        ('bitrate_kbps', 'Bitrate medio reproduzido', 'kbps'),
        ('stall_time_s', 'Tempo de rebuffering', 's'),
        ('startup_s', 'Tempo de inicio', 's'),
        ('switches', 'Trocas de qualidade', 'trocas'),
    ]
    fig, axes = plt.subplots(1, 4, figsize=(15, 4))
    for ax, (key, title, ylabel) in zip(axes, panels):
        labels = [LABEL[s] for s in conds]
        vals = [round(metrics[s][key], 2) for s in conds]
        ax.bar(labels, vals, color=[COLOR[s] for s in conds])
        ax.set_title(title, fontsize=10)
        ax.set_ylabel(ylabel)
        ax.grid(axis='y', alpha=0.3)
        ax.tick_params(axis='x', labelsize=8)
        for i, v in enumerate(vals):
            ax.text(i, v, f'{v:.2f}', ha='center', va='bottom', fontsize=8)
    fig.suptitle('Etapa 3 — QoE no cenario concorrente: efeito do controle SDN',
                 fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(os.path.join(PLOTS, 'control_qoe.png'), dpi=120)
    plt.close(fig)

    # --- timeline de bitrate do cliente c1 ---
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for sc in conds:
        c1 = data[sc][0]
        segs = [s for s in c1['segments'] if 'bitrate' in s]
        ax.plot([s['t'] for s in segs], [s['bitrate'] / 1000 for s in segs],
                marker='.', label=LABEL[sc].replace('\n', ' '),
                color=COLOR[sc])
    ax.set_xlabel('tempo (s)')
    ax.set_ylabel('bitrate do segmento (kbps)')
    ax.set_title('Etapa 3 — adaptacao de bitrate (cliente c1)')
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, 'control_timeline.png'), dpi=120)
    plt.close(fig)

    print('Graficos da Etapa 3 em', PLOTS)
    for sc in conds:
        print(sc, {k: round(v, 2) for k, v in metrics[sc].items()})


if __name__ == '__main__':
    main()
