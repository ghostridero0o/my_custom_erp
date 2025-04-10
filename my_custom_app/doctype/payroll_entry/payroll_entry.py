from frappe import msgprint
import erpnext
import frappe
import json
from frappe import _
from frappe.utils import cstr
from frappe.model.document import Document
from frappe.utils import get_datetime
from hrms.payroll.doctype.payroll_entry.payroll_entry import PayrollEntry, submit_salary_slips_for_employees
from hrms.payroll.doctype.payroll_entry.payroll_entry import get_existing_salary_slips, show_payroll_submission_status
from frappe.utils import get_link_to_form
from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip, make_loan_repayment_entry
from hrms.payroll.doctype.payroll_entry.payroll_entry import get_salary_withholdings, get_start_end_dates
from frappe.utils import flt
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)


class CustomPayrollEntry(PayrollEntry):
	def get_salary_components(self, component_type):
		salary_slips = self.get_sal_slip_list(ss_status=1, as_dict=True)

		if not salary_slips:
			return []

		ss = frappe.qb.DocType("Salary Slip")
		ssd = frappe.qb.DocType("Salary Detail")

		# Nếu là deduction thì không cần join project, không tính amount_against_project
		if component_type == "deductions":
			salary_components = (
				frappe.qb.from_(ss)
				.join(ssd)
				.on(ss.name == ssd.parent)
				.select(
					ssd.salary_component,
					ssd.amount,
					ssd.parentfield,
					ssd.additional_salary,
					ss.salary_structure,
					ss.employee,
				)
				.where((ssd.parentfield == component_type) & (ss.name.isin([d.name for d in salary_slips])))
			).run(as_dict=True)

			return salary_components

		# Ngược lại thì tính amount_against_project như cũ
		sep = frappe.qb.DocType("Employee Project")
		draft_salary_components = (
			frappe.qb.from_(ss)
			.join(ssd).on(ss.name == ssd.parent)
			.join(sep).on(ss.name == sep.parent)
			.select(
				ssd.salary_component,
				ssd.amount,
				ssd.parentfield,
				ssd.additional_salary,
				ss.salary_structure,
				ss.employee,
				sep.project,
				sep.percentage
			)
			.where((ssd.parentfield == component_type) & (ss.name.isin([d.name for d in salary_slips])))
		).run(as_dict=True)

		salary_components = []
		for row in draft_salary_components:
			amount_against_project = 0
			if row.get('amount', 0) != 0:
				amount_against_project = row.get('amount', 0) * row.get('percentage', 0) / 100

			if amount_against_project != 0:
				salary_components.append({
					"salary_component": row.get('salary_component', ''),
					"amount": amount_against_project,
					"parentfield": row.get('parentfield', ''),
					"additional_salary": row.get('additional_salary', None),
					"salary_structure": row.get('salary_structure', ''),
					"employee": row.get('employee', ''),
					"project": row.get('project', '')
				})

		return salary_components




	def get_salary_component_total(
		self,
		component_type=None,
		employee_wise_accounting_enabled=False,
	):
		salary_components = self.get_salary_components(component_type)
		if salary_components:
			component_dict = {}

			for item in salary_components:
				if not self.should_add_component_to_accrual_jv(component_type, item):
					continue

				employee_cost_centers = self.get_payroll_cost_centers_for_employee(
					item['employee'], item['salary_structure']
				)
				employee_advance = self.get_advance_deduction(component_type, item)

				for cost_center, percentage in employee_cost_centers.items():
					amount_against_cost_center = flt(item['amount']) * percentage / 100

					if employee_advance:
						self.add_advance_deduction_entry(
							item, amount_against_cost_center, cost_center, employee_advance
						)
					else:
						key = (item['salary_component'], cost_center,item.get('project'))
						component_dict[key] = component_dict.get(key, 0) + amount_against_cost_center

					if employee_wise_accounting_enabled:
						self.set_employee_based_payroll_payable_entries(
							component_type, item.employee, amount_against_cost_center
						)

			account_details = self.get_account(component_dict=component_dict)
			

			return account_details
			
	def get_account(self, component_dict=None):
		account_dict = {}
		for key, amount in component_dict.items():
			component, cost_center, project = key
			account = self.get_salary_component_account(component)
			accounting_key = (account, cost_center, project)

			account_dict[accounting_key] = account_dict.get(accounting_key, 0) + amount

		return account_dict



	

	def get_accounting_entries_and_payable_amount(
		self,
		account,
		cost_center,
		amount,
		currencies,
		company_currency,
		payable_amount,
		project,
		precision,  # Set a default value for precision
		entry_type="credit",
		party=None,
		accounts=None,
		reference_type=None,
		reference_name=None,
		is_advance=None,		
	):
		exchange_rate, amt = self.get_amount_and_exchange_rate_for_journal_entry(
			account, amount, company_currency, currencies
		)

		row = {
			"account": account,
			"exchange_rate": flt(exchange_rate),
			"cost_center": cost_center,
		}

		# Kiểm tra nếu project không phải là một danh sách
		if not isinstance(project, list):
			# Gán project vào row chỉ khi project không phải là danh sách
			row["project"] = project  # Gán project vào row nếu không phải là danh sách
		
		if entry_type == "debit":
			payable_amount += flt(amount, precision)
			row.update(
				{
					"debit_in_account_currency": flt(amt, precision),
				}
			)
		elif entry_type == "credit":
			payable_amount -= flt(amount, precision)
			row.update(
				{
					"credit_in_account_currency": flt(amt, precision),
				}
			)
		else:
			row.update(
				{
					"credit_in_account_currency": flt(amt, precision),
					"reference_type": self.doctype,
					"reference_name": self.name,
				}
			)

		if party:
			row.update(
				{
					"party_type": "Employee",
					"party": party,
				}
			)

		if reference_type:
			row.update(
				{
					"reference_type": reference_type,
					"reference_name": reference_name,
					"is_advance": is_advance,
				}
			)

		

		if amt:
			accounts.append(row)

		return payable_amount

	def get_payable_amount_for_earnings_and_deductions(
		self,
		accounts,
		earnings,
		deductions,
		currencies,
		company_currency,
		accounting_dimensions,
		precision,
		payable_amount,
	):
		# Earnings
		for acc_cc, amount in earnings.items():
			account, cost_center, project = acc_cc  # Unpack 3 phần tử
			payable_amount = self.get_accounting_entries_and_payable_amount(
				account,
				cost_center or self.cost_center,
				amount=amount,
				currencies=currencies,
				company_currency=company_currency,
				payable_amount=payable_amount,
				project=project,
				precision=precision,
				entry_type="debit",
				accounts=accounts,
			)

		# Deductions
		for acc_cc, amount in deductions.items():
			account, cost_center, project = acc_cc  # Unpack 3 phần tử
			payable_amount = self.get_accounting_entries_and_payable_amount(
				account,
				cost_center or self.cost_center,
				amount=amount,
				currencies=currencies,
				company_currency=company_currency,
				payable_amount=payable_amount,
				project=project,
				precision=precision,
				entry_type="credit",
				accounts=accounts,
			)

		return payable_amount
	

	








