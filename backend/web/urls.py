from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("sign-out/", views.sign_out, name="sign-out"),
    path("w/<int:workspace_id>/pipeline/", views.pipeline, name="pipeline"),
    path("w/<int:workspace_id>/applications/<int:application_id>/<str:action>/", views.application_action,
         name="application-action"),
]
