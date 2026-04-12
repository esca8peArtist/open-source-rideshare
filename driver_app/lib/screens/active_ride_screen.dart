import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:rideshare_driver/models/ride.dart';
import 'package:rideshare_driver/providers/driver_provider.dart';
import 'package:rideshare_driver/widgets/ride_action_bar.dart';

class ActiveRideScreen extends ConsumerWidget {
  final int rideId;

  const ActiveRideScreen({super.key, required this.rideId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final driverState = ref.watch(driverProvider);
    final ride = driverState.currentRide;

    if (ride == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Ride')),
        body: const Center(child: Text('No active ride')),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(_statusTitle(ride.status)),
        automaticallyImplyLeading: false,
        leading: ride.status == RideStatus.completed
            ? IconButton(
                icon: const Icon(Icons.close),
                onPressed: () {
                  ref.read(driverProvider.notifier).clearCurrentRide();
                  context.go('/');
                },
              )
            : null,
      ),
      body: Column(
        children: [
          // ── Status banner ────────────────────────────────────────
          _StatusBanner(status: ride.status),

          // ── Ride details ─────────────────────────────────────────
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
                  if (ride.riderName != null) ...[
                    _InfoRow(
                      icon: Icons.person,
                      label: 'Rider',
                      value: ride.riderName!,
                    ),
                    const SizedBox(height: 12),
                  ],
                  if (ride.riderPhone != null) ...[
                    _InfoRow(
                      icon: Icons.phone,
                      label: 'Phone',
                      value: ride.riderPhone!,
                    ),
                    const SizedBox(height: 12),
                  ],
                  _InfoRow(
                    icon: Icons.attach_money,
                    label: 'Estimated Fare',
                    value: '\$${ride.estimatedFare.toStringAsFixed(2)}',
                  ),
                  if (ride.distanceKm != null) ...[
                    const SizedBox(height: 12),
                    _InfoRow(
                      icon: Icons.straighten,
                      label: 'Distance',
                      value: '${ride.distanceKm!.toStringAsFixed(1)} km',
                    ),
                  ],
                  if (ride.actualFare != null) ...[
                    const SizedBox(height: 12),
                    _InfoRow(
                      icon: Icons.receipt,
                      label: 'Final Fare',
                      value: '\$${ride.actualFare!.toStringAsFixed(2)}',
                    ),
                  ],
                  const Spacer(),
                ],
              ),
            ),
          ),

          // ── Contextual action bar ────────────────────────────────
          RideActionBar(
            status: ride.status,
            onEnRoute: () =>
                ref.read(driverProvider.notifier).markEnRoute(),
            onArrived: () =>
                ref.read(driverProvider.notifier).markArrived(),
            onStartRide: () =>
                ref.read(driverProvider.notifier).startRide(),
            onCompleteRide: () =>
                ref.read(driverProvider.notifier).completeRide(),
            onDone: () {
              ref.read(driverProvider.notifier).clearCurrentRide();
              context.go('/');
            },
          ),
        ],
      ),
    );
  }

  String _statusTitle(RideStatus status) {
    switch (status) {
      case RideStatus.matched:
        return 'Ride Accepted';
      case RideStatus.driverEnRoute:
        return 'Heading to Pickup';
      case RideStatus.arrived:
        return 'At Pickup';
      case RideStatus.inProgress:
        return 'Ride In Progress';
      case RideStatus.completed:
        return 'Ride Complete';
      case RideStatus.cancelled:
        return 'Ride Cancelled';
      default:
        return 'Ride';
    }
  }
}

// ---------------------------------------------------------------------------
// Private helper widgets
// ---------------------------------------------------------------------------

class _StatusBanner extends StatelessWidget {
  final RideStatus status;

  const _StatusBanner({required this.status});

  @override
  Widget build(BuildContext context) {
    final (color, icon, text) = switch (status) {
      RideStatus.matched => (
          Colors.blue,
          Icons.check_circle,
          'Navigate to the pickup location'
        ),
      RideStatus.driverEnRoute => (
          Colors.blue,
          Icons.navigation,
          'Heading to pickup — tap Arrived when you get there'
        ),
      RideStatus.arrived => (
          Colors.orange,
          Icons.place,
          'Waiting for rider — tap Start when they board'
        ),
      RideStatus.inProgress => (
          Colors.green,
          Icons.directions_car,
          'Ride in progress — tap Complete at destination'
        ),
      RideStatus.completed => (
          Colors.teal,
          Icons.done_all,
          'Ride complete — nice work!'
        ),
      RideStatus.cancelled => (
          Colors.red,
          Icons.cancel,
          'This ride was cancelled'
        ),
      _ => (Colors.grey, Icons.info, 'Ride'),
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
            child: Text(text,
                style: TextStyle(
                    color: color, fontWeight: FontWeight.w500)),
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
        Icon(icon,
            size: 20,
            color: iconColor ?? Theme.of(context).colorScheme.outline),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: Theme.of(context).colorScheme.outline)),
              Text(value,
                  style: Theme.of(context).textTheme.bodyMedium),
            ],
          ),
        ),
      ],
    );
  }
}
