/// Shared ride model — mirrors the rider app's Ride model so both apps
/// speak the same backend schema.

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

  String toApiString() {
    switch (this) {
      case requested:
        return 'requested';
      case matched:
        return 'matched';
      case driverEnRoute:
        return 'driver_en_route';
      case arrived:
        return 'arrived';
      case inProgress:
        return 'in_progress';
      case completed:
        return 'completed';
      case cancelled:
        return 'cancelled';
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
  final String? riderName;
  final String? riderPhone;
  final LocationPoint? pickupLocation;
  final LocationPoint? dropoffLocation;
  final double? distanceKm;
  final double? durationMin;
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
    this.riderName,
    this.riderPhone,
    this.pickupLocation,
    this.dropoffLocation,
    this.distanceKm,
    this.durationMin,
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
        riderName: json['rider_name'] as String?,
        riderPhone: json['rider_phone'] as String?,
        pickupLocation: json['pickup'] != null
            ? LocationPoint.fromJson(json['pickup'] as Map<String, dynamic>)
            : null,
        dropoffLocation: json['dropoff'] != null
            ? LocationPoint.fromJson(json['dropoff'] as Map<String, dynamic>)
            : null,
        distanceKm: (json['distance_km'] as num?)?.toDouble(),
        durationMin: (json['duration_min'] as num?)?.toDouble(),
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

  Ride copyWith({
    RideStatus? status,
    double? actualFare,
    DateTime? matchedAt,
    DateTime? startedAt,
    DateTime? completedAt,
  }) =>
      Ride(
        id: id,
        status: status ?? this.status,
        pickupAddress: pickupAddress,
        dropoffAddress: dropoffAddress,
        estimatedFare: estimatedFare,
        actualFare: actualFare ?? this.actualFare,
        riderName: riderName,
        riderPhone: riderPhone,
        pickupLocation: pickupLocation,
        dropoffLocation: dropoffLocation,
        distanceKm: distanceKm,
        durationMin: durationMin,
        requestedAt: requestedAt,
        matchedAt: matchedAt ?? this.matchedAt,
        startedAt: startedAt ?? this.startedAt,
        completedAt: completedAt ?? this.completedAt,
      );
}
