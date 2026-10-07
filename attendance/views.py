from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from .models import (
    Attendance,
    Employee,
    SalaryPayment,
    EmployeeAdvance as Advance,
)


# =========================================================
# DATE HELPERS
# =========================================================

def add_months(d, months=1):

    index = d.month - 1 + months

    year = d.year + index // 12
    month = index % 12 + 1

    day = min(
        d.day,
        monthrange(year, month)[1]
    )

    return date(
        year,
        month,
        day
    )


# =========================================================
# SALARY CYCLE
# =========================================================

def salary_cycle(employee, ref=None):

    ref = ref or date.today()

    start_day = min(
        employee.joining_date.day,
        monthrange(ref.year, ref.month)[1]
    )

    start = date(
        ref.year,
        ref.month,
        start_day
    )

    if ref < start:

        start = add_months(
            start,
            -1
        )

    end = add_months(
        start,
        1
    )

    return start, end


def cycle_list(employee, through=None):

    through = through or date.today()

    current_start, _ = salary_cycle(
        employee,
        through
    )

    start = employee.joining_date

    cycles = []

    while start <= current_start:

        end = add_months(
            start,
            1
        )

        cycles.append(
            (
                start,
                end
            )
        )

        start = end

    return cycles


def cycle_totals(
    employee,
    start,
    end
):

    records = Attendance.objects.filter(
        employee=employee,
        date__gte=start,
        date__lt=end
    )

    hours = records.aggregate(
        total=Sum("hours_worked")
    )["total"] or Decimal("0")

    days = records.values(
        "date"
    ).distinct().count()

    salary = (
        hours
        * employee.hourly_rate
    )

    return (
        hours,
        days,
        salary
    )


# =========================================================
# ADVANCE HELPERS
# =========================================================

def get_active_advances(employee, cycle_start):
    """
    Get active advances which belong to this salary cycle.

    An advance given during a salary cycle must be
    considered for that same salary cycle.

    This function only reads advances.
    It does NOT reduce remaining_amount.
    """

    cycle_end = add_months(
        cycle_start,
        1
    )

    return Advance.objects.filter(
        employee=employee,
        status="active",
        remaining_amount__gt=Decimal("0"),
        start_month__lt=cycle_end
    ).order_by(
        "created_at",
        "id"
    )

def calculate_advance_deduction(
    employee,
    cycle_start,
    salary_amount
):

    """
    Calculate advance deduction for a salary cycle.

    IMPORTANT:
    This is a PREVIEW calculation.

    It does NOT modify Advance.remaining_amount.

    Actual reduction happens only when salary is marked PAID.
    """

    salary_amount = Decimal(
        salary_amount or "0"
    )

    if salary_amount <= 0:
        return Decimal("0")

    remaining_salary = salary_amount
    total_deduction = Decimal("0")

    advances = get_active_advances(
        employee,
        cycle_start
    )

    for advance in advances:

        if remaining_salary <= 0:
            break

        remaining_advance = Decimal(
            advance.remaining_amount or "0"
        )

        if remaining_advance <= 0:
            continue

        # -------------------------------------------------
        # FULL NEXT SALARY DEDUCTION
        # -------------------------------------------------

        if advance.deduction_type == "full":

            deduction = min(
                remaining_advance,
                remaining_salary
            )

        # -------------------------------------------------
        # MONTHLY INSTALLMENT
        # -------------------------------------------------

        elif advance.deduction_type == "installment":

            installment = Decimal(
                advance.installment_amount or "0"
            )

            if installment <= 0:
                continue

            deduction = min(
                installment,
                remaining_advance,
                remaining_salary
            )

        else:

            continue

        if deduction <= 0:
            continue

        total_deduction += deduction
        remaining_salary -= deduction

    return total_deduction


