import frappe
import json
from frappe import _

@frappe.whitelist(allow_guest=True)
def receive_pabbly_webhook():
    try:
        # L?y d? li?u t? webhook g?i l�n
        data = frappe.request.get_data(as_text=True)  # Chuy?n d?i th�nh chu?i
        
        # Ph�n t�ch d? li?u JSON
        data = json.loads(data)

        # L?y t�n s? ki?n t? d? li?u
        event_name = data.get("event_name")

        if event_name == "user_submit_info":
            # L?y c�c tru?ng th�ng tin t? d? li?u c?a Zalo
            sender = str(data.get("sender", {}).get("id", "")).strip()  # Chuy?n d?i th�nh chu?i
            lead_name = str(data.get("info", {}).get("name", "")).strip()  # Chuy?n d?i th�nh chu?i
            phone = str(data.get("info", {}).get("phone", "")).strip()  # Chuy?n d?i th�nh chu?i
            address = str(data.get("info", {}).get("address", "")).strip()  # Chuy?n d?i th�nh chu?i
            district = str(data.get("info", {}).get("district", "")).strip()  # Chuy?n d?i th�nh chu?i
            city = str(data.get("info", {}).get("city", "")).strip()  # Chuy?n d?i th�nh chu?i

            # Ki?m tra xem th�ng tin c� d?y d? hay kh�ng
            if not lead_name or not phone:
                return {"status": "error", "message": "Missing lead information"}

            # Ki?m tra xem lead_name d� t?n t?i hay chua
            existing_lead = frappe.db.exists("CRM Lead", {"custom_user_id": sender})
            if existing_lead:
                return {
                    "status": "success",
                    "message": "Lead already exists, no new entry created."
                }

            # T?o m?t b?n ghi Lead m?i trong ERPNext
            lead = frappe.get_doc({
                "doctype": "CRM Lead",
                "custom_user_id": sender,
                "first_name": lead_name,
                "mobile_no": phone,
                "custom_city": city,
                "custom_district": district,
                "custom_address": address,
                "status": "New",
                "source": "Zalo OA"
            })
            lead.insert(ignore_permissions=True)
            frappe.db.commit()

            return {"status": "success", "message": "CRM Lead created successfully"}

        elif event_name == "user_send_text":
            # X? l� s? ki?n user_send_text
            user_id = str(data.get("sender", {}).get("id", "")).strip()  # Chuy?n d?i th�nh chu?i

            # Ki?m tra xem user_id d� t?n t?i hay chua
            existing_user_lead = frappe.db.exists("CRM Lead", {"first_name": user_id})
            if existing_user_lead:
                return {
                    "status": "success",
                    "message": "User Lead already exists, no new entry created."
                }

            lead = frappe.get_doc({
                "doctype": "CRM Lead",
                "first_name": user_id,                
                "status": "Junk",
                "source": "Zalo OA"
            })
            lead.insert(ignore_permissions=True)
            frappe.db.commit()

            

            # Th?c hi?n h�nh d?ng c?n thi?t v?i tin nh?n
            # V� d?: ghi nh?n v�o log ho?c x? l� theo c�ch n�o d�
            frappe.log_error(f"Received message from user: {user_id}", "Zalo OA User Message")

            return {"status": "success", "message": "User message processed successfully"}

        else:
            return {"status": "error", "message": "Unknown event type"}
    except json.JSONDecodeError:
        # L?i JSON kh�ng h?p l?
        frappe.log_error("Invalid JSON format", "Zalo Webhook Error")
        return {"status": "error", "message": "Invalid JSON format"}

    except Exception as e:
        # Ghi l?i kh�c
        frappe.log_error(f"Error in zalo Webhook: {e}", "zalo Webhook Error")
        return {"status": "error", "message": str(e)}

