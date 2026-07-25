#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install -y \
    python3 python3-venv python3-dev \
    portaudio19-dev libsndfile1-dev \
    pps-tools alsa-utils

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [[ ! -f node_config.json ]]; then
    cp config.example.json node_config.json
    echo "Created node_config.json. Edit node_id and audio.device before capture."
fi

echo "Setup complete. Activate with: source .venv/bin/activate"
