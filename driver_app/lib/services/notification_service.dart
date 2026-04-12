import 'dart:io';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:go_router/go_router.dart';
import 'package:rideshare_driver/router.dart' show navigatorKey;
import 'package:rideshare_driver/services/api_client.dart';

/// Handles Firebase Cloud Messaging push notifications for the driver app.
///
/// Usage:
///   - Call [NotificationService.initialize] once at app startup.
///   - Call [NotificationService.registerDeviceToken] after a successful login.
///   - Call [NotificationService.unregisterDeviceToken] on logout.
///   - Subscribe to [onMessageStream] to react to foreground notifications.
@pragma('vm:entry-point')
Future<void> _firebaseBackgroundHandler(RemoteMessage message) async {
  // Background messages are handled by the OS; no app-level work needed here
  // unless the message contains a data payload that requires processing.
}

class NotificationService {
  static FirebaseMessaging? _messaging;
  static String? _currentToken;

  /// Deep link to navigate to when the home screen first mounts.
  /// Set when a notification is tapped while the app was terminated.
  static String? _pendingDeepLink;

  /// Consume any pending deep link after the home screen is ready.
  /// Returns the route string and clears it, or null if none.
  static String? consumePendingDeepLink() {
    final link = _pendingDeepLink;
    _pendingDeepLink = null;
    return link;
  }

  static Stream<RemoteMessage>? get onMessageStream =>
      _messaging?.onMessage;

  /// Initializes Firebase and sets up notification handlers.
  /// Safe to call even if Firebase is not configured — errors are caught and
  /// logged to stderr so CI/dev environments without google-services.json work.
  static Future<void> initialize() async {
    try {
      await Firebase.initializeApp();
      _messaging = FirebaseMessaging.instance;

      // Request permission (iOS; Android 13+ also needs this)
      final settings = await _messaging!.requestPermission(
        alert: true,
        badge: true,
        sound: true,
        provisional: false,
      );

      if (settings.authorizationStatus == AuthorizationStatus.denied) {
        // User declined — respect the choice, don't prompt again
        return;
      }

      // Register background message handler
      FirebaseMessaging.onBackgroundMessage(_firebaseBackgroundHandler);

      // Handle notification taps when app was terminated
      final initialMessage = await _messaging!.getInitialMessage();
      if (initialMessage != null) {
        _handleNotificationTap(initialMessage);
      }

      // Handle notification taps when app was in background
      FirebaseMessaging.onMessageOpenedApp.listen(_handleNotificationTap);

      // For iOS foreground notifications
      await _messaging!.setForegroundNotificationPresentationOptions(
        alert: true,
        badge: true,
        sound: true,
      );
    } catch (e) {
      // Firebase not configured (e.g. missing google-services.json in dev)
      debugPrint('[NotificationService] Firebase init skipped: $e');
    }
  }

  /// Gets the current FCM token and registers it with the backend.
  /// Call after a successful login or when the token refreshes.
  static Future<void> registerDeviceToken(ApiClient api) async {
    if (_messaging == null) return;

    try {
      final token = await _messaging!.getToken();
      if (token == null) return;

      _currentToken = token;
      final platform = _getPlatform();

      await api.post('/me/device-tokens', data: {
        'token': token,
        'platform': platform,
      });

      // Listen for token refreshes (e.g. after app reinstall)
      _messaging!.onTokenRefresh.listen((newToken) async {
        _currentToken = newToken;
        try {
          await api.post('/me/device-tokens', data: {
            'token': newToken,
            'platform': platform,
          });
        } catch (e) {
          debugPrint('[NotificationService] Token refresh registration failed: $e');
        }
      });
    } catch (e) {
      debugPrint('[NotificationService] Device token registration failed: $e');
    }
  }

  /// Unregisters the current device token from the backend on logout.
  static Future<void> unregisterDeviceToken(ApiClient api) async {
    if (_messaging == null || _currentToken == null) return;

    try {
      await api.delete('/me/device-tokens/$_currentToken');
      _currentToken = null;
    } catch (e) {
      debugPrint('[NotificationService] Token unregistration failed: $e');
    }
  }

  static String _getPlatform() {
    if (kIsWeb) return 'web';
    if (Platform.isIOS) return 'ios';
    return 'android';
  }

  static void _handleNotificationTap(RemoteMessage message) {
    debugPrint('[NotificationService] Notification tapped: ${message.data}');
    final route = _routeFromMessage(message);
    if (route == null) return;

    final context = navigatorKey.currentContext;
    if (context != null) {
      context.go(route);
    } else {
      // App was terminated — store for HomeScreen to consume on first mount.
      _pendingDeepLink = route;
    }
  }

  /// Maps an FCM message to a go_router route string.
  /// Returns null for notification types that don't require navigation.
  static String? _routeFromMessage(RemoteMessage message) {
    final type = message.data['notification_type'] as String?;
    final rideIdStr = message.data['ride_id'] as String?;
    final rideId = rideIdStr != null ? int.tryParse(rideIdStr) : null;

    switch (type) {
      case 'ride_matched':
        return rideId != null ? '/ride/$rideId' : '/';
      case 'ride_cancelled':
        return '/';
      case 'ride_completed':
      case 'rating_received':
        return '/history';
      case 'payment_received':
      case 'payout_completed':
        return '/earnings';
      case 'background_check_approved':
      case 'background_check_action_required':
        return '/profile';
      default:
        return null;
    }
  }
}
