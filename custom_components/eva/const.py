"""Constants for the personal Eva test integration."""

DOMAIN = "eva"
CLIENT_ID = "HomeAssistant-0.1.1-personal-test"
CLIENT_BRAND = "eva"
SCHEMA_VERSION = 7
STREAM_IDLE_TIMEOUT = 15
STREAM_REFRESH_INTERVAL = 9 * 60  # Reopen before the API's 10-minute expiry.
INITIAL_SNAPSHOT_TIMEOUT = 35
CONF_ENVIRONMENT = "environment"
CONF_HOME_ID = "home_id"
CONF_SSE_CLIENT_ID = "sse_client_id"
ENVIRONMENTS = {
    "test": "https://home-hla.smarthome-test.datek.io",
    "qa": "https://home-hla.smarthome-qa.datek.io",
    "prod": "https://home.api.evasmart.no",
}
ENVIRONMENT_NAMES = {"test": "Test", "qa": "QA", "prod": "Prod"}
