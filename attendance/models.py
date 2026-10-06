from django.db import models


class Employee(models.Model):

    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    employee_id = models.CharField(
        max_length=20,
        unique=True
    )

    name = models.CharField(
        max_length=100
    )

    phone = models.CharField(
        max_length=15
    )

    designation = models.CharField(
        max_length=100,
        blank=True
    )

    email = models.EmailField(
        blank=True
    )

    address = models.CharField(
        max_length=255,
        blank=True
    )

    joining_date = models.DateField()

    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="active"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"{self.employee_id} - {self.name}"


class Attendance(models.Model):

    PAYMENT_STATUS_CHOICES = [
        ("pending", "Unpaid"),
        ("paid", "Paid"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendances"
    )

    date = models.DateField()

    hours_worked = models.DecimalField(
        max_digits=5,
        decimal_places=2
    )

    payment_status = models.CharField(
        max_length=10,
        choices=PAYMENT_STATUS_CHOICES,
        default="pending"
    )

    payment_date = models.DateField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "date"],
                name="unique_employee_attendance_date"
            )
        ]

        ordering = ["-date"]

    @property
    def daily_salary(self):
        return self.hours_worked * self.employee.hourly_rate

    def __str__(self):
        return f"{self.employee.name} - {self.date}"


class SalaryPayment(models.Model):

    PAYMENT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="salary_payments"
    )

    month = models.DateField(
        help_text="Salary cycle start date"
    )

    total_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2
    )

    total_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    payment_status = models.CharField(
        max_length=10,
        choices=PAYMENT_STATUS_CHOICES,
        default="pending"
    )

    payment_date = models.DateField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "month"],
                name="unique_employee_salary_cycle"
            )
        ]

        ordering = ["-month"]

    def __str__(self):
        return f"{self.employee.name} - {self.month}"