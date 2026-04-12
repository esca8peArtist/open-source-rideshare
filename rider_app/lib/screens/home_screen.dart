import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';
import 'package:rideshare_rider/models/ride.dart';
import 'package:rideshare_rider/providers/auth_provider.dart';
import 'package:rideshare_rider/providers/ride_provider.dart';
import 'package:rideshare_rider/services/location_service.dart';
import 'package:rideshare_rider/services/notification_service.dart';
import 'package:rideshare_rider/widgets/fare_estimate_card.dart';
import 'package:rideshare_rider/widgets/location_search_bar.dart';

final locationServiceProvider = Provider((ref) => LocationService());

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  final _mapController = MapController();
  LatLng? _currentLocation;
  LatLng? _pickupLocation;
  LatLng? _dropoffLocation;
  String _pickupAddress = '';
  String _dropoffAddress = '';

  @override
  void initState() {
    super.initState();
    _loadCurrentLocation();
    _connectWebSocket();
    // Handle notification taps from a terminated app.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final route = NotificationService.consumePendingDeepLink();
      if (route != null && mounted) {
        context.go(route);
      }
    });
  }

  Future<void> _loadCurrentLocation() async {
    final locationService = ref.read(locationServiceProvider);
    final location = await locationService.getCurrentLocation();
    if (location != null && mounted) {
      setState(() {
        _currentLocation = LatLng(location.lat, location.lng);
        _pickupLocation = _currentLocation;
      });
      _mapController.move(_currentLocation!, 15);
    }
  }

  Future<void> _connectWebSocket() async {
    final ws = ref.read(webSocketProvider);
    await ws.connect();
  }

  void _onPickupSelected(LatLng location, String address) {
    setState(() {
      _pickupLocation = location;
      _pickupAddress = address;
    });
    _tryEstimateFare();
  }

  void _onDropoffSelected(LatLng location, String address) {
    setState(() {
      _dropoffLocation = location;
      _dropoffAddress = address;
    });
    _tryEstimateFare();
  }

  void _tryEstimateFare() {
    if (_pickupLocation != null && _dropoffLocation != null) {
      ref.read(rideProvider.notifier).estimateFare(
            LocationPoint(
                lat: _pickupLocation!.latitude,
                lng: _pickupLocation!.longitude),
            LocationPoint(
                lat: _dropoffLocation!.latitude,
                lng: _dropoffLocation!.longitude),
          );
    }
  }

  Future<void> _requestRide() async {
    if (_pickupLocation == null || _dropoffLocation == null) return;

    await ref.read(rideProvider.notifier).requestRide(
          pickup: LocationPoint(
              lat: _pickupLocation!.latitude,
              lng: _pickupLocation!.longitude),
          dropoff: LocationPoint(
              lat: _dropoffLocation!.latitude,
              lng: _dropoffLocation!.longitude),
          pickupAddress: _pickupAddress,
          dropoffAddress: _dropoffAddress,
        );

    final rideState = ref.read(rideProvider);
    if (rideState.activeRide != null && mounted) {
      context.go('/ride/${rideState.activeRide!.id}');
    }
  }

  @override
  Widget build(BuildContext context) {
    final rideState = ref.watch(rideProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Rideshare'),
        actions: [
          IconButton(
            icon: const Icon(Icons.history),
            onPressed: () => context.go('/history'),
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
          FlutterMap(
            mapController: _mapController,
            options: MapOptions(
              initialCenter: _currentLocation ?? const LatLng(37.7749, -122.4194),
              initialZoom: 14,
              onTap: (tapPosition, latLng) {
                if (_dropoffLocation == null) {
                  _onDropoffSelected(latLng, 'Selected location');
                }
              },
            ),
            children: [
              TileLayer(
                urlTemplate:
                    'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                userAgentPackageName: 'org.rideshare.rider',
              ),
              MarkerLayer(
                markers: [
                  if (_currentLocation != null)
                    Marker(
                      point: _currentLocation!,
                      width: 20,
                      height: 20,
                      child: Container(
                        decoration: BoxDecoration(
                          color: Theme.of(context).colorScheme.primary,
                          shape: BoxShape.circle,
                          border: Border.all(color: Colors.white, width: 2),
                        ),
                      ),
                    ),
                  if (_pickupLocation != null)
                    Marker(
                      point: _pickupLocation!,
                      width: 30,
                      height: 30,
                      child: const Icon(Icons.circle, color: Colors.green, size: 16),
                    ),
                  if (_dropoffLocation != null)
                    Marker(
                      point: _dropoffLocation!,
                      width: 30,
                      height: 30,
                      child: const Icon(Icons.location_on, color: Colors.red, size: 30),
                    ),
                ],
              ),
            ],
          ),
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  children: [
                    LocationSearchBar(
                      hint: 'Pickup location',
                      icon: Icons.circle,
                      iconColor: Colors.green,
                      onSelected: _onPickupSelected,
                    ),
                    const SizedBox(height: 8),
                    LocationSearchBar(
                      hint: 'Where to?',
                      icon: Icons.location_on,
                      iconColor: Colors.red,
                      onSelected: _onDropoffSelected,
                    ),
                  ],
                ),
              ),
            ),
          ),
          if (rideState.fareEstimate != null)
            Positioned(
              bottom: 0,
              left: 0,
              right: 0,
              child: FareEstimateCard(
                estimate: rideState.fareEstimate!,
                isLoading: rideState.isLoading,
                onRequest: _requestRide,
              ),
            ),
          if (rideState.error != null)
            Positioned(
              bottom: 80,
              left: 16,
              right: 16,
              child: Material(
                elevation: 4,
                borderRadius: BorderRadius.circular(8),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(
                    rideState.error!,
                    style: TextStyle(
                        color: Theme.of(context).colorScheme.error),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
