import { useCallback, useEffect, useState } from 'react';
import { format } from 'date-fns';
import { RefreshCw } from 'lucide-react';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import RevenueChart from '../components/RevenueChart';
import { fetchPayments, processRefund } from '../api/payments';
import { fetchRevenueTimeSeries } from '../api/stats';
import type { Payment, RevenueDataPoint, TableColumn, SortConfig, PaginationConfig } from '../types';

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'refunded', label: 'Refunded' },
];

export default function PaymentsPage() {
  const [payments, setPayments] = useState<Payment[]>([]);
  const [pagination, setPagination] = useState<PaginationConfig>({ page: 1, per_page: 20, total: 0 });
  const [statusFilter, setStatusFilter] = useState('');
  const [sort, setSort] = useState<SortConfig>({ key: 'created_at', direction: 'desc' });
  const [isLoading, setIsLoading] = useState(true);
  const [revenueData, setRevenueData] = useState<RevenueDataPoint[]>([]);
  const [revenuePeriod, setRevenuePeriod] = useState<'week' | 'month' | 'year'>('month');

  const loadPayments = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await fetchPayments({
        page: pagination.page,
        per_page: pagination.per_page,
        status: statusFilter || undefined,
        sort_by: sort.key,
        sort_dir: sort.direction,
      });
      setPayments(result.payments);
      setPagination(result.pagination);
    } catch (err) {
      console.error('Failed to load payments:', err);
    } finally {
      setIsLoading(false);
    }
  }, [pagination.page, pagination.per_page, statusFilter, sort]);

  useEffect(() => {
    loadPayments();
  }, [loadPayments]);

  useEffect(() => {
    fetchRevenueTimeSeries(revenuePeriod)
      .then(setRevenueData)
      .catch((err) => console.error('Failed to load revenue data:', err));
  }, [revenuePeriod]);

  const handleRefund = async (payment: Payment) => {
    if (!confirm(`Process refund for ride #${payment.ride_id} ($${payment.amount.toFixed(2)})?`)) return;
    try {
      await processRefund(payment.ride_id);
      loadPayments();
    } catch (err) {
      console.error('Failed to process refund:', err);
    }
  };

  const columns: TableColumn<Payment>[] = [
    { key: 'id', label: 'ID', sortable: true, render: (p) => `#${p.id}` },
    { key: 'ride_id', label: 'Ride', sortable: true, render: (p) => `#${p.ride_id}` },
    { key: 'rider_name', label: 'Rider', sortable: false,
      render: (p) => p.rider_name ?? '-' },
    { key: 'amount', label: 'Amount', sortable: true,
      render: (p) => `$${p.amount.toFixed(2)}` },
    { key: 'platform_fee', label: 'Platform Fee', sortable: true,
      render: (p) => `$${p.platform_fee.toFixed(2)}` },
    { key: 'driver_payout', label: 'Driver Payout', sortable: true,
      render: (p) => `$${p.driver_payout.toFixed(2)}` },
    { key: 'tip_amount', label: 'Tip', sortable: true,
      render: (p) => `$${p.tip_amount.toFixed(2)}` },
    { key: 'status', label: 'Status', sortable: true,
      render: (p) => <StatusBadge status={p.status} type="payment" /> },
    { key: 'created_at', label: 'Date', sortable: true,
      render: (p) => format(new Date(p.created_at), 'MMM d, yyyy h:mm a') },
    { key: 'actions', label: '', sortable: false,
      render: (p) =>
        p.status === 'completed' ? (
          <button
            onClick={(e) => { e.stopPropagation(); handleRefund(p); }}
            className="inline-flex items-center gap-1 text-xs font-medium text-orange-700 bg-orange-50
                       px-2.5 py-1 rounded-lg hover:bg-orange-100 transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refund
          </button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Payments</h2>
        <p className="text-sm text-gray-500 mt-1">Payment history, revenue tracking, and refund management</p>
      </div>

      {/* Revenue Chart */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <div />
          <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5">
            {(['week', 'month', 'year'] as const).map((p) => (
              <button
                key={p}
                onClick={() => setRevenuePeriod(p)}
                className={`px-3 py-1 text-sm rounded-md transition-colors ${
                  revenuePeriod === p
                    ? 'bg-white shadow-sm font-medium text-gray-900'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {p.charAt(0).toUpperCase() + p.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <RevenueChart data={revenueData} />
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap gap-4">
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPagination((p) => ({ ...p, page: 1 }));
            }}
            className="input-field max-w-[200px]"
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <DataTable
          columns={columns}
          data={payments}
          keyField="id"
          isLoading={isLoading}
          onSort={setSort}
          pagination={{
            ...pagination,
            onPageChange: (page) => setPagination((p) => ({ ...p, page })),
          }}
          emptyMessage="No payments match your filters."
        />
      </div>
    </div>
  );
}
