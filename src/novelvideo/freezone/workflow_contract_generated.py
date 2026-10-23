"""Generated from schemas/workflow/v1/stable-contract.json; do not edit."""

SOURCE_SHA256 = "1d3add9e7fc736e3ae534db40069e84882b9f00159bcb1bdf22e04a48c5f1666"
WORKFLOW_CONTRACT_SCHEMA_VERSION = "freezone_workflow_contract.v1"
WORKFLOW_PLAN_SCHEMA_VERSION = "freezone_workflow_plan.v1"
WORKFLOW_INTENT_SCHEMA_VERSION = "freezone_workflow_intent.v1"
WORKFLOW_NODE_TYPES = [
    "textAnnotationNode",
    "scriptNode",
    "beatContextNode",
    "imageGenNode",
    "videoNode",
    "audioNode",
    "htmlArtifactNode",
    "videoComposeNode",
]
AGENT_CREATABLE_NODE_TYPES = [
    "uploadNode",
    "imageGenNode",
    "beatContextNode",
    "textAnnotationNode",
    "videoNode",
    "audioNode",
    "videoComposeNode",
    "scriptNode",
    "pano360ViewerNode",
    "threeDWorldNode",
    "skillNode",
    "htmlArtifactNode",
]
WORKFLOW_LINK_TYPES = [
    "context_for",
    "prompt_for",
    "dependency_for",
    "media_input_for",
    "derived_from",
    "composition_input_for",
]
GENERATION_ACTION_TYPES = [
    "generate_text",
    "generate_story_script",
    "generate_image",
    "generate_video",
    "generate_text_video",
    "generate_audio",
    "generate_3gs_world",
    "auto_compose_video",
]
MODEL_ALIASES_BY_NODE_TYPE = {
    "imageGenNode": {
        "nano-banana-2": "nano-banana-2",
        "nanobanana2": "nano-banana-2",
        "nano_banana_2": "nano-banana-2",
        "gpt-image-2": "gpt-image-2",
        "openai/gpt-image-2": "gpt-image-2",
    },
    "videoNode": {
        "omni-flash": "seedance-2.0-fast",
        "omni_flash": "seedance-2.0-fast",
        "seedance_2_0_fast": "seedance-2.0-fast",
        "seedance-2.0-fast": "seedance-2.0-fast",
        "seedance-2.0": "seedance-2.0",
        "seedance-1.5-pro": "seedance-1.5-pro",
        "seedance-1.0-pro-fast": "seedance-1.0-pro-fast",
        "huimeng_seedance-2.0-fast": "seedance-2.0-fast",
        "huimeng_seedance-2.0": "seedance-2.0",
        "huimeng_seedance-1.5-pro": "seedance-1.5-pro",
        "huimeng_seedance-1.0-pro-fast": "seedance-1.0-pro-fast",
        "seedance-2.0-fast": "seedance-2.0-fast",
        "seedance-2.0": "seedance-2.0",
        "seedance-1.5-pro": "seedance-1.5-pro",
        "seedance-1.0-pro-fast": "seedance-1.0-pro-fast",
    },
}
RECIPE_ENVELOPE_CONTRACT = {
    "schema_version": "dramaclaw.recipe.v1",
    "required": [
        "id",
        "name",
        "output_kind",
        "action_keys",
        "system_prompt",
        "planning_prompt",
        "result_summary",
    ],
    "identifier_fields": ["id", "action_keys", "conflicts_with"],
    "version_fields": ["schema_version", "version"],
}
