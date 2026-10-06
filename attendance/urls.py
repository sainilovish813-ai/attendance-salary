from django.urls import path

from . import views


urlpatterns = [

    path(
        "",
        views.dashboard,
        name="dashboard"
    ),

    path(
        "add-employee/",
        views.add_employee,
        name="add_employee"
    ),

    path(
        "employee/<int:employee_id>/edit/",
        views.edit_employee,
        name="edit_employee"
    ),

    path(
        "employee/<int:employee_id>/delete/",
        views.delete_employee,
        name="delete_employee"
    ),

    path(
        "attendance/",
        views.attendance_page,
        name="attendance"
    ),

    path(
        "attendance/save/",
        views.save_attendance,
        name="save_attendance"
    ),

    path(
        "attendance/history/",
        views.attendance_history,
        name="attendance_history"
    ),

    path(
        "salary/",
        views.salary_page,
        name="salary"
    ),

    path(
        "salary/<int:payment_id>/paid/",
        views.mark_salary_paid,
        name="mark_salary_paid"
    ),

    path(
        "salary/history/",
        views.salary_history,
        name="salary_history"
    ),

    path(
        "salary/history/<int:employee_id>/",
        views.employee_salary_history,
        name="employee_salary_history"
    ),
]