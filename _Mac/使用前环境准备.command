#!/bin/bash
set -euo pipefail
unset PYTHONHOME PYTHONPATH
export PYTHONUTF8=1 PYTHONNOUSERSITE=1
cd "$(dirname "$0")"
trap 'status=$?; if [ "$status" -ne 0 ]; then echo "环境准备失败，请查看上方错误。"; fi; read -r -p "按回车关闭窗口…" || true' EXIT
if [ "$(uname -s)" != Darwin ] || [ "$(sw_vers -productVersion | cut -d. -f1)" -lt 14 ]; then
  echo "需要 macOS 14 或以上。"; exit 1
fi
export PATH="/Library/Frameworks/Python.framework/Versions/3.12/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v python3.12 >/dev/null 2>&1; then
  echo "请先从 https://www.python.org/downloads/macos/ 安装 Python 3.12，再运行本脚本。"; exit 1
fi
python3.12 -c 'import sys; assert sys.version_info[:2] == (3, 12)'
python3.12 -m venv .venv
if ! .venv/bin/python3 -X utf8 tools/diagnose.py --imports-only; then
  .venv/bin/python3 -m ensurepip --upgrade
  .venv/bin/python3 -m pip install --disable-pip-version-check --only-binary=:all: --force-reinstall -r requirements.txt
fi
.venv/bin/python3 -m pip check
.venv/bin/python3 tools/install_mxu.py
.venv/bin/python3 generate_interface.py
.venv/bin/python3 -X utf8 tools/diagnose.py --environment-only
chmod +x ./*.command
echo "Environment ready。请运行 启动自动化.command。"
