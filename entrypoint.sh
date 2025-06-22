#!/bin/bash
until xdpyinfo -display :99 >/dev/null 2>&1; do
  echo "Waiting for X display..."
  sleep 1
done
exec python webui.py --ip 0.0.0.0 --port 7788
