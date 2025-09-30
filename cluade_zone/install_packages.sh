#!/bin/bash
cd /home/kyj1435/project/perpdex_trading
source .venv/bin/activate
python -m ensurepip --default-pip 2>/dev/null || true
python -m pip install --upgrade pip setuptools wheel
python -m pip install aiohttp pandas numpy paradex-py backpack-exchange
