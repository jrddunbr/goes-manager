#!/usr/bin/env bash
set -euo pipefail

sudo mkdir -p /var/satellite/satellite_raw/_fancy
sudo cp -r html/_fancy/. /var/satellite/satellite_raw/_fancy/

sudo cp html/default_with_headers /etc/nginx/sites-available/default
sudo nginx -t
sudo systemctl reload nginx
