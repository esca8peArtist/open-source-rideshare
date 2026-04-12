import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';

class LocationSearchBar extends StatefulWidget {
  final String hint;
  final IconData icon;
  final Color? iconColor;
  final void Function(LatLng location, String address) onSelected;

  const LocationSearchBar({
    super.key,
    required this.hint,
    required this.icon,
    this.iconColor,
    required this.onSelected,
  });

  @override
  State<LocationSearchBar> createState() => _LocationSearchBarState();
}

class _LocationSearchBarState extends State<LocationSearchBar> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(8),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 4,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: TextField(
        controller: _controller,
        decoration: InputDecoration(
          hintText: widget.hint,
          prefixIcon: Icon(widget.icon,
              size: 16, color: widget.iconColor ?? Theme.of(context).colorScheme.outline),
          border: InputBorder.none,
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        ),
        onSubmitted: (value) {
          // TODO: integrate with geocoding service (Nominatim/MapBox)
          // For now, this is a placeholder — the map tap handler in HomeScreen
          // provides the actual location selection
        },
      ),
    );
  }
}
