from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from .models import Attendance, Employee, SalaryPayment


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

    return date(year, month, day)


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
        start = add_months(start, -1)

    end = add_months(start, 1)

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
                    "payment_status": "pending",
                }
            )

            if not created:

                if payment.payment_status != "paid":

                    payment.total_hours = hours
                    payment.total_salary = salary

                    payment.save(
                        update_fields=[
                            "total_hours",
                            "total_salary",
                        ]
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

    due_total = pending.aggregate(
        total=Sum("total_salary")
    )["total"] or Decimal("0")

    paid_total = SalaryPayment.objects.filter(
        payment_status="paid"
    ).aggregate(
        total=Sum("total_salary")
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

        selected = date.fromisoformat(raw)

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
            # No previous unpaid salary
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
                "salary": salary,
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

        employee = payment.employee

        cycle_start = payment.month

        cycle_end = add_months(
            cycle_start,
            1
        )

        # ---------------------------------------------
        # MARK ALL ATTENDANCE DAYS OF THIS CYCLE PAID
        # ---------------------------------------------

        Attendance.objects.filter(
            employee=employee,
            date__gte=cycle_start,
            date__lt=cycle_end
        ).update(
            payment_status="paid",
            payment_date=date.today()
        )

        # ---------------------------------------------
        # MARK COMPLETE SALARY CYCLE PAID
        # ---------------------------------------------

        payment.payment_status = "paid"

        payment.payment_date = date.today()

        payment.save(
            update_fields=[
                "payment_status",
                "payment_date",
            ]
        )

        messages.success(
            request,
            f"Complete salary of ₹{payment.total_salary:.2f} "
            f"for {employee.name} has been paid."
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

        if today < end:

            status = "running"

        elif payment and payment.payment_status == "paid":

            status = "paid"

        elif salary > 0:

            status = "overdue"

        else:

            status = "no_attendance"

        # ---------------------------------------------
        # DAILY DETAILS
        # ---------------------------------------------

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
                "salary": salary,
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