def apply_advance_deduction(
    employee,
    cycle_start,
    salary_amount
):

    """
    ACTUALLY deduct advances after salary is being paid.

    Returns:

        total_deduction
        list of deduction details
    """

    salary_amount = Decimal(
        salary_amount or "0"
    )

    if salary_amount <= 0:
        return (
            Decimal("0"),
            []
        )

    remaining_salary = salary_amount
    total_deduction = Decimal("0")

    deduction_details = []

    advances = get_active_advances(
        employee,
        cycle_start
    )

    for advance in advances:

        if remaining_salary <= 0:
            break

        remaining_advance = Decimal(
            advance.remaining_amount or "0"
        )

        if remaining_advance <= 0:
            continue

        # -------------------------------------------------
        # FULL NEXT SALARY
        # -------------------------------------------------

        if advance.deduction_type == "full":

            requested_deduction = remaining_advance

        # -------------------------------------------------
        # MONTHLY INSTALLMENT
        # -------------------------------------------------

        elif advance.deduction_type == "installment":

            requested_deduction = Decimal(
                advance.installment_amount or "0"
            )

            if requested_deduction <= 0:
                continue

        else:

            continue

        # Salary se zyada kabhi deduct nahi hoga.
        deduction = min(
            requested_deduction,
            remaining_advance,
            remaining_salary
        )

        if deduction <= 0:
            continue

        # -------------------------------------------------
        # UPDATE ADVANCE BALANCE
        # -------------------------------------------------

        advance.remaining_amount = (
            remaining_advance - deduction
        )

        if advance.remaining_amount <= 0:
            advance.remaining_amount = Decimal("0")
            advance.status = "completed"

        advance.save(
            update_fields=[
                "remaining_amount",
                "status",
                "updated_at",
            ]
        )

        total_deduction += deduction
        remaining_salary -= deduction

        deduction_details.append(
            {
                "advance": advance,
                "deduction": deduction,
                "remaining": advance.remaining_amount,
            }
        )

    return (
        total_deduction,
        deduction_details
    )


def refresh_pending_salary_advance(
    payment
):

    """
    Recalculate advance deduction for a PENDING salary.

    This only updates SalaryPayment.advance_deduction
    and SalaryPayment.net_salary.

    It does NOT reduce Advance.remaining_amount.
    """

    if payment.payment_status == "paid":
        return payment

    gross_salary = Decimal(
        payment.total_salary or "0"
    )

    advance_deduction = calculate_advance_deduction(
        payment.employee,
        payment.month,
        gross_salary
    )

    payment.advance_deduction = advance_deduction

    payment.net_salary = max(
        Decimal("0"),
        gross_salary - advance_deduction
    )

    payment.save(
        update_fields=[
            "advance_deduction",
            "net_salary",
        ]
    )

    return payment


# =========================================================
# AUTOMATIC SALARY SYNC
# =========================================================

def sync_completed_salaries():

    today = date.today()

    for employee in Employee.objects.all():

        for start, end in cycle_list(
            employee,
            today
        ):

            if today < end:
                continue

            hours, days, salary = cycle_totals(
                employee,
                start,
                end
            )

            if hours <= 0:
                continue

            payment, created = SalaryPayment.objects.get_or_create(

                employee=employee,

                month=start,

                defaults={
                    "total_hours": hours,
                    "total_salary": salary,
                    "advance_deduction": Decimal("0"),
                    "net_salary": salary,
                    "payment_status": "pending",
                }
            )

            # -------------------------------------------------
            # NEW PAYMENT
            # -------------------------------------------------

            if created:

                refresh_pending_salary_advance(
                    payment
                )

                continue

            # -------------------------------------------------
            # EXISTING UNPAID PAYMENT
            # -------------------------------------------------

            if payment.payment_status != "paid":

                payment.total_hours = hours
                payment.total_salary = salary

                payment.save(
                    update_fields=[
                        "total_hours",
                        "total_salary",
                    ]
                )

                refresh_pending_salary_advance(
                    payment
                )


# =========================================================
# DASHBOARD
# =========================================================

def dashboard(request):

    sync_completed_salaries()

    today = date.today()

    running_total = Decimal("0")

    for employee in Employee.objects.all():

        start, end = salary_cycle(
            employee,
            today
        )

        hours, days, salary = cycle_totals(
            employee,
            start,
            end
        )

        running_total += salary

    pending = SalaryPayment.objects.filter(
        payment_status="pending"
    )

    # IMPORTANT:
    # Dashboard due amount should use NET salary
    # after advance deduction.

    due_total = pending.aggregate(
        total=Sum("net_salary")
    )["total"] or Decimal("0")

    paid_total = SalaryPayment.objects.filter(
        payment_status="paid"
    ).aggregate(
        total=Sum("net_salary")
    )["total"] or Decimal("0")

    overdue_employees = pending.values(
        "employee_id"
    ).distinct().count()

    return render(
        request,
        "attendance/dashboard.html",
        {
            "total_employees": Employee.objects.count(),
            "running_total": running_total,
            "due_total": due_total,
            "paid_total": paid_total,
            "overdue_employees": overdue_employees,
            "employees": Employee.objects.all().order_by("-id"),
        }
    )


