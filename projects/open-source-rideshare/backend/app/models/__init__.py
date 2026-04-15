# Import all models so Base.metadata.create_all() discovers them
from app.models.chat import ChatMessage  # noqa: F401
from app.models.driver import DriverProfile  # noqa: F401
from app.models.payment import Payment  # noqa: F401
from app.models.pool import PoolLeg, RidePool  # noqa: F401
from app.models.ride import Ride  # noqa: F401
from app.models.safety import EmergencyContact, SOSAlert, TripShareToken  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.vehicle import Vehicle  # noqa: F401
from app.models.saved_location import SavedLocation  # noqa: F401
from app.models.recurring_ride import RecurringRide  # noqa: F401
from app.models.verification import DriverDocument  # noqa: F401
from app.models.waypoint import RideWaypoint  # noqa: F401
from app.models.fare_split import FareSplit  # noqa: F401
from app.models.notification import NotificationLog, NotificationPreference  # noqa: F401
from app.models.payout import DriverBankAccount, DriverPayout  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.background_check import BackgroundCheck  # noqa: F401
from app.models.device_token import DeviceToken  # noqa: F401
from app.models.tip import TipRecord  # noqa: F401
from app.models.incentive import DriverIncentiveProgress, IncentiveProgram  # noqa: F401
from app.models.rider_rating import RiderRating  # noqa: F401
from app.models.driver_availability import DriverSchedule, DriverOnlineStatus  # noqa: F401
from app.models.driver_insurance import DriverInsuranceDocument, InsuranceExpiryAlert  # noqa: F401
from app.models.vehicle_inspection import VehicleInspection, VehicleInspectionAlert  # noqa: F401
from app.models.driver_performance import DriverPerformanceSnapshot, DriverPerformanceAlert  # noqa: F401
from app.models.complaint import Complaint  # noqa: F401
from app.models.platform_config import PlatformConfig  # noqa: F401
from app.models.driver_tier import DriverCareerTier  # noqa: F401
from app.models.surge_price_lock import SurgePriceLock  # noqa: F401
from app.models.rider_referral import RiderReferralCode, RiderReferral  # noqa: F401
from app.models.service_area import ServiceArea  # noqa: F401
from app.models.driver_quest import DriverQuest, DriverQuestProgress  # noqa: F401
from app.models.driver_proposal import DriverProposal, DriverVote  # noqa: F401
from app.models.driver_dividend import CooperativeDividend, DriverDividendShare  # noqa: F401
from app.models.driver_earnings_guarantee import EarningsGuaranteePolicy, WeeklyGuaranteeRecord  # noqa: F401
from app.models.cancellation import CancellationPolicy, CancellationRecord  # noqa: F401
from app.models.feedback import RideFeedback, Dispute  # noqa: F401
from app.models.driver_rating_appeal import DriverRatingAppeal  # noqa: F401
from app.models.trusted_contact import TrustedContact, TripShareRecord  # noqa: F401
from app.models.driver_shift import DriverShift  # noqa: F401
