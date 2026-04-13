import { useCallback, useEffect, useState } from 'react';
import { CheckCircle, XCircle } from 'lucide-react';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import { fetchDrivers, approveDriver, suspendDriver } from '../api/drivers';
import type { DriverProfile, TableColumn, SortConfig, PaginationConfig } from '../types';

const FILTER_OPTIONS = [
  { value: 'all', label: 'All Drivers' },
  { value: 'approved', label: 'Approved' },
  { value: 'pending', label: 'Pending Approval' },
  { value: 'online', label: 'Online' },
  { value: 'offline', label: 'Offline' },
];

export default function DriversPage() {
  const [drivers, setDrivers] = useState<DriverProfile[]>([]);
  const [pagination, setPagination] = useState<PaginationConfig>({ page: 1, per_page: 20, total: 0 });
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [sort, setSort] = useState<SortConfig>({ key: 'created_at', direction: 'desc' });
  const [isLoading, setIsLoading] = useState(true);

  const loadDrivers = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await fetchDrivers({
        page: pagination.page,
        per_page: pagination.per_page,
        status: statusFilter as 'all' | 'approved' | 'pending' | 'online' | 'offline',
        search: searchQuery || undefined,
        sort_by: sort.key,
        sort_dir: sort.direction,
      });
      setDrivers(result.drivers);
      setPagination(result.pagination);
    } catch (err) {
      console.error('Failed to load drivers:', err);
    } finally {
      setIsLoading(false);
    }
  }, [pagination.page, pagination.per_page, statusFilter, searchQuery, sort]);

  useEffect(() => {
    loadDrivers();
  }, [loadDrivers]);

  const handleApprove = async (driver: DriverProfile) => {
    if (!confirm(`Approve driver ${driver.user_name ?? '#' + driver.user_id}?`)) return;
    try {
      await approveDriver(driver.id);
      loadDrivers();
    } catch (err) {
      console.error('Failed to approve driver:', err);
    }
  };

  const handleSuspend = async (driver: DriverProfile) => {
    const reason = prompt('Reason for suspension:');
    if (!reason) return;
    try {
      await suspendDriver(driver.id, reason);
      loadDrivers();
    } catch (err) {
      console.error('Failed to suspend driver:', err);
    }
  };

  const columns: TableColumn<DriverProfile>[] = [
    { key: 'id', label: 'ID', sortable: true, render: (d) => `#${d.id}` },
    { key: 'user_name', label: 'Name', sortable: true,
      render: (d) => d.user_name ?? `User #${d.user_id}` },
    { key: 'vehicle', label: 'Vehicle', sortable: false,
      render: (d) => `${d.vehicle_color} ${d.vehicle_year} ${d.vehicle_make} ${d.vehicle_model}` },
    { key: 'license_plate', label: 'Plate', sortable: false },
    { key: 'rating_avg', label: 'Rating', sortable: true,
      render: (d) => `${d.rating_avg.toFixed(1)} / 5` },
    { key: 'total_trips', label: 'Trips', sortable: true },
    { key: 'is_online', label: 'Online', sortable: true,
      render: (d) => <StatusBadge status={d.is_online ? 'online' : 'offline'} type="driver" /> },
    { key: 'is_approved', label: 'Approved', sortable: true,
      render: (d) => <StatusBadge status={d.is_approved ? 'approved' : 'pending'} type="driver" /> },
    { key: 'actions', label: 'Actions', sortable: false,
      render: (d) => (
        <div className="flex items-center gap-2">
          {!d.is_approved && (
            <button
              onClick={(e) => { e.stopPropagation(); handleApprove(d); }}
              className="inline-flex items-center gap-1 text-xs font-medium text-green-700 bg-green-50
                         px-2.5 py-1 rounded-lg hover:bg-green-100 transition-colors"
            >
              <CheckCircle className="h-3.5 w-3.5" />
              Approve
            </button>
          )}
          {d.is_approved && (
            <button
              onClick={(e) => { e.stopPropagation(); handleSuspend(d); }}
              className="inline-flex items-center gap-1 text-xs font-medium text-red-700 bg-red-50
                         px-2.5 py-1 rounded-lg hover:bg-red-100 transition-colors"
            >
              <XCircle className="h-3.5 w-3.5" />
              Suspend
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Drivers</h2>
        <p className="text-sm text-gray-500 mt-1">Manage driver profiles, approvals, and statuses</p>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap gap-4">
          <input
            type="text"
            placeholder="Search by name, phone, or plate..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setPagination((p) => ({ ...p, page: 1 }));
            }}
            className="input-field max-w-sm"
          />
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPagination((p) => ({ ...p, page: 1 }));
            }}
            className="input-field max-w-[200px]"
          >
            {FILTER_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <DataTable
          columns={columns}
          data={drivers}
          keyField="id"
          isLoading={isLoading}
          onSort={setSort}
          pagination={{
            ...pagination,
            onPageChange: (page) => setPagination((p) => ({ ...p, page })),
          }}
          emptyMessage="No drivers match your filters."
        />
      </div>
    </div>
  );
}
