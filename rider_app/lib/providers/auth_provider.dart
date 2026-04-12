import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:rideshare_rider/services/api_client.dart';
import 'package:rideshare_rider/services/notification_service.dart';

class AuthState {
  final String? token;
  final bool isLoading;
  final String? error;

  const AuthState({this.token, this.isLoading = false, this.error});

  AuthState copyWith({String? token, bool? isLoading, String? error}) =>
      AuthState(
        token: token ?? this.token,
        isLoading: isLoading ?? this.isLoading,
        error: error,
      );
}

class AuthNotifier extends StateNotifier<AuthState> {
  final ApiClient _api;
  final FlutterSecureStorage _storage;

  AuthNotifier(this._api, this._storage) : super(const AuthState()) {
    _loadToken();
  }

  Future<void> _loadToken() async {
    final token = await _storage.read(key: 'access_token');
    if (token != null) {
      state = state.copyWith(token: token);
    }
  }

  Future<void> login(String email, String password) async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final response = await _api.post('/auth/login', data: {
        'email': email,
        'password': password,
      });
      final accessToken = response.data['access_token'] as String;
      final refreshToken = response.data['refresh_token'] as String;

      await _storage.write(key: 'access_token', value: accessToken);
      await _storage.write(key: 'refresh_token', value: refreshToken);

      state = state.copyWith(token: accessToken, isLoading: false);
      await NotificationService.registerDeviceToken(_api);
    } catch (e) {
      state = state.copyWith(
        isLoading: false,
        error: 'Login failed. Check your credentials.',
      );
    }
  }

  Future<void> register(String email, String password, String name,
      String phone) async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      await _api.post('/auth/register', data: {
        'email': email,
        'password': password,
        'name': name,
        'phone': phone,
      });
      await login(email, password);
    } catch (e) {
      state = state.copyWith(
        isLoading: false,
        error: 'Registration failed.',
      );
    }
  }

  Future<void> logout() async {
    await NotificationService.unregisterDeviceToken(_api);
    await _storage.deleteAll();
    state = const AuthState();
  }
}

final apiClientProvider = Provider((ref) => ApiClient());

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  final api = ref.read(apiClientProvider);
  return AuthNotifier(api, const FlutterSecureStorage());
});
