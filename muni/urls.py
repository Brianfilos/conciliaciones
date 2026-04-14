from django.urls import path
from . import views

urlpatterns = [
    path("", views.MunicipioHomeView.as_view(), name="municipio_home"),
    path("admin/municipios/", views.AdminMunicipioView.as_view(), name="admin_municipio"),
    path("admin/ciiu/<str:codigo>/", views.CargarCIIUView.as_view(), name="cargar_ciiu"),
    path("admin/conceptos/<str:codigo>/", views.CargarConceptosView.as_view(), name="cargar_conceptos"),
    path("municipio-media/<str:codigo>/IMG/<str:filename>", views.serve_municipio_media, {"subfolder": "IMG"}, name="municipio_media"),
    path("gobs-media/<str:filename>", views.serve_gobs_media, name="gobs_media"),
]
