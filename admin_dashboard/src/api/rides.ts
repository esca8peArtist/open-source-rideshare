import { apiClient } from './client';
import type { Ride, PaginationConfig } from '../types';

interface RidesListParams {
  page?: number;
  per_page?: number;
  status?: string;
  search?: string;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
  date_from?: string;
  date_to?: string;
}

interface RidesListResponse {
  rides: Ride[];
  pagination: PaginationConfig;
}

export async function fetchRides(params: RidesListParams = {}): Promise<RidesListResponse> {
  const response = await apiClient.get<RidesListResponse>('/api/v1/admin/rides', { params });
  return response.data;
}

export async function fetchRide(rideId: number): Promise<Ride> {
  const response = await apiClient.get<Ride>(`/api/v1/admin/rides/${rideId}`);
  return response.data;
}

export async function cancelRide(rideId: number, reason: string): Promise<void> {
  await apiClient.post(`/api/v1/rides/${rideId}/cancel`, { reason });
}

export async function fetchRecentRides(limit: number = 10): Promise<Ride[]> {
  const response = await apiClient.get<RidesListResponse>('/api/v1/admin/rides', {
    params: { per_page: limit, sort_by: 'requested_at', sort_dir: 'desc' },
  });
  return response.data.rides;
}
