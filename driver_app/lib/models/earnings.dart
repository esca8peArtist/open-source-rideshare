/// Maps to backend EarningsResponse / EarningsSummary / EarningsTrip schemas.

class EarningsSummary {
  final double totalFares;
  final double totalTips;
  final double totalEarnings;
  final int tripCount;
  final double averageFare;
  final double averageTip;
  final DateTime periodStart;
  final DateTime periodEnd;

  const EarningsSummary({
    required this.totalFares,
    required this.totalTips,
    required this.totalEarnings,
    required this.tripCount,
    required this.averageFare,
    required this.averageTip,
    required this.periodStart,
    required this.periodEnd,
  });

  factory EarningsSummary.fromJson(Map<String, dynamic> json) =>
      EarningsSummary(
        totalFares: (json['total_fares'] as num).toDouble(),
        totalTips: (json['total_tips'] as num).toDouble(),
        totalEarnings: (json['total_earnings'] as num).toDouble(),
        tripCount: json['trip_count'] as int,
        averageFare: (json['average_fare'] as num).toDouble(),
        averageTip: (json['average_tip'] as num).toDouble(),
        periodStart: DateTime.parse(json['period_start'] as String),
        periodEnd: DateTime.parse(json['period_end'] as String),
      );
}

class EarningsTrip {
  final int rideId;
  final String pickupAddress;
  final String dropoffAddress;
  final double fare;
  final double tip;
  final double total;
  final double? distanceKm;
  final double? durationMin;
  final DateTime? completedAt;

  const EarningsTrip({
    required this.rideId,
    required this.pickupAddress,
    required this.dropoffAddress,
    required this.fare,
    required this.tip,
    required this.total,
    this.distanceKm,
    this.durationMin,
    this.completedAt,
  });

  factory EarningsTrip.fromJson(Map<String, dynamic> json) => EarningsTrip(
        rideId: json['ride_id'] as int,
        pickupAddress: json['pickup_address'] as String,
        dropoffAddress: json['dropoff_address'] as String,
        fare: (json['fare'] as num).toDouble(),
        tip: (json['tip'] as num).toDouble(),
        total: (json['total'] as num).toDouble(),
        distanceKm: (json['distance_km'] as num?)?.toDouble(),
        durationMin: (json['duration_min'] as num?)?.toDouble(),
        completedAt: json['completed_at'] != null
            ? DateTime.parse(json['completed_at'] as String)
            : null,
      );
}

class EarningsResponse {
  final EarningsSummary summary;
  final List<EarningsTrip> trips;

  const EarningsResponse({required this.summary, required this.trips});

  factory EarningsResponse.fromJson(Map<String, dynamic> json) =>
      EarningsResponse(
        summary: EarningsSummary.fromJson(
            json['summary'] as Map<String, dynamic>),
        trips: (json['trips'] as List<dynamic>)
            .map((e) => EarningsTrip.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}
