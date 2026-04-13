import { apiClient } from './client';
import type { DashboardStats, RevenueDataPoint, RideActivityDataPoint, PlatformSettings } from '../types';

export async function fetchDashboardStats(): Promise<DashboardStats> {
  const response = await apiClient.get<DashboardStats>('/api/v1/admin/stats');
  return response.data;
}

export async function fetchRevenueTimeSeries(
  period: 'week' | 'month' | 'year' = 'month',
): Promise<RevenueDataPoint[]> {
  const response = await apiClient.get<RevenueDataPoint[]>('/api/v1/admin/stats/revenue', {
    params: { period },
  });
  return response.data;
}

export async function fetchRideActivity(
  period: 'today' | 'week' = 'today',
): Promise<RideActivityDataPoint[]> {
  const response = await apiClient.get<RideActivityDataPoint[]>('/api/v1/admin/stats/ride-activity', {
    params: { period },
  });
  return response.data;
}

export async function fetchPlatformSettings(): Promise<PlatformSettings> {
  const response = await apiClient.get<PlatformSettings>('/api/v1/admin/settings');
  return response.data;
}

export async function updatePlatformSettings(settings: PlatformSettings): Promise<PlatformSettings> {
  const response = await apiClient.put<PlatformSettings>('/api/v1/admin/settings', settings);
  return response.data;
}
