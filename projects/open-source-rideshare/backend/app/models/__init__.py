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
from app.models.hardship_fund import DriverHardshipFund, HardshipContribution, HardshipApplication  # noqa: F401
from app.models.driver_language import DriverLanguage, RiderLanguagePreference  # noqa: F401
from app.models.corporate import BusinessAccount, BusinessAccountMember  # noqa: F401
from app.models.corporate_batch_booking import CorporateBatchBooking, CorporateBatchRideRequest  # noqa: F401
from app.models.corporate_trip_purpose import CorporateTripPurpose  # noqa: F401
from app.models.corporate_guest_pass import CorporateGuestPass  # noqa: F401
from app.models.corporate_cost_center import CorporateCostCenter  # noqa: F401
from app.models.corporate_budget_alert import CorporateBudgetAlert  # noqa: F401
from app.models.corporate_employee_invitation import CorporateEmployeeInvitation  # noqa: F401
from app.models.corporate_custom_field import CorporateCustomField, CorporateRideCustomFieldValue  # noqa: F401
from app.models.corporate_webhook import CorporateWebhook, CorporateWebhookDelivery  # noqa: F401
from app.models.corporate_scheduled_report import CorporateScheduledReport  # noqa: F401
from app.models.corporate_notification_settings import CorporateNotificationConfig  # noqa: F401
from app.models.corporate_employee_group import CorporateEmployeeGroup, CorporateGroupMembership  # noqa: F401
from app.models.corporate_commuter_benefit import CorporateCommuterProgram, CorporateCommuterAllotment  # noqa: F401
from app.models.corporate_member_policy_override import CorporateMemberPolicyOverride  # noqa: F401
from app.models.corporate_travel_itinerary import CorporateTravelItinerary, CorporateItineraryRide  # noqa: F401
from app.models.corporate_event import CorporateEvent, CorporateEventAttendee  # noqa: F401
from app.models.corporate_office_location import CorporateOfficeLocation, CorporateOfficeMembership  # noqa: F401
from app.models.corporate_account_hierarchy import CorporateAccountHierarchy  # noqa: F401
from app.models.corporate_carpool_group import CorporateCarpoolGroup, CorporateCarpoolMember  # noqa: F401
from app.models.corporate_member_offboarding import CorporateMemberOffboarding  # noqa: F401
from app.models.corporate_member_onboarding import CorporateMemberOnboarding  # noqa: F401
from app.models.corporate_billing_currency import CorporateBillingCurrency, CorporateInvoiceFXSnapshot  # noqa: F401
from app.models.corporate_fleet_vehicle import CorporateFleetVehicle, CorporateFleetAssignment  # noqa: F401
from app.models.corporate_vehicle_reservation import CorporateVehicleReservation, ReservationStatus  # noqa: F401
from app.models.corporate_mileage_reimbursement import CorporateMileagePolicy, CorporateMileageClaim, ClaimStatus  # noqa: F401
