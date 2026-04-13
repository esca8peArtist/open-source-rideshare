import type { RideStatus, PaymentStatus } from '../types';

type BadgeVariant = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

const RIDE_STATUS_MAP: Record<RideStatus, { label: string; variant: BadgeVariant }> = {
  requested: { label: 'Requested', variant: 'info' },
  matched: { label: 'Matched', variant: 'info' },
  driver_en_route: { label: 'En Route', variant: 'warning' },
  arrived: { label: 'Arrived', variant: 'warning' },
  in_progress: { label: 'In Progress', variant: 'warning' },
  completed: { label: 'Completed', variant: 'success' },
  cancelled: { label: 'Cancelled', variant: 'danger' },
};

const PAYMENT_STATUS_MAP: Record<PaymentStatus, { label: string; variant: BadgeVariant }> = {
  pending: { label: 'Pending', variant: 'warning' },
  completed: { label: 'Completed', variant: 'success' },
  failed: { label: 'Failed', variant: 'danger' },
  refunded: { label: 'Refunded', variant: 'neutral' },
};

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  success: 'bg-green-100 text-green-800',
  warning: 'bg-yellow-100 text-yellow-800',
  danger: 'bg-red-100 text-red-800',
  info: 'bg-blue-100 text-blue-800',
  neutral: 'bg-gray-100 text-gray-800',
};

interface StatusBadgeProps {
  status: string;
  type?: 'ride' | 'payment' | 'driver';
}

export default function StatusBadge({ status, type = 'ride' }: StatusBadgeProps) {
  let config: { label: string; variant: BadgeVariant };

  if (type === 'ride') {
    config = RIDE_STATUS_MAP[status as RideStatus] || { label: status, variant: 'neutral' };
  } else if (type === 'payment') {
    config = PAYMENT_STATUS_MAP[status as PaymentStatus] || { label: status, variant: 'neutral' };
  } else {
    // Driver status: online/offline/approved/pending
    if (status === 'online') config = { label: 'Online', variant: 'success' };
    else if (status === 'approved') config = { label: 'Approved', variant: 'success' };
    else if (status === 'pending') config = { label: 'Pending', variant: 'warning' };
    else if (status === 'suspended') config = { label: 'Suspended', variant: 'danger' };
    else config = { label: status, variant: 'neutral' };
  }

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${VARIANT_CLASSES[config.variant]}`}
    >
      {config.label}
    </span>
  );
}
