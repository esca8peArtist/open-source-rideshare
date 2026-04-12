import 'dart:async';
import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:rideshare_driver/config.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

/// WebSocket service for the driver app.
///
/// Connects to `/ws/driver` and handles:
///   - Outbound: location_update, accept_ride, ping
///   - Inbound:  ride_offer, location_ack, accept_ack, ride_status, pong
class WebSocketService {
  WebSocketChannel? _channel;
  final _messageController =
      StreamController<Map<String, dynamic>>.broadcast();
  final FlutterSecureStorage _storage;
  Timer? _pingTimer;

  WebSocketService({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  /// Stream of decoded JSON messages from the server.
  Stream<Map<String, dynamic>> get messages => _messageController.stream;

  bool get isConnected => _channel != null;

  Future<void> connect() async {
    final token = await _storage.read(key: 'access_token');
    if (token == null) return;

    _channel = WebSocketChannel.connect(
      Uri.parse('${AppConfig.wsBaseUrl}/ws/driver?token=$token'),
    );

    _channel!.stream.listen(
      (data) {
        final message = jsonDecode(data as String) as Map<String, dynamic>;
        _messageController.add(message);
      },
      onDone: _handleDisconnect,
      onError: (_) => _handleDisconnect(),
    );

    _pingTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => send({'type': 'ping'}),
    );
  }

  void send(Map<String, dynamic> message) {
    _channel?.sink.add(jsonEncode(message));
  }

  /// Stream the driver's current GPS position to the backend.
  void sendLocationUpdate(double lat, double lng) {
    send({'type': 'location_update', 'lat': lat, 'lng': lng});
  }

  /// Accept a ride offer by ride ID.
  void sendAcceptRide(int rideId) {
    send({'type': 'accept_ride', 'ride_id': rideId});
  }

  void _handleDisconnect() {
    _pingTimer?.cancel();
    _channel = null;
    // Auto-reconnect after 5 seconds
    Future.delayed(const Duration(seconds: 5), connect);
  }

  Future<void> disconnect() async {
    _pingTimer?.cancel();
    await _channel?.sink.close();
    _channel = null;
  }

  void dispose() {
    disconnect();
    _messageController.close();
  }
}
