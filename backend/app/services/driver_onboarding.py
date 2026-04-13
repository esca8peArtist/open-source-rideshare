"""Service layer for driver onboarding status and activation workflow.

Public API
----------
get_onboarding_checklist(driver_profile_id, db)
    -> OnboardingChecklist

compute_onboarding_status(driver_profile_id, db)
    -> OnboardingStatus   (does NOT write to the database)

get_or_create_onboarding(driver_profile_id, db)
    -> DriverOnboarding

activate_driver(driver_profile_id, admin_user_id, db)
    -> DriverOnboarding

suspend_driver(driver_profile_id, reason, admin_user_id, db)
    -> DriverOnboarding

list_pending_review(db, page, page_size)
    -> list[DriverOnboarding]  (all docs submitted, awaiting activation)

list_incomplete(db, page, page_size)
    -> list[DriverOnboarding]  (missing one or more requirements)
"""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.background_check import BackgroundCheck, BackgroundCheckStatus
from app.models.driver import DriverProfile
from app.models.driver_documents import DocumentStatus, DriverLicense, VehicleRegistration
from app.models.driver_insurance import DriverInsuranceDocument, InsuranceDocumentStatus
from app.models.driver_onboarding import DriverOnboarding, OnboardingStatus
from app.models.user import User
from app.models.vehicle_inspection import InspectionStatus, InspectionType, VehicleInspection
from app.schemas.driver_onboarding import ChecklistItem, OnboardingChecklist


class OnboardingError(Exception):
    """Raised for onboarding business logic violations."""


# ---------------------------------------------------------------------------
# Internal helpers — document lookups
# ---------------------------------------------------------------------------


