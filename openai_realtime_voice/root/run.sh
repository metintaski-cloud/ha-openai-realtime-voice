#!/usr/bin/with-contenv bashio
set -e

OPENAI_API_KEY=$(bashio::config 'openai_api_key')
WEBSOCKET_PORT=$(bashio::config 'websocket_port')
INSTRUCTIONS=$(bashio::config 'instructions')
VOICE=$(bashio::config 'voice')
GREETING_WORDS=$(bashio::config 'greeting_words')
LIVE_MODEL=$(bashio::config 'live_model')
BACKEND_MODEL=$(bashio::config 'backend_model')
ENABLE_WEB_SEARCH=$(bashio::config 'enable_web_search')
ENABLE_RECORDING=$(bashio::config 'enable_recording')
ENABLE_MEMORY=$(bashio::config 'enable_memory')
ENABLE_CONTEXT=$(bashio::config 'enable_context')
MEMORY_MODEL=$(bashio::config 'memory_model')
OPENAI_ADMIN_KEY=$(bashio::config 'openai_admin_key')
MONTHLY_BUDGET_USD=$(bashio::config 'monthly_budget_usd')
LIGHT_ENTITIES=$(bashio::config 'light_entities')
FORGET_FACTS=$(bashio::config 'forget_facts')

if [ -z "$OPENAI_API_KEY" ]; then
    bashio::log.error "OPENAI_API_KEY is required but not set"
    exit 1
fi

export OPENAI_API_KEY
export WEBSOCKET_PORT
export INSTRUCTIONS
export VOICE
export GREETING_WORDS
export LIVE_MODEL
export BACKEND_MODEL
export ENABLE_WEB_SEARCH
export ENABLE_RECORDING
export ENABLE_MEMORY
export ENABLE_CONTEXT
export MEMORY_MODEL
export OPENAI_ADMIN_KEY
export MONTHLY_BUDGET_USD
export LIGHT_ENTITIES
export FORGET_FACTS

export PYTHONUNBUFFERED=1
exec python3 -m app.main
