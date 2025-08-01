from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django_scopes.forms import SafeModelChoiceField, SafeModelMultipleChoiceField
from i18nfield.forms import I18nModelForm

from pretalx.cfp.forms.cfp import CfPFormMixin
from pretalx.common.forms.fields import ImageField, SizeFileField
from pretalx.common.forms.mixins import (
    I18nHelpText,
    PublicContent,
    ReadOnlyFlag,
    RequestRequire,
)
from pretalx.common.forms.renderers import InlineFormRenderer
from pretalx.common.forms.widgets import (
    ClearableBasenameFileInput,
    EnhancedSelect,
    EnhancedSelectMultiple,
    MarkdownWidget,
)
from pretalx.common.text.phrases import phrases
from pretalx.event.models import Event
from pretalx.person.models import SpeakerInformation, SpeakerProfile, User
from pretalx.schedule.forms import AvailabilitiesFormMixin
from pretalx.submission.models import Question
from pretalx.submission.models.submission import SubmissionStates


def get_email_address_error():
    return (
        _("There already exists an account for this email address.")
        + " "
        + _("Please choose a different email address.")
    )


class SpeakerProfileForm(
    CfPFormMixin,
    AvailabilitiesFormMixin,
    ReadOnlyFlag,
    PublicContent,
    RequestRequire,
    forms.ModelForm,
):
    USER_FIELDS = ["name", "email", "avatar", "get_gravatar"]
    FIRST_TIME_EXCLUDE = ["email"]

    def __init__(self, *args, name=None, **kwargs):
        self.user = kwargs.pop("user", None)
        self.event = kwargs.pop("event", None)
        self.with_email = kwargs.pop("with_email", True)
        self.essential_only = kwargs.pop("essential_only", False)
        kwargs["instance"] = None
        if self.user:
            kwargs["instance"] = self.user.event_profile(self.event)
        super().__init__(*args, **kwargs, event=self.event, limit_to_rooms=True)
        read_only = kwargs.get("read_only", False)
        initial = kwargs.get("initial", {})
        initial["name"] = name

        if self.user:
            initial.update(
                {field: getattr(self.user, field) for field in self.user_fields}
            )
        for field in self.user_fields:
            field_class = self.Meta.field_classes.get(
                field, User._meta.get_field(field).formfield
            )
            self.fields[field] = field_class(
                initial=initial.get(field),
                disabled=read_only,
                help_text=User._meta.get_field(field).help_text,
            )
            self._update_cfp_texts(field)

        if not self.event.cfp.request_avatar:
            self.fields.pop("avatar", None)
            self.fields.pop("get_gravatar", None)
        elif "avatar" in self.fields:
            self.fields["avatar"].required = False
            self.fields["avatar"].widget.is_required = False
        if self.is_bound and not self.is_valid() and "availabilities" in self.errors:
            # Replace self.data with a version that uses initial["availabilities"]
            # in order to have event and timezone data available
            self.data = self.data.copy()
            self.data["availabilities"] = self.initial["availabilities"]

    @cached_property
    def user_fields(self):
        if self.user and not self.essential_only:
            return [
                field
                for field in self.USER_FIELDS
                if field != "email" or self.with_email
            ]
        return [
            field
            for field in self.USER_FIELDS
            if field not in self.FIRST_TIME_EXCLUDE
            and (field != "email" or self.with_email)
        ]

    def clean_email(self):
        email = self.cleaned_data.get("email")
        qs = User.objects.all()
        if self.user:
            qs = qs.exclude(pk=self.user.pk)
        if qs.filter(email__iexact=email):
            raise ValidationError(get_email_address_error())
        return email

    def clean(self):
        data = super().clean()
        if (
            self.event.cfp.require_avatar
            and not data.get("avatar")
            and not data.get("get_gravatar")
        ):
            self.add_error(
                "avatar",
                forms.ValidationError(
                    _(
                        "Please provide a profile picture or allow us to load your picture from gravatar!"
                    )
                ),
            )
        return data

    def save(self, **kwargs):
        for user_attribute in self.user_fields:
            value = self.cleaned_data.get(user_attribute)
            if user_attribute == "avatar":
                if value is False:
                    self.user.avatar = None
                elif value:
                    self.user.avatar = value
            elif value is None and user_attribute == "get_gravatar":
                self.user.get_gravatar = False
            else:
                setattr(self.user, user_attribute, value)
            self.user.save(update_fields=[user_attribute])

        self.instance.event = self.event
        self.instance.user = self.user
        result = super().save(**kwargs)

        if self.user.avatar and "avatar" in self.changed_data:
            self.user.process_image("avatar", generate_thumbnail=True)
        return result

    class Meta:
        model = SpeakerProfile
        fields = ("biography",)
        public_fields = ["name", "biography", "avatar"]
        widgets = {
            "biography": MarkdownWidget,
            "avatar": ClearableBasenameFileInput,
        }
        field_classes = {
            "avatar": ImageField,
        }
        request_require = {"biography", "availabilities"}


class OrgaProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("name", "locale")


class SpeakerInformationForm(I18nHelpText, I18nModelForm):
    def __init__(self, *args, event=None, **kwargs):
        self.event = event
        super().__init__(*args, **kwargs)
        self.fields["limit_types"].queryset = event.submission_types.all()
        if not event.get_feature_flag("use_tracks"):
            self.fields.pop("limit_tracks")
        else:
            self.fields["limit_tracks"].queryset = event.tracks.all()

    def save(self, *args, **kwargs):
        self.instance.event = self.event
        return super().save(*args, **kwargs)

    class Meta:
        model = SpeakerInformation
        fields = (
            "title",
            "text",
            "target_group",
            "limit_types",
            "limit_tracks",
            "resource",
        )
        field_classes = {
            "limit_tracks": SafeModelMultipleChoiceField,
            "limit_types": SafeModelMultipleChoiceField,
            "resource": SizeFileField,
        }
        widgets = {
            "limit_tracks": EnhancedSelectMultiple(color_field="color"),
            "limit_types": EnhancedSelectMultiple,
        }


class SpeakerFilterForm(forms.Form):
    default_renderer = InlineFormRenderer

    role = forms.ChoiceField(
        choices=(
            ("", phrases.base.all_choices),
            ("true", phrases.schedule.speakers),
            ("false", _("Non-accepted submitters")),
        ),
        required=False,
        widget=EnhancedSelect,
    )
    arrived = forms.ChoiceField(
        choices=(
            ("", phrases.base.all_choices),
            ("true", _("Marked as arrived")),
            ("false", _("Not yet arrived")),
        ),
        required=False,
        widget=EnhancedSelect,
    )
    question = SafeModelChoiceField(
        queryset=Question.objects.none(), required=False, widget=forms.HiddenInput()
    )

    def __init__(self, *args, event=None, filter_arrival=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = event
        self.fields["question"].queryset = event.questions.all()
        if not filter_arrival:
            self.fields.pop("arrived")

    def filter_queryset(self, queryset):
        data = self.cleaned_data
        if data.get("role") == "true":
            queryset = queryset.filter(
                user__submissions__in=self.event.submissions.filter(
                    state__in=SubmissionStates.accepted_states
                )
            )
        elif data.get("role") == "false":
            queryset = queryset.exclude(
                user__submissions__in=self.event.submissions.filter(
                    state__in=SubmissionStates.accepted_states
                )
            )
        if has_arrived := data.get("arrived"):
            queryset = queryset.filter(has_arrived=(has_arrived == "true"))
        return queryset


class UserSpeakerFilterForm(forms.Form):
    default_renderer = InlineFormRenderer

    role = forms.ChoiceField(
        choices=(
            ("speaker", phrases.schedule.speakers),
            ("submitter", _("Non-accepted submitters")),
            ("all", phrases.base.all_choices),
        ),
        required=False,
        widget=EnhancedSelect,
    )
    events = SafeModelMultipleChoiceField(
        queryset=Event.objects.none(),
        required=False,
        widget=EnhancedSelectMultiple,
    )

    def __init__(self, *args, events=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = events
        if events.count() > 1:
            self.fields["events"].queryset = events
        else:
            self.fields.pop("events")

    def filter_queryset(self, queryset):
        data = self.cleaned_data
        events = data.get("events") or self.events
        role = data.get("role") or "speaker"

        qs = (
            queryset.filter(profiles__event__in=events)
            .prefetch_related("profiles", "profiles__event")
            .annotate(
                submission_count=Count(
                    "submissions",
                    filter=Q(submissions__event__in=events),
                    distinct=True,
                ),
                accepted_submission_count=Count(
                    "submissions",
                    filter=Q(submissions__event__in=events)
                    & Q(submissions__state__in=SubmissionStates.accepted_states),
                    distinct=True,
                ),
            )
        )
        if role == "speaker":
            qs = qs.filter(accepted_submission_count__gt=0)
        elif role == "submitter":
            qs = qs.filter(accepted_submission_count=0)
        qs = qs.order_by("id").distinct()
        return qs
