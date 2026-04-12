import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:rideshare_driver/models/driver_profile.dart';
import 'package:rideshare_driver/models/earnings.dart';
import 'package:rideshare_driver/models/ride.dart';
import 'package:rideshare_driver/models/ride_offer.dart';
import 'package:rideshare_driver/providers/auth_provider.dart';
import 'package:rideshare_driver/services/api_client.dart';
import 'package:rideshare_driver/services/location_service.dart';
import 'package:rideshare_driver/services/websocket_service.dart';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

class DriverState {
  final bool isOnline;
  final DriverProfile? profile;
  final Ride? currentRide;
  final RideOffer? pendingOffer;
  final EarningsResponse? earnings;
  final LocationPoint? currentLocation;
  final bool isLoading;
  final String? error;

  const DriverState({
    this.isOnline = false,
    this.profile,
    this.currentRide,
    this.pendingOffer,
    this.earnings,
    this.currentLocation,
    this.isLoading = false,
    this.error,
  });

  DriverState copyWith({
    bool? isOnline,
    DriverProfile? profile,
    Ride? currentRide,
    RideOffer? pendingOffer,
    EarningsResponse? earnings,
    LocationPoint? currentLocation,
    bool? isLoading,
    String? error,
    bool clearRide = false,
    bool clearOffer = false,
    bool clearError = false,
  }) =>
      DriverState(
        isOnline: isOnline ?? this.isOnline,
        profile: profile ?? this.profile,
        currentRide: clearRide ? null : (currentRide ?? this.currentRide),
        pendingOffer: clearOffer ? null : (pendingOffer ?? this.pendingOffer),
        earnings: earnings ?? this.earnings,
        currentLocation: currentLocation ?? this.currentLocation,
        isLoading: isLoading ?? this.isLoading,
        error: clearError ? null : (error ?? this.error),
      );
}

// ---------------------------------------------------------------------------
// Notifier
// ---------------------------------------------------------------------------

class DriverNotifier extends StateNotifier<DriverState> {
  final ApiClient _api;
  final WebSocketService _ws;
  final LocationService _locationService;

  StreamSubscription? _wsSubscription;
  StreamSubscription? _locationSubscription;

  DriverNotifier(this._api, this._ws, this._locationService)
      : super(const DriverState()) {
    _listenToWebSocket();
  }

  // ── WebSocket listener ──────────────────────────────────────────────

  void _listenToWebSocket() {
    _wsSubscription = _ws.messages.listen((message) {
      final type = message['type'] as String?;

      switch (type) {
        case 'ride_offer':
          _handleRideOffer(message);
        case 'accept_ack':
          _handleAcceptAck(message);
        case 'ride_status':
          _handleRideStatus(message);
        case 'location_ack':
          // Location acknowledged — nothing to do
          break;
      }
    });
  }

  void _handleRideOffer(Map<String, dynamic> message) {
    final offer = RideOffer.fromJson(message);
    state = state.copyWith(pendingOffer: offer);
  }

  void _handleAcceptAck(Map<String, dynamic> message) {
    final accepted = message['accepted'] as bool;
    if (accepted) {
      // The ride is now assigned to us — fetch full ride details
      final rideId = message['ride_id'] as int;
      _fetchCurrentRide(rideId);
    }
    state = state.copyWith(clearOffer: true);
  }

  void _handleRideStatus(Map<String, dynamic> message) {
    if (state.currentRide == null) return;
    final newStatus = RideStatus.fromString(message['status'] as String);
    state = state.copyWith(
      currentRide: state.currentRide!.copyWith(status: newStatus),
    );
  }

  // ── Online / Offline toggle ─────────────────────────────────────────

