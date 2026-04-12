import warnings

from pydantic_settings import BaseSettings


_DEFAULT_JWT_SECRET = "CHANGE-ME-IN-PRODUCTION"


class Settings(BaseSettings):
    app_name: str = "OpenRide"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://openride:openride@localhost:5432/openride"
    redis_url: str = "redis://localhost:6379/0"

    osrm_url: str = "http://localhost:5000"
    nominatim_url: str = "https://nominatim.openstreetmap.org"

    # CORS: comma-separated allowed origins, e.g. "https://admin.openride.coop,https://app.openride.coop"
    # In debug mode, all origins are allowed regardless of this setting.
    allowed_origins: str = ""

    jwt_secret_key: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    sms_provider: str = "twilio"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    email_provider: str = "sendgrid"
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@openride.coop"
    sendgrid_from_name: str = "OpenRide"

    # Notification feature flags
    notifications_sms_enabled: bool = False   # enable once Twilio credentials configured
    notifications_email_enabled: bool = False  # enable once SendGrid credentials configured
    notifications_push_enabled: bool = False   # enable once Firebase configured

    driver_search_radius_km: float = 8.0
    driver_search_initial_radius_km: float = 2.0
    ride_offer_timeout_seconds: int = 15
    max_ride_offers: int = 3
    driver_location_update_interval_seconds: int = 5
    driver_location_ttl_seconds: int = 30

    base_fare: float = 2.50
    per_km_rate: float = 1.50
    per_minute_rate: float = 0.25
    minimum_fare: float = 5.00

    # Rate limiting (requests per window)
    rate_limit_login: int = 5
    rate_limit_login_window: int = 60  # seconds
    rate_limit_register: int = 3
    rate_limit_register_window: int = 60
    rate_limit_ride_request: int = 10
    rate_limit_ride_request_window: int = 60
    rate_limit_location_update: int = 120
    rate_limit_location_update_window: int = 60

    # Scheduled rides
    schedule_min_advance_minutes: int = 30   # must schedule at least 30 min ahead
    schedule_max_advance_hours: int = 168    # up to 7 days ahead
    schedule_dispatch_before_minutes: int = 15  # start matching 15 min before pickup
    dispatch_check_interval_seconds: int = 30   # how often the scheduler checks for due rides
    dispatch_max_retries: int = 5               # max times to retry matching an unmatched ride
    dispatch_retry_interval_seconds: int = 60   # base interval between retries
    dispatch_retry_backoff: float = 1.5         # multiplier applied per retry (exponential backoff)

    # Demand pricing (transparent supply/demand-based fare adjustments)
    demand_pricing_enabled: bool = True          # cooperatives can disable entirely
    demand_pricing_max_multiplier: float = 1.5   # hard cap — cooperative policy (e.g. 1.5 = max 50% increase)
    demand_pricing_threshold: float = 2.0        # demand/supply ratio below which no adjustment applies
    demand_pricing_scale_factor: float = 0.25    # multiplier increase per unit of ratio above threshold

    # WebSocket heartbeat
    ws_heartbeat_interval_seconds: int = 30  # server pings every N seconds
    ws_heartbeat_timeout_seconds: int = 10   # client must pong within N seconds

    # Checkr background check integration
    checkr_api_key: str = ""
    checkr_webhook_secret: str = ""
    checkr_default_package: str = "driver_pro"

    # Firebase Cloud Messaging (push notifications)
    firebase_credentials_json: str = ""  # path to service account JSON
    firebase_project_id: str = ""

    model_config = {"env_prefix": "OPENRIDE_", "env_file": ".env"}


settings = Settings()

# Warn loudly if running with the default JWT secret outside debug mode.
if not settings.debug and settings.jwt_secret_key == _DEFAULT_JWT_SECRET:
    warnings.warn(
        "SECURITY: OPENRIDE_JWT_SECRET_KEY is set to the default value. "
        "Set a strong, unique secret via environment variable before deploying.",
        stacklevel=1,
    )
