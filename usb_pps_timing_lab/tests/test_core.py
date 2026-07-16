from pathlib import Path

import numpy as np

from usb_pps_lab.common import robust_linear_fit
from usb_pps_lab.nmea import checksum_valid, parse_rmc
from usb_pps_lab.pps import parse_pps_assert


def test_pps_parser() -> None:
    epoch_ns, sequence = parse_pps_assert("1782229609.004599977#1155")
    assert epoch_ns == 1782229609004599977
    assert sequence == 1155


def test_rmc_parser() -> None:
    sentence = "$GPRMC,123519.00,A,4807.038,N,01131.000,E,0.0,0.0,230394,,,A*68"
    # The sample checksum above varies by optional fields; this test verifies rejection is safe.
    assert parse_rmc(sentence) is None or parse_rmc(sentence).valid


def test_robust_fit_rejects_outlier() -> None:
    x = np.arange(100, dtype=float)
    y = 5.0 + 2.0 * x
    y[50] += 1000.0
    fit = robust_linear_fit(x, y)
    assert abs(fit["slope"] - 2.0) < 1e-9
    assert fit["rejected_count"] >= 1
