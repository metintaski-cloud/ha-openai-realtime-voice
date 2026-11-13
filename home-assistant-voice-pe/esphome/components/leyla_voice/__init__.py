"""leyla_voice: own ESPHome component for the conversation between the Voice PE and the server.

See leyla_voice_spec.md and REWRITE_PLAN.md in home-assistant-voice-pe. The logic lives in pure
headers (state_machine.h and friends) that are tested on the computer; leyla_voice.cpp is the glue
to ESPHome, the socket, the microphone and the speaker.
"""
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation
from esphome.components import microphone, speaker
from esphome.components.esp32 import add_idf_component
from esphome.const import CONF_ID, CONF_MICROPHONE, CONF_SPEAKER, CONF_TRIGGER_ID

DEPENDENCIES = ["microphone", "speaker"]
CODEOWNERS = ["@metintaski-cloud"]

leyla_ns = cg.esphome_ns.namespace("leyla_voice")
LeylaVoice = leyla_ns.class_("LeylaVoice", cg.Component)
EventTrigger = leyla_ns.class_("EventTrigger", automation.Trigger.template())
StartAction = leyla_ns.class_("StartAction", automation.Action)
StopAction = leyla_ns.class_("StopAction", automation.Action)
InterruptAction = leyla_ns.class_("InterruptAction", automation.Action)
IsRunningCondition = leyla_ns.class_("IsRunningCondition", automation.Condition)
IsBotSpeakingCondition = leyla_ns.class_("IsBotSpeakingCondition", automation.Condition)

CONF_SERVER_URL = "server_url"
CONF_AUTO_STOP_TIMEOUT = "auto_stop_timeout"
CONF_FULL_DUPLEX = "full_duplex"
CONF_MIC_AUTO_GAIN_MAX = "mic_auto_gain_max"
CONF_MIC_AUTO_GAIN_TARGET = "mic_auto_gain_target"
CONF_MIC_NOISE_FLOOR = "mic_noise_floor"

# Same names as the old component, the number is the index in LeylaVoice::set_trigger
TRIGGERS = {
    "on_connected": 0,
    "on_ready": 1,
    "on_thinking": 2,
    "on_replying": 3,
    "on_listening": 4,
    "on_searching": 5,
    "on_stopped": 6,
    "on_disconnected": 7,
    "on_error": 8,
    "on_quota_exceeded": 9,
}

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(LeylaVoice),
        cv.Required(CONF_SERVER_URL): cv.string,
        cv.Required(CONF_MICROPHONE): cv.use_id(microphone.Microphone),
        cv.Required(CONF_SPEAKER): cv.use_id(speaker.Speaker),
        cv.Optional(CONF_AUTO_STOP_TIMEOUT, default="20s"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_FULL_DUPLEX, default=False): cv.boolean,
        cv.Optional(CONF_MIC_AUTO_GAIN_MAX, default=1.0): cv.float_range(min=1.0, max=12.0),
        cv.Optional(CONF_MIC_AUTO_GAIN_TARGET, default=3000): cv.float_range(min=500, max=12000),
        cv.Optional(CONF_MIC_NOISE_FLOOR, default=150): cv.float_range(min=0, max=3000),
        **{
            cv.Optional(key): automation.validate_automation(
                {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(EventTrigger)}, single=True
            )
            for key in TRIGGERS
        },
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    # The WebSocket client of ESP-IDF lives in the esp-protocols repository
    add_idf_component(
        name="esp-protocols",
        repo="https://github.com/espressif/esp-protocols.git",
        ref="websocket-v1.6.1",
        path="components/esp_websocket_client",
    )

    cg.add(var.set_server_url(config[CONF_SERVER_URL]))
    cg.add(var.set_microphone(await cg.get_variable(config[CONF_MICROPHONE])))
    cg.add(var.set_speaker(await cg.get_variable(config[CONF_SPEAKER])))
    cg.add(var.set_auto_stop_timeout(config[CONF_AUTO_STOP_TIMEOUT]))
    cg.add(var.set_full_duplex(config[CONF_FULL_DUPLEX]))
    cg.add(
        var.set_mic_gain(
            config[CONF_MIC_AUTO_GAIN_MAX],
            config[CONF_MIC_AUTO_GAIN_TARGET],
            config[CONF_MIC_NOISE_FLOOR],
        )
    )
    for key, index in TRIGGERS.items():
        if key in config:
            conf = config[key]
            trigger = cg.new_Pvariable(conf[CONF_TRIGGER_ID])
            cg.add(var.set_trigger(index, trigger))
            await automation.build_automation(trigger, [], conf)


ACTION_SCHEMA = automation.maybe_simple_id({cv.GenerateID(): cv.use_id(LeylaVoice)})


async def _parented(config, action_id, template_arg):
    parent = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg)
    cg.add(var.set_parent(parent))
    return var


@automation.register_action("leyla_voice.start", StartAction, ACTION_SCHEMA, synchronous=True)
async def start_to_code(config, action_id, template_arg, args):
    return await _parented(config, action_id, template_arg)


@automation.register_action("leyla_voice.stop", StopAction, ACTION_SCHEMA, synchronous=True)
async def stop_to_code(config, action_id, template_arg, args):
    return await _parented(config, action_id, template_arg)


@automation.register_action("leyla_voice.interrupt", InterruptAction, ACTION_SCHEMA, synchronous=True)
async def interrupt_to_code(config, action_id, template_arg, args):
    return await _parented(config, action_id, template_arg)


@automation.register_condition("leyla_voice.is_running", IsRunningCondition, ACTION_SCHEMA)
async def is_running_to_code(config, condition_id, template_arg, args):
    return await _parented(config, condition_id, template_arg)


@automation.register_condition("leyla_voice.is_bot_speaking", IsBotSpeakingCondition, ACTION_SCHEMA)
async def is_bot_speaking_to_code(config, condition_id, template_arg, args):
    return await _parented(config, condition_id, template_arg)
