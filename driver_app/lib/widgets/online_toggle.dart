import 'package:flutter/material.dart';

/// A large, prominent button that toggles the driver between online and
/// offline states. Visually distinct so the driver can glance at it quickly.
class OnlineToggle extends StatelessWidget {
  final bool isOnline;
  final bool isLoading;
  final VoidCallback onToggle;

  const OnlineToggle({
    super.key,
    required this.isOnline,
    required this.isLoading,
    required this.onToggle,
  });

  @override
  Widget build(BuildContext context) {
    final color = isOnline ? Colors.green : Theme.of(context).colorScheme.outline;

    return Material(
      elevation: 6,
      shape: const CircleBorder(),
      color: color,
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: isLoading ? null : onToggle,
        child: SizedBox(
          width: 72,
          height: 72,
          child: Center(
            child: isLoading
                ? const SizedBox(
                    width: 28,
                    height: 28,
                    child: CircularProgressIndicator(
                      strokeWidth: 3,
                      color: Colors.white,
                    ),
                  )
                : Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        isOnline ? Icons.power_settings_new : Icons.power_off,
                        color: Colors.white,
                        size: 28,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        isOnline ? 'ON' : 'OFF',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}
