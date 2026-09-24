#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
trap 'read -r -p "按回车关闭窗口…" || true' EXIT
if [ ! -x .venv/bin/python3 ]; then
  echo "请先运行 使用前环境准备.command。"; exit 1
fi
.venv/bin/python3 tools/diagnose.py
