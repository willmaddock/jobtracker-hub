from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("sign-out/", views.sign_out, name="sign-out"),
    path("w/<int:workspace_id>/pipeline/", views.pipeline, name="pipeline"),
]