  Future<void> goOnline() async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      await _api.goOnline();
      await _ws.connect();
      _startLocationStreaming();
      state = state.copyWith(isOnline: true, isLoading: false);
    } catch (e) {
      state = state.copyWith(
          isLoading: false, error: 'Could not go online. Try again.');
    }
  }

  Future<void> goOffline() async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      _stopLocationStreaming();
      await _api.goOffline();
      await _ws.disconnect();
      state = state.copyWith(isOnline: false, isLoading: false);
    } catch (e) {
      state = state.copyWith(
          isLoading: false, error: 'Could not go offline. Try again.');
    }
  }

  // ── Location streaming ──────────────────────────────────────────────

  void _startLocationStreaming() {
    _locationSubscription?.cancel();
    _locationSubscription = _locationService.getLocationStream().listen(
      (point) {
        state = state.copyWith(currentLocation: point);
        // Push to backend via both REST (for DB persistence) and WS (for
        // real-time matching engine update).
        _api.updateLocation(point.lat, point.lng);
        _ws.sendLocationUpdate(point.lat, point.lng);
      },
    );
  }

  void _stopLocationStreaming() {
    _locationSubscription?.cancel();
    _locationSubscription = null;
  }

  // ── Ride offer handling ─────────────────────────────────────────────

  void acceptOffer() {
    final offer = state.pendingOffer;
    if (offer == null || offer.isExpired) return;
    _ws.sendAcceptRide(offer.rideId);
  }

  void declineOffer() {
    state = state.copyWith(clearOffer: true);
  }

  // ── Ride lifecycle ──────────────────────────────────────────────────

  Future<void> _fetchCurrentRide(int rideId) async {
    try {
      final response = await _api.getRide(rideId);
      final ride = Ride.fromJson(response.data as Map<String, dynamic>);
      state = state.copyWith(currentRide: ride);
    } catch (e) {
      state = state.copyWith(error: 'Could not load ride details.');
    }
  }

  Future<void> markEnRoute() async {
    if (state.currentRide == null) return;
    try {
      await _api.updateRideStatus(
          state.currentRide!.id, 'driver_en_route');
      state = state.copyWith(
        currentRide:
            state.currentRide!.copyWith(status: RideStatus.driverEnRoute),
      );
    } catch (e) {
      state = state.copyWith(error: 'Could not update ride status.');
    }
  }

  Future<void> markArrived() async {
    if (state.currentRide == null) return;
    try {
      await _api.updateRideStatus(state.currentRide!.id, 'arrived');
      state = state.copyWith(
        currentRide:
            state.currentRide!.copyWith(status: RideStatus.arrived),
      );
    } catch (e) {
      state = state.copyWith(error: 'Could not update ride status.');
    }
  }

  Future<void> startRide() async {
    if (state.currentRide == null) return;
    try {
      await _api.updateRideStatus(state.currentRide!.id, 'in_progress');
      state = state.copyWith(
        currentRide: state.currentRide!.copyWith(
          status: RideStatus.inProgress,
          startedAt: DateTime.now(),
        ),
      );
    } catch (e) {
      state = state.copyWith(error: 'Could not start ride.');
    }
  }

  Future<void> completeRide() async {
    if (state.currentRide == null) return;
    try {
      await _api.updateRideStatus(state.currentRide!.id, 'completed');
      state = state.copyWith(
        currentRide: state.currentRide!.copyWith(
          status: RideStatus.completed,
          completedAt: DateTime.now(),
        ),
      );
    } catch (e) {
      state = state.copyWith(error: 'Could not complete ride.');
    }
  }

  void clearCurrentRide() {
    state = state.copyWith(clearRide: true);
  }

  // ── Earnings ────────────────────────────────────────────────────────

  Future<void> loadEarnings({String period = 'week'}) async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final response = await _api.getEarnings(period: period);
      final earnings =
          EarningsResponse.fromJson(response.data as Map<String, dynamic>);
      state = state.copyWith(earnings: earnings, isLoading: false);
    } catch (e) {
      state =
          state.copyWith(isLoading: false, error: 'Could not load earnings.');
    }
  }

  // ── Cleanup ─────────────────────────────────────────────────────────

  @override
  void dispose() {
    _wsSubscription?.cancel();
    _locationSubscription?.cancel();
    super.dispose();
  }
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------

final webSocketProvider = Provider((ref) => WebSocketService());

final locationServiceProvider = Provider((ref) => LocationService());

final driverProvider =
    StateNotifierProvider<DriverNotifier, DriverState>((ref) {
  final api = ref.read(apiClientProvider);
  final ws = ref.read(webSocketProvider);
  final location = ref.read(locationServiceProvider);
  return DriverNotifier(api, ws, location);
});
