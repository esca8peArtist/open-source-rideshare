import { apiClient } from './client';
import type { Payment, PaginationConfig } from '../types';

interface PaymentsListParams {
  page?: number;
  per_page?: number;
  status?: string;
  date_from?: string;
  date_to?: string;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
}

interface PaymentsListResponse {
  payments: Payment[];
  pagination: PaginationConfig;
}

export async function fetchPayments(params: PaymentsListParams = {}): Promise<PaymentsListResponse> {
  const response = await apiClient.get<PaymentsListResponse>('/api/v1/admin/payments', { params });
  return response.data;
}

export async function fetchPayment(paymentId: number): Promise<Payment> {
  const response = await apiClient.get<Payment>(`/api/v1/admin/payments/${paymentId}`);
  return response.data;
}

export async function processRefund(rideId: number): Promise<{ status: string }> {
  const response = await apiClient.post<{ status: string }>(`/api/v1/payments/${rideId}/refund`);
  return response.data;
}
