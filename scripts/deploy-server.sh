#!/usr/bin/env bash
# This script is intended to run on a target Avalon server as the `avalon` user
set -euo pipefail

export PACK_NAME="$1" # i.e. frozenhell
export PACK_SUBPATH="$2" # i.e. descent/frozenhell
export SERVER_NAME="$3" # i.e. descent

export PACK_CDN="https://s3.eu-west-1.wasabisys.com/parallax-assets/data"
export SUPERVISOR_SERVICE_ID="avalon-$SERVER_NAME-$PACK_NAME"
export SERVER_PATH="/var/lib/avalon/mc/$PACK_NAME/$SERVER_NAME"

function halt_server() {
  echo "Stopping the Minecraft server"
  supervisorctl stop "$SUPERVISOR_SERVICE_ID" || true
}

function create_backup() {
  echo "Creating a world backup"
  # remove old backups
  (cd "$SERVER_PATH" && find backups/pre-update -mindepth 1 -mtime +1 -delete)
  (cd "$SERVER_PATH" && mkdir -p backups/pre-update && zip -r "backups/pre-update/world-$(date +%Y-%m-%d_%H-%M-%S).zip" world)
}

function install_modpack() {
  echo "Installing the modpack"
  mkdir -p "$SERVER_PATH"
  chmod -R 0770 "$SERVER_PATH" || true
  chown -R avalon:avalon "$SERVER_PATH" || true
  (cd "$SERVER_PATH" && java -Xmx4G -jar /var/lib/avalon/mc/packwiz-installer-bootstrap.jar -g -s server "$PACK_CDN/$PACK_SUBPATH/pack.toml")
  (cd "$SERVER_PATH" && chmod +x ./start.sh)
}

function install_plugins() {
  echo "Installing plugins"
}

function start_server() {
  echo "Starting the server"
  supervisorctl start "$SUPERVISOR_SERVICE_ID"
}

halt_server
# create_backup
install_modpack
install_plugins
start_server
