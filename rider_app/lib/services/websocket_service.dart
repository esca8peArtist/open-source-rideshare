import 'dart:async';
import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class WebSocketService {
  static const _baseWsUrl = String.fromEnvironment(
    'WS_BASE_URL',
    defaultValue: 'ws://localhost:8000',
  );

  WebSocketChannel? _channel;
  final _messageController = StreamController<Map<String, dynamic>>.broadcast();
  final FlutterSecureStorage _storage;
  Timer? _pingTimer;

  WebSocketService({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  Stream<Map<String, dynamic>> get messages => _messageController.stream;

  bool get isConnected => _channel != null;

  Future<void> connect() async {
    final token = await _storage.read(key: 'access_token');
    if (token == null) return;

    _channel = WebSocketChannel.connect(
      Uri.parse('$_baseWsUrl/ws/rider?token=$token'),
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

  void _handleDisconnect() {
    _pingTimer?.cancel();
    _channel = null;
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
