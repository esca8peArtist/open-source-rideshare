import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:rideshare_driver/models/ride.dart';
import 'package:rideshare_driver/providers/auth_provider.dart';

final driverRideHistoryProvider =
    FutureProvider.autoDispose<List<Ride>>((ref) async {
  final api = ref.read(apiClientProvider);
  final response = await api.getRideHistory();
  final list = response.data as List;
  return list
      .map((json) => Ride.fromJson(json as Map<String, dynamic>))
      .toList();
});

class DriverRideHistoryScreen extends ConsumerWidget {
  const DriverRideHistoryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final historyAsync = ref.watch(driverRideHistoryProvider);

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
                onPressed: () => ref.invalidate(driverRideHistoryProvider),
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
                  Icon(Icons.local_taxi,
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
            onRefresh: () async =>
                ref.invalidate(driverRideHistoryProvider),
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: rides.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, index) =>
                  _DriverRideCard(ride: rides[index]),
            ),
          );
        },
      ),
    );
  }
}

class _DriverRideCard extends StatelessWidget {
  final Ride ride;

  const _DriverRideCard({required this.ride});

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
      RideStatus.driverEnRoute => 'En Route',
      RideStatus.arrived => 'Arrived',
    };

    return Card(
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Date + status badge
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

            // Rider name (if available)
            if (ride.riderName != null) ...[
              Row(
                children: [
                  Icon(Icons.person, size: 14, color: colorScheme.outline),
                  const SizedBox(width: 6),
                  Text(ride.riderName!,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: colorScheme.outline,
                          )),
                ],
              ),
              const SizedBox(height: 8),
            ],

            // Pickup location
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
            // Dropoff location
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

            // Time + fare
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
    );
  }
}
