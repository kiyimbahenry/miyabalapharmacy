from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'stock'

urlpatterns = [
    # ============================================================
    # AUTHENTICATION
    # ============================================================
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # ============================================================
    # PASSWORD RESET URLs - ADDED
    # ============================================================
    path('password-reset/',
         auth_views.PasswordResetView.as_view(
             template_name='stock/password_reset.html',
             email_template_name='stock/password_reset_email.html',
             subject_template_name='stock/password_reset_subject.txt'
         ),
         name='password_reset'),

    path('password-reset/done/',
         auth_views.PasswordResetDoneView.as_view(
             template_name='stock/password_reset_done.html'
         ),
         name='password_reset_done'),

    path('password-reset-confirm/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(
             template_name='stock/password_reset_confirm.html'
         ),
         name='password_reset_confirm'),

    path('password-reset-complete/',
         auth_views.PasswordResetCompleteView.as_view(
             template_name='stock/password_reset_complete.html'
         ),
         name='password_reset_complete'),

    # ============================================================
    # DASHBOARD
    # ============================================================
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('test-smtp/', views.test_smtp, name='test_smtp'),

    # ============================================================
    # DRUG (MEDICINE) URLs
    # ============================================================
    path('drugs/', views.drug_list, name='drug_list'),
    path('medicines/', views.drug_list, name='medicine_list'),
    path('drugs/expired/', views.expired_drug_list, name='expired_drug_list'),
    path('drugs/create/', views.drug_create, name='drug_create'),
    path('autocomplete-drugs/', views.autocomplete_drugs, name='autocomplete_drugs'),
    path('add-stock-to-drug/', views.add_stock_to_drug, name='add_stock_to_drug'),
    path('drugs/<int:drug_id>/edit/', views.drug_edit, name='drug_edit'),
    path('drugs/<int:drug_id>/delete/', views.drug_delete, name='drug_delete'),

    # ============================================================
    # CHRONIC PATIENT URLs
    # ============================================================
    path('patients/', views.patient_list, name='patient_list'),
    path('patients/create/', views.patient_create, name='patient_create'),
    path('patients/<int:patient_id>/', views.patient_detail, name='patient_detail'),
    path('patients/<int:patient_id>/edit/', views.patient_edit, name='patient_edit'),
    path('patients/<int:patient_id>/delete/', views.patient_delete, name='patient_delete'),
    path('patients/<int:patient_id>/add-medication/', views.patient_add_medication, name='patient_add_medication'),
    path('patients/medication/<int:medication_id>/remove/', views.patient_remove_medication, name='patient_remove_medication'),

    # ============================================================
    # CATEGORY URLs
    # ============================================================
    path('categories/', views.category_list, name='category_list'),

    # ============================================================
    # SUPPLIER URLs
    # ============================================================
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.supplier_create, name='supplier_create'),
    path('suppliers/<int:supplier_id>/edit/', views.supplier_edit, name='supplier_edit'),
    path('suppliers/<int:supplier_id>/delete/', views.supplier_delete, name='supplier_delete'),

    # ============================================================
    # INVOICE URLs
    # ============================================================
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('invoices/create/', views.invoice_create, name='invoice_create'),
    path('invoices/<int:invoice_id>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/<int:invoice_id>/edit/', views.invoice_edit, name='invoice_edit'),
    path('invoices/<int:invoice_id>/delete/', views.invoice_delete, name='invoice_delete'),
    path('drug/create/ajax/', views.drug_create_ajax, name='drug_create_ajax'),

    # ============================================================
    # RECEIPT/SALES URLs
    # ============================================================
    path('receipts/', views.receipt_list, name='receipt_list'),
    path('receipts/<int:receipt_id>/', views.receipt_detail, name='receipt_detail'),
    path('receipts/<int:receipt_id>/print/', views.print_receipt, name='print_receipt'),
    path('sale/create/', views.create_sale_receipt, name='create_sale'),
    path('api/complete-sale/', views.complete_sale, name='complete_sale'),
    path('returns/', views.return_list, name='return_list'),
    path('returns/create/', views.return_create, name='return_create'),

    # ============================================================
    # REPORT URLs
    # ============================================================
    path('reports/', views.reports_dashboard, name='reports_dashboard'),
    path('api/generate-report/', views.generate_report_api, name='generate_report_api'),

    # ============================================================
    # API URLs
    # ============================================================
    path('api/drugs/', views.get_drugs_api, name='get_drugs_api'),
    path('api/drugs/all/', views.get_all_drugs_for_sale, name='drugs_all'),
    path('api/complete-sale/', views.complete_sale, name='complete_sale'),
    path('api/calculate-price/', views.calculate_selling_price, name='calculate_selling_price'),
    path('api/daily-sales/', views.get_daily_sales_api, name='daily_sales_api'),

    # ============================================================
    # USER MANAGEMENT URLs (Admin only)
    # ============================================================
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<int:user_id>/', views.user_detail, name='user_detail'),
    path('users/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:user_id>/delete/', views.user_delete, name='user_delete'),
]
