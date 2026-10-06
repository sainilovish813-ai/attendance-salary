from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Employee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("employee_id", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("phone", models.CharField(max_length=15)),
                ("designation", models.CharField(blank=True, max_length=100)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("address", models.CharField(blank=True, max_length=255)),
                ("joining_date", models.DateField()),
                ("hourly_rate", models.DecimalField(decimal_places=2, max_digits=10)),
                ("status", models.CharField(choices=[("active", "Active"), ("inactive", "Inactive")], default="active", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="Attendance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("hours_worked", models.DecimalField(decimal_places=2, max_digits=5)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attendances", to="attendance.employee")),
            ],
            options={"ordering": ["-date"], "constraints": [models.UniqueConstraint(fields=("employee", "date"), name="unique_employee_attendance_date")]},
        ),
        migrations.CreateModel(
            name="SalaryPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("month", models.DateField(help_text="Salary cycle start date")),
                ("total_hours", models.DecimalField(decimal_places=2, max_digits=8)),
                ("total_salary", models.DecimalField(decimal_places=2, max_digits=12)),
                ("payment_status", models.CharField(choices=[("pending", "Pending"), ("paid", "Paid")], default="pending", max_length=10)),
                ("payment_date", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="salary_payments", to="attendance.employee")),
            ],
            options={"ordering": ["-month"], "constraints": [models.UniqueConstraint(fields=("employee", "month"), name="unique_employee_salary_cycle")]},
        ),
    ]
