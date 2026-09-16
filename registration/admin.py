from django.contrib import admin
from .models import (
    AccountSetUp,
    FacilitatorAssistant,
    FacilitatorRegistration,
    FacilitatorWorkshop,
    NewSchool,
    Workshop,
    Location,
    Facilitator,
    School,
    Delegate,
    Registration,
    UIUCPromoCode,
)


@admin.register(Delegate)
class DelegateAdmin(admin.ModelAdmin):
    # One row per delegate showing UIUC verification + payment/order state
    # side by side — the "compare eduPersonID, order number, and the person"
    # view. uiuc_targeted_id is the opaque eduPersonTargetedID Shibboleth
    # hands back; there's no NetID/email/name in it or anywhere else on this
    # model by design (UIUC only releases that plus eduPersonAffiliation).
    list_display = (
        "__str__",
        "is_uiuc_verified",
        "uiuc_affiliation",
        "uiuc_netid_self_reported",
        "payment_status",
        "ticket_type",
        "eventbrite_order_id",
        "shibboleth_verified_at",
    )
    list_filter = ("is_uiuc_verified", "payment_status", "ticket_type")
    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "uiuc_targeted_id",
        "uiuc_netid_self_reported",
        "eventbrite_order_id",
    )


@admin.register(UIUCPromoCode)
class UIUCPromoCodeAdmin(admin.ModelAdmin):
    # Which UIUC-verified delegates have generated/used a discount code —
    # the "who used the UIUC promo code" view asked for while Shib is still
    # mock-only. redeemed_at/redeemed_order_id blank means issued but not
    # yet spent at checkout.
    list_display = (
        "code",
        "delegate",
        "ticket_type",
        "issued_at",
        "redeemed_at",
        "redeemed_order_id",
    )
    list_filter = ("ticket_type",)
    search_fields = (
        "code",
        "delegate__user__email",
        "delegate__uiuc_targeted_id",
        "redeemed_order_id",
    )


admin.site.register(Workshop)
admin.site.register(Location)
admin.site.register(Facilitator)
admin.site.register(School)
admin.site.register(Registration)
admin.site.register(FacilitatorRegistration)
admin.site.register(FacilitatorWorkshop)
admin.site.register(FacilitatorAssistant)
admin.site.register(NewSchool)
admin.site.register(AccountSetUp)
