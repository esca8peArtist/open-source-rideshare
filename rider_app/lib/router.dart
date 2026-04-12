import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:rideshare_rider/providers/auth_provider.dart';
import 'package:rideshare_rider/screens/home_screen.dart';
import 'package:rideshare_rider/screens/login_screen.dart';
import 'package:rideshare_rider/screens/ride_history_screen.dart';
import 'package:rideshare_rider/screens/ride_rating_screen.dart';
import 'package:rideshare_rider/screens/profile_screen.dart';
import 'package:rideshare_rider/screens/ride_tracking_screen.dart';

/// Global navigator key — used by NotificationService to navigate on tap.
final navigatorKey = GlobalKey<NavigatorState>();

final routerProvider = Provider<GoRouter>((ref) {
  final authState = ref.watch(authProvider);

  return GoRouter(
    navigatorKey: navigatorKey,
    initialLocation: '/',
    redirect: (context, state) {
      final isLoggedIn = authState.token != null;
      final isLoginRoute = state.matchedLocation == '/login';

      if (!isLoggedIn && !isLoginRoute) return '/login';
      if (isLoggedIn && isLoginRoute) return '/';
      return null;
    },
    routes: [
      GoRoute(
        path: '/',
        builder: (context, state) => const HomeScreen(),
      ),
      GoRoute(
        path: '/login',
        builder: (context, state) => const LoginScreen(),
      ),
      GoRoute(
        path: '/ride/:id',
        builder: (context, state) {
          final rideId = int.parse(state.pathParameters['id']!);
          return RideTrackingScreen(rideId: rideId);
        },
      ),
      GoRoute(
        path: '/ride/:id/rate',
        builder: (context, state) {
          final rideId = int.parse(state.pathParameters['id']!);
          return RideRatingScreen(rideId: rideId);
        },
      ),
      GoRoute(
        path: '/history',
        builder: (context, state) => const RideHistoryScreen(),
      ),
      GoRoute(
        path: '/profile',
        builder: (context, state) => const ProfileScreen(),
      ),
    ],
  );
});
