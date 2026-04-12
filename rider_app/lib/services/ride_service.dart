import 'package:rideshare_rider/models/ride.dart';
import 'package:rideshare_rider/services/api_client.dart';

class RideService {
  final ApiClient _api;

  RideService(this._api);

  Future<FareEstimate> getFareEstimate(
      LocationPoint pickup, LocationPoint dropoff) async {
    final response = await _api.post('/rides/estimate', data: {
      'pickup': pickup.toJson(),
      'dropoff': dropoff.toJson(),
    });
    return FareEstimate.fromJson(response.data);
  }

  Future<Ride> requestRide({
    required LocationPoint pickup,
    required LocationPoint dropoff,
    required String pickupAddress,
    required String dropoffAddress,
  }) async {
    final response = await _api.post('/rides/request', data: {
      'pickup': pickup.toJson(),
      'dropoff': dropoff.toJson(),
      'pickup_address': pickupAddress,
      'dropoff_address': dropoffAddress,
    });
    return Ride.fromJson(response.data);
  }

  Future<List<Ride>> getRideHistory({int limit = 20, int offset = 0}) async {
    final response = await _api.get('/rides/history', params: {
      'limit': limit,
      'offset': offset,
    });
    return (response.data as List)
        .map((json) => Ride.fromJson(json as Map<String, dynamic>))
        .toList();
  }

  Future<Ride> getRide(int rideId) async {
    final response = await _api.get('/rides/$rideId');
    return Ride.fromJson(response.data);
  }

  Future<void> cancelRide(int rideId, {String? reason}) async {
    await _api.post('/rides/$rideId/cancel', data: {
      if (reason != null) 'reason': reason,
    });
  }

  Future<void> rateRide(int rideId, int rating, {double tipAmount = 0}) async {
    await _api.post('/rides/$rideId/rate', data: {
      'rating': rating,
      'tip_amount': tipAmount,
    });
  }

  Future<void> addTip(int rideId, double amount) async {
    await _api.post('/payments/$rideId/tip', data: {
      'amount': amount,
    });
  }
}
