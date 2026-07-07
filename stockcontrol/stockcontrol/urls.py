from django.contrib import admin
from django.urls import path, include
from stock.admin import admin_site

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('stock.urls')),
]
