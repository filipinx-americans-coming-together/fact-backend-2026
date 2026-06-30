import os
import pandas as pd
import environ

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.core.mail import EmailMessage

from registration.models import (
    Delegate,
    FacilitatorWorkshop,
    Location,
    Registration,
    School,
    Workshop,
)

env = environ.Env()
environ.Env.read_env()


def set_locations(self):
    # set all workshop locations as "unassigned"
    location_assignments = pd.DataFrame(columns=["workshop", "location"])
    location_assignments["workshop"] = [value["pk"] for value in Workshop.objects.all().values("pk")]

    # for session 1 and 2
    for i in range(1, 3):
        # all workshops/locations ordered (asc) by caps and registrations
        locations = pd.DataFrame(
            Location.objects.filter(session=i).order_by("capacity").values()
        )

        workshops = pd.DataFrame(data=Workshop.objects.filter(session=i).values())

        registrations = []
        facilitators = []

        for idx, row in workshops.iterrows():
            registrations.append(
                len(Registration.objects.filter(workshop_id=row["id"]))
            )

            facilitators.append(
                FacilitatorWorkshop.objects.filter(workshop_id=row["id"])
                .first()
                .facilitator.pk
            )

        workshops["facilitator"] = facilitators
        workshops["registrations"] = registrations

        # replace empty caps with rly big number
        workshops["preferred_cap"] = workshops["preferred_cap"].fillna(1000)

        workshops = workshops.sort_values(["registrations", "preferred_cap"])

        # for each unassigned workshop, find next location that will fit the preferred cap/current registrations
        location_idx = 0
        moveable_locations = locations[locations["moveable_seats"] == True]

        for idx, row in workshops[workshops["moveable_seats"] == True].iterrows():
            # if the number of registrations exceeds the number of seats, move on to the next location
            # if the location has already been assigned, move on to the next location
            # since workshops are sorted by registrations first, every other workshop after this will have more registrations
            while (
                moveable_locations.iloc[location_idx]["capacity"]
                < row["registrations"]
                or moveable_locations.iloc[location_idx]["id"]
                in location_assignments["location"].values
            ):
                location_idx += 1

                if location_idx > len(moveable_locations):
                    self.stdout.write(
                        self.style.ERROR(
                            f"Not enough compatible moveable seating locations for session {i}"
                        )
                    )
                    return

            location_assignments.loc[
                location_assignments["workshop"] == row["id"], "location"
            ] = moveable_locations.iloc[location_idx]["id"]

            # if it is session 1 and facilitator is facilitating in session 2, assign their session to workshop to the chosen location
            if i == 1:
                session_2 = FacilitatorWorkshop.objects.filter(
                    facilitator_id=row["facilitator"]
                )

                if session_2.exists():
                    location_assignments.loc[
                        location_assignments["workshop"]
                        == session_2.first().workshop
                    ] = moveable_locations.iloc[location_idx]["id"]

            location_idx += 1

        # for no moveable seat preference, assign to any open location (seats do not need to be taken into account)
        location_idx = 0

        for idx, row in workshops[workshops["moveable_seats"] == False].iterrows():
            while (
                locations.iloc[location_idx]["capacity"] < row["registrations"]
                or locations.iloc[location_idx]["id"]
                in location_assignments["location"].values
            ):
                location_idx += 1

                if location_idx > len(locations):
                    self.stdout.write(
                        self.style.ERROR(
                            f"Not enough compatible locations for session {i}"
                        )
                    )
                    return

            location_assignments.loc[
                location_assignments["workshop"] == row["id"], "location"
            ] = locations.iloc[location_idx]["id"]

            # if it is session 1 and facilitator is facilitating in session 2, assign their session to workshop to the chosen location
            if i == 1:
                session_2 = FacilitatorWorkshop.objects.filter(
                    facilitator_id=row["facilitator"]
                )

                if session_2.exists():
                    location_assignments.loc[
                        location_assignments["workshop"]
                        == session_2.first().workshop
                    ] = moveable_locations.iloc[location_idx]["id"]

            location_idx += 1

    # for session 3 sort by registrations (workshops), cap (locations) match one to one in desc. order
    locations = pd.DataFrame(
        Location.objects.filter(session=3).order_by("capacity").values()
    )

    workshops = pd.DataFrame(data=Workshop.objects.filter(session=3).values())

    registrations = []

    for idx, row in workshops.iterrows():
        registrations.append(
            len(Registration.objects.filter(workshop_id=row["id"]))
        )

    workshops["registrations"] = registrations

    workshops = workshops.sort_values("registrations")

    location_idx = 0
    for idx, row in workshops.iterrows():
        location_assignments.loc[
            location_assignments["workshop"] == row["id"], "location"
        ] = locations.iloc[location_idx]["id"]

        location_idx += 1
        if location_idx > len(locations):
            self.stdout.write(
                self.style.ERROR(f"Not enough compatible locations for session 3")
            )
            return

    # clear locations
    Workshop.objects.all().update(location=None)

    # assign locations
    for idx, row in location_assignments.iterrows():
        workshop = Workshop.objects.get(pk=row["workshop"])
        workshop.location_id = row["location"]
        workshop.save()




class Command(BaseCommand):
    def handle(self, *args, **options):
        set_locations(self)

        # save file
        workshops = Workshop.objects.all().order_by("session").values()
        workshop_df = pd.DataFrame(data=workshops)

        location_data = {"building": [], "room_num": [], "capacity": []}

        for idx, row in workshop_df.iterrows():
            location = Location.objects.get(id=row["location_id"])

            location_data["building"].append(location.building)
            location_data["room_num"].append(location.room_num)
            location_data["capacity"].append(location.capacity)

        location_df = pd.DataFrame(data=location_data)
        final_df = pd.concat([workshop_df, location_df], axis=1)

        base_path = "./registration/management/commands/data"
        os.mkdir(base_path)
        file_name = "workshop_locations.xlsx"
        path = f"{base_path}/{file_name}"

        final_df.to_excel(path, index=False)

        # email
        subject = "FACT 2024 Automated Workshop Location Update"
        message = "Workshop location data attached."
        from_email = env("EMAIL_HOST_USER")
        recipient_list = ["fact.it@psauiuc.org"]

        email = EmailMessage(subject, message, from_email, recipient_list)

        with open(path, "rb") as file:
            email.attach(
                file_name,
                file.read(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        email.send()

        self.stdout.write(self.style.SUCCESS("Workshop Location update success"))

        # clean up
        os.remove(path)
        os.rmdir(base_path)