# =========================================================
# EMPLOYEE
# =========================================================

def add_employee(request):

    if request.method == "POST":

        Employee.objects.create(

            employee_id=request.POST["employee_id"],

            name=request.POST["name"],

            phone=request.POST["phone"],

            designation=request.POST.get(
                "designation",
                ""
            ),

            email=request.POST.get(
                "email",
                ""
            ),

            address=request.POST.get(
                "address",
                ""
            ),

            joining_date=request.POST["joining_date"],

            hourly_rate=request.POST["hourly_rate"],

            status=request.POST["status"],
        )

        messages.success(
            request,
            "Employee added successfully."
        )

        return redirect("dashboard")

    return render(
        request,
        "attendance/add_employee.html"
    )


def edit_employee(request, employee_id):

    employee = get_object_or_404(
        Employee,
        id=employee_id
    )

    if request.method == "POST":

        employee.employee_id = request.POST[
            "employee_id"
        ]

        employee.name = request.POST[
            "name"
        ]

        employee.phone = request.POST[
            "phone"
        ]

        employee.designation = request.POST.get(
            "designation",
            ""
        )

        employee.email = request.POST.get(
            "email",
            ""
        )

        employee.address = request.POST.get(
            "address",
            ""
        )

        employee.joining_date = request.POST[
            "joining_date"
        ]

        employee.hourly_rate = request.POST[
            "hourly_rate"
        ]

        employee.status = request.POST[
            "status"
        ]

        employee.save()

        messages.success(
            request,
            "Employee updated successfully."
        )

        return redirect("dashboard")

    return render(
        request,
        "attendance/edit_employee.html",
        {
            "employee": employee
        }
    )


def delete_employee(request, employee_id):

    employee = get_object_or_404(
        Employee,
        id=employee_id
    )

    if request.method == "POST":

        employee.delete()

        messages.success(
            request,
            "Employee deleted successfully."
        )

    return redirect("dashboard")


# =========================================================
# ATTENDANCE
# =========================================================

def attendance_page(request):

    today = date.today()

    raw = request.GET.get(
        "date",
        today.isoformat()
    )

    try:

        selected = date.fromisoformat(
            raw
        )

    except (ValueError, TypeError):

        selected = today

    if selected > today:

        selected = today

    records = Attendance.objects.filter(
        date=selected
    ).select_related(
        "employee"
    )

    record_map = {
        r.employee_id: r
        for r in records
    }

    rows = []

    employees = Employee.objects.filter(
        status="active"
    ).order_by(
        "name"
    )

    for employee in employees:

        rows.append(
            {
                "employee": employee,
                "record": record_map.get(
                    employee.id
                ),
            }
        )

    return render(
        request,
        "attendance/attendance.html",
        {
            "rows": rows,
            "selected_date": selected.isoformat(),
            "today": today.isoformat(),
        }
    )


def save_attendance(request):

    if request.method != "POST":

        return redirect(
            "attendance"
        )

    raw_date = request.GET.get(
        "date"
    )

    if not raw_date:

        raw_date = request.POST.get(
            "date"
        )

    try:

        work_date = date.fromisoformat(
            raw_date
        )

    except (ValueError, TypeError):

        messages.error(
            request,
            "Invalid attendance date."
        )

        return redirect(
            "attendance"
        )

    today = date.today()

    if work_date > today:

        messages.error(
            request,
            "Future date attendance is not allowed."
        )

        return redirect(
            f"/attendance/?date={today.isoformat()}"
        )

    employees = Employee.objects.filter(
        status="active"
    )

    for employee in employees:

        if work_date < employee.joining_date:
            continue

        raw_hours = request.POST.get(
            f"hours_{employee.id}",
            ""
        ).strip()

        if raw_hours == "":
            continue

        try:

            hours = Decimal(
                raw_hours
            )

        except Exception:

            continue

        if hours < 0 or hours > 24:
            continue

        Attendance.objects.update_or_create(

            employee=employee,

            date=work_date,

            defaults={
                "hours_worked": hours
            }
        )

    sync_completed_salaries()

    messages.success(
        request,
        f"Attendance saved for {work_date.strftime('%d %b %Y')}."
    )

    return redirect(
        f"/attendance/?date={work_date.isoformat()}"
    )


