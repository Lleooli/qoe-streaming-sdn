#!/usr/bin/env python3
"""
Topologia do projeto QoE/SDN.

    srv ---+                    +--- c1
           |                    |
    txg ---+-- s1 ====== s2 ----+--- c2
                (gargalo)       |
                                +--- c3
                                +--- rxg

- srv : servidor de video DASH (HTTP)
- c1-c3: clientes de video
- txg/rxg: gerador/receptor de trafego concorrente (iperf3)
- s1, s2: switches OpenFlow 1.3 (controlador remoto)
- Link s1<->s2 e o gargalo (10 Mbps); demais links 100 Mbps.
"""

from mininet.topo import Topo
from mininet.link import TCLink

BOTTLENECK_BW = 10   # Mbps
EDGE_BW = 100        # Mbps


class QoETopo(Topo):
    def build(self):
        s1 = self.addSwitch('s1', protocols='OpenFlow13')
        s2 = self.addSwitch('s2', protocols='OpenFlow13')

        srv = self.addHost('srv', ip='10.0.0.1/24')
        txg = self.addHost('txg', ip='10.0.0.2/24')
        c1 = self.addHost('c1', ip='10.0.0.11/24')
        c2 = self.addHost('c2', ip='10.0.0.12/24')
        c3 = self.addHost('c3', ip='10.0.0.13/24')
        rxg = self.addHost('rxg', ip='10.0.0.14/24')

        self.addLink(srv, s1, cls=TCLink, bw=EDGE_BW)
        self.addLink(txg, s1, cls=TCLink, bw=EDGE_BW)
        self.addLink(c1, s2, cls=TCLink, bw=EDGE_BW)
        self.addLink(c2, s2, cls=TCLink, bw=EDGE_BW)
        self.addLink(c3, s2, cls=TCLink, bw=EDGE_BW)
        self.addLink(rxg, s2, cls=TCLink, bw=EDGE_BW)
        # gargalo
        self.addLink(s1, s2, cls=TCLink, bw=BOTTLENECK_BW)


topos = {'qoe': QoETopo}
