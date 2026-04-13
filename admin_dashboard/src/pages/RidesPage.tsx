import { useCallback, useEffect, useState } from 'react';
import { format } from 'date-fns';
import { X } from 'lucide-react';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import { fetchRides, fetchRide } from '../api/rides';
import type { Ride, TableColumn, SortConfig, PaginationConfig } from '../types';

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'requested', label: 'Requested' },
  { value: 'matched', label: 'Matched' },
  { value: 'driver_en_route', label: 'En Route' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
];

export default function RidesPage() {
  const [rides, setRides] = useState<Ride[]>([]);
  const [pagination, setPagination] = useState<PaginationConfig>({ page: 1, per_page: 20, total: 0 });
  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [sort, setSort] = useState<SortConfig>({ key: 'requested_at', direction: 'desc' });
  const [isLoading, setIsLoading] = useState(true);
  const [selectedRide, setSelectedRide] = useState<Ride | null>(null);

  const loadRides = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await fetchRides({
        page: pagination.page,
        per_page: pagination.per_page,
        status: statusFilter || undefined,
        search: searchQuery || undefined,
        sort_by: sort.key,
        sort_dir: sort.direction,
      });
      setRides(result.rides);
      setPagination(result.pagination);
    } catch (err) {
      console.error('Failed to load rides:', err);
    } finally {
      setIsLoading(false);
    }
  }, [pagination.page, pagination.per_page, statusFilter, searchQuery, sort]);

  useEffect(() => {
    loadRides();
  }, [loadRides]);

  const handleRowClick = async (ride: Ride) => {
    try {
      const detail = await fetchRide(ride.id);
      setSelectedRide(detail);
    } catch {
      setSelectedRide(ride);
    }
  };

  const columns: TableColumn<Ride>[] = [
    { key: 'id', label: 'ID', sortable: true, render: (r) => `#${r.id}` },
    { key: 'pickup_address', label: 'Pickup', sortable: false,
      render: (r) => <span className="max-w-[180px] truncate block">{r.pickup_address}</span> },
    { key: 'dropoff_address', label: 'Dropoff', sortable: false,
      render: (r) => <span className="max-w-[180px] truncate block">{r.dropoff_address}</span> },
    { key: 'rider_name', label: 'Rider', sortable: true,
      render: (r) => r.rider_name ?? `User #${r.rider_id}` },
    { key: 'driver_name', label: 'Driver', sortable: true,
      render: (r) => r.driver_name ?? (r.driver_id ? `User #${r.driver_id}` : '-') },
    { key: 'estimated_fare', label: 'Fare', sortable: true,
      render: (r) => `$${(r.actual_fare ?? r.estimated_fare).toFixed(2)}` },
    { key: 'status', label: 'Status', sortable: true,
      render: (r) => <StatusBadge status={r.status} type="ride" /> },
    { key: 'requested_at', label: 'Date', sortable: true,
      render: (r) => format(new Date(r.requested_at), 'MMM d, yyyy h:mm a') },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Rides</h2>
        <p className="text-sm text-gray-500 mt-1">View and manage all rides on the platform</p>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap gap-4">
          <input
            type="text"
            placeholder="Search by address, rider, or driver..."
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
          data={rides}
          keyField="id"
          isLoading={isLoading}
          onSort={setSort}
          onRowClick={handleRowClick}
          pagination={{
            ...pagination,
            onPageChange: (page) => setPagination((p) => ({ ...p, page })),
          }}
          emptyMessage="No rides match your filters."
        />
      </div>

      {/* Ride Detail Modal */}
      {selectedRide && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h3 className="text-lg font-semibold">Ride #{selectedRide.id}</h3>
              <button onClick={() => setSelectedRide(null)} className="p-1 hover:bg-gray-100 rounded-lg">
                <X className="h-5 w-5 text-gray-500" />
              </button>
            </div>
            <div className="px-6 py-4 space-y-4">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-500">Status:</span>
                <StatusBadge status={selectedRide.status} type="ride" />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <DetailField label="Pickup" value={selectedRide.pickup_address} />
                <DetailField label="Dropoff" value={selectedRide.dropoff_address} />
                <DetailField label="Estimated Fare" value={`$${selectedRide.estimated_fare.toFixed(2)}`} />
                <DetailField label="Actual Fare" value={selectedRide.actual_fare ? `$${selectedRide.actual_fare.toFixed(2)}` : '-'} />
                <DetailField label="Distance" value={selectedRide.distance_km ? `${selectedRide.distance_km} km` : '-'} />
                <DetailField label="Duration" value={selectedRide.duration_min ? `${selectedRide.duration_min} min` : '-'} />
                <DetailField label="Tip" value={`$${selectedRide.tip_amount.toFixed(2)}`} />
                <DetailField label="Rider" value={selectedRide.rider_name ?? `#${selectedRide.rider_id}`} />
                <DetailField label="Driver" value={selectedRide.driver_name ?? (selectedRide.driver_id ? `#${selectedRide.driver_id}` : 'Unassigned')} />
                <DetailField label="Rider Rating" value={selectedRide.rider_rating ? `${selectedRide.rider_rating}/5` : '-'} />
                <DetailField label="Driver Rating" value={selectedRide.driver_rating ? `${selectedRide.driver_rating}/5` : '-'} />
                <DetailField label="Requested" value={format(new Date(selectedRide.requested_at), 'MMM d, yyyy h:mm a')} />
              </div>

              {selectedRide.cancellation_reason && (
                <div>
                  <span className="text-sm font-medium text-gray-500">Cancellation Reason:</span>
                  <p className="text-sm text-gray-700 mt-1">{selectedRide.cancellation_reason}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-gray-500 uppercase">{label}</p>
      <p className="text-sm text-gray-900 mt-0.5">{value}</p>
    </div>
  );
}
