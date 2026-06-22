from django.urls import path
from . import views

urlpatterns = [
    path("tally/masters/", views.master_list, name="tally_master_list"),
    path("tally/masters/create/", views.create_master, name="tally_create_master"),
    path("tally/masters/<int:l_id>/edit/", views.edit_master, name="tally_edit_master"),
    path("tally/masters/<int:l_id>/delete/", views.delete_master, name="tally_delete_master"),

    path("tally/payment/", views.payment_voucher, name="tally_payment_voucher"),
    path("tally/receipt/", views.receipt_voucher, name="tally_receipt_voucher"),
    path("tally/journal/", views.journal_entry, name="tally_journal_entry"),

    path("tally/vouchers/", views.voucher_list, name="tally_voucher_list"),
    path("tally/vouchers/<int:v_id>/", views.voucher_detail, name="tally_voucher_detail"),
    path("tally/vouchers/<int:v_id>/delete/", views.delete_voucher, name="tally_delete_voucher"),

    path("tally/account-statement/", views.account_statement, name="tally_account_statement"),
    path("tally/unified-ledger/", views.unified_ledger, name="tally_unified_ledger"),
]
