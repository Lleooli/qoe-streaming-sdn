#!/usr/bin/env python3
"""
Controlador SDN do projeto (os-ken / API compativel com Ryu, OpenFlow 1.3).

Etapas 1-2: learning switch L2 — instala fluxos reativos por (in_port, eth_dst)
e registra estatisticas de portas periodicamente (base de telemetria que a
Etapa 3 usara para detectar degradacao e aplicar mitigacao).

Executar: osken-manager controller/qoe_controller.py --ofp-tcp-listen-port 6653
"""

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.lib import hub
from os_ken.lib.packet import ether_types, ethernet, packet
from os_ken.ofproto import ofproto_v1_3

STATS_INTERVAL = 5  # s entre coletas de estatisticas de porta


class QoEController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.monitor_thread = hub.spawn(self._monitor)

    # --- conexao do switch: regra table-miss -> controlador ---
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        self.datapaths[dp.id] = dp
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER,
                                          ofp.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)
        self.logger.info('switch conectado: dpid=%016x', dp.id)

    def add_flow(self, dp, priority, match, actions, idle=0):
        parser = dp.ofproto_parser
        inst = [parser.OFPInstructionActions(
            dp.ofproto.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority,
                                      match=match, instructions=inst,
                                      idle_timeout=idle))

    # --- packet-in: aprendizado L2 ---
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
            self.add_flow(dp, 1, match, actions, idle=60)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                        in_port=in_port, actions=actions,
                                        data=data))

    # --- telemetria periodica (base para deteccao na Etapa 3) ---
    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                parser = dp.ofproto_parser
                dp.send_msg(parser.OFPPortStatsRequest(
                    dp, 0, dp.ofproto.OFPP_ANY))
            hub.sleep(STATS_INTERVAL)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        for stat in sorted(ev.msg.body, key=lambda s: s.port_no):
            if stat.port_no > 100:   # ignora porta LOCAL
                continue
            self.logger.info(
                'stats dpid=%x porta=%d tx_bytes=%d rx_bytes=%d '
                'tx_drop=%d rx_drop=%d',
                dpid, stat.port_no, stat.tx_bytes, stat.rx_bytes,
                stat.tx_dropped, stat.rx_dropped)
