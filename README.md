# Melhoria da QoE em Streaming de Vídeo com Mininet, SDN e P4

Projeto final de Programabilidade de Redes — Etapas 1 a 3.

Detecta e caracteriza degradação de QoE em streaming DASH sobre uma rede
emulada (Mininet + controlador SDN os-ken/Ryu, OpenFlow 1.3) e, na Etapa 3,
**mitiga** a degradação programando regras OpenFlow dinamicamente no
controlador (rate-limit do fluxo concorrente via meter).

## Topologia

```
   srv ──┐                       ┌── c1
          ├── s1 ═══════════ s2 ─┼── c2
   txg ──┘     (gargalo 10M)     ├── c3
                                 └── rxg
```

| Nó | IP | Papel |
|---|---|---|
| srv | 10.0.0.1 | servidor de vídeo DASH (HTTP, porta 8080) |
| txg | 10.0.0.2 | gerador de tráfego concorrente (iperf3) |
| c1–c3 | 10.0.0.11–13 | clientes de vídeo instrumentados |
| rxg | 10.0.0.14 | receptor do tráfego concorrente |
| s1, s2 | — | switches OpenFlow 1.3 (OVS), controlador remoto |

Links de borda: 100 Mbps. Link s1↔s2: gargalo de 10 Mbps onde os cenários
de degradação são aplicados.

## Estrutura

```
controller/qoe_controller.py   controlador SDN (os-ken, learning switch + telemetria)
topology/qoe_topo.py           topologia p/ uso interativo (mn --custom)
video/generate_video.sh        codifica vídeo fonte em DASH (240p/360p/720p, seg. 2 s)
streaming/dash_server.py       servidor HTTP do conteúdo
streaming/dash_client.py       cliente DASH com ABR + métricas de QoE
scripts/run_experiment.py      orquestrador dos cenários (Mininet API)
scripts/plot_results.py        gráficos e tabela comparativa
scripts/check_env.sh           verificação do ambiente
results/<cenário>/             saídas (JSON de QoE, ping, iperf, logs)
relatorio/                     relatórios das etapas
```

## Pré-requisitos

WSL2 Ubuntu 24.04 (ou Linux nativo). Instalação:

```bash
wsl -d Ubuntu-24.04 -u root -- make -C "/mnt/c/.../Projeto programabilidade de redes" setup
```

Pacotes: `mininet openvswitch-switch iperf iperf3 ffmpeg python3-matplotlib python3-os-ken`.

> Nota: usa-se **os-ken** (fork mantido do Ryu pela OpenStack; mesma API).
> O Ryu original não roda em Python ≥ 3.10.

## Reprodução

```bash
# dentro do WSL, como root, na raiz do projeto
make check        # verifica ambiente
make video        # gera conteúdo DASH (usa vídeo fonte real; fallback sintético)
make baseline     # Etapa 1 — ambiente estável
make cenarios     # Etapa 2 — banda, atraso, perda, concorrente
make controle     # Etapa 3 — concorrente com controle SDN (mitigação)
make plots        # gráficos em results/plots/
```

Ou tudo de uma vez: `make all`.

Uso interativo da topologia:

```bash
osken-manager controller/qoe_controller.py --ofp-tcp-listen-port 6653 &
mn --custom topology/qoe_topo.py --topo qoe --controller remote,port=6653 \
   --switch ovs,protocols=OpenFlow13 --link tc
```

## Cenários (Etapa 2)

| Cenário | Impairment no gargalo s1↔s2 |
|---|---|
| baseline | nenhum (10 Mbps) |
| banda | limitação a 3 Mbps |
| atraso | 50 ms + jitter 20 ms por sentido (RTT ≈ 100 ms) |
| perda | 3% de perda de pacotes |
| concorrente | UDP 8 Mbps (txg→rxg) disputando o gargalo |

## Controle SDN (Etapa 3)

O controlador detecta a saturação do gargalo pela telemetria de portas
(vazão > 85% da capacidade por 2 janelas) e mitiga programando, na tabela 0
do pipeline OpenFlow, um rate-limit (meter de 2 Mbps) sobre o tráfego UDP
concorrente — priorizando o vídeo TCP. As decisões ficam em
`results/concorrente_controle/decisions.log`. No cenário concorrente o controle
recupera o bitrate de 436 → 1336 kbps (+206%).

## Métricas

- **Rede**: RTT/perda (ping antes e durante o streaming), capacidade TCP (iperf3).
- **QoE**: tempo de início (startup), nº e duração de stalls (rebuffering),
  bitrate médio reproduzido, nº de trocas de qualidade (ABR).

Relatórios: `relatorio/etapa1.md`, `relatorio/etapa2.md` e
`relatorio/etapa3.md` (Etapa 3 também em `relatorio/relatorio_etapa3.pdf`).
