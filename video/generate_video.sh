#!/usr/bin/env bash
# Gera conteudo DASH a partir de um video real, com 3 representacoes
# (240p/360p/720p), segmentos de 2 s e 60 s de duracao total.
# Saida: video/dash/manifest.mpd + segmentos .m4s
#
# Uso: bash generate_video.sh [arquivo_fonte.mp4]
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$DIR/dash"
DUR=60
SRC="${1:-/mnt/c/Users/leona/Downloads/YTDown.com_YouTube_Rick-Astley-Never-Gonna-Give-You-Up-Offi_Media_dQw4w9WgXcQ_001_1080p.mp4}"

if [ ! -f "$SRC" ]; then
    echo "Fonte nao encontrada: $SRC"
    echo "Gerando video sintetico (testsrc2) como fallback."
    SRC_ARGS=(-f lavfi -i "testsrc2=size=1280x720:rate=24,format=yuv420p")
else
    echo "Fonte: $SRC"
    SRC_ARGS=(-i "$SRC")
fi

mkdir -p "$OUT"
rm -f "$OUT"/*.m4s "$OUT"/*.mpd 2>/dev/null || true

ffmpeg -y -loglevel error "${SRC_ARGS[@]}" -t $DUR -an \
  -filter_complex "[0:v]fps=24,format=yuv420p,split=3[v1][v2][v3];[v1]scale=426:240[v240];[v2]scale=640:360[v360];[v3]scale=1280:720[v720]" \
  -map "[v240]" -c:v:0 libx264 -b:v:0 300k  -maxrate:v:0 330k  -bufsize:v:0 600k \
  -map "[v360]" -c:v:1 libx264 -b:v:1 800k  -maxrate:v:1 880k  -bufsize:v:1 1600k \
  -map "[v720]" -c:v:2 libx264 -b:v:2 2400k -maxrate:v:2 2640k -bufsize:v:2 4800k \
  -preset veryfast -g 48 -keyint_min 48 -sc_threshold 0 \
  -use_template 1 -use_timeline 0 -seg_duration 2 \
  -init_seg_name 'init-stream$RepresentationID$.m4s' \
  -media_seg_name 'chunk-stream$RepresentationID$-$Number%05d$.m4s' \
  -adaptation_sets "id=0,streams=v" \
  -f dash "$OUT/manifest.mpd"

echo "DASH gerado em $OUT:"
ls "$OUT" | head -5
echo "... ($(ls "$OUT" | wc -l) arquivos)"
