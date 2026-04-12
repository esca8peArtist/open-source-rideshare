import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:rideshare_rider/models/ride.dart';
import 'package:rideshare_rider/providers/ride_provider.dart';

class RideTrackingScreen extends ConsumerWidget {
  final int rideId;

  const RideTrackingScreen({super.key, required this.rideId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rideState = ref.watch(rideProvider);
    final ride = rideState.activeRide;

    if (ride == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Ride')),
        body: const Center(child: Text('No active ride')),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(_statusTitle(ride.status)),
        leading: ride.status == RideStatus.completed
            ? IconButton(
                icon: const Icon(Icons.close),
                onPressed: () {
                  ref.read(rideProvider.notifier).clearState();
                  context.go('/ride/${ride.id}/rate');
                },
              )
            : ride.status == RideStatus.cancelled
                ? IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: () {
                      ref.read(rideProvider.notifier).clearState();
                      context.go('/');
                    },
                  )
                : null,
        automaticallyImplyLeading: false,
      ),
      body: Column(
        children: [
          _StatusBanner(status: ride.status),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _InfoRow(
                    icon: Icons.circle,
                    iconColor: Colors.green,
                    label: 'Pickup',
                    value: ride.pickupAddress,
                  ),
                  const SizedBox(height: 12),
                  _InfoRow(
                    icon: Icons.location_on,
                    iconColor: Colors.red,
                    label: 'Dropoff',
                    value: ride.dropoffAddress,
                  ),
                  const Divider(height: 32),
                  if (ride.driverName != null) ...[
                    _InfoRow(
                      icon: Icons.person,
                      label: 'Driver',
                      value: ride.driverName!,
                    ),
                    const SizedBox(height: 12),
                  ],
                  if (ride.vehicleInfo != null) ...[
                    _InfoRow(
                      icon: Icons.directions_car,
                      label: 'Vehicle',
                      value: ride.vehicleInfo!,
                    ),
                    const SizedBox(height: 12),
                  ],
                  _InfoRow(
                    icon: Icons.attach_money,
                    label: 'Estimated Fare',
                    value: '\$${ride.estimatedFare.toStringAsFixed(2)}',
                  ),
                  if (ride.actualFare != null) ...[
                    const SizedBox(height: 12),
                    _InfoRow(
                      icon: Icons.receipt,
                      label: 'Final Fare',
                      value: '\$${ride.actualFare!.toStringAsFixed(2)}',
                    ),
                  ],
                  const Spacer(),
                  if (ride.status == RideStatus.requested ||
                      ride.status == RideStatus.matched ||
                      ride.status == RideStatus.driverEnRoute)
                    SizedBox(
                      width: double.infinity,
                      child: OutlinedButton(
                        onPressed: () {
                          ref.read(rideProvider.notifier).cancelRide();
                          context.go('/');
                        },
                        style: OutlinedButton.styleFrom(
                          foregroundColor:
                              Theme.of(context).colorScheme.error,
                        ),
                        child: const Text('Cancel Ride'),
                      ),
                    ),
                  if (ride.status == RideStatus.completed)
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: () {
                          ref.read(rideProvider.notifier).clearState();
                          context.go('/ride/${ride.id}/rate');
                        },
                        child: const Text('Rate Your Ride'),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _statusTitle(RideStatus status) {
    switch (status) {
      case RideStatus.requested:
        return 'Finding Driver...';
      case RideStatus.matched:
        return 'Driver Matched';
      case RideStatus.driverEnRoute:
        return 'Driver On The Way';
      case RideStatus.arrived:
        return 'Driver Arrived';
      case RideStatus.inProgress:
        return 'Ride In Progress';
      case RideStatus.completed:
        return 'Ride Complete';
      case RideStatus.cancelled:
        return 'Ride Cancelled';
    }
  }
}

class _StatusBanner extends StatelessWidget {
  final RideStatus status;

  const _StatusBanner({required this.status});

  @override
  Widget build(BuildContext context) {
    final (color, icon, text) = switch (status) {
      RideStatus.requested => (
          Colors.orange,
          Icons.search,
          'Looking for a driver nearby...'
        ),
      RideStatus.matched => (
          Colors.blue,
          Icons.check_circle,
          'A driver accepted your ride'
        ),
      RideStatus.driverEnRoute => (
          Colors.blue,
          Icons.navigation,
          'Your driver is heading to you'
        ),
      RideStatus.arrived => (
          Colors.green,
          Icons.place,
          'Your driver has arrived'
        ),
      RideStatus.inProgress => (
          Colors.green,
          Icons.directions_car,
          'On the way to your destination'
        ),
      RideStatus.completed => (
          Colors.teal,
          Icons.done_all,
          'You have arrived!'
        ),
      RideStatus.cancelled => (
          Colors.red,
          Icons.cancel,
          'This ride was cancelled'
        ),
    };

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      color: color.withValues(alpha: 0.1),
      child: Row(
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 12),
          Expanded(
            child: Text(text, style: TextStyle(color: color, fontWeight: FontWeight.w500)),
          ),
          if (status == RideStatus.requested)
            SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: color,
              ),
            ),
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final IconData icon;
  final Color? iconColor;
  final String label;
  final String value;

  const _InfoRow({
    required this.icon,
    this.iconColor,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 20, color: iconColor ?? Theme.of(context).colorScheme.outline),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label,
                  style: Theme.of(context)
                      .textTheme
                      .labelSmall
                      ?.copyWith(color: Theme.of(context).colorScheme.outline)),
              Text(value, style: Theme.of(context).textTheme.bodyMedium),
            ],
          ),
        ),
      ],
    );
  }
}
