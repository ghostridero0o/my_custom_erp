import frappe
from frappe.utils import get_datetime, nowdate
import datetime

def update_last_sync_of_checkin():
    try:
        # L?y t?t c? c�c b?n ghi trong doctype Shift Type
        shift_types = frappe.get_all('Shift Type', fields=['name'])

        # L?y ng�y hi?n t?i v� chuy?n th�nh datetime, sau d� d?t gi? th�nh 23:00:00
        current_time = get_datetime(nowdate()).replace(hour=23, minute=0, second=0, microsecond=0)

        # C?p nh?t tru?ng 'last_sync_of_checkin' cho t?t c? c�c b?n ghi
        for shift in shift_types:
            frappe.db.set_value('Shift Type', shift['name'], 'last_sync_of_checkin', current_time)

        # Commit c�c thay d?i
        frappe.db.commit()

    except Exception as e:
        # N?u c� l?i x?y ra, ghi l?i l?i v�o log
        frappe.log_error(f"Error in update_last_sync_of_checkin: {str(e)}", "Scheduled Job Error")
