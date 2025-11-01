#!/usr/bin/env bash
set -euo pipefail

sudo mkdir -p /var/satellite/satellite_raw/_fancy
sudo cp -r web/_fancy/. /var/satellite/satellite_raw/_fancy/

sudo cp web/goes.conf /etc/nginx/sites-available/default
sudo nginx -t
sudo systemctl reload nginx
