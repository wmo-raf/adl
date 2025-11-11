from wagtail import blocks


class ColorScaleBlock(blocks.StructBlock):
    """Block for defining a color scale stop"""
    value = blocks.FloatBlock(
        required=True,
        help_text="Data value for this color"
    )
    color = blocks.CharBlock(
        required=True,
        max_length=7,
        help_text="Hex color code (e.g., #FF0000)"
    )
    label = blocks.CharBlock(
        required=False,
        max_length=50,
        help_text="Optional label for this value (e.g., 'Very Cold', 'Hot')"
    )
    
    class Meta:
        icon = 'image'
        label = 'Color Stop'
