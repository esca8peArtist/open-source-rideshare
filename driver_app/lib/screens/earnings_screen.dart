import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:rideshare_driver/models/earnings.dart';
import 'package:rideshare_driver/providers/driver_provider.dart';

class EarningsScreen extends ConsumerStatefulWidget {
  const EarningsScreen({super.key});

  @override
  ConsumerState<EarningsScreen> createState() => _EarningsScreenState();
}

class _EarningsScreenState extends ConsumerState<EarningsScreen> {
  String _selectedPeriod = 'week';

  @override
  void initState() {
    super.initState();
    // Load initial earnings data
    Future.microtask(
        () => ref.read(driverProvider.notifier).loadEarnings(period: _selectedPeriod));
  }

  void _onPeriodChanged(String period) {
    setState(() => _selectedPeriod = period);
    ref.read(driverProvider.notifier).loadEarnings(period: period);
  }

  @override
  Widget build(BuildContext context) {
    final driverState = ref.watch(driverProvider);
    final earnings = driverState.earnings;

    return Scaffold(
      appBar: AppBar(title: const Text('Earnings')),
      body: Column(
        children: [
          // ── Period selector ──────────────────────────────────────
          Padding(
            padding: const EdgeInsets.all(16),
            child: SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'day', label: Text('Today')),
                ButtonSegment(value: 'week', label: Text('Week')),
                ButtonSegment(value: 'month', label: Text('Month')),
                ButtonSegment(value: 'all', label: Text('All')),
              ],
              selected: {_selectedPeriod},
              onSelectionChanged: (s) => _onPeriodChanged(s.first),
            ),
          ),

          // ── Summary card ────────────────────────────────────────
          if (earnings != null)
            _SummaryCard(summary: earnings.summary)
          else if (driverState.isLoading)
            const Padding(
              padding: EdgeInsets.all(32),
              child: CircularProgressIndicator(),
            )
          else if (driverState.error != null)
            Padding(
              padding: const EdgeInsets.all(32),
              child: Text(driverState.error!,
                  style: TextStyle(
                      color: Theme.of(context).colorScheme.error)),
            ),

          // ── Trip list ───────────────────────────────────────────
          if (earnings != null)
            Expanded(
              child: earnings.trips.isEmpty
                  ? const Center(
                      child: Text('No trips in this period'))
                  : ListView.separated(
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      itemCount: earnings.trips.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (context, index) =>
                          _TripTile(trip: earnings.trips[index]),
                    ),
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Summary card
// ---------------------------------------------------------------------------

class _SummaryCard extends StatelessWidget {
  final EarningsSummary summary;

  const _SummaryCard({required this.summary});

  @override
  Widget build(BuildContext context) {
    final currencyFormat = NumberFormat.currency(symbol: '\$');

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            Text(
              currencyFormat.format(summary.totalEarnings),
              style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: Theme.of(context).colorScheme.primary,
                  ),
            ),
            const SizedBox(height: 4),
            Text('Total Earnings',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.outline)),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _StatColumn(
                  label: 'Trips',
                  value: summary.tripCount.toString(),
                ),
                _StatColumn(
                  label: 'Fares',
                  value: currencyFormat.format(summary.totalFares),
                ),
                _StatColumn(
                  label: 'Tips',
                  value: currencyFormat.format(summary.totalTips),
                ),
                _StatColumn(
                  label: 'Avg Fare',
                  value: currencyFormat.format(summary.averageFare),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _StatColumn extends StatelessWidget {
  final String label;
  final String value;

  const _StatColumn({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(value,
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.w600)),
        const SizedBox(height: 2),
        Text(label,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: Theme.of(context).colorScheme.outline)),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Trip list tile
// ---------------------------------------------------------------------------

class _TripTile extends StatelessWidget {
  final EarningsTrip trip;

  const _TripTile({required this.trip});

  @override
  Widget build(BuildContext context) {
    final dateFormat = DateFormat('MMM d, h:mm a');

    return ListTile(
      contentPadding: const EdgeInsets.symmetric(vertical: 8),
      leading: const CircleAvatar(child: Icon(Icons.directions_car)),
      title: Text(
        '${trip.pickupAddress} -> ${trip.dropoffAddress}',
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: Text(
        trip.completedAt != null
            ? dateFormat.format(trip.completedAt!)
            : 'Pending',
      ),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(
            '\$${trip.total.toStringAsFixed(2)}',
            style: Theme.of(context)
                .textTheme
                .titleSmall
                ?.copyWith(fontWeight: FontWeight.bold),
          ),
          if (trip.tip > 0)
            Text(
              '+\$${trip.tip.toStringAsFixed(2)} tip',
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Colors.green),
            ),
        ],
      ),
    );
  }
}
