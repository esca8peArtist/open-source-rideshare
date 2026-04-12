import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:rideshare_driver/config.dart';

class ApiClient {
  late final Dio _dio;
  final FlutterSecureStorage _storage;

  ApiClient({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage() {
    _dio = Dio(BaseOptions(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 10),
      headers: {'Content-Type': 'application/json'},
    ));

    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) async {
        final token = await _storage.read(key: 'access_token');
        if (token != null) {
          options.headers['Authorization'] = 'Bearer $token';
        }
        handler.next(options);
      },
      onError: (error, handler) async {
        if (error.response?.statusCode == 401) {
          final refreshed = await _refreshToken();
          if (refreshed) {
            final retryResponse = await _dio.fetch(error.requestOptions);
            return handler.resolve(retryResponse);
          }
        }
        handler.next(error);
      },
    ));
  }

  Future<bool> _refreshToken() async {
    final refreshToken = await _storage.read(key: 'refresh_token');
    if (refreshToken == null) return false;

    try {
      final response = await Dio(BaseOptions(baseUrl: AppConfig.apiBaseUrl))
          .post(
        '/auth/refresh',
        data: {'refresh_token': refreshToken},
      );
      await _storage.write(
        key: 'access_token',
        value: response.data['access_token'],
      );
      await _storage.write(
        key: 'refresh_token',
        value: response.data['refresh_token'],
      );
      return true;
    } catch (_) {
      await _storage.deleteAll();
      return false;
    }
  }

  // ── Generic HTTP helpers ──────────────────────────────────────────

  Future<Response> get(String path, {Map<String, dynamic>? params}) =>
      _dio.get(path, queryParameters: params);

  Future<Response> post(String path, {dynamic data}) =>
      _dio.post(path, data: data);

  Future<Response> put(String path, {dynamic data}) =>
      _dio.put(path, data: data);

  Future<Response> delete(String path) => _dio.delete(path);

  // ── Driver-specific endpoints ─────────────────────────────────────

  /// POST /driver/go-online
  Future<Response> goOnline() => post('/driver/go-online');

  /// POST /driver/go-offline
  Future<Response> goOffline() => post('/driver/go-offline');

  /// POST /driver/location  — called on each GPS tick
  Future<Response> updateLocation(double lat, double lng) =>
      post('/driver/location', data: {'lat': lat, 'lng': lng});

  /// GET /driver/earnings?period=day|week|month|all
  Future<Response> getEarnings({String period = 'week'}) =>
      get('/driver/earnings', params: {'period': period});

  /// POST /driver/profile
  Future<Response> createProfile(Map<String, dynamic> data) =>
      post('/driver/profile', data: data);

  /// GET /rides/history — paginated ride history for the authenticated driver
  Future<Response> getRideHistory({int limit = 20, int offset = 0}) =>
      get('/rides/history', params: {'limit': limit, 'offset': offset});

  /// GET /auth/me — current user profile
  Future<Response> getProfile() => get('/auth/me');

  /// PUT /auth/me — update user profile
  Future<Response> updateProfile({String? name, String? email}) {
    final data = <String, dynamic>{};
    if (name != null) data['name'] = name;
    if (email != null) data['email'] = email;
    return put('/auth/me', data: data);
  }

  /// GET /driver/profile — current driver's vehicle/status profile
  Future<Response> getDriverProfile() => get('/driver/profile');

  /// Ride lifecycle — these hit the rides router, not the driver router.
  /// The backend determines auth from the JWT (driver role).

  Future<Response> getRide(int rideId) => get('/rides/$rideId');

  Future<Response> updateRideStatus(int rideId, String status) =>
      post('/rides/$rideId/status', data: {'status': status});
}
