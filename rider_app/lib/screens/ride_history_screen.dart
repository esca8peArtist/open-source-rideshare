import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:rideshare_rider/models/ride.dart';
import 'package:rideshare_rider/providers/auth_provider.dart';
import 'package:rideshare_rider/providers/ride_provider.dart';

final rideHistoryProvider =
    FutureProvider.autoDispose<List<Ride>>((ref) async {
  final rideService = ref.read(rideServiceProvider);
  return rideService.getRideHistory();
});

class RideHistoryScreen extends ConsumerWidget {
  const RideHistoryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final historyAsync = ref.watch(rideHistoryProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Ride History'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
      ),
      body: historyAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, size: 48, color: Colors.grey),
              const SizedBox(height: 16),
              Text('Could not load ride history',
                  style: Theme.of(context).textTheme.bodyLarge),
              const SizedBox(height: 8),
              FilledButton.tonal(
                onPressed: () => ref.invalidate(rideHistoryProvider),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
        data: (rides) {
          if (rides.isEmpty) {
            return Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.directions_car,
                      size: 64,
                      color: Theme.of(context).colorScheme.outline),
                  const SizedBox(height: 16),
                  Text('No rides yet',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  Text('Your completed rides will appear here',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            color: Theme.of(context).colorScheme.outline,
                          )),
                ],
              ),
            );
          }

          return RefreshIndicator(
            onRefresh: () async => ref.invalidate(rideHistoryProvider),
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: rides.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, index) {
                final ride = rides[index];
                return _RideHistoryCard(ride: ride);
              },
            ),
          );
        },
      ),
    );
  }
}

class _RideHistoryCard extends StatelessWidget {
  final Ride ride;

  const _RideHistoryCard({required this.ride});

  @override
  Widget build(BuildContext context) {
    final dateFormat = DateFormat('MMM d, yyyy');
    final timeFormat = DateFormat('h:mm a');
    final colorScheme = Theme.of(context).colorScheme;

    final statusColor = switch (ride.status) {
      RideStatus.completed => Colors.green,
      RideStatus.cancelled => Colors.red,
      RideStatus.inProgress => Colors.blue,
      _ => Colors.orange,
    };

    final statusLabel = switch (ride.status) {
      RideStatus.completed => 'Completed',
      RideStatus.cancelled => 'Cancelled',
      RideStatus.inProgress => 'In Progress',
      RideStatus.requested => 'Requested',
      RideStatus.matched => 'Matched',
      RideStatus.driverEnRoute => 'Driver En Route',
      RideStatus.arrived => 'Driver Arrived',
    };

    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: ride.status == RideStatus.completed
            ? () => context.go('/ride/${ride.id}/rate')
            : null,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    dateFormat.format(ride.requestedAt),
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: statusColor.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      statusLabel,
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                            color: statusColor,
                            fontWeight: FontWeight.w600,
                          ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  const Icon(Icons.circle, size: 10, color: Colors.green),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(ride.pickupAddress,
                        maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                ],
              ),
              Padding(
                padding: const EdgeInsets.only(left: 4),
                child: Container(
                  width: 2,
                  height: 16,
                  color: colorScheme.outlineVariant,
                ),
              ),
              Row(
                children: [
                  const Icon(Icons.location_on, size: 10, color: Colors.red),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(ride.dropoffAddress,
                        maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    timeFormat.format(ride.requestedAt),
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: colorScheme.outline,
                        ),
                  ),
                  Text(
                    '\$${(ride.actualFare ?? ride.estimatedFare).toStringAsFixed(2)}',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
