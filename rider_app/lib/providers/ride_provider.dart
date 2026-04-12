import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:rideshare_rider/models/ride.dart';
import 'package:rideshare_rider/providers/auth_provider.dart';
import 'package:rideshare_rider/services/ride_service.dart';
import 'package:rideshare_rider/services/websocket_service.dart';

class RideState {
  final Ride? activeRide;
  final FareEstimate? fareEstimate;
  final bool isLoading;
  final String? error;

  const RideState({
    this.activeRide,
    this.fareEstimate,
    this.isLoading = false,
    this.error,
  });

  RideState copyWith({
    Ride? activeRide,
    FareEstimate? fareEstimate,
    bool? isLoading,
    String? error,
    bool clearRide = false,
    bool clearEstimate = false,
  }) =>
      RideState(
        activeRide: clearRide ? null : (activeRide ?? this.activeRide),
        fareEstimate:
            clearEstimate ? null : (fareEstimate ?? this.fareEstimate),
        isLoading: isLoading ?? this.isLoading,
        error: error,
      );
}

class RideNotifier extends StateNotifier<RideState> {
  final RideService _rideService;
  final WebSocketService _ws;
  StreamSubscription? _wsSubscription;

  RideNotifier(this._rideService, this._ws) : super(const RideState()) {
    _listenToWebSocket();
  }

  void _listenToWebSocket() {
    _wsSubscription = _ws.messages.listen((message) {
      final type = message['type'] as String?;
      if (type == 'ride_status' && state.activeRide != null) {
        final newStatus = RideStatus.fromString(message['status'] as String);
        state = state.copyWith(
          activeRide: Ride(
            id: state.activeRide!.id,
            status: newStatus,
            pickupAddress: state.activeRide!.pickupAddress,
            dropoffAddress: state.activeRide!.dropoffAddress,
            estimatedFare: state.activeRide!.estimatedFare,
            actualFare: state.activeRide!.actualFare,
            driverName: message['driver_name'] as String? ??
                state.activeRide!.driverName,
            driverRating: state.activeRide!.driverRating,
            vehicleInfo: state.activeRide!.vehicleInfo,
            requestedAt: state.activeRide!.requestedAt,
            matchedAt: state.activeRide!.matchedAt,
            startedAt: state.activeRide!.startedAt,
            completedAt: state.activeRide!.completedAt,
          ),
        );
      }
    });
  }

  Future<void> estimateFare(
      LocationPoint pickup, LocationPoint dropoff) async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final estimate = await _rideService.getFareEstimate(pickup, dropoff);
      state = state.copyWith(fareEstimate: estimate, isLoading: false);
    } catch (e) {
      state = state.copyWith(
          isLoading: false, error: 'Could not get fare estimate');
    }
  }

  Future<void> requestRide({
    required LocationPoint pickup,
    required LocationPoint dropoff,
    required String pickupAddress,
    required String dropoffAddress,
  }) async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final ride = await _rideService.requestRide(
        pickup: pickup,
        dropoff: dropoff,
        pickupAddress: pickupAddress,
        dropoffAddress: dropoffAddress,
      );
      state = state.copyWith(activeRide: ride, isLoading: false);
    } catch (e) {
      state =
          state.copyWith(isLoading: false, error: 'Could not request ride');
    }
  }

  Future<void> cancelRide({String? reason}) async {
    if (state.activeRide == null) return;
    try {
      await _rideService.cancelRide(state.activeRide!.id, reason: reason);
      state = state.copyWith(clearRide: true, clearEstimate: true);
    } catch (e) {
      state = state.copyWith(error: 'Could not cancel ride');
    }
  }

  void clearState() {
    state = const RideState();
  }

  @override
  void dispose() {
    _wsSubscription?.cancel();
    super.dispose();
  }
}

final webSocketProvider = Provider((ref) => WebSocketService());

final rideServiceProvider = Provider((ref) {
  final api = ref.read(apiClientProvider);
  return RideService(api);
});

final rideProvider = StateNotifierProvider<RideNotifier, RideState>((ref) {
  final rideService = ref.read(rideServiceProvider);
  final ws = ref.read(webSocketProvider);
  return RideNotifier(rideService, ws);
});
