// ---- User / Auth ----

export type UserRole = 'rider' | 'driver' | 'admin';

export interface User {
  id: number;
  phone: string;
  email: string | null;
  name: string;
  role: UserRole;
  is_active: boolean;
  phone_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface LoginRequest {
  phone: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

// ---- Ride ----

export type RideStatus =
  | 'requested'
  | 'matched'
  | 'driver_en_route'
  | 'arrived'
  | 'in_progress'
  | 'completed'
  | 'cancelled';

export interface Ride {
  id: number;
  status: RideStatus;
  pickup_address: string;
  dropoff_address: string;
  estimated_fare: number;
  actual_fare: number | null;
  distance_km: number | null;
  duration_min: number | null;
  tip_amount: number;
  rider_id: number;
  driver_id: number | null;
  rider_name?: string;
  driver_name?: string;
  rider_rating: number | null;
  driver_rating: number | null;
  cancellation_reason: string | null;
  requested_at: string;
  matched_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
}

// ---- Driver ----

export interface DriverProfile {
  id: number;
  user_id: number;
  user_name?: string;
  user_phone?: string;
  vehicle_type: string;
  vehicle_make: string;
  vehicle_model: string;
  vehicle_year: number;
  vehicle_color: string;
  license_plate: string;
  license_number: string;
  insurance_policy: string | null;
  background_check_status: string;
  rating_avg: number;
  total_trips: number;
  is_online: boolean;
  is_approved: boolean;
  created_at: string;
  updated_at: string;
}

// ---- Payment ----

export type PaymentStatus = 'pending' | 'completed' | 'failed' | 'refunded';

export interface Payment {
  id: number;
  ride_id: number;
  amount: number;
  platform_fee: number;
  driver_payout: number;
  tip_amount: number;
  status: PaymentStatus;
  created_at: string;
  rider_name?: string;
  driver_name?: string;
  pickup_address?: string;
  dropoff_address?: string;
}

// ---- Stats / Dashboard ----

export interface DashboardStats {
  active_rides: number;
  online_drivers: number;
  revenue_today: number;
  total_users: number;
  rides_today: number;
  completed_today: number;
  cancelled_today: number;
}

export interface RevenueDataPoint {
  date: string;
  revenue: number;
  rides: number;
  tips: number;
}

export interface RideActivityDataPoint {
  hour: string;
  rides: number;
}

// ---- Platform Settings ----

export interface PlatformSettings {
  base_fare: number;
  per_km_rate: number;
  per_min_rate: number;
  platform_fee_percent: number;
  max_search_radius_km: number;
  surge_multiplier: number;
}

// ---- Table / UI ----

export interface SortConfig {
  key: string;
  direction: 'asc' | 'desc';
}

export interface PaginationConfig {
  page: number;
  per_page: number;
  total: number;
}

export interface TableColumn<T> {
  key: keyof T | string;
  label: string;
  sortable?: boolean;
  render?: (row: T) => React.ReactNode;
}
