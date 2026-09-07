from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, Workspace

admin.site.register(User, UserAdmin)
admin.site.register(Workspace)
