import 'dart:async';

import 'package:flutter/material.dart';
import 'package:rideshare_driver/models/ride_offer.dart';

/// Displays an incoming ride offer with pickup/dropoff preview, estimated fare,
/// and accept/decline buttons. Includes a countdown timer that auto-declines
/// when it reaches zero.
class RideOfferCard extends StatefulWidget {
  final RideOffer offer;
  final VoidCallback onAccept;
  final VoidCallback onDecline;

  const RideOfferCard({
    super.key,
    required this.offer,
    required this.onAccept,
    required this.onDecline,
  });

  @override
  State<RideOfferCard> createState() => _RideOfferCardState();
}

class _RideOfferCardState extends State<RideOfferCard> {
  late int _secondsRemaining;
  Timer? _countdownTimer;

  @override
  void initState() {
    super.initState();
    _secondsRemaining = widget.offer.secondsRemaining();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      final remaining = widget.offer.secondsRemaining();
      if (remaining <= 0) {
        _countdownTimer?.cancel();
        widget.onDecline();
      } else {
        setState(() => _secondsRemaining = remaining);
      }
    });
  }

  @override
  void dispose() {
    _countdownTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final progress = _secondsRemaining / widget.offer.timeoutSeconds;

    return Card(
      elevation: 8,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // ── Countdown indicator ─────────────────────────────────
            Row(
              children: [
                Text(
                  'New Ride Request',
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.bold),
                ),
                const Spacer(),
                Stack(
                  alignment: Alignment.center,
                  children: [
                    SizedBox(
                      width: 36,
                      height: 36,
                      child: CircularProgressIndicator(
                        value: progress,
                        strokeWidth: 3,
                        color: _secondsRemaining > 10
                            ? Theme.of(context).colorScheme.primary
                            : Theme.of(context).colorScheme.error,
                      ),
                    ),
                    Text(
                      '$_secondsRemaining',
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 12),

            // ── Pickup / dropoff ────────────────────────────────────
            Row(
              children: [
                const Icon(Icons.circle, size: 12, color: Colors.green),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    widget.offer.pickupAddress,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                const Icon(Icons.location_on, size: 12, color: Colors.red),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    widget.offer.dropoffAddress,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),

            // ── Fare and distance chips ─────────────────────────────
            Row(
              children: [
                _Chip(
                  icon: Icons.attach_money,
                  label:
                      '\$${widget.offer.estimatedFare.toStringAsFixed(2)}',
                ),
                const SizedBox(width: 8),
                _Chip(
                  icon: Icons.straighten,
                  label:
                      '${widget.offer.pickupDistanceKm.toStringAsFixed(1)} km away',
                ),
              ],
            ),
            const SizedBox(height: 16),

            // ── Accept / Decline buttons ────────────────────────────
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: widget.onDecline,
                    style: OutlinedButton.styleFrom(
                      foregroundColor:
                          Theme.of(context).colorScheme.error,
                    ),
                    child: const Text('Decline'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  flex: 2,
                  child: FilledButton(
                    onPressed: widget.onAccept,
                    child: const Text('Accept'),
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

class _Chip extends StatelessWidget {
  final IconData icon;
  final String label;

  const _Chip({required this.icon, required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: Theme.of(context).colorScheme.outline),
          const SizedBox(width: 4),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
