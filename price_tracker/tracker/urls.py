from django.urls import path
from . import views

urlpatterns = [
    path("healthz/", views.healthcheck, name="healthcheck"),
    path("", views.home, name="home"),
    path("product/<int:pk>/", views.product_detail, name="product_detail"),
    path("alerts/", views.alerts_dashboard, name="alerts"),
    path("create-alert/", views.create_alert, name="create_alert"),
    path("delete-alert/<int:pk>/", views.delete_alert, name="delete_alert"),
    path("predict/<int:product_id>/", views.predict_price_view, name="predict_price"),
]
