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
ENABLE_CONTEXT=$(bashio::config 'enable_context')
MEMORY_MODEL=$(bashio::config 'memory_model')
OPENAI_ADMIN_KEY=$(bashio::config 'openai_admin_key')
CREDIT_TOPUP_USD=$(bashio::config 'credit_topup_usd')
CREDIT_TOPUP_DATE=$(bashio::config 'credit_topup_date')

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
export ENABLE_CONTEXT
export MEMORY_MODEL
export OPENAI_ADMIN_KEY
export CREDIT_TOPUP_USD
export CREDIT_TOPUP_DATE

export PYTHONUNBUFFERED=1
exec python3 -m app.main