class CustomSalarySlip(SalarySlip):
	def get_status(self):
		
		self.create_custom_employee_project_entries()
		if self.docstatus == 2:
			return "Cancelled"
		else:
			if self.salary_withholding:
				return "Withheld"
			elif self.docstatus == 0:
				return "Draft"
			elif self.docstatus == 1:
				return "Submitted"

	def create_custom_employee_project_entries(self):
		"""Lấy dữ liệu từ Attendance và thêm vào bảng custom_employee_project"""
		
		employee = self.employee

		# Lọc bản ghi Attendance theo các tiêu chí
		attendance_records = frappe.get_all(
			'Attendance', 
			filters={ 
				'employee': employee, 
				'attendance_date': ('between', [self.start_date, self.end_date]), 
				'docstatus': 1,  # Đảm bảo chỉ lấy các bản ghi đã được duyệt
				'status': ('not in', ['Absent', 'On Leave'])  # Điều kiện lọc status không phải "Absent" và "On Leave"
			},
			fields=['custom_project', 'attendance_date']
		)

		# Nếu không có attendance_records, thêm một dòng vào bảng với project rỗng và tỷ lệ là 100%
		if not attendance_records:
			self.set('custom_employee_project', [])
			self.append('custom_employee_project', {
				'project': "",  # Project trống
				'percentage': 100  # Tỷ lệ 100% cho dòng trống
			})
			return

		# Tính toán tổng số bản ghi Attendance hợp lệ
		total_attendance = len(attendance_records)

		# Tính số lượng bản ghi Attendance cho mỗi project, bao gồm cả trường hợp project null hoặc trống
		project_counts = {}
		for record in attendance_records:
			project = record.custom_project if record.custom_project else "No Project"
			project_counts[project] = project_counts.get(project, 0) + 1

		# Nếu không có project_counts, thêm dòng có project trống và tỷ lệ = 100%
		if not project_counts:
			self.set('custom_employee_project', [])
			self.append('custom_employee_project', {
				'project': "",  # Project trống
				'percentage': 100  # Tỷ lệ 100% cho dòng trống
			})
			return

		# Tính toán tỷ lệ phần trăm cho mỗi project
		total_percentage = 0
		percentages = {}
		for project, count in project_counts.items():
			if project != "No Project":  # Chỉ tính tỷ lệ cho các project không trống
				percentage = (count / total_attendance) * 100  # Tính tỷ lệ phần trăm cho project
				percentages[project] = int(percentage)  # Lấy phần nguyên của tỷ lệ phần trăm
				total_percentage += int(percentage)

		# Tính toán giá trị của dòng project trống (đảm bảo tổng tỷ lệ phần trăm = 100)
		remaining_percentage = 100 - total_percentage

		# Xóa các dòng cũ trong bảng custom_employee_project
		self.set('custom_employee_project', [])

		# Lặp qua các project và thêm vào child table custom_employee_project
		for project, percentage in percentages.items():
			# Thêm dữ liệu vào child table custom_employee_project
			self.append('custom_employee_project', {
				'project': project,  # Dự án không trống
				'percentage': percentage  # Tỷ lệ phần trăm là phần nguyên
			})

		# Thêm dòng cho project trống với phần trăm còn lại
		self.append('custom_employee_project', {
			'project': "",  # Project trống
			'percentage': remaining_percentage  # Tỷ lệ phần trăm còn lại
		})

