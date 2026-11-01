#!/usr/bin/with-contenv bashio
set -e

OPENAI_API_KEY=$(bashio::config 'openai_api_key')
WEBSOCKET_PORT=$(bashio::config 'websocket_port')
INSTRUCTIONS=$(bashio::config 'instructions')
VOICE=$(bashio::config 'voice')
LIVE_MODEL=$(bashio::config 'live_model')
BACKEND_MODEL=$(bashio::config 'backend_model')
ENABLE_WEB_SEARCH=$(bashio::config 'enable_web_search')
ENABLE_RECORDING=$(bashio::config 'enable_recording')
ENABLE_MEMORY=$(bashio::config 'enable_memory')
MEMORY_MODEL=$(bashio::config 'memory_model')

if [ -z "$OPENAI_API_KEY" ]; then
    bashio::log.error "OPENAI_API_KEY is required but not set"
    exit 1
fi

export OPENAI_API_KEY
export WEBSOCKET_PORT
export INSTRUCTIONS
export VOICE
export LIVE_MODEL
export BACKEND_MODEL
export ENABLE_WEB_SEARCH
export ENABLE_RECORDING
export ENABLE_MEMORY
export MEMORY_MODEL

export PYTHONUNBUFFERED=1
exec python3 -m app.main
