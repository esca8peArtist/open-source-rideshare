import { apiClient } from './client';
import type { DriverProfile, PaginationConfig } from '../types';

interface DriversListParams {
  page?: number;
  per_page?: number;
  status?: 'all' | 'approved' | 'pending' | 'online' | 'offline';
  search?: string;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
}

interface DriversListResponse {
  drivers: DriverProfile[];
  pagination: PaginationConfig;
}

export async function fetchDrivers(params: DriversListParams = {}): Promise<DriversListResponse> {
  const response = await apiClient.get<DriversListResponse>('/api/v1/admin/drivers', { params });
  return response.data;
}

export async function fetchDriver(driverId: number): Promise<DriverProfile> {
  const response = await apiClient.get<DriverProfile>(`/api/v1/admin/drivers/${driverId}`);
  return response.data;
}

export async function approveDriver(driverId: number): Promise<void> {
  await apiClient.post(`/api/v1/admin/drivers/${driverId}/approve`);
}

export async function suspendDriver(driverId: number, reason: string): Promise<void> {
  await apiClient.post(`/api/v1/admin/drivers/${driverId}/suspend`, { reason });
}

export async function reactivateDriver(driverId: number): Promise<void> {
  await apiClient.post(`/api/v1/admin/drivers/${driverId}/reactivate`);
}
