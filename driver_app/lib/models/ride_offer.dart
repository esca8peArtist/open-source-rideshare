/// A ride offer pushed to the driver via WebSocket.
/// Maps to the `send_ride_offer` message from backend/app/api/websocket.py.

class RideOffer {
  final int rideId;
  final String pickupAddress;
  final String dropoffAddress;
  final double estimatedFare;
  final double pickupDistanceKm;
  final int timeoutSeconds;
  final DateTime receivedAt;

  const RideOffer({
    required this.rideId,
    required this.pickupAddress,
    required this.dropoffAddress,
    required this.estimatedFare,
    required this.pickupDistanceKm,
    required this.timeoutSeconds,
    required this.receivedAt,
  });

  factory RideOffer.fromJson(Map<String, dynamic> json) => RideOffer(
        rideId: json['ride_id'] as int,
        pickupAddress: json['pickup_address'] as String,
        dropoffAddress: json['dropoff_address'] as String,
        estimatedFare: (json['estimated_fare'] as num).toDouble(),
        pickupDistanceKm: (json['pickup_distance_km'] as num).toDouble(),
        timeoutSeconds: json['timeout_seconds'] as int,
        receivedAt: DateTime.now(),
      );

  /// Seconds remaining before this offer expires.
  int secondsRemaining() {
    final elapsed = DateTime.now().difference(receivedAt).inSeconds;
    final remaining = timeoutSeconds - elapsed;
    return remaining > 0 ? remaining : 0;
  }

  bool get isExpired => secondsRemaining() <= 0;
}
