#!/usr/bin/env python3
"""Recalcula metricas 'during' dos net_metrics.json a partir dos logs
ping_during.txt ja coletados (apos correcao do parser de perda)."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from run_experiment import parse_ping_during, RESULTS

for sc in sorted(os.listdir(RESULTS)):
    d = os.path.join(RESULTS, sc)
    log = os.path.join(d, 'ping_during.txt')
    nm = os.path.join(d, 'net_metrics.json')
    if not (os.path.exists(log) and os.path.exists(nm)):
        continue
    with open(log) as f:
        during = parse_ping_during(f.read())
    data = json.load(open(nm))
    data['during'] = during
    with open(nm, 'w') as f:
        json.dump(data, f, indent=1)
    print(sc, during)
