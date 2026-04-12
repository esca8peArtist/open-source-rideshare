/// Maps to backend DriverProfileResponse schema.

class DriverProfile {
  final int id;
  final int userId;
  final String vehicleType;
  final String vehicleMake;
  final String vehicleModel;
  final int vehicleYear;
  final String vehicleColor;
  final String licensePlate;
  final bool isOnline;
  final bool isApproved;
  final double ratingAvg;
  final int totalTrips;

  const DriverProfile({
    required this.id,
    required this.userId,
    required this.vehicleType,
    required this.vehicleMake,
    required this.vehicleModel,
    required this.vehicleYear,
    required this.vehicleColor,
    required this.licensePlate,
    required this.isOnline,
    required this.isApproved,
    required this.ratingAvg,
    required this.totalTrips,
  });

  factory DriverProfile.fromJson(Map<String, dynamic> json) => DriverProfile(
        id: json['id'] as int,
        userId: json['user_id'] as int,
        vehicleType: json['vehicle_type'] as String,
        vehicleMake: json['vehicle_make'] as String,
        vehicleModel: json['vehicle_model'] as String,
        vehicleYear: json['vehicle_year'] as int,
        vehicleColor: json['vehicle_color'] as String,
        licensePlate: json['license_plate'] as String,
        isOnline: json['is_online'] as bool,
        isApproved: json['is_approved'] as bool,
        ratingAvg: (json['rating_avg'] as num).toDouble(),
        totalTrips: json['total_trips'] as int,
      );

  String get vehicleDescription =>
      '$vehicleColor $vehicleYear $vehicleMake $vehicleModel';
}
