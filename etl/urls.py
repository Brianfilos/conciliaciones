from django.urls import path
from . import views, views_envio, views_reporteria

urlpatterns = [
    path("procesos/", views.ProcesoListView.as_view(), name="proceso_list"),
    path("ejecutar/<int:proceso_id>/", views.EjecutarProcesoView.as_view(), name="ejecutar_proceso"),
    path("historial/", views.HistorialView.as_view(), name="historial"),
    path("reporteria/", views_reporteria.ReporteriaView.as_view(), name="reporteria"),
    path("reporteria/datos/", views_reporteria.ReporteriaDatosView.as_view(), name="reporteria_datos"),
    path("reporteria/buscar/", views_reporteria.ReporteriaBuscarView.as_view(), name="reporteria_buscar"),
    path("dashboard/<int:proceso_id>/", views.DashboardView.as_view(), name="dashboard"),
    path("exportar/<int:proceso_id>/", views.ExportarView.as_view(), name="exportar"),
    path("exportar/<int:proceso_id>/correo/", views_envio.EnviarExportacionView.as_view(), name="exportar_correo"),
    path("progreso/<int:ejecucion_id>/", views.ejecutar_progreso, name="ejecutar_progreso"),
    path("status/<int:ejecucion_id>/", views.ejecucion_status, name="ejecucion_status"),
    path("limpiar/<int:proceso_id>/", views.LimpiarProcesoView.as_view(), name="limpiar_proceso"),
]
