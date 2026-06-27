# Etapa 3 — Implementação do Controle via SDN

## Objetivo

Detectar a degradação de QoE em tempo de execução no controlador SDN e
mitigá-la programando regras OpenFlow dinamicamente. O alvo é o cenário
**concorrente** (Etapa 2), o de pior QoE: um fluxo UDP de 8 Mbps (txg→rxg) sem
controle de congestionamento ocupa o gargalo de 10 Mbps e derruba o bitrate do
vídeo de 2241 kbps (baseline) para 436 kbps (−81%).

## Arquitetura do controle

O controlador (`controller/qoe_controller.py`, os-ken / OpenFlow 1.3) passa a
usar um pipeline de **duas tabelas**:

- **Tabela 0 — classificação/policiamento.** Por padrão encaminha para a tabela
  1 (`GotoTable(1)`). É nela que a mitigação instala regras de alta prioridade.
- **Tabela 1 — learning switch L2.** Lógica das Etapas 1–2 (regras reativas por
  `(in_port, eth_dst)`; table-miss → controlador).

A telemetria de portas (já coletada a cada 5 s) alimenta a detecção.

## Detecção de degradação

A cada janela de 5 s o controlador calcula a vazão de cada porta a partir do
delta de `tx_bytes`. Considera o gargalo **saturado** quando a porta de maior
vazão de `s1` ultrapassa **85% da capacidade** (8,5 Mbps de 10 Mbps). Para
evitar disparo por rajada, exige-se a condição sustentada por **2 janelas
consecutivas** (~10 s). Confirmada a saturação, dispara-se a mitigação; quando
a utilização cai e se mantém baixa por 2 janelas, a restrição é removida.

A detecção fica restrita ao cenário com controle ativo (variável de ambiente
`QOE_MITIGATION=on`), de modo que os cenários das Etapas 1–2 permanecem
inalterados.

## Mitigação (rate-limit via OpenFlow meter)

Classificação dos fluxos: o **vídeo é TCP** (porta 8080) e o **tráfego
concorrente é UDP** (iperf3). Ao detectar saturação, o controlador:

1. cria um **meter** OpenFlow 1.3 de rate-limit (`OFPMeterMod`, banda
   `DROP` a 2000 kbps);
2. instala na tabela 0 uma regra de prioridade 100 casando `eth_type=IPv4,
   ip_proto=UDP` com as instruções `Meter(1)` + `GotoTable(1)`.

Assim o fluxo UDP é limitado a 2 Mbps no gargalo e o vídeo TCP recupera a banda
restante. Há um modo alternativo de **descarte** (`QOE_MODE=drop`) que derruba o
fluxo concorrente; o padrão é o rate-limit, menos agressivo.

## Logs de decisão

As decisões são registradas no `controller.log` (prefixo `DECISION`) e em
`results/concorrente_controle/decisions.log`:

```
22:16:03  degradacao detectada em dpid=1 porta=3: utilizacao 100% do gargalo (9.96 Mbps) por 2 janelas
22:16:03  mitigacao: rate-limit do trafego UDP concorrente a 2000 kbps (meter 1, tabela 0) em dpid=1 — prioriza o video TCP no gargalo
```

A detecção ocorre na porta 3 de `s1` (uplink s1→s2), exatamente o gargalo.

## Resultados — baseline vs. concorrente vs. controle

Média dos três clientes:

| condição | bitrate (kbps) | startup (s) | t. parado (s) | trocas | RTT durante (ms) |
|---|---|---|---|---|---|
| baseline (referência) | 2241 | 0,23 | 0,00 | 1,7 | 21,5 |
| concorrente (sem controle) | 436 | 0,54 | 0,30 | 3,0 | 57,1 |
| **concorrente (com controle)** | **1336** | 0,53 | 0,89 | 4,0 | 44,1 |

O controle **triplica o bitrate** reproduzido (436 → 1336 kbps, **+206%**),
recuperando ~60% do baseline, e reduz o RTT durante o streaming (57 → 44 ms). A
figura da linha do tempo (`results/plots/control_timeline.png`) mostra o cliente
preso em 300 kbps até ~15 s e, logo após a decisão do controlador, subindo para
2400 kbps.

**Trade-off honesto:** o tempo de rebuffering sobe levemente (0,30 → 0,89 s) e há
uma troca de qualidade a mais. O salto abrupto de qualidade quando a banda é
liberada provoca um breve reajuste do buffer em 2 dos 3 clientes — efeito
transitório, compensado pela melhora expressiva e sustentada da qualidade visual.

Figuras geradas por `scripts/plot_control.py`:
`results/plots/control_qoe.png` e `results/plots/control_timeline.png`.

## Reprodução

```bash
# dentro do WSL, como root, na raiz do projeto
sudo make controle   # roda o cenário concorrente_controle + gera as figuras
```

Equivale a `python3 scripts/run_experiment.py --scenario concorrente_controle`
seguido de `plot_results.py` e `plot_control.py`.
