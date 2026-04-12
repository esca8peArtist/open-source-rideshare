import 'package:flutter/material.dart';
import 'package:rideshare_driver/models/ride.dart';

/// Contextual action buttons shown at the bottom of [ActiveRideScreen].
///
/// The visible button changes based on the current [RideStatus]:
///   matched       -> "En Route to Pickup"
///   driverEnRoute -> "Arrived at Pickup"
///   arrived       -> "Start Ride"
///   inProgress    -> "Complete Ride"
///   completed     -> "Done"
class RideActionBar extends StatelessWidget {
  final RideStatus status;
  final VoidCallback onEnRoute;
  final VoidCallback onArrived;
  final VoidCallback onStartRide;
  final VoidCallback onCompleteRide;
  final VoidCallback onDone;

  const RideActionBar({
    super.key,
    required this.status,
    required this.onEnRoute,
    required this.onArrived,
    required this.onStartRide,
    required this.onCompleteRide,
    required this.onDone,
  });

  @override
  Widget build(BuildContext context) {
    final (label, icon, callback, color) = _actionForStatus();

    if (label == null) return const SizedBox.shrink();

    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 8,
            offset: const Offset(0, -2),
          ),
        ],
      ),
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      child: SafeArea(
        top: false,
        child: SizedBox(
          width: double.infinity,
          height: 52,
          child: FilledButton.icon(
            onPressed: callback,
            icon: Icon(icon),
            label: Text(label, style: const TextStyle(fontSize: 16)),
            style: FilledButton.styleFrom(
              backgroundColor: color,
            ),
          ),
        ),
      ),
    );
  }

  (String?, IconData, VoidCallback, Color?) _actionForStatus() {
    switch (status) {
      case RideStatus.matched:
        return ('En Route to Pickup', Icons.navigation, onEnRoute, Colors.blue);
      case RideStatus.driverEnRoute:
        return ('Arrived at Pickup', Icons.place, onArrived, Colors.orange);
      case RideStatus.arrived:
        return ('Start Ride', Icons.play_arrow, onStartRide, Colors.green);
      case RideStatus.inProgress:
        return (
          'Complete Ride',
          Icons.check_circle,
          onCompleteRide,
          Colors.teal
        );
      case RideStatus.completed:
        return ('Done', Icons.done, onDone, null);
      default:
        return (null, Icons.error, () {}, null);
    }
  }
}
