# ============================================================
# ENVIROPULSE
# ALIGNED FEATURE MANAGER
# ============================================================

"""
Purpose
-------
Select and extract the active alignment feature.

This manager:
- chooses WHICH feature is used for alignment
- exposes a unified extraction interface
- allows easy manual swapping
- supports future adaptive selection

This manager DOES NOT:
- perform matching
- perform correlation
- compute consensus
- solve TDOA
"""

# ============================================================
# FEATURE FUNCTIONS
# ============================================================

def onset_feature(event):

    """
    Use onset sample as timing anchor.
    """

    return event["onset_sample"]


def peak_amplitude_feature(event):

    """
    Use peak amplitude position
    inside the event window.
    """

    event_window = event["event_window"]

    local_peak_index = abs(
        event_window
    ).argmax()

    return (

        event["onset_sample"]
        +
        int(local_peak_index)

    )


def offset_feature(event):

    """
    Use offset sample as timing anchor.
    """

    return event["offset_sample"]


# ============================================================
# FEATURE MANAGER
# ============================================================

class AlignedFeatureManager:

    def __init__(self):

        """
        Manual feature selection.

        Future versions may:
        - adapt dynamically
        - choose based on environment
        - use detector confidence
        """

        # ====================================================
        # ACTIVE FEATURE
        # ====================================================

        self.active_feature = "onset"

        # ====================================================
        # FEATURE REGISTRY
        # ====================================================

        self.feature_registry = {

            "onset":
                onset_feature,

            "peak_amplitude":
                peak_amplitude_feature,

            "offset":
                offset_feature

        }

        # ====================================================
        # LOAD ACTIVE FEATURE
        # ====================================================

        self.feature_function = (
            self._load_feature()
        )

    # ========================================================
    # LOAD FEATURE
    # ========================================================

    def _load_feature(self):

        if self.active_feature not in (
            self.feature_registry
        ):

            raise ValueError(

                f"Unknown feature: "
                f"{self.active_feature}"

            )

        return self.feature_registry[
            self.active_feature
        ]

    # ========================================================
    # EXTRACT FEATURE
    # ========================================================

    def extract_feature(

        self,
        event

    ):

        """
        Extract timing feature
        from an event.
        """

        return self.feature_function(
            event
        )

    # ========================================================
    # STATUS
    # ========================================================

    def get_active_feature(self):

        return {

            "active_feature":
                self.active_feature

        }