#!/usr/bin/env python3
"""
Controlador SDN do projeto (os-ken / API compativel com Ryu, OpenFlow 1.3).

Etapas 1-2: learning switch L2 + telemetria de portas (estatisticas periodicas).

Etapa 3 (controle): a partir da telemetria, o controlador DETECTA degradacao no
gargalo (saturacao sustentada do enlace s1<->s2) e aplica MITIGACAO programando
regras OpenFlow dinamicamente para limitar o fluxo concorrente (UDP) que disputa
a banda com o video (TCP). As decisoes sao registradas em log (requisito da
etapa: "logs demonstrando decisoes em tempo de execucao").

Pipeline de tabelas (OpenFlow 1.3):
  tabela 0 -> classificacao/policiamento  (default: GotoTable(1))
  tabela 1 -> learning switch L2           (table-miss -> controlador)

Quando a saturacao e detectada, instala-se na tabela 0 uma regra de alta
prioridade que casa o trafego UDP e o submete a um *meter* de rate-limit antes
de seguir para a tabela 1. Assim o video (TCP) recupera banda no gargalo.

Configuracao por variaveis de ambiente (definidas pelo orquestrador):
  QOE_MITIGATION   = on|off  (default off) — habilita deteccao+mitigacao
  QOE_DECISION_LOG = caminho do arquivo de log de decisoes (opcional)
  QOE_CAP_MBPS     = capacidade do gargalo em Mbps (default 10)
  QOE_LIMIT_KBPS   = rate-limit aplicado ao fluxo concorrente (default 2000)
  QOE_MODE         = meter|drop (default meter) — estrategia de mitigacao

Executar: osken-manager controller/qoe_controller.py --ofp-tcp-listen-port 6653
"""

import os
import time

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.lib import hub
from os_ken.lib.packet import ether_types, ethernet, packet
from os_ken.ofproto import ofproto_v1_3

STATS_INTERVAL = 5            # s entre coletas de estatisticas de porta
T_POLICE = 0                  # tabela de classificacao/policiamento
T_SWITCH = 1                  # tabela de encaminhamento (learning switch)
MITI_METER_ID = 1            # id do meter de rate-limit

SAT_HIGH = 0.85               # >85% da capacidade => enlace saturado
SAT_WIN = 2                   # janelas consecutivas para confirmar deteccao


def _env_on(name):
    return os.environ.get(name, '').lower() in ('1', 'on', 'true', 'yes')