def attendance_history(request):

    records = Attendance.objects.select_related(
        "employee"
    ).order_by(
        "-date",
        "employee__name"
    )

    return render(
        request,
        "attendance/attendance_history.html",
        {
            "records": records
        }
    )


# =========================================================
# SALARY PAGE
# =========================================================

def salary_page(request):

    sync_completed_salaries()

    today = date.today()

    rows = []

    for employee in Employee.objects.all().order_by("name"):

        # Current salary cycle
        start, end = salary_cycle(
            employee,
            today
        )

        hours, days, salary = cycle_totals(
            employee,
            start,
            end
        )

        payment = SalaryPayment.objects.filter(
            employee=employee,
            month=start
        ).first()

        # =================================================
        # ADVANCE CALCULATION
        # =================================================

        advance_deduction = Decimal("0")
        net_salary = salary

        if payment:

            if payment.payment_status == "paid":

                advance_deduction = (
                    payment.advance_deduction
                    or Decimal("0")
                )

                net_salary = (
                    payment.net_salary
                    or max(
                        Decimal("0"),
                        salary - advance_deduction
                    )
                )

            else:

                payment = refresh_pending_salary_advance(
                    payment
                )

                advance_deduction = (
                    payment.advance_deduction
                    or Decimal("0")
                )

                net_salary = (
                    payment.net_salary
                    or max(
                        Decimal("0"),
                        salary - advance_deduction
                    )
                )

        else:

            # Current running cycle may not have
            # SalaryPayment yet.
            advance_deduction = calculate_advance_deduction(
                employee,
                start,
                salary
            )

            net_salary = max(
                Decimal("0"),
                salary - advance_deduction
            )

        # =================================================
        # STATUS LOGIC
        # =================================================

        # Check whether ANY previous completed salary
        # cycle is still unpaid
        previous_unpaid = SalaryPayment.objects.filter(
            employee=employee,
            month__lt=start,
            payment_status="pending",
            total_salary__gt=0
        ).exists()

        if previous_unpaid:

            # Previous salary is unpaid
            status = "overdue"

        elif today < end:

            # Current salary cycle is still running
            status = "running"

        elif salary > 0:

            status = "overdue"

        else:

            status = "running"

        rows.append(
            {
                "employee": employee,
                "cycle_start": start,
                "cycle_end": end,
                "hours": hours,
                "days": days,

                # Existing field
                "salary": salary,

                # New advance fields
                "advance_deduction": advance_deduction,
                "net_salary": net_salary,

                "status": status,
                "payment": payment,
            }
        )

    return render(
        request,
        "attendance/salary.html",
        {
            "rows": rows
        }
    )


# =========================================================
# MARK COMPLETE SALARY CYCLE AS PAID
# =========================================================

def mark_salary_paid(
    request,
    payment_id
):

    payment = get_object_or_404(
        SalaryPayment,
        id=payment_id
    )

    if request.method == "POST":

        # -------------------------------------------------
        # ALREADY PAID
        # -------------------------------------------------

        if payment.payment_status == "paid":

            messages.info(
                request,
                "This salary has already been paid."
            )

            return redirect(
                f"/salary/history/{payment.employee.id}/"
            )

        employee = payment.employee

        cycle_start = payment.month

        cycle_end = add_months(
            cycle_start,
            1
        )

        # -------------------------------------------------
        # RECALCULATE CURRENT GROSS SALARY
        # -------------------------------------------------

        hours, days, salary = cycle_totals(
            employee,
            cycle_start,
            cycle_end
        )

        if salary <= 0:

            messages.error(
                request,
                "This salary cycle has no payable salary."
            )

            return redirect(
                f"/salary/history/{employee.id}/"
            )

        # -------------------------------------------------
        # ACTUAL ADVANCE DEDUCTION
        #
        # This is the ONLY place where
        # Advance.remaining_amount is reduced.
        # -------------------------------------------------

        with transaction.atomic():

            (
                advance_deduction,
                deduction_details
            ) = apply_advance_deduction(
                employee,
                cycle_start,
                salary
            )

            net_salary = max(
                Decimal("0"),
                salary - advance_deduction
            )

            # -------------------------------------------------
            # UPDATE SALARY PAYMENT
            # -------------------------------------------------

            payment.total_hours = hours

            payment.total_salary = salary

            payment.advance_deduction = (
                advance_deduction
            )

            payment.net_salary = (
                net_salary
            )

            payment.payment_status = "paid"

            payment.payment_date = date.today()

            payment.save(
                update_fields=[
                    "total_hours",
                    "total_salary",
                    "advance_deduction",
                    "net_salary",
                    "payment_status",
                    "payment_date",
                ]
            )

            # -------------------------------------------------
            # MARK ALL ATTENDANCE DAYS OF THIS CYCLE PAID
            # -------------------------------------------------

            Attendance.objects.filter(
                employee=employee,
                date__gte=cycle_start,
                date__lt=cycle_end
            ).update(
                payment_status="paid",
                payment_date=date.today()
            )

        # -------------------------------------------------
        # SUCCESS MESSAGE
        # -------------------------------------------------

        if advance_deduction > 0:

            messages.success(
                request,
                (
                    f"Salary paid successfully for {employee.name}. "
                    f"Gross: ₹{salary:.2f}, "
                    f"Advance deducted: ₹{advance_deduction:.2f}, "
                    f"Net paid: ₹{net_salary:.2f}."
                )
            )

        else:

            messages.success(
                request,
                (
                    f"Complete salary of ₹{net_salary:.2f} "
                    f"for {employee.name} has been paid."
                )
            )

    return redirect(
        f"/salary/history/{payment.employee.id}/"
    )


