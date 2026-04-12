import 'package:geolocator/geolocator.dart';
import 'package:rideshare_rider/models/ride.dart';

class LocationService {
  Future<bool> checkPermission() async {
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
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

  Stream<LocationPoint> getLocationStream() {
    return Geolocator.getPositionStream(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 10,
      ),
    ).map((p) => LocationPoint(lat: p.latitude, lng: p.longitude));
  }
}
