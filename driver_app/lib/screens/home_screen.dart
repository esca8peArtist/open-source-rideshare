import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';
import 'package:rideshare_driver/providers/auth_provider.dart';
import 'package:rideshare_driver/providers/driver_provider.dart';
import 'package:rideshare_driver/services/notification_service.dart';
import 'package:rideshare_driver/widgets/online_toggle.dart';
import 'package:rideshare_driver/widgets/ride_offer_card.dart';

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  final _mapController = MapController();

  @override
  void initState() {
    super.initState();
    _loadInitialLocation();
    // Handle notification taps from a terminated app.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final route = NotificationService.consumePendingDeepLink();
      if (route != null && mounted) {
        context.go(route);
      }
    });
  }

  Future<void> _loadInitialLocation() async {
    final locationService = ref.read(locationServiceProvider);
    final location = await locationService.getCurrentLocation();
    if (location != null && mounted) {
      _mapController.move(LatLng(location.lat, location.lng), 15);
    }
  }

  void _onOfferAccepted() {
    ref.read(driverProvider.notifier).acceptOffer();
    // Navigation to ActiveRideScreen happens reactively when currentRide
    // is set after the accept_ack arrives via WebSocket.
  }

  void _onOfferDeclined() {
    ref.read(driverProvider.notifier).declineOffer();
  }

  @override
  Widget build(BuildContext context) {
    final driverState = ref.watch(driverProvider);
    final currentLocation = driverState.currentLocation;

    // Navigate to active ride screen when a ride is assigned
    ref.listen<DriverState>(driverProvider, (prev, next) {
      if (prev?.currentRide == null && next.currentRide != null) {
        context.go('/ride/${next.currentRide!.id}');
      }
    });

    return Scaffold(
      appBar: AppBar(
        title: const Text('Rideshare Driver'),
        actions: [
          IconButton(
            icon: const Icon(Icons.history),
            tooltip: 'Ride History',
            onPressed: () => context.go('/history'),
          ),
          IconButton(
            icon: const Icon(Icons.bar_chart),
            tooltip: 'Earnings',
            onPressed: () => context.go('/earnings'),
          ),
          IconButton(
            icon: const Icon(Icons.person),
            tooltip: 'Profile',
            onPressed: () => context.go('/profile'),
          ),
        ],
      ),
      body: Stack(
        children: [
          // ── Map ───────────────────────────────────────────────────
          FlutterMap(
            mapController: _mapController,
            options: MapOptions(
              initialCenter: currentLocation != null
                  ? LatLng(currentLocation.lat, currentLocation.lng)
                  : const LatLng(37.7749, -122.4194),
              initialZoom: 15,
            ),
            children: [
              TileLayer(
                urlTemplate:
                    'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                userAgentPackageName: 'org.rideshare.driver',
              ),
              MarkerLayer(
                markers: [
                  if (currentLocation != null)
                    Marker(
                      point:
                          LatLng(currentLocation.lat, currentLocation.lng),
                      width: 24,
                      height: 24,
                      child: Container(
                        decoration: BoxDecoration(
                          color: driverState.isOnline
                              ? Colors.green
                              : Theme.of(context).colorScheme.outline,
                          shape: BoxShape.circle,
                          border:
                              Border.all(color: Colors.white, width: 3),
                        ),
                        child: const Icon(Icons.navigation,
                            size: 14, color: Colors.white),
                      ),
                    ),
                ],
              ),
            ],
          ),

          // ── Online/Offline toggle ─────────────────────────────────
          Positioned(
            bottom: 24,
            left: 0,
            right: 0,
            child: Center(
              child: OnlineToggle(
                isOnline: driverState.isOnline,
                isLoading: driverState.isLoading,
                onToggle: () {
                  if (driverState.isOnline) {
                    ref.read(driverProvider.notifier).goOffline();
                  } else {
                    ref.read(driverProvider.notifier).goOnline();
                  }
                },
              ),
            ),
          ),

          // ── Ride offer overlay ────────────────────────────────────
          if (driverState.pendingOffer != null)
            Positioned(
              bottom: 100,
              left: 16,
              right: 16,
              child: RideOfferCard(
                offer: driverState.pendingOffer!,
                onAccept: _onOfferAccepted,
                onDecline: _onOfferDeclined,
              ),
            ),

          // ── Error snackbar ────────────────────────────────────────
          if (driverState.error != null)
            Positioned(
              top: 0,
              left: 16,
              right: 16,
              child: SafeArea(
                child: Material(
                  elevation: 4,
                  borderRadius: BorderRadius.circular(8),
                  color: Theme.of(context).colorScheme.errorContainer,
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Text(
                      driverState.error!,
                      style: TextStyle(
                          color: Theme.of(context)
                              .colorScheme
                              .onErrorContainer),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
