#!/usr/bin/env python3
"""
Cliente DASH instrumentado para medicao de QoE.

Baixa segmentos do manifest MPD via HTTP, executa adaptacao de bitrate
(ABR baseada em throughput) e simula a reproducao com um modelo de buffer,
registrando as metricas de QoE:

  - startup_time  : tempo entre requisicao do MPD e inicio da reproducao
  - stalls        : numero de pausas por buffer vazio (rebuffering)
  - stall_time    : tempo total parado em rebuffering
  - avg_bitrate   : bitrate medio dos segmentos reproduzidos
  - switches      : numero de trocas de representacao

Uso:
  dash_client.py --url http://10.0.0.1:8080/manifest.mpd --out results/c1 [--duration 60]
"""

import argparse
import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET

NS = {'mpd': 'urn:mpeg:dash:schema:mpd:2011'}

STARTUP_BUFFER = 2.0    # s de buffer para iniciar reproducao
TARGET_BUFFER = 12.0    # s; acima disso o cliente espera (pacing)
SAFETY = 0.8            # fator de seguranca do estimador de throughput


def fetch(url, timeout=30):
    """Baixa uma URL e devolve (bytes, duracao_download_s)."""
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = r.read()
    return data, time.time() - t0


def parse_mpd(mpd_bytes, base_url):
    """Extrai representacoes e template de segmentos do MPD."""
    root = ET.fromstring(mpd_bytes)
    period = root.find('mpd:Period', NS)
    aset = period.find('mpd:AdaptationSet', NS)
    # SegmentTemplate pode estar no AdaptationSet ou na Representation
    common_st = aset.find('mpd:SegmentTemplate', NS)
    reps = []
    for rep in aset.findall('mpd:Representation', NS):
        st = rep.find('mpd:SegmentTemplate', NS)
        if st is None:
            st = common_st
        timescale = float(st.get('timescale', '1'))
        reps.append({
            'id': rep.get('id'),
            'bandwidth': int(rep.get('bandwidth')),
            'media': st.get('media'),
            'init': st.get('initialization'),
            'start': int(st.get('startNumber', '1')),
            'seg_dur': float(st.get('duration')) / timescale,
        })
    reps.sort(key=lambda r: r['bandwidth'])

    # duracao total da midia (atributo mediaPresentationDuration: PT...S)
    dur_attr = root.get('mediaPresentationDuration', 'PT60S')
    media_dur = _parse_iso_duration(dur_attr)
    return reps, media_dur, base_url


def _parse_iso_duration(s):
    """PT1M3.2S -> segundos (parser minimo p/ saidas do ffmpeg)."""
    s = s.replace('PT', '')
    total = 0.0
    for unit, mult in (('H', 3600), ('M', 60), ('S', 1)):
        if unit in s:
            val, s = s.split(unit, 1)
            total += float(val) * mult
    return total


def seg_url(base, rep, number):
    name = rep['media'].replace('$RepresentationID$', rep['id'])
    if '$Number%05d$' in name:
        name = name.replace('$Number%05d$', '%05d' % number)
    else:
        name = name.replace('$Number$', str(number))
    return base + name


def init_url(base, rep):
    return base + rep['init'].replace('$RepresentationID$', rep['id'])


def choose_rep(reps, samples):
    """ABR: media harmonica dos ultimos 3 throughputs * fator de seguranca."""
    if not samples:
        return reps[0]
    last = samples[-3:]
    harmonic = len(last) / sum(1.0 / s for s in last)
    est = harmonic * SAFETY
    chosen = reps[0]
    for r in reps:
        if r['bandwidth'] <= est:
            chosen = r
    return chosen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True, help='URL do manifest.mpd')
    ap.add_argument('--out', required=True, help='diretorio de saida')
    ap.add_argument('--duration', type=float, default=0,
                    help='limite de tempo de parede (0 = video inteiro)')
    ap.add_argument('--name', default='client', help='rotulo do cliente')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    base = args.url.rsplit('/', 1)[0] + '/'

    t_start = time.time()
    mpd_bytes, _ = fetch(args.url)
    reps, media_dur, base = parse_mpd(mpd_bytes, base)
    n_segs = int(round(media_dur / reps[0]['seg_dur']))
    seg_dur = reps[0]['seg_dur']

    # inits de todas as representacoes (pequenos; baixados uma vez)
    for r in reps:
        fetch(init_url(base, r))

    samples = []          # throughput por segmento (bit/s)
    segments = []         # registro por segmento
    buffer_s = 0.0        # buffer de reproducao (s de midia)
    playing = False
    startup_time = None
    stalls = 0
    stall_time = 0.0
    switches = 0
    bits_played = 0
    last_rep = None
    play_clock = None     # instante de parede da ultima atualizacao do buffer

    def drain():
        """Atualiza buffer consumido pela reproducao desde a ultima chamada."""
        nonlocal buffer_s, playing, stalls, stall_time, play_clock
        now = time.time()
        if playing and play_clock is not None:
            consumed = now - play_clock
            if consumed >= buffer_s:           # buffer esvaziou -> stall
                stall_start = play_clock + buffer_s
                buffer_s = 0.0
                playing = False
                stalls += 1
                stall_time += now - stall_start
            else:
                buffer_s -= consumed
        play_clock = now

    number = reps[0]['start']
    end_number = reps[0]['start'] + n_segs - 1

    while number <= end_number:
        if args.duration and (time.time() - t_start) > args.duration:
            break
        rep = choose_rep(reps, samples)
        if last_rep is not None and rep['id'] != last_rep:
            switches += 1
        last_rep = rep['id']

        url = seg_url(base, rep, number)
        try:
            data, dl = fetch(url)
        except Exception as e:
            segments.append({'n': number, 'rep': rep['id'], 'error': str(e)})
            number += 1
            continue

        thr = len(data) * 8 / max(dl, 1e-6)
        samples.append(thr)
        drain()
        buffer_s += seg_dur
        bits_played += len(data) * 8

        if not playing and buffer_s >= STARTUP_BUFFER:
            playing = True
            play_clock = time.time()
            if startup_time is None:
                startup_time = time.time() - t_start

        segments.append({
            'n': number,
            'rep': rep['id'],
            'bitrate': rep['bandwidth'],
            'bytes': len(data),
            'dl_s': round(dl, 4),
            'thr_bps': int(thr),
            'buffer_s': round(buffer_s, 2),
            't': round(time.time() - t_start, 3),
        })

        # pacing: nao baixar alem do buffer alvo
        drain()
        if buffer_s > TARGET_BUFFER:
            time.sleep(buffer_s - TARGET_BUFFER)
        number += 1

    # drena o restante do buffer (fim da sessao)
    drain()

    played_segs = [s for s in segments if 'bitrate' in s]
    avg_bitrate = (sum(s['bitrate'] for s in played_segs) / len(played_segs)
                   if played_segs else 0)

    summary = {
        'client': args.name,
        'startup_time_s': round(startup_time, 3) if startup_time else None,
        'stalls': stalls,
        'stall_time_s': round(stall_time, 3),
        'avg_bitrate_bps': int(avg_bitrate),
        'switches': switches,
        'segments_ok': len(played_segs),
        'segments_total': n_segs,
        'avg_throughput_bps': int(sum(samples) / len(samples)) if samples else 0,
        'wall_time_s': round(time.time() - t_start, 2),
    }

    with open(os.path.join(args.out, f'qoe_{args.name}.json'), 'w') as f:
        json.dump({'summary': summary, 'segments': segments}, f, indent=1)
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
