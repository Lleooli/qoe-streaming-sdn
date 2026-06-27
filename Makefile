# Projeto QoE em Streaming com Mininet/SDN — automacao (rodar dentro do WSL, como root)
# Uso a partir do Windows:
#   wsl -d Ubuntu-24.04 -u root -- make -C "/mnt/c/Users/leona/Desktop/Projetos/Projeto programabilidade de redes" <alvo>

SHELL := /bin/bash
PY := python3

.PHONY: help setup check video baseline cenarios controle all plots clean mn-clean

help:
	@echo "Alvos: setup check video baseline cenarios controle all plots clean mn-clean"

setup:            ## instala dependencias (apt)
	apt-get update -qq
	DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mininet \
	  openvswitch-switch iperf iperf3 ffmpeg python3-pip \
	  python3-matplotlib python3-numpy net-tools dos2unix python3-os-ken

check:            ## verifica ambiente
	bash scripts/check_env.sh

video:            ## gera conteudo DASH (3 qualidades, 60 s)
	bash video/generate_video.sh

baseline:         ## Etapa 1: cenario sem degradacao
	$(PY) scripts/run_experiment.py --scenario baseline

cenarios:         ## Etapa 2: cenarios adversos
	$(PY) scripts/run_experiment.py --scenario banda
	$(PY) scripts/run_experiment.py --scenario atraso
	$(PY) scripts/run_experiment.py --scenario perda
	$(PY) scripts/run_experiment.py --scenario concorrente

controle:         ## Etapa 3: cenario concorrente com controle SDN (mitigacao)
	$(PY) scripts/run_experiment.py --scenario concorrente_controle
	$(PY) scripts/plot_results.py
	$(PY) scripts/plot_control.py

all:              ## todos os cenarios + graficos
	$(PY) scripts/run_experiment.py --all
	$(PY) scripts/plot_results.py
	$(PY) scripts/plot_control.py

plots:            ## gera graficos e tabela consolidada
	$(PY) scripts/plot_results.py
	$(PY) scripts/plot_control.py

clean:            ## remove resultados
	rm -rf results/

mn-clean:         ## limpa estado residual do Mininet
	mn -c
