from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from wagtail import blocks
from wagtail.blocks import StructBlockValidationError


class RangeCheckConfig(blocks.StructBlock):
    min_value = blocks.FloatBlock(
        required=False,
        help_text="The smallest acceptable value for this parameter. Leave blank if there's no minimum limit.",
    )
    max_value = blocks.FloatBlock(
        required=False,
        help_text="The largest acceptable value for this parameter. Leave blank if there's no maximum limit.",
    )
    inclusive_bounds = blocks.BooleanBlock(
        required=False,
        default=True,
        help_text="Check this box if the min/max values themselves are acceptable. Uncheck if they should be excluded.",
    )
    
    def clean(self, value):
        cleaned_data = super().clean(value)
        min_val = cleaned_data.get('min_value')
        max_val = cleaned_data.get('max_value')
        
        if min_val is not None and max_val is not None and min_val > max_val:
            raise StructBlockValidationError({
                'min_value': ValidationError("Minimum value cannot be greater than maximum value."),
                'max_value': ValidationError("Maximum value cannot be less than minimum value."),
            })
        
        return cleaned_data
    
    class Meta:
        label = "Range Check Configuration"
        icon = "up-down"
        help_text = "Reject values that are too high or too low. Use this to catch sensor readings that are clearly impossible."


# Detects unrealistic jumps between consecutive readings that violate physics
class StepCheckConfig(blocks.StructBlock):
    max_step_change = blocks.FloatBlock(
        required=True,
        min_value=0,
        help_text="Maximum allowed jump between consecutive readings. Larger jumps usually indicate sensor problems.",
    )
    max_step_change_per_minute = blocks.FloatBlock(
        required=False,
        min_value=0,
        help_text="Maximum rate of change per minute. Leave blank to only check absolute jumps.",
    )
    ignore_after_gap_minutes = blocks.IntegerBlock(
        required=True,
        min_value=1,
        default=30,
        help_text="Skip this check if there's been a data gap longer than this many minutes. This prevents false alarms after maintenance or outages.",
    )
    
    class Meta:
        label = "Step Check Configuration"
        icon = "resubmit"
        help_text = "Catch sudden unrealistic jumps in readings. Useful for detecting sensor malfunctions or data transmission errors."


# Identifies stuck sensors that report identical values for extended periods
class PersistenceCheckConfig(blocks.StructBlock):
    max_identical_readings = blocks.IntegerBlock(
        required=True,
        min_value=2,
        default=10,
        help_text="Flag the data if this many consecutive readings are identical. For example, 10 identical readings might indicate a stuck sensor.",
    )
    tolerance = blocks.FloatBlock(
        required=True,
        min_value=0,
        default=0.001,
        help_text="How close values need to be to count as 'identical'. Use 0.1 for whole numbers, 0.01 for one decimal place, etc.",
    )
    allow_zero_persistence = blocks.BooleanBlock(
        required=True,
        default=True,
        help_text="Allow zero values to repeat without triggering alerts. Useful for parameters like precipitation that naturally stay at zero.",
    )
    
    class Meta:
        label = "Persistence Check Configuration"
        icon = "time"
        help_text = "Detect sensors that are stuck reporting the same value repeatedly. Helps identify frozen or broken instruments."


# Finds sudden anomalous spikes that deviate from statistical patterns
class SpikeCheckConfig(blocks.StructBlock):
    threshold_multiplier = blocks.FloatBlock(
        required=True,
        min_value=0.1,
        default=3.0,
        help_text="How many 'standard deviations' away from normal before flagging as a spike. 3.0 catches extreme outliers, 2.0 is more strict.",
    )
    lookback_samples = blocks.IntegerBlock(
        required=True,
        min_value=5,
        default=20,
        help_text="Number of previous readings to analyze for 'normal' behavior. More samples give better statistics but use older data.",
    )
    min_samples = blocks.IntegerBlock(
        required=True,
        min_value=3,
        default=5,
        help_text="Minimum previous readings needed before spike detection starts working. Prevents errors when there's insufficient data.",
    )
    
    class Meta:
        label = "Spike Check Configuration"
        icon = "chart-line"
        help_text = "Identify sudden abnormal spikes using statistical analysis. Compares each reading to recent patterns to spot outliers."


class QCChecksStreamBlock(blocks.StreamBlock):
    """Custom StreamBlock for Quality Control checks with constraints"""
    
    range_check = RangeCheckConfig(label=_("Range Check"))
    step_check = StepCheckConfig(label=_("Step Check"))
    persistence_check = PersistenceCheckConfig(label=_("Persistence Check"))
    spike_check = SpikeCheckConfig(label=_("Spike Check"))
    
    class Meta:
        label = _("Quality Control Checks")
        help_text = mark_safe("""
           <p>Quality control checks help identify bad or suspicious data automatically:</p>
           <ul>
               <li><strong>Range Check</strong> - Rejects impossible values</li>
               <li><strong>Step Check</strong> - Catches sudden unrealistic jumps between readings</li>
               <li><strong>Persistence Check</strong> - Flags sensors stuck on the same value</li>
               <li><strong>Spike Check</strong> - Uses statistics to identify unusual outliers</li>
           </ul>
           <br>
           <p><em>Start with Range Check for basic validation, then add others as needed.<br>
           Each check type can only be added once per parameter.</em></p>
           """)
        block_counts = {
            'range_check': {'min_num': 0, 'max_num': 1},
            'step_check': {'min_num': 0, 'max_num': 1},
            'persistence_check': {'min_num': 0, 'max_num': 1},
            'spike_check': {'min_num': 0, 'max_num': 1},
        }
