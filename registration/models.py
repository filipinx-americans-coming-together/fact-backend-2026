from django.db import models
from django.contrib.auth.models import User


class Location(models.Model):
    """
    Represents a physical location for workshops.
    Fields:
        room_num: Room identifier
        building: Building name
        capacity: Maximum number of attendees
        session: Workshop session number
        moveable_seats: Whether room has movable seating
    """
    room_num = models.CharField(max_length=50, default="")
    building = models.CharField(max_length=50, default="")
    capacity = models.IntegerField(default=0)
    session = models.IntegerField(default=0)
    moveable_seats = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.room_num} - {self.building}, session {self.session}"


class Facilitator(models.Model):
    """
    Represents a workshop facilitator.
    Fields:
        user: Associated Django user account
        fa_name: Display name
        fa_contact: Contact information
        department_name: Department affiliation
        position: Job title/position
        facilitators: List of additional facilitators
        image_url: Profile image URL
        bio: Professional biography
        attending_networking_session: Networking session attendance flag
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    fa_name = models.CharField(max_length=150, blank=True)
    fa_contact = models.CharField(max_length=150, blank=True)
    department_name = models.CharField(max_length=150)
    position = models.CharField(null=True, blank=True, max_length=200)
    facilitators = models.JSONField(default=list)
    image_url = models.URLField()
    bio = models.TextField()
    attending_networking_session = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.department_name} - {self.fa_name}"


class Workshop(models.Model):
    """
    Represents a workshop session.
    Fields:
        title: Workshop name
        description: Detailed description
        location: Assigned room
        session: Session number
        preferred_cap: Preferred capacity
        moveable_seats: Whether room has movable seating
    """
    title = models.CharField(max_length=150, default="")
    description = models.TextField()
    location = models.OneToOneField(
        Location, on_delete=models.CASCADE, null=True, blank=True
    )
    session = models.IntegerField(default=0)
    preferred_cap = models.IntegerField(null=True, blank=True)
    moveable_seats = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.title} - session {self.session}"


class School(models.Model):
    """
    Represents a participating school.
    """
    name = models.CharField(max_length=150)

    def __str__(self):
        return f"{self.name}"


class NewSchool(models.Model):
    """
    Temporary model for new school submissions.
    """
    name = models.CharField(max_length=150)


class Delegate(models.Model):
    """
    Represents a workshop participant.
    Fields:
        user: Associated Django user account
        pronouns: Preferred pronouns
        year: Academic year
        school: Associated school
        other_school: Custom school name if not in list
        date_created: Account creation timestamp
        is_uiuc_verified: Whether this delegate was verified via Shibboleth SSO
        uiuc_netid: The UIUC NetID (unique, set during Shibboleth login)
        uiuc_eppn: The eduPersonPrincipalName from Shibboleth (e.g. netid@illinois.edu)
        shibboleth_verified_at: Timestamp of Shibboleth verification
        ticket_type: Which Eventbrite ticket tier this delegate purchased
        payment_status: Current payment state, verified server-side against Eventbrite
        eventbrite_order_id: The verified Eventbrite order ID (globally unique)
        payment_verified_at: Timestamp of successful payment verification
    """

    class TicketType(models.TextChoices):
        VARIETY_SHOW = "variety_show", "Variety Show Only"
        WORKSHOP = "workshop", "Workshop Only"
        BUNDLE = "bundle", "Variety Show + Workshop Bundle"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    pronouns = models.CharField(max_length=30, default="")
    year = models.CharField(max_length=40, null=True, default="")
    school = models.ForeignKey(
        School, default=None, null=True, on_delete=models.CASCADE
    )
    other_school = models.CharField(max_length=150, null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True)

    # Shibboleth / UIUC verification fields
    is_uiuc_verified = models.BooleanField(default=False)
    uiuc_netid = models.CharField(max_length=100, blank=True, null=True, unique=True)
    uiuc_eppn = models.CharField(max_length=200, blank=True, null=True)
    shibboleth_verified_at = models.DateTimeField(blank=True, null=True)

    # Eventbrite payment verification fields
    ticket_type = models.CharField(
        max_length=20, choices=TicketType.choices, null=True, blank=True
    )
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    eventbrite_order_id = models.CharField(
        max_length=100, null=True, blank=True, unique=True
    )
    payment_verified_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.last_name}, {self.user.first_name} - {self.user.email}"


class UIUCPromoCode(models.Model):
    """
    A single-use, tier-scoped Eventbrite discount code issued to a
    Shibboleth-verified UIUC delegate. At most one live code per
    (delegate, ticket_type) pair.
    """
    delegate = models.ForeignKey(Delegate, on_delete=models.CASCADE)
    ticket_type = models.CharField(max_length=20, choices=Delegate.TicketType.choices)
    code = models.CharField(max_length=100, unique=True)
    eventbrite_discount_id = models.CharField(max_length=100)
    issued_at = models.DateTimeField(auto_now_add=True)
    redeemed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = ("delegate", "ticket_type")

    def __str__(self):
        return f"{self.code} ({self.delegate})"


class Registration(models.Model):
    """
    Links delegates to workshops.
    """
    delegate = models.ForeignKey(Delegate, on_delete=models.CASCADE)
    workshop = models.ForeignKey(Workshop, on_delete=models.CASCADE)


class FacilitatorRegistration(models.Model):
    """
    Links facilitators to workshops.
    """
    facilitator_name = models.CharField(max_length=200)
    workshop = models.ForeignKey(Workshop, on_delete=models.CASCADE)


class FacilitatorWorkshop(models.Model):
    """
    Links facilitators to workshops with additional metadata.
    """
    facilitator = models.ForeignKey(Facilitator, on_delete=models.CASCADE)
    workshop = models.ForeignKey(Workshop, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.facilitator} - {self.workshop}"


class FacilitatorAssistant(models.Model):
    """
    Represents workshop assistants.
    """
    name = models.CharField(max_length=200)
    contact = models.CharField(max_length=150)
    workshop = models.ForeignKey(Workshop, on_delete=models.CASCADE)


class PasswordReset(models.Model):
    """
    Manages password reset tokens.
    """
    email = models.EmailField()
    token = models.CharField(max_length=150)
    expiration = models.DateTimeField()


class AccountSetUp(models.Model):
    """
    Manages account setup tokens.
    """
    username = models.CharField(max_length=30)
    token = models.CharField(max_length=150)
    expiration = models.DateTimeField()
