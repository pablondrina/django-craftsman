"""
Base classes for Unfold admin in Craftsman.

Provides BaseModelAdmin and BaseTabularInline with sensible defaults
for textarea fields and numeric formatting.
"""

from decimal import Decimal

from django import forms
from django.contrib.admin.widgets import AdminTextareaWidget
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.widgets import UnfoldAdminTextareaWidget


def format_quantity(value: Decimal, decimal_places: int = 2) -> str:
    """
    Format a quantity value.

    Args:
        value: Decimal value to format
        decimal_places: Number of decimal places (default: 2)

    Returns:
        Formatted string (e.g., "10.50")
    """
    if value is None:
        return "-"
    return f"{value:.{decimal_places}f}"


class _TextareaCustomizationMixin:
    """Mixin to customize textarea fields in inlines."""

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)

        # Customize text widgets in inlines (reduced height)
        for field_name, field in formset.form.base_fields.items():
            widget = field.widget

            # Textarea (long TextField, JSONField, etc) - reduce height
            if isinstance(
                widget, (forms.Textarea, AdminTextareaWidget, UnfoldAdminTextareaWidget)
            ):
                if not hasattr(widget, "attrs"):
                    widget.attrs = {}

                # Adjust rows if Textarea (reduce height)
                if "rows" in widget.attrs:
                    try:
                        rows = int(widget.attrs["rows"])
                        widget.attrs["rows"] = max(1, rows // 2)
                    except (ValueError, TypeError):
                        widget.attrs["rows"] = 2
                elif isinstance(widget, forms.Textarea):
                    widget.attrs["rows"] = 2

        return formset


class BaseTabularInline(_TextareaCustomizationMixin, TabularInline):
    """
    TabularInline base with customizations for text and numeric fields.

    - Reduced height (50%) for TextField, Textarea and JSONField in inlines
    """

    pass


class BaseStackedInline(_TextareaCustomizationMixin, StackedInline):
    """
    StackedInline base with customizations for text and numeric fields.

    - Reduced height (50%) for TextField, Textarea and JSONField in inlines
    - Better layout for inlines with many fields
    """

    pass


class BaseModelAdmin(ModelAdmin):
    """
    ModelAdmin base with sensible defaults.

    Applies customizations for TextField, Textarea and JSONField:
    - Reduced height (50%)
    - Max width of 42rem (aligned with other form fields)
    """

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        # Customize text widgets in regular forms
        for field_name, field in form.base_fields.items():
            widget = field.widget

            # Detect Textarea (used by long TextField, JSONField, etc)
            if isinstance(
                widget, (forms.Textarea, AdminTextareaWidget, UnfoldAdminTextareaWidget)
            ):
                if not hasattr(widget, "attrs"):
                    widget.attrs = {}

                current_style = widget.attrs.get("style", "")

                # 1. Reduce height by 50%
                style_parts = [
                    s
                    for s in current_style.split(";")
                    if "height" not in s.lower() and "max-height" not in s.lower()
                ]
                style_parts.append("height: 50%; max-height: 50%;")

                # 2. Apply max width of 42rem (aligned with other fields)
                style_parts = [
                    s
                    for s in style_parts
                    if "width" not in s.lower() and "max-width" not in s.lower()
                ]
                style_parts.append("width: 100%; max-width: 42rem;")

                widget.attrs["style"] = "; ".join(
                    [s.strip() for s in style_parts if s.strip()]
                )

                # Adjust rows if Textarea
                if "rows" in widget.attrs:
                    try:
                        rows = int(widget.attrs["rows"])
                        widget.attrs["rows"] = max(1, rows // 2)
                    except (ValueError, TypeError):
                        widget.attrs["rows"] = 2
                elif isinstance(widget, forms.Textarea):
                    widget.attrs["rows"] = 2

        return form