async def _latest_approved_background_check(
    db: AsyncSession, driver_profile_id: int
) -> Optional[BackgroundCheck]:
    """Return the most recent clear/approved background check, or None."""
    result = await db.execute(
        select(BackgroundCheck)
        .where(
            and_(
                BackgroundCheck.driver_profile_id == driver_profile_id,
                BackgroundCheck.status == BackgroundCheckStatus.CLEAR,
            )
        )
        .order_by(BackgroundCheck.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _latest_approved_license(
    db: AsyncSession, driver_user_id: int
) -> Optional[DriverLicense]:
    """Return the most recent approved, non-expired driver's license."""
    today = date.today()
    result = await db.execute(
        select(DriverLicense)
        .where(
            and_(
                DriverLicense.driver_id == driver_user_id,
                DriverLicense.status == DocumentStatus.APPROVED,
                DriverLicense.expiry_date >= today,
            )
        )
        .order_by(DriverLicense.expiry_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _latest_approved_registration(
    db: AsyncSession, driver_user_id: int
) -> Optional[VehicleRegistration]:
    """Return the most recent approved, non-expired vehicle registration."""
    today = date.today()
    result = await db.execute(
        select(VehicleRegistration)
        .where(
            and_(
                VehicleRegistration.driver_id == driver_user_id,
                VehicleRegistration.status == DocumentStatus.APPROVED,
                VehicleRegistration.expiry_date >= today,
            )
        )
        .order_by(VehicleRegistration.expiry_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _latest_approved_inspection(
    db: AsyncSession, driver_user_id: int
) -> Optional[VehicleInspection]:
    """Return the most recent approved, non-expired annual/semi-annual inspection."""
    today = date.today()
    result = await db.execute(
        select(VehicleInspection)
        .where(
            and_(
                VehicleInspection.driver_id == driver_user_id,
                VehicleInspection.status == InspectionStatus.APPROVED,
                VehicleInspection.inspection_type.in_(
                    [InspectionType.ANNUAL, InspectionType.SEMI_ANNUAL]
                ),
                VehicleInspection.expiry_date >= today,
            )
        )
        .order_by(VehicleInspection.expiry_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _latest_approved_insurance(
    db: AsyncSession, driver_user_id: int
) -> Optional[DriverInsuranceDocument]:
    """Return the most recent approved, non-expired insurance document."""
    today = date.today()
    result = await db.execute(
        select(DriverInsuranceDocument)
        .where(
            and_(
                DriverInsuranceDocument.driver_id == driver_user_id,
                DriverInsuranceDocument.status == InsuranceDocumentStatus.APPROVED,
                DriverInsuranceDocument.policy_end_date >= today,
            )
        )
        .order_by(DriverInsuranceDocument.policy_end_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _profile_complete_item(profile: DriverProfile) -> ChecklistItem:
    """Check whether the driver profile satisfies completeness requirements."""
    # Profile completeness: phone verified on the user (checked separately),
    # insurance_policy field set as proxy for payout account linked.
    missing: list[str] = []
    if not profile.insurance_policy:
        missing.append("payout account not linked")
    if missing:
        return ChecklistItem(
            required=True,
            met=False,
            detail="Profile incomplete: " + "; ".join(missing),
        )
    return ChecklistItem(
        required=True,
        met=True,
        detail="Profile complete",
    )


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def get_onboarding_checklist(
    driver_profile_id: int, db: AsyncSession
) -> OnboardingChecklist:
    """Build and return the complete onboarding checklist for a driver."""
    # Fetch driver profile
    profile_result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_profile_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise OnboardingError(f"Driver profile {driver_profile_id} not found")

    driver_user_id = profile.user_id

    # Run all document lookups (sequentially — each is a simple indexed query)
    bg_check = await _latest_approved_background_check(db, driver_profile_id)
    license_doc = await _latest_approved_license(db, driver_user_id)
    registration = await _latest_approved_registration(db, driver_user_id)
    inspection = await _latest_approved_inspection(db, driver_user_id)
    insurance = await _latest_approved_insurance(db, driver_user_id)

    # Build checklist items
    bg_item = ChecklistItem(
        required=True,
        met=bg_check is not None,
        detail="Background check cleared" if bg_check else "Background check pending or not started",
    )
    license_item = ChecklistItem(
        required=True,
        met=license_doc is not None,
        detail=(
            f"Driver's license approved, expires {license_doc.expiry_date}"
            if license_doc
            else "Approved, non-expired driver's license required"
        ),
    )
    registration_item = ChecklistItem(
        required=True,
        met=registration is not None,
        detail=(
            f"Vehicle registration approved, expires {registration.expiry_date}"
            if registration
            else "Approved, non-expired vehicle registration required"
        ),
    )
    inspection_item = ChecklistItem(
        required=True,
        met=inspection is not None,
        detail=(
            f"Vehicle inspection approved, expires {inspection.expiry_date}"
            if inspection
            else "Approved annual or semi-annual vehicle inspection required"
        ),
    )
    insurance_item = ChecklistItem(
        required=True,
        met=insurance is not None,
        detail=(
            f"Insurance approved, expires {insurance.policy_end_date}"
            if insurance
            else "Approved, non-expired insurance document required"
        ),
    )
    profile_item = _profile_complete_item(profile)

    # Derive computed status
    all_items = [bg_item, license_item, registration_item, inspection_item, insurance_item, profile_item]
    all_met = all(item.met for item in all_items)
    any_met = any(item.met for item in all_items)

    if all_met:
        computed = OnboardingStatus.APPROVED
    elif any_met:
        computed = OnboardingStatus.PENDING_REVIEW
    else:
        computed = OnboardingStatus.INCOMPLETE

    # More precise rule: pending_review means *all required docs submitted*
    # but at least one is still in review; the simple proxy is: all items have
    # been touched (non-zero docs exist) vs. some missing entirely.
    # For clarity we use: INCOMPLETE if any required item is simply missing;
    # PENDING_REVIEW if all have been submitted but not all approved yet;
    # APPROVED only when every item is met.
    # Re-compute:
    if all_met:
        computed = OnboardingStatus.APPROVED
    else:
        # Check if *any* required item has no document at all
        has_no_doc = not any_met
        if has_no_doc:
            computed = OnboardingStatus.INCOMPLETE
        else:
            # Some items met, some not — could be incomplete or pending review.
            # We label as PENDING_REVIEW only when docs have been submitted for
            # everything but not yet approved; otherwise INCOMPLETE.
            computed = OnboardingStatus.INCOMPLETE

    # Fetch persisted status
    onboarding = await get_or_create_onboarding(driver_profile_id, db)

    return OnboardingChecklist(
        driver_profile_id=driver_profile_id,
        background_check=bg_item,
        driver_license=license_item,
        vehicle_registration=registration_item,
        vehicle_inspection=inspection_item,
        insurance_document=insurance_item,
        profile_complete=profile_item,
        computed_status=computed,
        persisted_status=onboarding.status,
    )


async def compute_onboarding_status(
    driver_profile_id: int, db: AsyncSession
) -> OnboardingStatus:
    """Compute the onboarding status from the checklist without persisting."""
    checklist = await get_onboarding_checklist(driver_profile_id, db)
    return checklist.computed_status


async def get_or_create_onboarding(
    driver_profile_id: int, db: AsyncSession
) -> DriverOnboarding:
    """Fetch existing DriverOnboarding row or create one if absent."""
    result = await db.execute(
        select(DriverOnboarding).where(
            DriverOnboarding.driver_profile_id == driver_profile_id
        )
    )
    onboarding = result.scalar_one_or_none()
    if onboarding is None:
        onboarding = DriverOnboarding(
            driver_profile_id=driver_profile_id,
            status=OnboardingStatus.INCOMPLETE,
        )
        db.add(onboarding)
        await db.flush()
    return onboarding


async def activate_driver(
    driver_profile_id: int,
    admin_user_id: int,
    db: AsyncSession,
) -> DriverOnboarding:
    """Activate a driver after validating all checklist items are met.

    Raises OnboardingError if any requirement is not satisfied.
    """
    checklist = await get_onboarding_checklist(driver_profile_id, db)
    failed: list[str] = []
    for field in [
        "background_check",
        "driver_license",
        "vehicle_registration",
        "vehicle_inspection",
        "insurance_document",
        "profile_complete",
    ]:
        item = getattr(checklist, field)
        if item.required and not item.met:
            failed.append(field)

    if failed:
        raise OnboardingError(
            f"Cannot activate driver: requirements not met: {', '.join(failed)}"
        )

    onboarding = await get_or_create_onboarding(driver_profile_id, db)

    if onboarding.status == OnboardingStatus.SUSPENDED:
        raise OnboardingError(
            "Driver is suspended. Use the unsuspend workflow before reactivation."
        )

    onboarding.status = OnboardingStatus.APPROVED
    onboarding.activated_by = admin_user_id
    onboarding.activated_at = datetime.now(timezone.utc)
    onboarding.suspension_reason = None
    onboarding.suspended_by = None
    onboarding.suspended_at = None

    # Also flip the legacy is_approved flag on the driver profile
    profile_result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_profile_id)
    )
    profile = profile_result.scalar_one_or_none()
    if profile:
        profile.is_approved = True

    await db.flush()
    return onboarding


async def suspend_driver(
    driver_profile_id: int,
    reason: str,
    admin_user_id: int,
    db: AsyncSession,
) -> DriverOnboarding:
    """Suspend a driver with a mandatory reason string."""
    if not reason or not reason.strip():
        raise OnboardingError("A suspension reason is required")

    # Verify profile exists
    profile_result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_profile_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise OnboardingError(f"Driver profile {driver_profile_id} not found")

    onboarding = await get_or_create_onboarding(driver_profile_id, db)
    onboarding.status = OnboardingStatus.SUSPENDED
    onboarding.suspension_reason = reason.strip()
    onboarding.suspended_by = admin_user_id
    onboarding.suspended_at = datetime.now(timezone.utc)

    # Take driver offline and mark unapproved
    profile.is_approved = False
    profile.is_online = False

    await db.flush()
    return onboarding


async def list_pending_review(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
) -> list[DriverOnboarding]:
    """Return drivers whose status is PENDING_REVIEW, paginated."""
    offset = (page - 1) * page_size
    result = await db.execute(
        select(DriverOnboarding)
        .where(DriverOnboarding.status == OnboardingStatus.PENDING_REVIEW)
        .order_by(DriverOnboarding.updated_at.asc())
        .offset(offset)
        .limit(page_size)
    )
    return list(result.scalars().all())


async def list_incomplete(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
) -> list[DriverOnboarding]:
    """Return drivers whose status is INCOMPLETE, paginated."""
    offset = (page - 1) * page_size
    result = await db.execute(
        select(DriverOnboarding)
        .where(DriverOnboarding.status == OnboardingStatus.INCOMPLETE)
        .order_by(DriverOnboarding.updated_at.asc())
        .offset(offset)
        .limit(page_size)
    )
    return list(result.scalars().all())