# =========================================================
# SALARY HISTORY
# =========================================================

def salary_history(request):

    sync_completed_salaries()

    employees = Employee.objects.all().order_by(
        "name"
    )

    return render(
        request,
        "attendance/salary_history.html",
        {
            "employees": employees
        }
    )


def employee_salary_history(
    request,
    employee_id
):

    sync_completed_salaries()

    employee = get_object_or_404(
        Employee,
        id=employee_id
    )

    today = date.today()

    history = []

    for start, end in reversed(
        cycle_list(
            employee,
            today
        )
    ):

        hours, days, salary = cycle_totals(
            employee,
            start,
            end
        )

        payment = SalaryPayment.objects.filter(
            employee=employee,
            month=start
        ).first()

        # =================================================
        # ADVANCE INFORMATION
        # =================================================

        advance_deduction = Decimal("0")
        net_salary = salary

        if payment:

            if payment.payment_status == "paid":

                advance_deduction = (
                    payment.advance_deduction
                    or Decimal("0")
                )

                net_salary = (
                    payment.net_salary
                    or max(
                        Decimal("0"),
                        salary - advance_deduction
                    )
                )

            else:

                payment = refresh_pending_salary_advance(
                    payment
                )

                advance_deduction = (
                    payment.advance_deduction
                    or Decimal("0")
                )

                net_salary = (
                    payment.net_salary
                    or max(
                        Decimal("0"),
                        salary - advance_deduction
                    )
                )

        else:

            if today >= end:

                advance_deduction = calculate_advance_deduction(
                    employee,
                    start,
                    salary
                )

            else:

                advance_deduction = calculate_advance_deduction(
                    employee,
                    start,
                    salary
                )

            net_salary = max(
                Decimal("0"),
                salary - advance_deduction
            )

        # =================================================
        # STATUS
        # =================================================

        if today < end:

            status = "running"

        elif payment and payment.payment_status == "paid":

            status = "paid"

        elif salary > 0:

            status = "overdue"

        else:

            status = "no_attendance"

        # =================================================
        # DAILY DETAILS
        # =================================================

        daily_details = []

        last_day = min(
            end,
            today + timedelta(days=1)
        )

        current_day = start

        attendance_map = {
            record.date: record
            for record in Attendance.objects.filter(
                employee=employee,
                date__gte=start,
                date__lt=end
            )
        }

        while current_day < last_day:

            record = attendance_map.get(
                current_day
            )

            if record:

                daily_details.append(
                    {
                        "date": current_day,
                        "worked": True,
                        "hours": record.hours_worked,
                        "salary": record.daily_salary,
                    }
                )

            else:

                daily_details.append(
                    {
                        "date": current_day,
                        "worked": False,
                        "hours": Decimal("0"),
                        "salary": Decimal("0"),
                    }
                )

            current_day += timedelta(
                days=1
            )

        history.append(
            {
                "start": start,
                "end": end,
                "hours": hours,
                "days": days,

                # Existing salary
                "salary": salary,

                # New advance fields
                "advance_deduction": advance_deduction,
                "net_salary": net_salary,

                "status": status,
                "payment": payment,
                "daily_details": daily_details,
            }
        )

    return render(
        request,
        "attendance/employee_salary_history.html",
        {
            "employee": employee,
            "history": history,
        }
    )


