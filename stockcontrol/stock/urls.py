from django.urls import path
from . import views

app_name = 'stock'

urlpatterns = [
    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Suppliers
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.supplier_create, name='supplier_create'),
    path('suppliers/edit/<int:supplier_id>/', views.supplier_edit, name='supplier_edit'),
    path('suppliers/delete/<int:supplier_id>/', views.supplier_delete, name='supplier_delete'),

    # Invoices
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('invoices/create/', views.invoice_create, name='invoice_create'),
    path('invoices/<int:invoice_id>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/delete/<int:invoice_id>/', views.invoice_delete, name='invoice_delete'),

    # Drugs (Medicines)
    path('drugs/', views.drug_list, name='drug_list'),
    path('drugs/create/', views.drug_create, name='drug_create'),
    path('drugs/edit/<int:drug_id>/', views.drug_edit, name='drug_edit'),
    path('drugs/delete/<int:drug_id>/', views.drug_delete, name='drug_delete'),

    # Categories
    path('categories/', views.category_list, name='category_list'),

    # ===== API ENDPOINTS (NEW) =====
    path('api/drugs/', views.get_drugs_api, name='drugs_api'),
    path('api/sale/', views.complete_sale, name='complete_sale'),
    path('api/calculate-selling-price/', views.calculate_selling_price, name='calculate_selling_price'),

    # Users (Admin only)
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/edit/<int:user_id>/', views.user_edit, name='user_edit'),
    path('users/delete/<int:user_id>/', views.user_delete, name='user_delete'),
]