class QoEController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}

        # --- configuracao da Etapa 3 ---
        self.mitigation = _env_on('QOE_MITIGATION')
        self.cap_bps = float(os.environ.get('QOE_CAP_MBPS', '10')) * 1e6
        self.limit_kbps = int(os.environ.get('QOE_LIMIT_KBPS', '2000'))
        self.mode = os.environ.get('QOE_MODE', 'meter').lower()
        self.decision_path = os.environ.get('QOE_DECISION_LOG')

        # estado de deteccao/mitigacao
        self._port_prev = {}        # (dpid, port) -> (tx_bytes, t)
        self._sat_count = {}        # dpid -> janelas saturadas consecutivas
        self._low_count = {}        # dpid -> janelas ociosas consecutivas
        self._mitigated = set()     # dpids com mitigacao ativa

        if self.decision_path:
            os.makedirs(os.path.dirname(self.decision_path) or '.',
                        exist_ok=True)
            # zera o arquivo no inicio da sessao
            open(self.decision_path, 'w').close()

        self.logger.info('controle SDN: mitigation=%s mode=%s cap=%.0fMbps '
                         'limite=%dkbps', self.mitigation, self.mode,
                         self.cap_bps / 1e6, self.limit_kbps)
        self.monitor_thread = hub.spawn(self._monitor)

    # ------------------------------------------------------------------ #
    # Log de decisoes (controller.log + arquivo dedicado, se configurado)
    # ------------------------------------------------------------------ #
    def decide(self, fmt, *args):
        line = fmt % args if args else fmt
        self.logger.info('DECISION %s', line)
        if self.decision_path:
            with open(self.decision_path, 'a') as f:
                f.write('%s  %s\n' % (time.strftime('%H:%M:%S'), line))

    # ------------------------------------------------------------------ #
    # Conexao do switch: instala o pipeline de duas tabelas
    # ------------------------------------------------------------------ #
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        self.datapaths[dp.id] = dp

        # tabela 0: por padrao, segue para a tabela de encaminhamento
        self.add_flow(dp, 0, parser.OFPMatch(), table=T_POLICE,
                      goto=T_SWITCH)

        # tabela 1: table-miss -> controlador (learning switch)
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER,
                                          ofp.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, parser.OFPMatch(), actions=actions,
                      table=T_SWITCH)
        self.logger.info('switch conectado: dpid=%016x', dp.id)

    def add_flow(self, dp, priority, match, actions=None, idle=0,
                 table=0, goto=None, meter=None):
        parser = dp.ofproto_parser
        inst = []
        if meter is not None:
            inst.append(parser.OFPInstructionMeter(meter))
        if actions is not None:
            inst.append(parser.OFPInstructionActions(
                dp.ofproto.OFPIT_APPLY_ACTIONS, actions))
        if goto is not None:
            inst.append(parser.OFPInstructionGotoTable(goto))
        dp.send_msg(parser.OFPFlowMod(datapath=dp, table_id=table,
                                      priority=priority, match=match,
                                      instructions=inst, idle_timeout=idle))

    # ------------------------------------------------------------------ #
    # packet-in: aprendizado L2 (tabela 1)
    # ------------------------------------------------------------------ #
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        dst, src = eth.dst, eth.src

        self.mac_to_port.setdefault(dp.id, {})
        self.mac_to_port[dp.id][src] = in_port
        out_port = self.mac_to_port[dp.id].get(dst, ofp.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            self.add_flow(dp, 1, match, actions=actions, idle=60,
                          table=T_SWITCH)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                        in_port=in_port, actions=actions,
                                        data=data))

    # ------------------------------------------------------------------ #
    # Telemetria periodica + deteccao de degradacao (Etapa 3)
    # ------------------------------------------------------------------ #
    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                parser = dp.ofproto_parser
                dp.send_msg(parser.OFPPortStatsRequest(
                    dp, 0, dp.ofproto.OFPP_ANY))
            hub.sleep(STATS_INTERVAL)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dp = ev.msg.datapath
        dpid = dp.id
        now = time.time()
        max_rate = 0.0
        max_port = None
        for stat in sorted(ev.msg.body, key=lambda s: s.port_no):
            if stat.port_no > 100:        # ignora porta LOCAL
                continue
            self.logger.info(
                'stats dpid=%x porta=%d tx_bytes=%d rx_bytes=%d '
                'tx_drop=%d rx_drop=%d',
                dpid, stat.port_no, stat.tx_bytes, stat.rx_bytes,
                stat.tx_dropped, stat.rx_dropped)
            key = (dpid, stat.port_no)
            prev = self._port_prev.get(key)
            self._port_prev[key] = (stat.tx_bytes, now)
            if prev:
                dt = now - prev[1]
                if dt > 0:
                    rate = (stat.tx_bytes - prev[0]) * 8 / dt   # bits/s
                    if rate > max_rate:
                        max_rate, max_port = rate, stat.port_no

        if self.mitigation and max_port is not None:
            self._detect(dp, max_port, max_rate)

    def _detect(self, dp, port, rate):
        """Deteccao de saturacao do gargalo e acionamento da mitigacao."""
        dpid = dp.id
        util = rate / self.cap_bps
        if util >= SAT_HIGH:
            self._sat_count[dpid] = self._sat_count.get(dpid, 0) + 1
            self._low_count[dpid] = 0
        else:
            self._low_count[dpid] = self._low_count.get(dpid, 0) + 1
            self._sat_count[dpid] = 0

        if (dpid not in self._mitigated
                and self._sat_count.get(dpid, 0) >= SAT_WIN):
            self.decide('degradacao detectada em dpid=%x porta=%d: '
                        'utilizacao %.0f%% do gargalo (%.2f Mbps) por %d janelas',
                        dpid, port, util * 100, rate / 1e6, SAT_WIN)
            self._apply_mitigation(dp)
        elif (dpid in self._mitigated
              and self._low_count.get(dpid, 0) >= SAT_WIN):
            self.decide('gargalo normalizado em dpid=%x (utilizacao %.0f%%): '
                        'removendo restricao', dpid, util * 100)
            self._remove_mitigation(dp)

    # ------------------------------------------------------------------ #
    # Mitigacao: rate-limit (meter) ou descarte do fluxo concorrente UDP
    # ------------------------------------------------------------------ #
    def _apply_mitigation(self, dp):
        parser = dp.ofproto_parser
        ofp = dp.ofproto
        # casa o trafego concorrente: UDP sobre IPv4 (o video e TCP)
        match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP,
                                ip_proto=17)
        if self.mode == 'drop':
            # descarta o fluxo concorrente (instrucao vazia = drop)
            self.add_flow(dp, 100, match, table=T_POLICE)
            self.decide('mitigacao: DROP do trafego UDP concorrente '
                        '(prioridade 100, tabela 0) em dpid=%x', dp.id)
        else:
            # cria meter de rate-limit e direciona o UDP para ele
            band = parser.OFPMeterBandDrop(rate=self.limit_kbps, burst_size=0)
            dp.send_msg(parser.OFPMeterMod(
                datapath=dp, command=ofp.OFPMC_ADD,
                flags=ofp.OFPMF_KBPS, meter_id=MITI_METER_ID, bands=[band]))
            self.add_flow(dp, 100, match, table=T_POLICE,
                          meter=MITI_METER_ID, goto=T_SWITCH)
            self.decide('mitigacao: rate-limit do trafego UDP concorrente a '
                        '%d kbps (meter %d, tabela 0) em dpid=%x — prioriza '
                        'o video TCP no gargalo',
                        self.limit_kbps, MITI_METER_ID, dp.id)
        self._mitigated.add(dp.id)

    def _remove_mitigation(self, dp):
        parser = dp.ofproto_parser
        ofp = dp.ofproto
        match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ip_proto=17)
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp, table_id=T_POLICE, command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
            priority=100, match=match))
        if self.mode != 'drop':
            dp.send_msg(parser.OFPMeterMod(
                datapath=dp, command=ofp.OFPMC_DELETE,
                meter_id=MITI_METER_ID))
        self._mitigated.discard(dp.id)
