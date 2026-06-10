# Etapa 1 — Construção do Ambiente Experimental

**Projeto:** Melhoria da QoE em Streaming de Vídeo com Mininet, SDN e P4

## 1. Ambiente

| Componente | Escolha | Justificativa |
|---|---|---|
| Emulador | Mininet 2.3 (Ubuntu 24.04 / WSL2, kernel 6.6) | requisito do projeto; OVS nativo |
| Controlador SDN | **os-ken 2.8.1** (fork mantido do Ryu, mesma API) | Ryu original não roda em Python ≥ 3.10; os-ken é o sucessor oficial (OpenStack) |
| Protocolo | OpenFlow 1.3 | suportado pelo OVS e pelo os-ken |
| Streaming | MPEG-DASH (ffmpeg) + servidor HTTP Python | mesmas ferramentas do trabalho de sala (tutorial DASH+VLC) |
| Cliente | cliente DASH próprio em Python com ABR e instrumentação de QoE | VLC não expõe métricas de QoE (startup/stalls/bitrate) de forma programática; cliente próprio registra tudo em JSON |
| Métricas de rede | ping (RTT/perda) e iperf3 (vazão) | requisito do projeto |
| Automação | `Makefile` + `scripts/run_experiment.py` (API Python do Mininet) | execução reproduzível com um comando |

## 2. Topologia

```
   srv ──┐                       ┌── c1
          ├── s1 ═══════════ s2 ─┼── c2
   txg ──┘     (gargalo 10M)     ├── c3
                                 └── rxg
```

- **srv** (10.0.0.1): servidor DASH — HTTP na porta 8080, segmentos de 2 s
  em 3 qualidades (426x240 @ 300 kbps, 640x360 @ 800 kbps, 1280x720 @ 2400 kbps),
  60 s de vídeo real.
- **c1–c3** (10.0.0.11–13): clientes DASH com adaptação de bitrate
  (média harmônica dos últimos 3 throughputs × 0,8).
- **txg/rxg**: hosts geradores de tráfego concorrente (iperf3) — usados na Etapa 2.
- **s1, s2**: switches OpenFlow 1.3 controlados remotamente pelo
  `controller/qoe_controller.py` (learning switch L2 + coleta periódica de
  estatísticas de porta, base para a detecção da Etapa 3).
- Links de borda: 100 Mbps; link s1↔s2: **gargalo de 10 Mbps** (TCLink/htb),
  ponto onde a degradação será induzida na Etapa 2.

Dimensionamento: 3 clientes × 2,4 Mbps (máx.) = 7,2 Mbps < 10 Mbps —
o baseline comporta todos os clientes na qualidade máxima, com folga.

## 3. Reprodução

```bash
# Windows: terminal no diretório do projeto
wsl -d Ubuntu-24.04 -u root -- make -C "/mnt/c/Users/leona/Desktop/Projetos/Projeto programabilidade de redes" setup
wsl -d Ubuntu-24.04 -u root -- make -C "..." video baseline
```

Ou, dentro do WSL (root, raiz do projeto): `make setup && make video && make baseline`.

O orquestrador executa, por cenário: limpeza (`mn -c`) → controlador →
topologia → `pingAll` → servidor DASH → medições pré (ping 10 pacotes,
iperf3 5 s) → ping contínuo + 3 clientes DASH → coleta e desmontagem.
Saídas em `results/baseline/`.

## 4. Medições iniciais (sem degradação)

Rede (gargalo 10 Mbps):

| Métrica | Valor |
|---|---|
| pingAll | 0% perda (30/30) |
| RTT pré-streaming (c1→srv) | 0,097 ms (média) |
| Capacidade TCP (iperf3, 5 s) | 9,64 Mbps (≈ gargalo nominal) |
| RTT durante streaming | 21,5 ms (média) — fila no gargalo sob carga dos 3 clientes |
| Perda ICMP durante streaming | 0% |

QoE (3 clientes simultâneos, vídeo 60 s):

| Cliente | Startup (s) | Stalls | Tempo parado (s) | Bitrate médio (kbps) | Trocas | Segmentos |
|---|---|---|---|---|---|---|
| c1 | 0,264 | 0 | 0 | 2330 | 1 | 30/30 |
| c2 | 0,197 | 0 | 0 | 2330 | 1 | 30/30 |
| c3 | 0,232 | 0 | 0 | 2063 | 3 | 30/30 |

**Conclusão:** ambiente estável e reproduzível. Streaming sem rebuffering,
startup < 0,3 s e os três clientes convergindo para a qualidade máxima
(720p; bitrate médio ≥ 2 Mbps — o valor < 2400 se deve apenas ao primeiro
segmento, baixado em 240p por conservadorismo do ABR). Critérios da Etapa 1
atendidos: sem degradação significativa.

## 5. Observação sobre o ambiente

- A VM oficial do Mininet (`Projetos/Mininet/`, OVF) é alternativa caso o
  WSL2 não esteja disponível; todo o projeto roda por scripts e independe
  do ambiente gráfico.
- Avisos `sch_htb: quantum of class ... is big` do kernel são cosméticos
  (parâmetro r2q do htb) e não afetam as medições.
