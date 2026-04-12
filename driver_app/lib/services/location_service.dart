import 'dart:async';

import 'package:geolocator/geolocator.dart';
import 'package:rideshare_driver/models/ride.dart';

/// Handles GPS permissions and provides a continuous position stream
/// tuned for driver usage (higher frequency than rider app, lower
/// distance filter for smoother tracking).
class LocationService {
  Future<bool> checkPermission() async {
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) return false;

    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.deniedForever) return false;

    return permission == LocationPermission.whileInUse ||
        permission == LocationPermission.always;
  }

  Future<LocationPoint?> getCurrentLocation() async {
    if (!await checkPermission()) return null;

    final position = await Geolocator.getCurrentPosition(
      desiredAccuracy: LocationAccuracy.high,
    );
    return LocationPoint(lat: position.latitude, lng: position.longitude);
  }

  /// Returns a continuous stream of driver positions.
  ///
  /// Uses a 5-meter distance filter (tighter than rider's 10m) so the
  /// backend receives frequent updates for accurate matching.
  Stream<LocationPoint> getLocationStream() {
    return Geolocator.getPositionStream(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 5,
      ),
    ).map((p) => LocationPoint(lat: p.latitude, lng: p.longitude));
  }
}
