# Rideshare Rider App

Flutter mobile app for riders.

## Setup

```bash
# Install Flutter (https://flutter.dev/docs/get-started/install)
flutter --version  # Requires 3.2+

# Generate platform projects (run once)
flutter create --org org.rideshare . --platforms android,ios,web

# Install dependencies
flutter pub get

# Run
flutter run
```

## Architecture

- **Riverpod** for state management
- **GoRouter** for navigation
- **Dio** for HTTP with automatic token refresh
- **flutter_map** + OpenStreetMap tiles (no Google Maps dependency)
- **WebSocket** for real-time ride status updates

## Key Files

```
lib/
  main.dart              # App entry point
  router.dart            # Route definitions with auth guard
  config.dart            # API/WS URLs
  models/
    ride.dart            # Ride, FareEstimate, LocationPoint, RideStatus
    user.dart            # User, AuthTokens
  services/
    api_client.dart      # HTTP client with auth interceptor
    ride_service.dart    # Ride API calls
    websocket_service.dart  # Real-time connection
    location_service.dart   # GPS access
  providers/
    auth_provider.dart   # Login/register/logout state
    ride_provider.dart   # Ride request/tracking state + WebSocket listener
  screens/
    login_screen.dart    # Auth screen (login + register)
    home_screen.dart     # Map + location search + fare estimate
    ride_tracking_screen.dart  # Live ride status
  widgets/
    fare_estimate_card.dart    # Bottom sheet with fare + request button
    location_search_bar.dart   # Address input
```

## Environment

Pass API URLs at build time:

```bash
flutter run --dart-define=API_BASE_URL=https://api.rideshare.coop/api/v1 \
            --dart-define=WS_BASE_URL=wss://api.rideshare.coop
```
