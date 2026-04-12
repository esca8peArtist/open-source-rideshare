import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:rideshare_rider/providers/ride_provider.dart';

class RideRatingScreen extends ConsumerStatefulWidget {
  final int rideId;

  const RideRatingScreen({super.key, required this.rideId});

  @override
  ConsumerState<RideRatingScreen> createState() => _RideRatingScreenState();
}

class _RideRatingScreenState extends ConsumerState<RideRatingScreen> {
  int _rating = 0;
  double _tipAmount = 0;
  bool _isSubmitting = false;
  final _tipController = TextEditingController();

  final _tipPresets = [0.0, 1.0, 2.0, 5.0];

  @override
  void dispose() {
    _tipController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_rating == 0) return;

    setState(() => _isSubmitting = true);
    try {
      final rideService = ref.read(rideServiceProvider);
      await rideService.rateRide(widget.rideId, _rating, tipAmount: _tipAmount);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Thanks for your feedback!')),
        );
        context.go('/history');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not submit rating. Try again.')),
        );
      }
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Rate Your Ride'),
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: () => context.go('/history'),
        ),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            children: [
              const Spacer(),
              Icon(
                Icons.star_rounded,
                size: 64,
                color: colorScheme.primary,
              ),
              const SizedBox(height: 16),
              Text(
                'How was your ride?',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 24),

              // Star rating
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(5, (index) {
                  final starValue = index + 1;
                  return GestureDetector(
                    onTap: () => setState(() => _rating = starValue),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: Icon(
                        starValue <= _rating
                            ? Icons.star_rounded
                            : Icons.star_outline_rounded,
                        size: 48,
                        color: starValue <= _rating
                            ? Colors.amber
                            : colorScheme.outlineVariant,
                      ),
                    ),
                  );
                }),
              ),
              if (_rating > 0) ...[
                const SizedBox(height: 8),
                Text(
                  _ratingLabel(_rating),
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: colorScheme.outline,
                      ),
                ),
              ],

              const SizedBox(height: 32),

              // Tip section
              Text(
                'Add a tip for your driver',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: _tipPresets.map((amount) {
                  final isSelected = _tipAmount == amount;
                  return Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    child: ChoiceChip(
                      label: Text(
                          amount == 0 ? 'No tip' : '\$${amount.toInt()}'),
                      selected: isSelected,
                      onSelected: (selected) {
                        setState(() {
                          _tipAmount = amount;
                          _tipController.clear();
                        });
                      },
                    ),
                  );
                }).toList(),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: 120,
                child: TextField(
                  controller: _tipController,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  textAlign: TextAlign.center,
                  decoration: const InputDecoration(
                    hintText: 'Custom',
                    prefixText: '\$ ',
                    border: OutlineInputBorder(),
                    isDense: true,
                  ),
                  onChanged: (value) {
                    final parsed = double.tryParse(value);
                    if (parsed != null && parsed >= 0) {
                      setState(() => _tipAmount = parsed);
                    }
                  },
                ),
              ),

              const Spacer(),

              // Submit button
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed:
                      _rating > 0 && !_isSubmitting ? _submit : null,
                  child: _isSubmitting
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Text(_tipAmount > 0
                          ? 'Submit Rating & \$${_tipAmount.toStringAsFixed(2)} Tip'
                          : 'Submit Rating'),
                ),
              ),
              const SizedBox(height: 8),
              TextButton(
                onPressed: () => context.go('/history'),
                child: const Text('Skip'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _ratingLabel(int rating) => switch (rating) {
        1 => 'Poor',
        2 => 'Below Average',
        3 => 'Average',
        4 => 'Great',
        5 => 'Excellent!',
        _ => '',
      };
}
