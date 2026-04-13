import { useEffect, useState } from 'react';
import { Car, Users, DollarSign, Activity } from 'lucide-react';
import { format } from 'date-fns';
import MetricCard from '../components/MetricCard';
import RevenueChart from '../components/RevenueChart';
import RideActivityChart from '../components/RideActivityChart';
import StatusBadge from '../components/StatusBadge';
import { fetchDashboardStats, fetchRevenueTimeSeries, fetchRideActivity } from '../api/stats';
import { fetchRecentRides } from '../api/rides';
import type { DashboardStats, RevenueDataPoint, RideActivityDataPoint, Ride } from '../types';

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [revenueData, setRevenueData] = useState<RevenueDataPoint[]>([]);
  const [activityData, setActivityData] = useState<RideActivityDataPoint[]>([]);
  const [recentRides, setRecentRides] = useState<Ride[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [s, r, a, rides] = await Promise.all([
          fetchDashboardStats(),
          fetchRevenueTimeSeries('month'),
          fetchRideActivity('today'),
          fetchRecentRides(8),
        ]);
        setStats(s);
        setRevenueData(r);
        setActivityData(a);
        setRecentRides(rides);
      } catch (err) {
        console.error('Failed to load dashboard data:', err);
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Dashboard</h2>
        <p className="text-sm text-gray-500 mt-1">Platform overview and key metrics</p>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          label="Active Rides"
          value={stats?.active_rides ?? '-'}
          icon={Activity}
          color="blue"
        />
        <MetricCard
          label="Online Drivers"
          value={stats?.online_drivers ?? '-'}
          icon={Car}
          color="green"
        />
        <MetricCard
          label="Revenue Today"
          value={stats ? `$${stats.revenue_today.toFixed(2)}` : '-'}
          icon={DollarSign}
          color="yellow"
        />
        <MetricCard
          label="Total Users"
          value={stats?.total_users ?? '-'}
          icon={Users}
          color="purple"
        />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <RevenueChart data={revenueData} isLoading={isLoading} />
        <RideActivityChart data={activityData} isLoading={isLoading} />
      </div>

      {/* Recent Rides */}
      <div className="card">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Recent Rides</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Pickup</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Dropoff</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Fare</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Requested</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                    Loading...
                  </td>
                </tr>
              ) : recentRides.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                    No recent rides
                  </td>
                </tr>
              ) : (
                recentRides.map((ride) => (
                  <tr key={ride.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">#{ride.id}</td>
                    <td className="px-4 py-3 text-sm text-gray-600 max-w-[200px] truncate">
                      {ride.pickup_address}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 max-w-[200px] truncate">
                      {ride.dropoff_address}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900">
                      ${(ride.actual_fare ?? ride.estimated_fare).toFixed(2)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={ride.status} type="ride" />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {format(new Date(ride.requested_at), 'MMM d, h:mm a')}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
