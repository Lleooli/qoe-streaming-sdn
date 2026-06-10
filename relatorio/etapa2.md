# Etapa 2 — Indução de Degradação e Caracterização da QoE

**Projeto:** Melhoria da QoE em Streaming de Vídeo com Mininet, SDN e P4

## 1. Metodologia

Sobre o ambiente da Etapa 1 (3 clientes DASH simultâneos, vídeo de 60 s,
gargalo s1↔s2 de 10 Mbps), quatro cenários adversos foram induzidos no
gargalo. A limitação de banda, o atraso/jitter e a perda são aplicados via
disciplinas de fila do `tc` (htb/netem, encapsuladas pelo `TCLink` do
Mininet); o tráfego concorrente é gerado com iperf3.

| Cenário | Indução | Parâmetros |
|---|---|---|
| baseline | — | gargalo 10 Mbps |
| banda | tc/htb | gargalo reduzido a **3 Mbps** |
| atraso | tc/netem | **50 ms ± 20 ms** por sentido (RTT ≈ 100 ms) |
| perda | tc/netem | **3%** de perda de pacotes |
| concorrente | iperf3 | UDP **8 Mbps** (txg→rxg) disputando o gargalo |

Cada cenário executa o mesmo protocolo: medições de referência
(ping 10 pacotes + iperf3 TCP 5 s), depois streaming nos 3 clientes com
ping contínuo (0,5 s) em paralelo. Reprodução: `make cenarios && make plots`.

## 2. Métricas escolhidas e justificativa

**Rede** (causa):
- *RTT médio/máximo* (ping) — atraso de propagação + enfileiramento; afeta
  o tempo de resposta de cada requisição HTTP de segmento.
- *Perda ICMP* — induz retransmissões TCP e queda de vazão efetiva
  (modelo de Mathis: vazão ∝ 1/√perda).
- *Capacidade TCP* (iperf3) — banda efetivamente disponível ao streaming.

**QoE** (efeito percebido), conforme literatura de vídeo adaptativo:
- *Tempo de início (startup)* — primeira impressão do usuário; dominado
  pelo RTT (handshakes + download do MPD/init/primeiro segmento).
- *Stalls (nº e duração)* — métrica de maior impacto na QoE; ocorre quando
  o buffer esvazia (vazão < bitrate consumido).
- *Bitrate médio reproduzido* — qualidade visual entregue; resposta direta
  do ABR à banda disponível.
- *Trocas de qualidade* — instabilidade do ABR; trocas frequentes degradam
  a experiência mesmo sem stall.

## 3. Resultados (média dos 3 clientes)

| cenário | startup (s) | stalls | t. parado (s) | bitrate (kbps) | trocas | RTT durante (ms) | perda ICMP (%) | iperf3 (Mbps) |
|---|---|---|---|---|---|---|---|---|
| baseline | 0,23 | 0 | 0 | **2241** | 1,7 | 21,5 | 0 | 9,64 |
| banda | 0,53 | 0 | 0 | **611** | 2,0 | 131,4 | 0 | **2,71** |
| atraso | **1,29** | 0 | 0 | 783 | 1,0 | 109,1 | 0 | 9,02 |
| perda | 0,19 | 0 | 0 | 1698 | **4,0** | 22,3 | **2,06** | 9,44 |
| concorrente | 0,54 | **0,33** | **0,30** | **436** | 3,0 | 57,1 | 0 | 9,44 |

Gráficos em `results/plots/`: `qoe_startup.png`, `qoe_stalls.png`,
`qoe_bitrate.png`, `qoe_switches.png`, `net_rtt.png`, `net_throughput.png`,
`net_loss.png` e `bitrate_timeline.png` (adaptação ao longo do tempo).

## 4. Análise — correlação rede ↔ QoE

**Evidência de degradação sob carga**: todos os cenários adversos pioraram
ao menos uma métrica de QoE em relação ao baseline (bitrate −73% no caso
de banda, startup +458% no caso de atraso, stall surgindo apenas no caso
concorrente).

- **Banda (3 Mbps)**: capacidade medida caiu para 2,7 Mbps ÷ 3 clientes ≈
  0,9 Mbps cada → ABR estabiliza entre 300 e 800 kbps (bitrate médio 611
  kbps, −73% vs. baseline). RTT durante o streaming sobe a 131 ms — fila
  cheia no htb (buffer do gargalo). Sem stalls: o ABR sacrifica qualidade
  para proteger o buffer, comportamento esperado do DASH.
- **Atraso (RTT ≈ 100 ms)**: capacidade quase intacta (9 Mbps), mas o
  startup quintuplica (0,23 → 1,29 s) — handshake TCP + MPD + init +
  primeiro segmento, cada um pagando o RTT. O bitrate médio cai (783 kbps)
  porque cada requisição de segmento paga ~100 ms ociosos antes dos bytes
  fluírem, reduzindo o throughput percebido pelo estimador do ABR
  (limitação clássica de ABR baseado em throughput sob RTT alto).
- **Perda (3%)**: TCP retransmite e a vazão fica errática — o throughput
  por segmento oscila, o ABR responde com **4 trocas** de qualidade em
  média (vs. 1,7 no baseline; um cliente chegou a 7), com bitrate médio
  24% menor. Perda ICMP medida durante o streaming: 2,06% (~3% nominal).
  É o cenário que mais gera *instabilidade* em vez de queda uniforme.
- **Concorrente (UDP 8 Mbps)**: pior QoE global — UDP não recua (sem
  controle de congestionamento) e ocupa ~80% do gargalo; sobram ~2 Mbps
  para os 3 clientes. Bitrate médio despenca a 436 kbps (−81%) e surge o
  único caso de **rebuffering** (1 stall, 0,9 s, em c2). RTT triplica
  (57 ms) pela fila permanentemente ocupada.

**Síntese da correlação**:

| Métrica de rede degradada | Métrica de QoE afetada |
|---|---|
| ↓ banda disponível | ↓ bitrate; risco de stall quando vazão < bitrate mínimo |
| ↑ RTT | ↑ startup; ↓ bitrate (estimador de throughput penalizado) |
| ↑ perda | ↑ trocas de qualidade (instabilidade); ↓ bitrate |
| tráfego concorrente UDP | combinação: ↓ bitrate, ↑ RTT, stalls |

## 5. Implicações para a Etapa 3

O controlador SDN já coleta estatísticas de porta a cada 5 s
(`controller/qoe_controller.py`). Os resultados indicam os gatilhos de
detecção: vazão no gargalo próxima da saturação + crescimento de RTT/fila.
A mitigação mais promissora é **priorizar/limitar o tráfego concorrente**
(cenário de pior QoE), via regras OpenFlow com filas (QoS) ou drop seletivo
do fluxo iperf3 — exatamente o cenário `concorrente` reproduzível aqui.
