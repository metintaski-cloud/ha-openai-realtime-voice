#!/usr/bin/with-contenv bashio
set -e

OPENAI_API_KEY=$(bashio::config 'openai_api_key')
WEBSOCKET_PORT=$(bashio::config 'websocket_port')
INSTRUCTIONS=$(bashio::config 'instructions')
VOICE=$(bashio::config 'voice')
GREETING_WORDS=$(bashio::config 'greeting_words')
LIVE_MODEL=$(bashio::config 'live_model')
BACKEND_MODEL=$(bashio::config 'backend_model')
BACKEND_REASONING_EFFORT=$(bashio::config 'backend_reasoning_effort')
ENABLE_WEB_SEARCH=$(bashio::config 'enable_web_search')
ENABLE_RECORDING=$(bashio::config 'enable_recording')
RECORD_FALSE_WAKES=$(bashio::config 'record_false_wakes')
ENABLE_MEMORY=$(bashio::config 'enable_memory')
ENABLE_CONTEXT=$(bashio::config 'enable_context')
MEMORY_MODEL=$(bashio::config 'memory_model')
OPENAI_ADMIN_KEY=$(bashio::config 'openai_admin_key')
MONTHLY_BUDGET_USD=$(bashio::config 'monthly_budget_usd')
LIGHT_ENTITIES=$(bashio::config 'light_entities')
FORGET_FACTS=$(bashio::config 'forget_facts')
ADD_FACTS=$(bashio::config 'add_facts')
RF_HOST=$(bashio::config 'rf_host')
RF_FREQUENCY=$(bashio::config 'rf_frequency')
TV_CHANNELS=$(bashio::config 'tv_channels')
TV_REMOTE=$(bashio::config 'tv_remote')
TV_DUCK=$(bashio::config 'tv_duck')
LAMP_SHOW=$(bashio::config 'lamp_show')
LAMP_SHOW_LIGHTS=$(bashio::config 'lamp_show_lights')
STROMPREIS_CT=$(bashio::config 'strompreis_ct')
CODE_PHRASE=$(bashio::config 'code_phrase')
NOTIFY_SERVICE=$(bashio::config 'notify_service')
ANNOUNCE_PLAYER=$(bashio::config 'announce_player')
ANNOUNCE_BASE_URL=$(bashio::config 'announce_base_url')

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
export BACKEND_REASONING_EFFORT
export ENABLE_WEB_SEARCH
export ENABLE_RECORDING
export RECORD_FALSE_WAKES
export ENABLE_MEMORY
export ENABLE_CONTEXT
export MEMORY_MODEL
export OPENAI_ADMIN_KEY
export MONTHLY_BUDGET_USD
export LIGHT_ENTITIES
export FORGET_FACTS
export ADD_FACTS
export RF_HOST
export RF_FREQUENCY
export TV_CHANNELS
export TV_REMOTE
export TV_DUCK
export LAMP_SHOW LAMP_SHOW_LIGHTS
export STROMPREIS_CT
export CODE_PHRASE
export NOTIFY_SERVICE
export ANNOUNCE_PLAYER
export ANNOUNCE_BASE_URL

export PYTHONUNBUFFERED=1
exec python3 -m app.main
