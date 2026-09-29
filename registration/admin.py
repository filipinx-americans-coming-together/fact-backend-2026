from collections import Counter

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    AccountSetUp,
    FacilitatorAssistant,
    FacilitatorContact,
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


def registration_problems(delegate, workshops):
    """
    The website's workshop-registration rules, for admin edits: `workshops`
    is the delegate's full intended list. Returns error messages (empty if
    fine). Capacity and room are only checked for workshops the delegate
    doesn't already hold, so keeping an existing pick is never blocked.
    Locks the workshop rows like _lock_and_register_workshops does; the
    admin's save runs in the same transaction, so the lock covers the write.
    """
    problems = []

    counts = Counter(w.pk for w in workshops)
    for w in {w.pk: w for w in workshops}.values():
        if counts[w.pk] > 1:
            problems.append(f'"{w.title}" is listed more than once.')

    by_session = {}
    for w in {w.pk: w for w in workshops}.values():
        by_session.setdefault(w.session, []).append(w)
    for session, items in sorted(by_session.items()):
        if len(items) > 1:
            titles = " and ".join(f'"{w.title}"' for w in items)
            problems.append(f"Only one workshop per session: {titles} are both in session {session}.")

    held = set()
    if delegate.pk:
        held = set(
            Registration.objects.filter(delegate=delegate).values_list("workshop_id", flat=True)
        )
    new_ids = sorted({w.pk for w in workshops} - held)
    with transaction.atomic():
        locked = Workshop.objects.select_for_update().select_related("location").filter(pk__in=new_ids)
        for w in locked.order_by("pk"):
            if w.location is None:
                problems.append(f'"{w.title}" has no room yet, so it can\'t take registrations.')
                continue
            # w isn't one the delegate holds, so every seat counted is
            # someone else's (and the delegate may not be saved yet).
            taken = (
                Registration.objects.filter(workshop=w).count()
                + FacilitatorRegistration.objects.filter(workshop=w).count()
            )
            if taken >= w.location.capacity:
                problems.append(f'"{w.title}" is full ({taken}/{w.location.capacity}).')

    return problems


def warn_if_not_eligible(request, delegate):
    """The website only lets paid workshop/bundle ticket holders register."""
    if delegate.payment_status != Delegate.PaymentStatus.PAID or delegate.ticket_type not in (
        Delegate.TicketType.WORKSHOP,
        Delegate.TicketType.BUNDLE,
    ):
        messages.warning(
            request,
            f"Saved, but {delegate} isn't a paid workshop or bundle ticket holder "
            f"(payment: {delegate.payment_status}, ticket: {delegate.ticket_type or 'none'}). "
            "The website wouldn't have let them register.",
        )


class RegistrationInlineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        workshops = [
            form.cleaned_data["workshop"]
            for form in self.forms
            if form.cleaned_data
            and not form.cleaned_data.get("DELETE")
            and form.cleaned_data.get("workshop")
        ]
        problems = registration_problems(self.instance, workshops)
        if problems:
            raise ValidationError(problems)


class RegistrationInline(admin.TabularInline):
    # A delegate's workshops, shown on their own admin page. Session/title
    # are read-only mirrors of the chosen workshop so the list is readable
    # at a glance without clicking through.
    model = Registration
    formset = RegistrationInlineFormSet
    extra = 0
    fields = ("workshop", "workshop_session", "workshop_title")
    readonly_fields = ("workshop_session", "workshop_title")
    ordering = ("workshop__session",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("workshop")

    @admin.display(description="Session", ordering="workshop__session")
    def workshop_session(self, obj):
        return obj.workshop.session if obj.workshop_id else "-"

    @admin.display(description="Title", ordering="workshop__title")
    def workshop_title(self, obj):
        return obj.workshop.title if obj.workshop_id else "-"


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
    inlines = (RegistrationInline,)

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if formset.model is Registration and formset.has_changed() and any(
            not f.cleaned_data.get("DELETE") for f in formset.forms if f.cleaned_data
        ):
            warn_if_not_eligible(request, form.instance)


class RegistrationAdminForm(forms.ModelForm):
    class Meta:
        model = Registration
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        delegate = cleaned.get("delegate")
        workshop = cleaned.get("workshop")
        if delegate and workshop:
            others = Registration.objects.filter(delegate=delegate).select_related("workshop")
            if self.instance.pk:
                others = others.exclude(pk=self.instance.pk)
            problems = registration_problems(
                delegate, [r.workshop for r in others] + [workshop]
            )
            if problems:
                raise ValidationError(problems)
        return cleaned


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    form = RegistrationAdminForm
    list_display = ("delegate", "workshop", "workshop_session")
    list_filter = ("workshop__session", "workshop")
    search_fields = (
        "delegate__user__first_name",
        "delegate__user__last_name",
        "delegate__user__email",
    )
    list_select_related = ("delegate__user", "workshop")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        warn_if_not_eligible(request, obj.delegate)

    @admin.display(description="Session", ordering="workshop__session")
    def workshop_session(self, obj):
        return obj.workshop.session


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
admin.site.register(FacilitatorRegistration)
admin.site.register(FacilitatorWorkshop)
admin.site.register(FacilitatorAssistant)
admin.site.register(FacilitatorContact)
admin.site.register(NewSchool)
admin.site.register(AccountSetUp)
