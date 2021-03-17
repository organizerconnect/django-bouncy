"""Admin code for django_bouncy app"""

from django.contrib import admin

from django_bouncy.models import Bounce, Complaint, Delivery, Send, Open, Click, RenderingFailure, DeliveryDelay


class BounceAdmin(admin.ModelAdmin):
    """Admin model for 'Bounce' objects"""
    list_display = (
        'feedback_timestamp', 'address', 'mail_from', 'bounce_type', 'bounce_subtype', 'status')
    list_filter = (
        'hard', 'action', 'bounce_type', 'bounce_subtype',
        'feedback_timestamp'
    )
    search_fields = ('address',)


class ComplaintAdmin(admin.ModelAdmin):
    """Admin model for 'Complaint' objects"""
    list_display = ('feedback_timestamp', 'address', 'mail_from', 'feedback_type')
    list_filter = ('feedback_type', 'feedback_timestamp')
    search_fields = ('address',)


class DeliveryAdmin(admin.ModelAdmin):
    """Admin model for 'Delivery' objects"""
    list_display = ('delivered_time', 'address', 'mail_from')
    list_filter = ('delivered_time',)
    search_fields = ('address',)


class SendAdmin(admin.ModelAdmin):
    list_display = ('mail_timestamp', 'address', 'mail_from',)
    list_filter = ('mail_timestamp',)
    search_fields = ('address',)


class OpenAdmin(admin.ModelAdmin):
    list_display = ('opened_time', 'address', 'mail_from',)
    list_filter = ('opened_time',)
    search_fields = ('address',)


class ClickAdmin(admin.ModelAdmin):
    list_display = ('clicked_time', 'address', 'mail_from', 'link',)
    list_filter = ('clicked_time',)
    search_fields = ('address',)


class RenderingFailureAdmin(admin.ModelAdmin):
    list_display = ('mail_timestamp', 'address', 'mail_from', 'template_name', 'error_message',)
    list_filter = ('mail_timestamp',)
    search_fields = ('address', 'template_name',)


class DeliveryDelayAdmin(admin.ModelAdmin):
    list_display = ('delayed_time', 'address', 'mail_from', 'delay_type',)
    list_filter = ('delayed_time',)
    search_fields = ('address', 'delay_type',)


admin.site.register(Bounce, BounceAdmin)
admin.site.register(Complaint, ComplaintAdmin)
admin.site.register(Delivery, DeliveryAdmin)
admin.site.register(Send, SendAdmin)
admin.site.register(Open, OpenAdmin)
admin.site.register(Click, ClickAdmin)
admin.site.register(RenderingFailure, RenderingFailureAdmin)
admin.site.register(DeliveryDelay, DeliveryDelayAdmin)
