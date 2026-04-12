class AppConfig {
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://localhost:8000/api/v1',
  );

  static const wsBaseUrl = String.fromEnvironment(
    'WS_BASE_URL',
    defaultValue: 'ws://localhost:8000',
  );

  /// How often the driver streams location updates (in seconds).
  static const locationStreamIntervalSeconds = 5;

  /// Ride offer countdown duration (in seconds).
  static const rideOfferTimeoutSeconds = 30;
}
