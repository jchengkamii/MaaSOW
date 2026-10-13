#!/bin/bash
set -euo pipefail
unset PYTHONHOME PYTHONPATH
export PYTHONUTF8=1 PYTHONNOUSERSITE=1
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python3 ]; then
  echo "请先运行 使用前环境准备.command。"
  read -r -p "按回车关闭…" || true
  exit 1
fi
export PYTHONUTF8=1
if ! .venv/bin/python3 launcher.py; then
  read -r -p "启动失败，请查看错误；按回车关闭…" || true
  exit 1
fi