# =========================================================
# EMPLOYEE ADVANCE
# =========================================================

def employee_advance(request):

    employees = Employee.objects.filter(
        status="active"
    ).order_by(
        "name"
    )

    advances = Advance.objects.select_related(
        "employee"
    ).order_by(
        "-created_at"
    )

    if request.method == "POST":

        employee_id = request.POST.get(
            "employee"
        )

        amount_raw = request.POST.get(
            "advance_amount"
        )

        deduction_type = request.POST.get(
            "deduction_type"
        )

        installment_raw = request.POST.get(
            "installment_amount"
        )

        start_month_raw = request.POST.get(
            "start_month"
        )

        notes = request.POST.get(
            "notes",
            ""
        ).strip()

        # -------------------------------------------------
        # EMPLOYEE
        # -------------------------------------------------

        employee = get_object_or_404(
            Employee,
            id=employee_id
        )

        # -------------------------------------------------
        # ADVANCE AMOUNT
        # -------------------------------------------------

        try:

            amount = Decimal(
                amount_raw
            )

        except (
            InvalidOperation,
            TypeError,
            ValueError
        ):

            messages.error(
                request,
                "Please enter a valid advance amount."
            )

            return redirect(
                "employee_advance"
            )

        if amount <= 0:

            messages.error(
                request,
                "Advance amount must be greater than zero."
            )

            return redirect(
                "employee_advance"
            )

        # -------------------------------------------------
        # DEDUCTION TYPE
        # -------------------------------------------------

        if deduction_type not in [
            "full",
            "installment"
        ]:

            messages.error(
                request,
                "Please select a valid deduction method."
            )

            return redirect(
                "employee_advance"
            )

        # -------------------------------------------------
        # INSTALLMENT
        # -------------------------------------------------

        installment_amount = None

        if deduction_type == "installment":

            try:

                installment_amount = Decimal(
                    installment_raw
                )

            except (
                InvalidOperation,
                TypeError,
                ValueError
            ):

                messages.error(
                    request,
                    "Please enter a valid monthly installment."
                )

                return redirect(
                    "employee_advance"
                )

            if installment_amount <= 0:

                messages.error(
                    request,
                    "Monthly installment must be greater than zero."
                )

                return redirect(
                    "employee_advance"
                )

            if installment_amount > amount:

                messages.error(
                    request,
                    "Monthly installment cannot be greater than the advance amount."
                )

                return redirect(
                    "employee_advance"
                )

        # -------------------------------------------------
        # START MONTH
        # -------------------------------------------------

        try:

            start_month = date.fromisoformat(
                start_month_raw
            )

        except (
            ValueError,
            TypeError
        ):

            messages.error(
                request,
                "Please select a valid deduction start date."
            )

            return redirect(
                "employee_advance"
            )

        # -------------------------------------------------
        # CREATE ADVANCE
        # -------------------------------------------------

        Advance.objects.create(

            employee=employee,

            advance_amount=amount,

            remaining_amount=amount,

            deduction_type=deduction_type,

            installment_amount=installment_amount,

            start_month=start_month,

            status="active",

            notes=notes,
        )

        messages.success(
            request,
            (
                f"₹{amount:.2f} advance added successfully "
                f"for {employee.name}."
            )
        )

        return redirect(
            "employee_advance"
        )

    return render(
        request,
        "attendance/advance.html",
        {
            "employees": employees,
            "advances": advances,
            "today": date.today(),
        }
    )


# =========================================================
# CANCEL ADVANCE
# =========================================================

def cancel_advance(
    request,
    advance_id
):

    advance = get_object_or_404(
        Advance,
        id=advance_id
    )

    if request.method == "POST":

        if advance.status == "active":

            advance.status = "cancelled"

            advance.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            messages.success(
                request,
                (
                    f"Advance for {advance.employee.name} "
                    f"has been cancelled successfully."
                )
            )

        else:

            messages.info(
                request,
                "This advance is no longer active."
            )

    return redirect(
        "employee_advance"
    )