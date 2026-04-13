import { useEffect, useState } from 'react';
import { Save, RotateCcw } from 'lucide-react';
import { fetchPlatformSettings, updatePlatformSettings } from '../api/stats';
import type { PlatformSettings } from '../types';

const DEFAULT_SETTINGS: PlatformSettings = {
  base_fare: 2.50,
  per_km_rate: 1.20,
  per_min_rate: 0.30,
  platform_fee_percent: 15,
  max_search_radius_km: 10,
  surge_multiplier: 1.0,
};

interface SettingField {
  key: keyof PlatformSettings;
  label: string;
  description: string;
  unit: string;
  step: number;
  min: number;
  max: number;
}

const FIELDS: SettingField[] = [
  { key: 'base_fare', label: 'Base Fare', description: 'Fixed charge applied to every ride', unit: '$', step: 0.25, min: 0, max: 50 },
  { key: 'per_km_rate', label: 'Per-Kilometer Rate', description: 'Charge per kilometer of travel distance', unit: '$/km', step: 0.05, min: 0, max: 20 },
  { key: 'per_min_rate', label: 'Per-Minute Rate', description: 'Charge per minute of ride duration', unit: '$/min', step: 0.05, min: 0, max: 10 },
  { key: 'platform_fee_percent', label: 'Platform Fee', description: 'Percentage deducted from each fare as cooperative platform fee', unit: '%', step: 0.5, min: 0, max: 50 },
  { key: 'max_search_radius_km', label: 'Max Search Radius', description: 'Maximum distance to search for available drivers', unit: 'km', step: 1, min: 1, max: 100 },
  { key: 'surge_multiplier', label: 'Surge Multiplier', description: 'Current surge pricing multiplier (1.0 = no surge)', unit: 'x', step: 0.1, min: 1, max: 5 },
];

export default function SettingsPage() {
  const [settings, setSettings] = useState<PlatformSettings>(DEFAULT_SETTINGS);
  const [originalSettings, setOriginalSettings] = useState<PlatformSettings>(DEFAULT_SETTINGS);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');

  useEffect(() => {
    fetchPlatformSettings()
      .then((s) => {
        setSettings(s);
        setOriginalSettings(s);
      })
      .catch((err) => console.error('Failed to load settings:', err))
      .finally(() => setIsLoading(false));
  }, []);

  const hasChanges = JSON.stringify(settings) !== JSON.stringify(originalSettings);

  const handleSave = async () => {
    setIsSaving(true);
    setSuccessMessage('');
    try {
      const updated = await updatePlatformSettings(settings);
      setSettings(updated);
      setOriginalSettings(updated);
      setSuccessMessage('Settings saved successfully.');
      setTimeout(() => setSuccessMessage(''), 3000);
    } catch (err) {
      console.error('Failed to save settings:', err);
      alert('Failed to save settings. Please try again.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    setSettings(originalSettings);
  };

  const updateField = (key: keyof PlatformSettings, value: number) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Platform Settings</h2>
        <p className="text-sm text-gray-500 mt-1">Configure pricing, search radius, and platform parameters</p>
      </div>

      {successMessage && (
        <div className="bg-green-50 border border-green-200 text-green-700 text-sm rounded-lg px-4 py-3">
          {successMessage}
        </div>
      )}

      <div className="card space-y-6">
        {FIELDS.map((field) => (
          <div key={field.key} className="flex items-start justify-between gap-8">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-900">{field.label}</label>
              <p className="text-xs text-gray-500 mt-0.5">{field.description}</p>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="number"
                value={settings[field.key]}
                onChange={(e) => updateField(field.key, parseFloat(e.target.value) || 0)}
                step={field.step}
                min={field.min}
                max={field.max}
                className="input-field w-28 text-right"
              />
              <span className="text-sm text-gray-500 w-12">{field.unit}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <button onClick={handleSave} disabled={!hasChanges || isSaving} className="btn-primary flex items-center gap-2">
          <Save className="h-4 w-4" />
          {isSaving ? 'Saving...' : 'Save Changes'}
        </button>
        <button onClick={handleReset} disabled={!hasChanges} className="btn-secondary flex items-center gap-2">
          <RotateCcw className="h-4 w-4" />
          Reset
        </button>
      </div>
    </div>
  );
}
