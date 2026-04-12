class LocationPoint {
  final double lat;
  final double lng;

  const LocationPoint({required this.lat, required this.lng});

  factory LocationPoint.fromJson(Map<String, dynamic> json) => LocationPoint(
        lat: (json['lat'] as num).toDouble(),
        lng: (json['lng'] as num).toDouble(),
      );

  Map<String, dynamic> toJson() => {'lat': lat, 'lng': lng};
}

enum RideStatus {
  requested,
  matched,
  driverEnRoute,
  arrived,
  inProgress,
  completed,
  cancelled;

  static RideStatus fromString(String s) {
    switch (s) {
      case 'requested':
        return requested;
      case 'matched':
        return matched;
      case 'driver_en_route':
        return driverEnRoute;
      case 'arrived':
        return arrived;
      case 'in_progress':
        return inProgress;
      case 'completed':
        return completed;
      case 'cancelled':
        return cancelled;
      default:
        throw ArgumentError('Unknown ride status: $s');
    }
  }
}

class Ride {
  final int id;
  final RideStatus status;
  final String pickupAddress;
  final String dropoffAddress;
  final double estimatedFare;
  final double? actualFare;
  final String? driverName;
  final double? driverRating;
  final String? vehicleInfo;
  final DateTime requestedAt;
  final DateTime? matchedAt;
  final DateTime? startedAt;
  final DateTime? completedAt;

  const Ride({
    required this.id,
    required this.status,
    required this.pickupAddress,
    required this.dropoffAddress,
    required this.estimatedFare,
    this.actualFare,
    this.driverName,
    this.driverRating,
    this.vehicleInfo,
    required this.requestedAt,
    this.matchedAt,
    this.startedAt,
    this.completedAt,
  });

  factory Ride.fromJson(Map<String, dynamic> json) => Ride(
        id: json['id'] as int,
        status: RideStatus.fromString(json['status'] as String),
        pickupAddress: json['pickup_address'] as String,
        dropoffAddress: json['dropoff_address'] as String,
        estimatedFare: (json['estimated_fare'] as num).toDouble(),
        actualFare: (json['actual_fare'] as num?)?.toDouble(),
        driverName: json['driver_name'] as String?,
        driverRating: (json['driver_rating'] as num?)?.toDouble(),
        vehicleInfo: json['vehicle_info'] as String?,
        requestedAt: DateTime.parse(json['requested_at'] as String),
        matchedAt: json['matched_at'] != null
            ? DateTime.parse(json['matched_at'] as String)
            : null,
        startedAt: json['started_at'] != null
            ? DateTime.parse(json['started_at'] as String)
            : null,
        completedAt: json['completed_at'] != null
            ? DateTime.parse(json['completed_at'] as String)
            : null,
      );
}

class FareEstimate {
  final double estimatedFare;
  final double distanceKm;
  final double durationMin;
  final String currency;

  const FareEstimate({
    required this.estimatedFare,
    required this.distanceKm,
    required this.durationMin,
    this.currency = 'USD',
  });

  factory FareEstimate.fromJson(Map<String, dynamic> json) => FareEstimate(
        estimatedFare: (json['estimated_fare'] as num).toDouble(),
        distanceKm: (json['distance_km'] as num).toDouble(),
        durationMin: (json['duration_min'] as num).toDouble(),
        currency: json['currency'] as String? ?? 'USD',
      );
}
