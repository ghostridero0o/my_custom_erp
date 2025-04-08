import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def after_install():
    create_custom_fields(get_custom_fields(), ignore_validate=True)

def check_project_field_exists_anywhere():
    meta = frappe.get_meta("Employee Attendance Tool")
    if "project" in [f.fieldname for f in meta.fields]:
        frappe.msgprint("✅ Trường 'project' đã tồn tại trong DocType 'Employee Attendance Tool'.")
    else:
        frappe.msgprint("❌ Trường 'project' chưa tồn tại trong DocType 'Employee Attendance Tool'.")
def after_migrate():
    create_custom_fields(get_custom_fields(), ignore_validate=True)
    check_project_field_exists_anywhere()    

def get_custom_fields():
    return {
        "Employee Attendance Tool": [
            {
                "fieldname": "project",
                "label": "Project",
                "fieldtype": "Link",
                "options": "Project",
                "insert_after": "shift",  # thêm sau trường 'shift'
                "reqd": 0,
                "in_list_view": 0
            }
        ]
    }
